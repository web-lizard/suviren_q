#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BookForge Engine v1 — CLI-first audiobook compositor and renderer for YouTube.

Commands:
  doctor         Validate environment
  scan           Auto-discover media files in data/
  chapters       Extract chapters from RPP
  preset         Generate visual layout preset (e.g. zina-noir)
  waveform       Generate waveform data from audio
  preview        Render PNG preview (single / contact sheet)
  render-test    Render 60-second test MP4
  render-full    Render full MP4 for YouTube
  status         Show project status
  clean-temp     Remove temp files and lock
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Optional

# ── Reuse from suviren_q.py ─────────────────────────────────────
# We import core functions/classes to avoid code duplication.
# suviren_q.py provides: Chapter, parse_rpp, detect_chapters_from_rpp,
# normalize_chapters, save_chapters, save_youtube_chapters,
# seconds_to_timecode, parse_time_value, build_dir, ensure_dir, etc.

from suviren_q import (
    Chapter,
    parse_rpp,
    detect_chapters_from_rpp,
    normalize_chapters,
    save_chapters,
    save_youtube_chapters,
    seconds_to_timecode,
    parse_time_value,
    build_dir,
    ensure_dir,
    ffprobe_duration,
    log as sq_log,
    warn as sq_warn,
    APP_NAME,
    BUILD_DIR_NAME,
    DEFAULT_WIDTH,
    DEFAULT_HEIGHT,
    DEFAULT_FPS,
)

# ── Constants ─────────────────────────────────────────────────────
APP = "bookforge"
DATA_DIR_DEFAULT = "data"
PROJECT_CONFIG = "bookforge.project.json"
LAYOUT_FILE = "layout.json"
WAVEFORM_FILE = "waveform.json"
RENDER_LOCK = "render.lock"
PREVIEW_PNG = "preview.png"
CONTACT_PNG = "preview_contact.png"
TEST_MP4 = "test_60sec.mp4"
FULL_MP4 = "zina_book_youtube_full.mp4"
REPORT_JSON = "bookforge_report.json"
REPORT_MD = "bookforge_report.md"
RENDER_TEST_LOG = "render_test.log"
RENDER_FULL_LOG = "render_full.log"

QUALITY_PRESETS = {
    "fast_test": {
        "preset": "veryfast",
        "crf": "23",
        "audio_bitrate": "192k",
        "scale": "1920:1080",
    },
    "youtube_high": {
        "preset": "medium",
        "crf": "18",
        "audio_bitrate": "256k",
        "scale": "1920:1080",
    },
}

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
RPP_EXTENSION = ".rpp"

AUDIO_KEYWORDS = ["book", "zina", "zinaida", "audio", "audiobook", "озвучка"]
COVER_KEYWORDS = ["cover", "обложка", "zina-cover", "обложка"]
BG_KEYWORDS = ["background", "bg", "backdrop", "фон", "background"]

# ── Logging ───────────────────────────────────────────────────────

def log(msg: str) -> None:
    sq_log(msg)

def warn(msg: str) -> None:
    sq_warn(msg)

def fail(msg: str, code: int = 1) -> None:
    print(f"[{APP}][ERROR] {msg}", file=sys.stderr, flush=True)
    raise SystemExit(code)

def ok(msg: str) -> None:
    print(f"[OK] {msg}", flush=True)

def info(msg: str) -> None:
    print(f"[INFO] {msg}", flush=True)

def warn_msg(msg: str) -> None:
    print(f"[WARN] {msg}", flush=True)


# ── File Scanner ───────────────────────────────────────────────────

@dataclass
class ScanResult:
    audio: Optional[Path] = None
    cover: Optional[Path] = None
    background: Optional[Path] = None
    rpp: Optional[Path] = None
    all_audio: list[Path] = None
    all_images: list[Path] = None
    all_rpp: list[Path] = None

    def __post_init__(self):
        if self.all_audio is None:
            self.all_audio = []
        if self.all_images is None:
            self.all_images = []
        if self.all_rpp is None:
            self.all_rpp = []

    def is_complete(self) -> bool:
        return all([self.audio, self.cover, self.rpp])


def _score_by_name(path: Path, keywords: list[str]) -> int:
    name = path.stem.lower()
    score = 0
    for kw in keywords:
        if kw in name:
            score += 10
    return score


def _pick_best_audio(candidates: list[Path]) -> Optional[Path]:
    if not candidates:
        return None
    # Priority 0: exact match for the known final file
    EXACT_FINAL = "ЗИНА. Книга. final last version"
    for p in candidates:
        if p.stem == EXACT_FINAL:
            return p  # Absolute priority — exact match wins immediately
    # Priority keywords in order (higher = earlier in list = higher priority)
    PRIORITY_KEYWORDS = [
        "final last",
        "final",
        "master",
        "full",
        "complete",
        "version",
    ]
    # Blacklist: avoid old/legacy files if better alternatives exist
    BLACKLIST = ["zinaida"]
    scored = []
    for p in candidates:
        name = p.stem.lower()
        # Check blacklist — apply heavy penalty
        blacklist_penalty = 0
        for bl in BLACKLIST:
            if bl in name:
                blacklist_penalty = 10000  # Effectively last unless only option
        # Score based on priority keyword position
        kw_score = 0
        for idx, kw in enumerate(PRIORITY_KEYWORDS):
            if kw in name:
                # Higher priority keywords get exponentially higher score
                kw_score = max(kw_score, (len(PRIORITY_KEYWORDS) - idx) * 100)
        keyword_score = _score_by_name(p, AUDIO_KEYWORDS)
        size_score = p.stat().st_size / 1_000_000  # Larger files preferred
        total = kw_score + keyword_score + size_score - blacklist_penalty
        scored.append((p, total))
    scored.sort(key=lambda x: -x[1])
    return scored[0][0]


def _pick_best_image(candidates: list[Path], keywords: list[str]) -> Optional[Path]:
    if not candidates:
        return None
    scored = [(p, _score_by_name(p, keywords)) for p in candidates]
    scored.sort(key=lambda x: -x[1])
    return scored[0][0]


def _pick_best_cover(candidates: list[Path]) -> Optional[Path]:
    """Pick cover by keywords, preferring square-ish images."""
    if not candidates:
        return None
    scored = []
    for p in candidates:
        base_score = _score_by_name(p, COVER_KEYWORDS)
        # Try to check aspect ratio
        try:
            from PIL import Image
            with Image.open(p) as im:
                w, h = im.size
                aspect = w / h if h > 0 else 1
                # Square bonus: aspect ratio between 0.8 and 1.2
                if 0.8 <= aspect <= 1.2:
                    base_score += 5
        except Exception:
            pass
        scored.append((p, base_score))
    scored.sort(key=lambda x: -x[1])
    return scored[0][0]


def _pick_best_background(candidates: list[Path]) -> Optional[Path]:
    """Pick background by keywords, preferring 16:9 landscape."""
    if not candidates:
        return None
    scored = []
    for p in candidates:
        base_score = _score_by_name(p, BG_KEYWORDS)
        try:
            from PIL import Image
            with Image.open(p) as im:
                w, h = im.size
                aspect = w / h if h > 0 else 1
                # 16:9 bonus: aspect between 1.6 and 1.9
                if 1.6 <= aspect <= 1.9:
                    base_score += 5
                elif aspect > 1.4:
                    base_score += 2
        except Exception:
            pass
        scored.append((p, base_score))
    scored.sort(key=lambda x: -x[1])
    return scored[0][0]


def scan_data(data_dir: Path) -> ScanResult:
    """Scan data_dir and auto-discover best candidates for each role."""
    result = ScanResult()

    if not data_dir.exists():
        warn(f"Data directory not found: {data_dir}")
        return result

    audio_files = []
    image_files = []
    rpp_files = []

    for f in data_dir.iterdir():
        if f.is_dir():
            continue
        ext = f.suffix.lower()
        if ext in AUDIO_EXTENSIONS:
            audio_files.append(f)
        elif ext in IMAGE_EXTENSIONS:
            image_files.append(f)
        elif ext == RPP_EXTENSION:
            rpp_files.append(f)

    result.all_audio = sorted(audio_files)
    result.all_images = sorted(image_files)
    result.all_rpp = sorted(rpp_files)

    # Pick audio
    if audio_files:
        result.audio = _pick_best_audio(audio_files)
        if len(audio_files) > 1:
            other = [str(p.name) for p in audio_files if p != result.audio]
            warn(f"Multiple audio files found: {', '.join(other)}")
            info(f"Selected: {result.audio.name}")

    # Pick cover (separate from background)
    if image_files:
        result.cover = _pick_best_cover(image_files)
        remaining = [p for p in image_files if p != result.cover]
        result.background = _pick_best_background(remaining)

    # Pick RPP
    if rpp_files:
        result.rpp = rpp_files[0]
        if len(rpp_files) > 1:
            warn(f"Multiple RPP files found, using: {result.rpp.name}")

    return result


def print_scan_table(result: ScanResult) -> None:
    """Pretty-print scan results as a table."""
    print()
    print("  ┌──────────────────────┬────────────────────────────────────┐")
    print("  │ Resource             │ File                               │")
    print("  ├──────────────────────┼────────────────────────────────────┤")

    def fmt_row(label: str, path: Optional[Path]) -> str:
        name = path.name if path else "— NOT FOUND —"
        return f"  │ {label:<20} │ {name:<34} │"

    print(fmt_row("Audio", result.audio))
    print(fmt_row("Cover", result.cover))
    print(fmt_row("Background", result.background))
    print(fmt_row("RPP", result.rpp))
    print("  └──────────────────────┴────────────────────────────────────┘")
    print()


# ── Project Config ────────────────────────────────────────────────

def default_project_config(data_dir: Path, build: Path, scan: ScanResult, chapters_path: Path) -> dict:
    return {
        "version": 1,
        "project_name": "ЗИНА. Книга",
        "data_dir": str(data_dir),
        "build_dir": str(build),
        "audio": str(scan.audio) if scan.audio else "",
        "cover": str(scan.cover) if scan.cover else "",
        "background": str(scan.background) if scan.background else "",
        "rpp": str(scan.rpp) if scan.rpp else "",
        "chapters": str(chapters_path),
        "layout": str(build / LAYOUT_FILE),
        "waveform": str(build / WAVEFORM_FILE),
        "outputs": {
            "preview": str(build / PREVIEW_PNG),
            "contact": str(build / CONTACT_PNG),
            "test": str(build / TEST_MP4),
            "full": str(build / FULL_MP4),
        },
        "quality": "youtube_high",
    }


def save_project_config(path: Path, config: dict) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Project config saved: {path}")


def load_project_config(path: Path) -> dict:
    if not path.exists():
        fail(f"Project config not found: {path}. Run 'scan' first.")
    return json.loads(path.read_text(encoding="utf-8"))


# ── Layout / Preset ───────────────────────────────────────────────

def build_zina_noir_layout() -> dict:
    """Create the noir cyberpunk layout for Zina book."""
    return {
        "version": 1,
        "name": "zina-noir",
        "scene": {
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "safe_margin": 72,
        },
        "theme": {
            "name": "zina-noir",
            "background_blur": 0,
            "background_dim": 0.30,
            "background_overlay": "linear-gradient(180deg, rgba(5,5,10,0.50) 0%, rgba(5,5,10,0.75) 100%)",
            "accent": "#72ffd9",
            "accent_2": "#b69aff",
            "text": "#f7f1ff",
            "muted": "#b9abc9",
            "shadow": "#05050a",
            "waveform_played": "#72ffd9",
            "waveform_unplayed": "#b69aff",
            "progress_bg": "rgba(255,255,255,0.12)",
            "progress_fg": "#72ffd9",
        },
        "fonts": {
            "title": "",
            "chapter": "",
            "ui": "",
            "fallback": "Arial",
        },
        "objects": [
            {
                "id": "background",
                "type": "image",
                "source": "background",
                "x": 0,
                "y": 0,
                "w": 1920,
                "h": 1080,
                "fit": "cover",
                "opacity": 1.0,
                "z_index": 0,
            },
            {
                "id": "background_overlay",
                "type": "overlay",
                "color": "rgba(5,5,10,0.30)",
                "gradient": "linear-gradient(180deg, rgba(5,5,10,0.50) 0%, rgba(5,5,10,0.80) 100%)",
                "x": 0,
                "y": 0,
                "w": 1920,
                "h": 1080,
                "z_index": 1,
            },
            {
                "id": "cover",
                "type": "image",
                "source": "cover",
                "x": 112,
                "y": 158,
                "w": 520,
                "h": 520,
                "fit": "cover",
                "radius": 28,
                "shadow": True,
                "shadow_color": "#05050a",
                "shadow_offset": (0, 6),
                "shadow_blur": 32,
                "shadow_opacity": 0.6,
                "z_index": 2,
            },
            {
                "id": "bookTitle",
                "type": "text",
                "text": "Интимный протокол",
                "x": 700,
                "y": 145,
                "w": 1060,
                "h": 110,
                "font_size": 58,
                "font_weight": 900,
                "align": "left",
                "color": "theme.text",
                "letter_spacing": 1,
                "z_index": 3,
            },
            {
                "id": "chapterNumber",
                "type": "text",
                "text": "Глава {n}",
                "x": 700,
                "y": 268,
                "w": 1060,
                "h": 40,
                "font_size": 22,
                "font_weight": 600,
                "align": "left",
                "color": "theme.accent_2",
                "letter_spacing": 2,
                "z_index": 3,
            },
            {
                "id": "currentChapter",
                "type": "chapter_title",
                "x": 700,
                "y": 310,
                "w": 1060,
                "h": 200,
                "font_size": 44,
                "auto_fit": True,
                "max_lines": 3,
                "color": "theme.accent",
                "z_index": 3,
            },
            {
                "id": "waveform",
                "type": "waveform",
                "x": 700,
                "y": 610,
                "w": 1060,
                "h": 145,
                "style": "bars",
                "bars": 160,
                "color": "theme.waveform_unplayed",
                "played_color": "theme.waveform_played",
                "opacity": 0.9,
                "z_index": 4,
            },
            {
                "id": "progress",
                "type": "progress_bar",
                "x": 112,
                "y": 905,
                "w": 1696,
                "h": 18,
                "radius": 9,
                "bg": "theme.progress_bg",
                "fg": "theme.progress_fg",
                "z_index": 5,
            },
            {
                "id": "timeDisplay",
                "type": "text",
                "text": "{time} / {total}",
                "x": 112,
                "y": 870,
                "w": 400,
                "h": 30,
                "font_size": 20,
                "align": "left",
                "color": "theme.muted",
                "opacity": 0.7,
                "z_index": 5,
            },
            {
                "id": "chapterProgress",
                "type": "text",
                "text": "Chapter {n} / {total_chapters}",
                "x": 1408,
                "y": 870,
                "w": 400,
                "h": 30,
                "font_size": 20,
                "align": "right",
                "color": "theme.muted",
                "opacity": 0.7,
                "z_index": 5,
            },
            {
                "id": "brand",
                "type": "text",
                "text": "Monsieur Souveraineté / BookForge Studio",
                "x": 112,
                "y": 958,
                "w": 1696,
                "h": 42,
                "font_size": 26,
                "align": "center",
                "color": "theme.muted",
                "opacity": 0.70,
                "z_index": 5,
            },
        ],
        "render": {
            "quality": "youtube_high",
            "codec": "libx264",
            "crf": 18,
            "preset": "slow",
            "audio_codec": "aac",
            "audio_bitrate": "256k",
            "pixel_format": "yuv420p",
            "movflags": "+faststart",
        },
    }


def save_layout(path: Path, layout: dict) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Layout saved: {path}")


def load_layout(path: Path) -> dict:
    if not path.exists():
        fail(f"Layout not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


# ── Font Utils ────────────────────────────────────────────────────

def find_font(layout_fonts: dict, data_dir: Path) -> Optional[Path]:
    """Try to find a TTF font with Cyrillic support."""
    # Check fonts specified in layout
    for key in ["title", "chapter", "ui"]:
        f = layout_fonts.get(key, "")
        if f:
            fp = Path(f)
            if fp.exists():
                return fp
            # Maybe in data/fonts
            fp2 = data_dir / "fonts" / f
            if fp2.exists():
                return fp2
            # Maybe in fonts directory
            fp3 = Path("fonts") / f
            if fp3.exists():
                return fp3

    # Check data/fonts directory
    fonts_dir = data_dir / "fonts"
    if fonts_dir.exists():
        ttf = sorted(fonts_dir.glob("*.ttf")) + sorted(fonts_dir.glob("*.otf"))
        if ttf:
            return ttf[0]

    # Windows fonts with Cyrillic
    win_fonts = [
        Path(os.environ.get("SystemRoot", "C:\\Windows")) / "Fonts" / "segoeui.ttf",
        Path(os.environ.get("SystemRoot", "C:\\Windows")) / "Fonts" / "arial.ttf",
        Path(os.environ.get("SystemRoot", "C:\\Windows")) / "Fonts" / "Calibri.ttf",
        Path(os.environ.get("SystemRoot", "C:\\Windows")) / "Fonts" / "DejaVuSans.ttf",
        Path(os.environ.get("SystemRoot", "C:\\Windows")) / "Fonts" / "times.ttf",
        Path(os.environ.get("SystemRoot", "C:\\Windows")) / "Fonts" / "consola.ttf",
    ]
    for fp in win_fonts:
        if fp.exists():
            return fp

    # Last resort: check fonts/ locally
    local_fonts = sorted(Path("fonts").glob("*.ttf")) + sorted(Path("fonts").glob("*.otf"))
    if local_fonts:
        return local_fonts[0]

    return None


def resolve_font_path(layout: dict, data_dir: Path) -> Optional[Path]:
    fonts_cfg = layout.get("fonts", {})
    return find_font(fonts_cfg, data_dir)


# ── Waveform Generator ────────────────────────────────────────────

def resolve_color_value(val: str, theme: dict, default: str = "#ffffff") -> str:
    """Resolve a color value string that may be a theme reference like 'theme.accent'."""
    if isinstance(val, str) and val.startswith("theme."):
        key = val.split(".", 1)[1]
        return theme.get(key, default)
    if isinstance(val, str) and val.startswith("rgba"):
        return val
    return val

def resolve_color(obj: dict, theme: dict, key_name: str = "color", default: str = "#ffffff") -> str:
    """Resolve a color from an object's field, supporting theme references."""
    val = obj.get(key_name, default)
    return resolve_color_value(val, theme, default)


def generate_waveform(audio_path: Path, samples: int = 2000) -> Optional[dict]:
    """Generate waveform data using ffmpeg. Low-memory: decodes at very low sample rate."""
    if not audio_path.exists():
        warn(f"Audio not found: {audio_path}")
        return None

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        warn("ffmpeg not found, cannot generate waveform")
        return None

    # Get duration
    duration = ffprobe_duration(audio_path)
    if duration is None or duration <= 0:
        warn("Could not determine audio duration")
        return None

    import struct
    import tempfile

    # Strategy: decode at very low sample rate (~200 Hz) to get ~3M raw samples = ~6MB for 15h audio
    # Then downsample to requested number
    LOW_AR = 200  # 200 Hz gives ~200 samples/sec * 56955s = ~11.4M samples = ~22MB, acceptable
    bytes_per_sample = 2  # s16le

    raw_expected = int(duration * LOW_AR)
    step = max(1, raw_expected // samples)

    try:
        log(f"Decoding audio at {LOW_AR} Hz (target: ~{raw_expected//1000}K raw samples)...")
        
        with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as tmp:
            raw_path = tmp.name

        # Use shell=True on Windows to handle cyrillic filenames (ffmpeg 69 error)
        cmd_str = f'"{ffmpeg}" -y -v error -i "{audio_path}" -ac 1 -ar {LOW_AR} -f s16le "{raw_path}"'
        subprocess.run(cmd_str, check=True, capture_output=True, timeout=600, shell=True)

        raw_size = Path(raw_path).stat().st_size
        total_raw_samples = raw_size // bytes_per_sample
        if total_raw_samples == 0:
            warn("No audio samples decoded")
            return None

        # Memory-map the file to avoid loading all at once
        import mmap
        with open(raw_path, "rb") as f:
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                fmt = f"<{total_raw_samples}h"
                try:
                    samples_all = struct.unpack(fmt, mm[:total_raw_samples * 2])
                except struct.error as e:
                    warn(f"Struct unpack error: {e}")
                    return None

        del mm  # release mmap

        # Downsample: take peak per segment
        downsampled = []
        step = max(1, len(samples_all) // samples)
        for i in range(0, len(samples_all), step):
            chunk = samples_all[i:i + step]
            if chunk:
                peak = max(abs(s) for s in chunk) / 32768.0
                downsampled.append(peak)

        if not downsampled:
            warn("No waveform samples after downsampling")
            return None

        # Normalize
        max_val = max(downsampled)
        if max_val > 0:
            normalized = [min(1.0, v / max_val) for v in downsampled]
        else:
            normalized = [0.0] * len(downsampled)

        result = {
            "version": 1,
            "audio": str(audio_path),
            "duration": duration,
            "samples": normalized,
            "sample_count": len(normalized),
        }
        log(f"Waveform generated: {len(normalized)} samples from {seconds_to_timecode(duration)} audio")
        return result

    except subprocess.TimeoutExpired:
        warn("Waveform generation timed out")
        return None
    except Exception as e:
        warn(f"Waveform generation error: {e}")
        return None
    finally:
        try:
            Path(raw_path).unlink(missing_ok=True)
        except Exception:
            pass


def save_waveform(path: Path, data: dict) -> None:
    if data is None:
        warn("No waveform data to save")
        return
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Waveform saved: {path}")


def load_waveform(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# ── Preview Renderer ──────────────────────────────────────────────

def render_preview(
    layout: dict,
    config: dict,
    chapter: Chapter,
    chapter_index: int,
    total_chapters: int,
    out_path: Path,
    waveform_data: Optional[dict] = None,
    font_path: Optional[Path] = None,
) -> None:
    """Render single frame using layout-driven composition."""
    from PIL import Image, ImageDraw, ImageFont

    scene = layout.get("scene", {})
    W = scene.get("width", DEFAULT_WIDTH)
    H = scene.get("height", DEFAULT_HEIGHT)
    theme = layout.get("theme", {})
    objects = layout.get("objects", [])

    # Sort by z_index
    objects_sorted = sorted(objects, key=lambda o: o.get("z_index", 0))

    # Create base canvas
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Resolve paths from config
    data_dir = Path(config.get("data_dir", DATA_DIR_DEFAULT))
    cover_path = Path(config.get("cover", "")) if config.get("cover") else None
    bg_path = Path(config.get("background", "")) if config.get("background") else None

    # Load background image
    bg_img = None
    if bg_path and bg_path.exists():
        try:
            bg_img = Image.open(bg_path).convert("RGBA")
            bg_img = bg_img.resize((W, H), Image.LANCZOS)
        except Exception:
            bg_img = None

    # Load cover image
    cover_img = None
    if cover_path and cover_path.exists():
        try:
            cover_img = Image.open(cover_path).convert("RGBA")
        except Exception:
            cover_img = None

    # Font loading
    font_title = ImageFont.load_default()
    font_chapter = ImageFont.load_default()
    font_ui = ImageFont.load_default()

    if font_path and font_path.exists():
        try:
            # Try multiple sizes
            font_title = ImageFont.truetype(str(font_path), size=58)
            font_chapter = ImageFont.truetype(str(font_path), size=44)
            font_ui = ImageFont.truetype(str(font_path), size=22)
        except Exception:
            pass

    # Process each object
    for obj in objects_sorted:
        obj_type = obj.get("type", "")
        obj_id = obj.get("id", "")

        if obj_type == "image":
            source = obj.get("source", "")
            src_path = None
            if source == "background":
                src_img = bg_img
            elif source == "cover":
                src_img = cover_img
            else:
                # Custom source from config or path
                sp = Path(source)
                if sp.exists():
                    try:
                        src_img = Image.open(sp).convert("RGBA")
                    except Exception:
                        src_img = None
                else:
                    src_img = None

            if src_img is None:
                continue

            ox = obj.get("x", 0)
            oy = obj.get("y", 0)
            ow = obj.get("w", W)
            oh = obj.get("h", H)
            fit = obj.get("fit", "cover")
            opacity = obj.get("opacity", 1.0)

            # Resize
            resized = src_img.resize((ow, oh), Image.LANCZOS)

            # Apply opacity
            if opacity < 1.0:
                r, g, b, a = resized.split()
                a = a.point(lambda x: int(x * opacity))
                resized = Image.merge("RGBA", (r, g, b, a))

            # Rounded corners
            radius = obj.get("radius", 0)
            if radius > 0:
                mask = Image.new("RGBA", (ow, oh), (0, 0, 0, 0))
                mdraw = ImageDraw.Draw(mask)
                mdraw.rounded_rectangle([(0, 0), (ow, oh)], radius=radius, fill=(255, 255, 255, 255))
                img.paste(resized, (ox, oy), mask=mask)
            else:
                img.paste(resized, (ox, oy), resized)

            # Shadow
            if obj.get("shadow", False) and source == "cover":
                shadow_color = obj.get("shadow_color", "#05050a")
                shadow_offset = obj.get("shadow_offset", (0, 6))
                shadow_blur = obj.get("shadow_blur", 32)
                shadow_opacity = obj.get("shadow_opacity", 0.6)
                sx, sy = shadow_offset
                # Simple shadow: dark rectangle behind
                shadow_layer = Image.new("RGBA", (ow + shadow_blur, oh + shadow_blur), (0, 0, 0, 0))
                sdraw = ImageDraw.Draw(shadow_layer)
                # Parse shadow color
                try:
                    sc = shadow_color.lstrip("#")
                    sr, sg, sb = int(sc[0:2], 16), int(sc[2:4], 16), int(sc[4:6], 16)
                except Exception:
                    sr, sg, sb = 5, 5, 10
                sa = int(255 * shadow_opacity)
                sdraw.rounded_rectangle(
                    [(shadow_blur // 2, shadow_blur // 2), (ow + shadow_blur // 2, oh + shadow_blur // 2)],
                    radius=radius or 0, fill=(sr, sg, sb, sa)
                )
                img.paste(shadow_layer, (ox - shadow_blur // 2 + sx, oy - shadow_blur // 2 + sy), shadow_layer)

        elif obj_type == "overlay":
            # Semi-transparent overlay (e.g. gradient simulation)
            ox = obj.get("x", 0)
            oy = obj.get("y", 0)
            ow = obj.get("w", W)
            oh = obj.get("h", H)
            overlay = Image.new("RGBA", (ow, oh), (5, 5, 10, 76))  # ~30% opacity
            img.paste(overlay, (ox, oy), overlay)

        elif obj_type == "text":
            ox = obj.get("x", 0)
            oy = obj.get("y", 0)
            ow = obj.get("w", 200)
            oh = obj.get("h", 50)
            align = obj.get("align", "left")
            color_val = resolve_color(obj, theme, "#ffffff")
            font_size = obj.get("font_size", 24)
            opacity = obj.get("opacity", 1.0)

            # Build text
            text = obj.get("text", "")
            # Substitute variables
            text = text.replace("{n}", str(chapter_index + 1))
            text = text.replace("{total_chapters}", str(total_chapters))
            text = text.replace("{time}", seconds_to_timecode(chapter.start_seconds, millis=False))
            text = text.replace("{total}", seconds_to_timecode(
                chapters[-1].end_seconds if 'chapters' in dir() and chapters else chapter.end_seconds,
                millis=False
            ))

            # Parse color
            try:
                if color_val.startswith("#"):
                    c = color_val.lstrip("#")
                    if len(c) == 6:
                        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
                        a = int(255 * opacity)
                    else:
                        r, g, b, a = 255, 255, 255, int(255 * opacity)
                elif color_val.startswith("rgba"):
                    parts = color_val.strip("rgba()").split(",")
                    r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
                    a_val = float(parts[3]) * opacity
                    a = int(255 * min(1.0, a_val))
                else:
                    r, g, b, a = 255, 255, 255, int(255 * opacity)
            except Exception:
                r, g, b, a = 255, 255, 255, int(255 * opacity)

            # Select font based on context
            if obj_id == "bookTitle":
                fnt = font_title
            elif obj_id in ("currentChapter", "chapterNumber"):
                fnt = font_chapter
            else:
                fnt = font_ui

            # Handle position
            if align == "left":
                pos = (ox, oy)
            elif align == "center":
                # Measure text
                try:
                    bbox = draw.textbbox((0, 0), text, font=fnt)
                    tw = bbox[2] - bbox[0]
                except Exception:
                    tw = len(text) * font_size * 0.6
                pos = (ox + (ow - tw) // 2, oy)
            elif align == "right":
                try:
                    bbox = draw.textbbox((0, 0), text, font=fnt)
                    tw = bbox[2] - bbox[0]
                except Exception:
                    tw = len(text) * font_size * 0.6
                pos = (ox + ow - tw, oy)
            else:
                pos = (ox, oy)

            draw.text(pos, text, fill=(r, g, b, a), font=fnt)

        elif obj_type == "chapter_title":
            # Special: draw chapter title with auto-fit
            ox = obj.get("x", 0)
            oy = obj.get("y", 0)
            ow = obj.get("w", 1060)
            oh = obj.get("h", 200)
            color_val = resolve_color(obj, theme, "#72ffd9")
            max_lines = obj.get("max_lines", 3)
            auto_fit = obj.get("auto_fit", True)

            title = chapter.title.strip()
            # Clean title: remove file extensions, chapter numbers
            title_clean = re.sub(r'^\d+\s*[-–—]\s*', '', title)
            title_clean = re.sub(r'\.mp3$', '', title_clean)
            title_clean = title_clean.strip()

            # Parse color
            try:
                if color_val.startswith("#"):
                    c = color_val.lstrip("#")
                    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
                else:
                    r, g, b = 114, 255, 217
            except Exception:
                r, g, b = 114, 255, 217

            # Try to fit text
            font_size = obj.get("font_size", 44)
            fnt = ImageFont.load_default()
            if font_path and font_path.exists():
                try:
                    fnt = ImageFont.truetype(str(font_path), size=font_size)
                except Exception:
                    pass

            # Word wrap
            lines = textwrap.wrap(title_clean, width=50)
            if len(lines) > max_lines:
                lines = lines[:max_lines]
                lines[-1] = lines[-1] + "..."

            line_h = font_size + 8
            for i, line in enumerate(lines):
                ly = oy + i * line_h
                draw.text((ox, ly), line, fill=(r, g, b, 255), font=fnt)

        elif obj_type == "waveform":
            ox = obj.get("x", 0)
            oy = obj.get("y", 0)
            ow = obj.get("w", 1060)
            oh = obj.get("h", 145)
            bar_count = obj.get("bars", 160)
            color = resolve_color(obj, theme, "color", "#b69aff")
            played_color = resolve_color(obj, theme, "played_color", "#72ffd9")
            opacity = obj.get("opacity", 0.9)

            try:
                if color.startswith("#"):
                    c = color.lstrip("#")
                    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
                else:
                    r, g, b = 182, 154, 255
            except Exception:
                r, g, b = 182, 154, 255

            # Waveform data
            samples = []
            if waveform_data:
                samples = waveform_data.get("samples", [])

            if samples:
                # Map samples to bars
                step = max(1, len(samples) // bar_count)
                bar_samples = []
                for i in range(0, min(len(samples), bar_count * step), step):
                    chunk = samples[i:i + step]
                    bar_samples.append(sum(chunk) / len(chunk) if chunk else 0)

                # Pad or trim
                while len(bar_samples) < bar_count:
                    bar_samples.append(0)
                bar_samples = bar_samples[:bar_count]
            else:
                # Deterministic fake waveform
                import random as rnd_module
                rnd_obj = rnd_module.Random(chapter.start_seconds)
                bar_samples = [rnd_obj.random() * 0.6 + 0.2 for _ in range(bar_count)]

            bar_w = max(2, ow // bar_count - 1)
            for i, val in enumerate(bar_samples):
                bx = ox + i * (bar_w + 1)
                bh = max(2, int(oh * val * 0.9))
                by = oy + (oh - bh) // 2
                draw.rectangle([(bx, by), (bx + bar_w, by + bh)], fill=(r, g, b, int(255 * opacity)))

        elif obj_type == "progress_bar":
            ox = obj.get("x", 0)
            oy = obj.get("y", 0)
            ow = obj.get("w", 1696)
            oh = obj.get("h", 18)
            radius = obj.get("radius", 9)
            bg_color = resolve_color(obj, theme, "rgba(255,255,255,0.12)")
            fg_color = resolve_color(obj, theme, "#72ffd9")
            opacity = obj.get("opacity", 1.0)

            # Parse bg color
            try:
                if bg_color.startswith("rgba"):
                    parts = bg_color.strip("rgba()").split(",")
                    bg_r, bg_g, bg_b = int(parts[0]), int(parts[1]), int(parts[2])
                    bg_a = int(float(parts[3]) * 255)
                elif bg_color.startswith("#"):
                    c = bg_color.lstrip("#")
                    bg_r, bg_g, bg_b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
                    bg_a = 40
                else:
                    bg_r, bg_g, bg_b, bg_a = 255, 255, 255, 40
            except Exception:
                bg_r, bg_g, bg_b, bg_a = 255, 255, 255, 40

            try:
                if fg_color.startswith("#"):
                    c = fg_color.lstrip("#")
                    fg_r, fg_g, fg_b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
                else:
                    fg_r, fg_g, fg_b = 114, 255, 217
            except Exception:
                fg_r, fg_g, fg_b = 114, 255, 217

            # Background bar
            draw.rounded_rectangle(
                [(ox, oy), (ox + ow, oy + oh)],
                radius=radius, fill=(bg_r, bg_g, bg_b, bg_a)
            )

            # Progress fill
            progress = chapter_index / max(1, total_chapters - 1)
            fg_w = int(ow * progress)
            if fg_w > 0:
                draw.rounded_rectangle(
                    [(ox, oy), (ox + fg_w, oy + oh)],
                    radius=radius, fill=(fg_r, fg_g, fg_b, 255)
                )

    # Save
    img.convert("RGB").save(out_path, "PNG")
    log(f"Preview saved: {out_path}")


# ── Contact Sheet ─────────────────────────────────────────────────

def render_contact_sheet(
    layout: dict,
    config: dict,
    chapters: list[Chapter],
    out_path: Path,
    font_path: Optional[Path] = None,
) -> None:
    """Render a 2×2 contact sheet with 4 key frames."""
    from PIL import Image

    indices = [0, max(0, len(chapters) // 4), max(0, len(chapters) // 2), len(chapters) - 1]
    panels = []
    scene = layout.get("scene", {})
    W = scene.get("width", DEFAULT_WIDTH)
    H = scene.get("height", DEFAULT_HEIGHT)

    for idx in indices:
        tmp = out_path.parent / f"_contact_{idx}.png"
        render_preview(
            layout=layout,
            config=config,
            chapter=chapters[idx],
            chapter_index=idx,
            total_chapters=len(chapters),
            out_path=tmp,
            font_path=font_path,
        )
        panels.append(tmp)

    # Compose 2×2
    half_w = W // 2
    half_h = H // 2
    sheet = Image.new("RGB", (W, H), (0, 0, 0))

    positions = [(0, 0), (half_w, 0), (0, half_h), (half_w, half_h)]
    for panel_path, (px, py) in zip(panels, positions):
        try:
            pimg = Image.open(panel_path).resize((half_w, half_h), Image.LANCZOS)
            sheet.paste(pimg, (px, py))
        except Exception:
            pass

    sheet.save(out_path, "PNG")
    log(f"Contact sheet saved: {out_path}")

    # Cleanup temp panels
    for p in panels:
        try:
            p.unlink()
        except Exception:
            pass


# ── Locks ─────────────────────────────────────────────────────────

def check_lock(build_dir: Path) -> bool:
    lock = build_dir / RENDER_LOCK
    return lock.exists()


def create_lock(build_dir: Path) -> None:
    lock = build_dir / RENDER_LOCK
    lock.write_text(json.dumps({
        "pid": os.getpid(),
        "started": time.time(),
        "host": os.uname().nodename if hasattr(os, 'uname') else "windows",
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def release_lock(build_dir: Path) -> None:
    lock = build_dir / RENDER_LOCK
    try:
        lock.unlink()
    except Exception:
        pass


# ── Video Renderer ────────────────────────────────────────────────

def build_ffmpeg_command(
    audio_path: Path,
    chapters: list[Chapter],
    chapter_index: int,
    panel_path: Path,
    out_path: Path,
    fps: int = DEFAULT_FPS,
    crf: int = 18,
    preset: str = "slow",
    audio_bitrate: str = "256k",
    duration: Optional[float] = None,
) -> list[str]:
    """Build ffmpeg command for a single chapter panel + audio segment."""
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(panel_path),
        "-i", str(audio_path),
        "-c:v", "libx264",
        "-t", str(duration) if duration else str(chapters[chapter_index].duration_seconds),
        "-vf", f"scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p",
        "-r", str(fps),
        "-preset", preset,
        "-crf", str(crf),
        "-c:a", "aac",
        "-b:a", audio_bitrate,
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-ss", str(chapters[chapter_index].start_seconds),
        "-to", str(chapters[chapter_index].end_seconds) if duration is None else str(chapters[chapter_index].start_seconds + duration),
        str(out_path),
    ]
    return cmd


def render_video(
    config: dict,
    chapters: list[Chapter],
    layout: dict,
    build_dir: Path,
    out_path: Path,
    max_duration: Optional[float] = None,
    log_path: Optional[Path] = None,
    progress_callback=None,
) -> bool:
    """Render video by generating one panel per chapter and concatting via ffmpeg."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        fail("ffmpeg not found. Install ffmpeg and add to PATH.")

    if not config.get("audio"):
        fail("No audio configured. Run 'scan' first.")

    audio_path = Path(config["audio"])
    if not audio_path.exists():
        fail(f"Audio not found: {audio_path}")

    if not chapters:
        fail("No chapters to render. Run 'chapters' first.")

    # Resolve font
    font_path = resolve_font_path(layout, Path(config.get("data_dir", DATA_DIR_DEFAULT)))

    # Render panels for each chapter
    panels_dir = build_dir / "panels_render"
    ensure_dir(panels_dir)

    # Determine which chapters to render
    total_duration = sum(c.duration_seconds for c in chapters)
    duration_so_far = 0.0
    render_chapters = []
    for c in chapters:
        if max_duration is not None and duration_so_far >= max_duration:
            break
        render_chapters.append(c)
        duration_so_far += c.duration_seconds

    if not render_chapters:
        fail("No chapters to render after duration filter")

    log(f"Rendering {len(render_chapters)}/{len(chapters)} chapters ({seconds_to_timecode(duration_so_far)} total)")

    # Render panels
    for i, ch in enumerate(render_chapters):
        panel_out = panels_dir / f"chapter_{i:03d}.png"
        log(f"Panel {i+1}/{len(render_chapters)}: {ch.title}")

        duration = None
        if max_duration is not None:
            remaining = max_duration - sum(c.duration_seconds for c in render_chapters[:i])
            ch_duration = ch.duration_seconds
            if remaining < ch_duration:
                duration = remaining
            else:
                duration = ch_duration
            if duration <= 0:
                break

        render_preview(
            layout=layout,
            config=config,
            chapter=ch,
            chapter_index=i,
            total_chapters=len(render_chapters),
            out_path=panel_out,
            font_path=font_path,
        )

        if progress_callback:
            progress_callback(i + 1, len(render_chapters))

    # Render each chapter as video segment
    segments_dir = build_dir / "segments"
    ensure_dir(segments_dir)
    segment_files = []

    for i, ch in enumerate(render_chapters):
        panel_path = panels_dir / f"chapter_{i:03d}.png"
        seg_path = segments_dir / f"seg_{i:03d}.mp4"

        if not panel_path.exists():
            warn(f"Panel not found: {panel_path}, skipping")
            continue

        cmd = build_ffmpeg_command(
            audio_path=audio_path,
            chapters=render_chapters,
            chapter_index=i,
            panel_path=panel_path,
            out_path=seg_path,
        )

        log(f"Encoding segment {i+1}/{len(render_chapters)}: {ch.title}")
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=3600)
        except subprocess.CalledProcessError as e:
            warn(f"Failed to render segment {i}: {e}")
            warn(f"ffmpeg stderr: {e.stderr.decode('utf-8', errors='replace') if e.stderr else 'N/A'}")
            continue
        except subprocess.TimeoutExpired:
            warn(f"Segment {i} timed out")
            continue

        segment_files.append(seg_path)

    if not segment_files:
        fail("No segments were rendered successfully")

    # Concat all segments
    if len(segment_files) == 1:
        shutil.copy(segment_files[0], out_path)
        log(f"Single segment copied to: {out_path}")
    else:
        concat_file = build_dir / "concat_list.txt"
        with concat_file.open("w", encoding="utf-8") as f:
            for seg in segment_files:
                f.write(f"file '{seg}'\n")

        concat_cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy",
            str(out_path),
        ]
        log(f"Concatenating {len(segment_files)} segments...")
        try:
            subprocess.run(concat_cmd, check=True, capture_output=True, timeout=3600)
            log(f"Output: {out_path}")
        except subprocess.CalledProcessError as e:
            warn(f"Concat failed: {e}")
            warn(f"ffmpeg stderr: {e.stderr.decode('utf-8', errors='replace') if e.stderr else 'N/A'}")
            return False
        except subprocess.TimeoutExpired:
            warn("Concat timed out")
            return False

    return True


# ── Doctor ─────────────────────────────────────────────────────────

def cmd_doctor(args: argparse.Namespace) -> None:
    """Check environment for required tools and files."""
    data_dir = Path(args.data)
    build = build_dir(Path(args.build_dir)) if args.build_dir else build_dir()

    issues = 0

    # Python version
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}"
    print(f"[{'OK' if sys.version_info >= (3, 8) else 'WARN'}] Python {py_ver}")

    # ffmpeg
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        ok(f"ffmpeg found: {ffmpeg}")
    else:
        warn_msg("ffmpeg not found. Install ffmpeg and add to PATH.")
        issues += 1

    # ffprobe
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        ok(f"ffprobe found: {ffprobe}")
    else:
        warn_msg("ffprobe not found")
        issues += 1

    # Pillow
    try:
        import PIL
        ok(f"Pillow installed (PIL {PIL.__version__})")
    except ImportError:
        warn_msg("Pillow not installed. Run: pip install pillow")
        issues += 1

    # Data directory
    if data_dir.exists():
        ok(f"data folder found: {data_dir}")
    else:
        warn_msg(f"Data folder not found: {data_dir}. Create a 'data/' directory with your book files.")
        issues += 1

    # Build directory writable
    try:
        ensure_dir(build)
        test_file = build / ".write_test"
        test_file.write_text("test")
        test_file.unlink()
        ok(f"Build directory writable: {build}")
    except Exception:
        warn_msg(f"Cannot write to build directory: {build}")
        issues += 1

    # suviren_q.py compiles
    try:
        import py_compile
        py_compile.compile("suviren_q.py", doraise=True)
        ok("suviren_q.py compiles")
    except py_compile.PyCompileError as e:
        warn_msg(f"suviren_q.py compile error: {e}")
        issues += 1

    # Scan data
    scan = scan_data(data_dir)

    if scan.audio:
        ok(f"audio: {scan.audio}")
    else:
        warn_msg("Audio not found in data/. Place .mp3/.wav file.")
        issues += 1

    if scan.cover:
        ok(f"cover: {scan.cover}")
    else:
        warn_msg("Cover image not found in data/. Place cover.png/jpg.")
        issues += 1

    if scan.background:
        ok(f"background: {scan.background}")
    else:
        warn_msg("Background not found in data/. Optional but recommended.")

    if scan.rpp:
        ok(f"rpp: {scan.rpp}")
    else:
        warn_msg("RPP file not found in data/. Place .rpp REAPER project.")
        issues += 1

    # Summary
    print()
    if issues == 0:
        ok("All checks passed. Project is ready to render.")
    else:
        warn_msg(f"{issues} issue(s) found. Fix them before rendering.")
        print(f"  Tip: Place book files in {data_dir}/ directory:")
        print(f"    - audio: .mp3, .wav, .m4a, .flac")
        print(f"    - cover: square image (png/jpg)")
        print(f"    - background: 16:9 image (png/jpg)")
        print(f"    - rpp: REAPER project file")


# ── Scan ───────────────────────────────────────────────────────────

def cmd_scan(args: argparse.Namespace) -> None:
    """Scan data directory and save project config."""
    data_dir = Path(args.data)
    build = Path(args.build_dir) if args.build_dir else build_dir()
    config_path = Path(args.config)

    if not data_dir.exists():
        warn(f"Data directory not found: {data_dir}")
        info("Create the directory and place your book files inside.")
        return

    scan = scan_data(data_dir)
    print_scan_table(scan)

    chapters_path = build / "chapters.detected.json"
    config = default_project_config(data_dir, build, scan, chapters_path)

    save_project_config(config_path, config)

    if scan.is_complete():
        ok("Project scan complete. Ready for next steps.")
    else:
        warn_msg("Some resources are missing. See table above.")
        info(f"Place missing files in {data_dir}/ and re-run 'scan'.")


# ── Chapters ───────────────────────────────────────────────────────

def cmd_chapters(args: argparse.Namespace) -> None:
    """Extract chapters from RPP and save."""
    config_path = Path(args.config)

    if config_path.exists():
        config = load_project_config(config_path)
        data_dir = Path(config.get("data_dir", DATA_DIR_DEFAULT))
        build = Path(config.get("build_dir", BUILD_DIR_NAME))
    else:
        data_dir = Path(args.data)
        build = Path(args.build_dir) if args.build_dir else build_dir()

    ensure_dir(build)

    # Find RPP
    if config_path.exists() and config.get("rpp"):
        rpp_path = Path(config["rpp"])
    else:
        scan = scan_data(data_dir)
        if not scan.rpp:
            fail("No RPP file found. Run 'scan' first or place .rpp in data/.")
        rpp_path = scan.rpp
        # Save scan results
        chapters_path = build / "chapters.detected.json"
        cfg = default_project_config(data_dir, build, scan, chapters_path)
        save_project_config(config_path, cfg)

    if not rpp_path.exists():
        fail(f"RPP file not found: {rpp_path}")

    # Parse RPP
    report = parse_rpp(rpp_path)
    chapters = detect_chapters_from_rpp(
        report,
        rpp_track=args.rpp_track,
        chapter_pattern=args.chapter_pattern,
        add_intro=args.add_intro,
        origin=args.origin,
        end_mode=args.end_mode,
        offset=args.offset,
        min_item_length=args.min_item_length,
    )

    # Save
    chapters_path = build / "chapters.detected.json"
    save_chapters(chapters_path, chapters)

    youtube_path = build / "youtube_chapters.txt"
    save_youtube_chapters(youtube_path, chapters)

    # Print summary
    total_dur = sum(c.duration_seconds for c in chapters)
    print()
    print(f"  Chapters detected:   {len(chapters)}")
    print(f"  First segment:       {chapters[0].title}")
    print(f"  Last segment:        {chapters[-1].title}")
    print(f"  Total duration:      {seconds_to_timecode(total_dur)}")
    
    # Intro detection
    has_intro = any(ch.source in ("synthetic_intro", "auto_intro") for ch in chapters)
    first_book_idx = 1 if has_intro else 0
    if has_intro:
        print(f"  Intro detected:      YES")
        print(f"  Intro title:         {chapters[0].title}")
        print(f"  Intro start:         {seconds_to_timecode(chapters[0].start_seconds)}")
        print(f"  Intro end:           {seconds_to_timecode(chapters[0].end_seconds)}")
    else:
        print(f"  Intro detected:      NO")
    
    if first_book_idx < len(chapters):
        print(f"  First main chapter:  {chapters[first_book_idx].title} @ {seconds_to_timecode(chapters[first_book_idx].start_seconds)}")
    
    # Epilogue detection
    epilogue_ch = None
    for ch in chapters:
        if 'эпилог' in ch.title.lower() or 'epilog' in ch.title.lower() or 'epilogue' in ch.title.lower():
            epilogue_ch = ch
            break
    if epilogue_ch:
        print(f"  Epilogue detected:   YES")
        print(f"  Epilogue title:      {epilogue_ch.title}")
        print(f"  Epilogue start:      {seconds_to_timecode(epilogue_ch.start_seconds)}")
        print(f"  Epilogue end:        {seconds_to_timecode(epilogue_ch.end_seconds)}")
    else:
        print(f"  Epilogue detected:   NO")
    
    print()

    # Check for gaps
    gaps = []
    bridge_warnings = []
    for i in range(1, len(chapters)):
        gap = chapters[i].start_seconds - chapters[i - 1].end_seconds
        if abs(gap) > 0.5:
            if gap > 60:
                bridge_warnings.append((chapters[i-1].title, chapters[i].title, gap))
            gaps.append(gap)

    if not gaps:
        ok("No gaps between chapters (interval mode: next-start)")
    else:
        warn_msg(f"{len(gaps)} gap(s)/bridge(s) detected between chapters")
        for bw in bridge_warnings:
            warn_msg(f"Large bridge before '{bw[1]}': {bw[2]:.3f}s. Covered by previous segment using next-start mode.")
    
    # Bookends
    print(f"\n  Timeline: {seconds_to_timecode(chapters[0].start_seconds)} → {seconds_to_timecode(chapters[-1].end_seconds)}")
    print()

    # Save to config
    if config_path.exists():
        config = load_project_config(config_path)
        config["chapters"] = str(chapters_path)
        save_project_config(config_path, config)


# ── Preset ─────────────────────────────────────────────────────────

def cmd_preset(args: argparse.Namespace) -> None:
    """Generate layout preset from template file."""
    build = Path(args.build_dir) if args.build_dir else build_dir()
    ensure_dir(build)

    preset_name = args.preset_name
    layout_path = build / LAYOUT_FILE

    # Try external preset file first
    preset_file = Path("presets") / f"{preset_name}.json"
    if preset_file.exists():
        try:
            layout = json.loads(preset_file.read_text(encoding="utf-8"))
            info(f"Loaded preset template: {preset_file}")
        except Exception as e:
            fail(f"Failed to load preset template {preset_file}: {e}")
    elif preset_name == "zina-noir":
        # Fallback to hardcoded layout
        layout = build_zina_noir_layout()
    else:
        fail(f"Unknown preset: {preset_name}. Available: zina-noir (presets/zina-noir.json)")

    # Try to get project name from config
    config_path = Path(args.config)
    if config_path.exists():
        config = load_project_config(config_path)
        title_obj = next((o for o in layout.get("objects", []) if o["id"] == "bookTitle"), None)
        if title_obj:
            title_obj["text"] = config.get("project_name", "ЗИНА. Книга")

    save_layout(layout_path, layout)
    ok(f"Layout preset '{preset_name}' saved to {layout_path}")


# ── Waveform ───────────────────────────────────────────────────────

def cmd_waveform(args: argparse.Namespace) -> None:
    """Generate waveform data from audio."""
    config_path = Path(args.config)
    build = Path(args.build_dir) if args.build_dir else build_dir()
    ensure_dir(build)

    # Find audio
    if config_path.exists():
        config = load_project_config(config_path)
        audio_path = config.get("audio", "")
        if not audio_path:
            fail("No audio in project config. Run 'scan' first.")
        audio_path = Path(audio_path)
    else:
        data_dir = Path(args.data)
        scan = scan_data(data_dir)
        if not scan.audio:
            fail("No audio found. Run 'scan' first.")
        audio_path = scan.audio

    if not audio_path.exists():
        fail(f"Audio not found: {audio_path}")

    samples = args.samples
    data = generate_waveform(audio_path, samples=samples)

    if data:
        wf_path = build / WAVEFORM_FILE
        save_waveform(wf_path, data)

        # Update config
        if config_path.exists():
            config = load_project_config(config_path)
            config["waveform"] = str(wf_path)
            save_project_config(config_path, config)
    else:
        warn("Waveform generation failed")


# ── Preview ────────────────────────────────────────────────────────

def cmd_preview(args: argparse.Namespace) -> None:
    """Render preview PNG(s)."""
    config_path = Path(args.config)
    build = Path(args.build_dir) if args.build_dir else build_dir()
    ensure_dir(build)

    if not config_path.exists():
        fail("Project config not found. Run 'scan' first.")

    config = load_project_config(config_path)
    layout_path = Path(config.get("layout", ""))
    if not layout_path.exists():
        fail(f"Layout not found: {layout_path}. Run 'preset zina-noir' first.")

    layout = load_layout(layout_path)
    chapters_path = Path(config.get("chapters", ""))
    if not chapters_path.exists():
        fail(f"Chapters not found: {chapters_path}. Run 'chapters' first.")

    chapters = [Chapter(**{k: v for k, v in c.items() if k in ("title", "start_seconds", "end_seconds", "source", "raw_name", "file", "track")}) for c in json.loads(chapters_path.read_text(encoding="utf-8"))]
    chapters = normalize_chapters(chapters)

    if not chapters:
        fail("No chapters loaded")

    # Resolve font
    font_path = resolve_font_path(layout, Path(config.get("data_dir", DATA_DIR_DEFAULT)))

    # Load waveform
    waveform_path = Path(config.get("waveform", "")) if config.get("waveform") else build / WAVEFORM_FILE
    waveform_data = load_waveform(waveform_path) if waveform_path.exists() else None
    if not waveform_data:
        warn_msg("No waveform data loaded. Run 'waveform' for better preview.")

    contact = args.contact
    chapter_idx = args.chapter
    open_preview = args.open

    if contact:
        # Render contact sheet (4 frames)
        contact_path = build / CONTACT_PNG
        render_contact_sheet(
            layout=layout,
            config=config,
            chapters=chapters,
            out_path=contact_path,
            font_path=font_path,
        )
    else:
        # Render single preview
        if chapter_idx is not None:
            idx = max(0, min(len(chapters) - 1, chapter_idx))
        else:
            idx = 0

        preview_path = build / PREVIEW_PNG
        render_preview(
            layout=layout,
            config=config,
            chapter=chapters[idx],
            chapter_index=idx,
            total_chapters=len(chapters),
            out_path=preview_path,
            waveform_data=waveform_data,
            font_path=font_path,
        )

        if open_preview:
            try:
                os.startfile(preview_path)
            except Exception:
                try:
                    subprocess.run(["start", "", str(preview_path)], shell=True)
                except Exception:
                    pass


# ── Render Full ────────────────────────────────────────────────────

def cmd_render_full(args: argparse.Namespace) -> None:
    """Render full video for YouTube."""
    config_path = Path(args.config)
    build = Path(args.build_dir) if args.build_dir else build_dir()
    ensure_dir(build)

    if check_lock(build):
        fail("Render lock detected. Use 'clean-temp' if stuck.")

    if not args.force:
        # Check if output already exists
        full_out = build / FULL_MP4
        if full_out.exists():
            if not args.overwrite:
                warn(f"Output exists: {full_out}")
                info("Use --overwrite to overwrite or --force to force render.")
                return

    if not config_path.exists():
        fail("Project config not found. Run 'scan' first.")

    config = load_project_config(config_path)
    layout_path = Path(config.get("layout", ""))
    if not layout_path.exists():
        fail(f"Layout not found: {layout_path}. Run 'preset zina-noir' first.")

    layout = load_layout(layout_path)
    chapters_path = Path(config.get("chapters", ""))
    if not chapters_path.exists():
        fail(f"Chapters not found: {chapters_path}. Run 'chapters' first.")

    chapters = [Chapter(**{k: v for k, v in c.items() if k in ("title", "start_seconds", "end_seconds", "source", "raw_name", "file", "track")}) for c in json.loads(chapters_path.read_text(encoding="utf-8"))]
    chapters = normalize_chapters(chapters)

    if not chapters:
        fail("No chapters loaded")

    total_dur = sum(c.duration_seconds for c in chapters)
    log(f"Full render: {len(chapters)} chapters, {seconds_to_timecode(total_dur)} total")

    log_path = build / "render_full.log"

    create_lock(build)
    try:
        full_out = build / FULL_MP4
        success = render_video(
            config=config,
            chapters=chapters,
            layout=layout,
            build_dir=build,
            out_path=full_out,
            log_path=log_path,
        )
        if success:
            ok(f"Full render complete: {full_out}")
            size_mb = full_out.stat().st_size / (1024 * 1024)
            info(f"File size: {size_mb:.1f} MB")
        else:
            warn("Full render had errors")
    finally:
        release_lock(build)


# ── Clean Temp ─────────────────────────────────────────────────────

def cmd_clean_temp(args: argparse.Namespace) -> None:
    """Remove temporary files and lock."""
    build = Path(args.build_dir) if args.build_dir else build_dir()

    removed = []

    # Lock
    lock = build / RENDER_LOCK
    if lock.exists():
        lock.unlink()
        removed.append(str(lock))

    # Temp panels
    for d in ["panels", "panels_render", "segments"]:
        dp = build / d
        if dp.exists():
            for f in dp.iterdir():
                f.unlink()
            try:
                dp.rmdir()
            except Exception:
                pass
            removed.append(str(dp))

    # Temp contact panels
    for f in build.glob("_contact_*.png"):
        f.unlink()
        removed.append(str(f))

    # Concat list
    cl = build / "concat_list.txt"
    if cl.exists():
        cl.unlink()
        removed.append(str(cl))

    if removed:
        for r in removed:
            info(f"Removed: {r}")
    else:
        info("Nothing to clean")


# ═══════════════════════════════════════════════════════════════════
# Phase 2 — Report
# ═══════════════════════════════════════════════════════════════════

def _get_img_dimensions(path: Path) -> tuple[Optional[int], Optional[int]]:
    """Get image dimensions using Pillow."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:
        return (None, None)


def _get_file_size_mb(path: Path) -> float:
    return path.stat().st_size / (1024 * 1024)


def _ffprobe_duration_safe(path: Path) -> Optional[float]:
    """Try to get duration via ffprobe, return None on failure."""
    try:
        return ffprobe_duration(path)
    except Exception:
        return None


def _ffprobe_file_info(path: Path) -> dict:
    """Run ffprobe and return JSON info."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return {}
    try:
        cmd = [ffprobe, "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return json.loads(result.stdout)
    except Exception:
        return {}


def cmd_report(args: argparse.Namespace) -> None:
    """Generate project report (JSON + MD)."""
    config_path = Path(args.config)
    build = Path(args.build_dir) if args.build_dir else build_dir()
    data_dir = Path(args.data)
    ensure_dir(build)

    missing = []
    warnings = []

    # ── 1. Environment ────────────────────────────────────────────
    ffmpeg_path = shutil.which("ffmpeg") or ""
    ffprobe_path = shutil.which("ffprobe") or ""
    py_exe = sys.executable
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

    env = {
        "python_executable": py_exe,
        "python_version": py_ver,
        "ffmpeg_path": ffmpeg_path,
        "ffprobe_path": ffprobe_path,
        "project_root": str(Path.cwd()),
        "data_dir": str(data_dir),
        "build_dir": str(build),
    }
    if not ffmpeg_path:
        warnings.append("ffmpeg not found in PATH")

    # ── 2. Project files ──────────────────────────────────────────
    cfg = {}
    if config_path.exists():
        cfg = load_project_config(config_path)

    project_name = cfg.get("project_name", "Unknown")

    # Audio
    audio_info = {}
    audio_path_str = cfg.get("audio", "")
    if audio_path_str:
        ap = Path(audio_path_str)
        if ap.exists():
            dur = _ffprobe_duration_safe(ap)
            audio_info = {
                "path": str(ap),
                "exists": True,
                "size_mb": round(_get_file_size_mb(ap), 2),
                "duration_seconds": dur,
                "duration_str": seconds_to_timecode(dur) if dur else None,
            }
        else:
            audio_info = {"path": str(ap), "exists": False}
            missing.append("audio")
    else:
        missing.append("audio")

    # Cover
    cover_info = {}
    cover_path_str = cfg.get("cover", "")
    if cover_path_str:
        cp = Path(cover_path_str)
        if cp.exists():
            w, h = _get_img_dimensions(cp)
            cover_info = {
                "path": str(cp),
                "exists": True,
                "width": w,
                "height": h,
                "size_mb": round(_get_file_size_mb(cp), 2),
            }
        else:
            cover_info = {"path": str(cover_path_str), "exists": False}
            missing.append("cover")
    else:
        missing.append("cover")

    # Background
    bg_info = {}
    bg_path_str = cfg.get("background", "")
    if bg_path_str:
        bp = Path(bg_path_str)
        if bp.exists():
            w, h = _get_img_dimensions(bp)
            bg_info = {
                "path": str(bp),
                "exists": True,
                "width": w,
                "height": h,
                "size_mb": round(_get_file_size_mb(bp), 2),
            }
        else:
            bg_info = {"path": str(bg_path_str), "exists": False}
            warnings.append("background not found (optional)")
    else:
        warnings.append("background not configured (optional)")

    # RPP
    rpp_info = {}
    rpp_path_str = cfg.get("rpp", "")
    if rpp_path_str:
        rp = Path(rpp_path_str)
        if rp.exists():
            rpp_info = {
                "path": str(rp),
                "exists": True,
                "size_mb": round(_get_file_size_mb(rp), 2),
            }
        else:
            rpp_info = {"path": str(rpp_path_str), "exists": False}
            missing.append("rpp")
    else:
        missing.append("rpp")

    # Chapters
    chapters_info = {}
    chapters_path_str = cfg.get("chapters", "")
    if chapters_path_str:
        chp = Path(chapters_path_str)
        if chp.exists():
            try:
                ch_data = json.loads(chp.read_text(encoding="utf-8"))
                count = len(ch_data)
                first = ch_data[0].get("title", "?") if count > 0 else "?"
                last = ch_data[-1].get("title", "?") if count > 0 else "?"
                total_dur = sum(c.get("duration_seconds", 0) for c in ch_data)
                chapters_info = {
                    "path": str(chp),
                    "exists": True,
                    "count": count,
                    "first": first,
                    "last": last,
                    "total_duration_seconds": total_dur,
                    "total_duration_str": seconds_to_timecode(total_dur),
                }
            except Exception as e:
                chapters_info = {"path": str(chp), "exists": True, "error": str(e)}
        else:
            chapters_info = {"path": str(chapters_path_str), "exists": False}
            missing.append("chapters")
    else:
        missing.append("chapters")

    # Layout
    layout_info = {}
    layout_path = build / LAYOUT_FILE
    if layout_path.exists():
        try:
            lo = json.loads(layout_path.read_text(encoding="utf-8"))
            layout_info = {
                "path": str(layout_path),
                "exists": True,
                "preset_name": lo.get("name", "unknown"),
            }
        except Exception:
            layout_info = {"path": str(layout_path), "exists": True, "error": "parse error"}
    else:
        layout_info = {"path": str(layout_path), "exists": False}
        missing.append("layout")

    # Waveform
    waveform_info = {}
    wf_path = build / WAVEFORM_FILE
    if wf_path.exists():
        try:
            wf = json.loads(wf_path.read_text(encoding="utf-8"))
            waveform_info = {
                "path": str(wf_path),
                "exists": True,
                "sample_count": wf.get("sample_count", 0),
                "duration_seconds": wf.get("duration"),
            }
        except Exception:
            waveform_info = {"path": str(wf_path), "exists": True, "error": "parse error"}
    else:
        waveform_info = {"path": str(wf_path), "exists": False}
        warnings.append("waveform not generated (run 'waveform')")

    # Preview
    preview_info = {}
    pp = build / PREVIEW_PNG
    if pp.exists():
        w, h = _get_img_dimensions(pp)
        preview_info = {
            "path": str(pp),
            "exists": True,
            "width": w,
            "height": h,
            "size_mb": round(_get_file_size_mb(pp), 2),
        }
    else:
        preview_info = {"path": str(pp), "exists": False}
        warnings.append("preview.png not generated (run 'preview')")

    # Contact
    contact_info = {}
    cp = build / CONTACT_PNG
    if cp.exists():
        w, h = _get_img_dimensions(cp)
        contact_info = {
            "path": str(cp),
            "exists": True,
            "width": w,
            "height": h,
            "size_mb": round(_get_file_size_mb(cp), 2),
        }
    else:
        contact_info = {"path": str(cp), "exists": False}
        warnings.append("preview_contact.png not generated")

    # Test render output
    test_info = {}
    tp = build / TEST_MP4
    if tp.exists():
        info_data = _ffprobe_file_info(tp)
        fmt = info_data.get("format", {})
        dur_str = fmt.get("duration", "?")
        test_info = {
            "path": str(tp),
            "exists": True,
            "size_mb": round(_get_file_size_mb(tp), 2),
            "duration_seconds": float(fmt.get("duration", 0)),
        }
    else:
        test_info = {"path": str(tp), "exists": False}

    # Full render output
    full_info = {}
    fp = build / FULL_MP4
    if fp.exists():
        full_info = {
            "path": str(fp),
            "exists": True,
            "size_mb": round(_get_file_size_mb(fp), 2),
        }
    else:
        full_info = {"path": str(fp), "exists": False}

    # ── 3. Readiness ──────────────────────────────────────────────
    is_ready = len(missing) == 0

    # ── Build report ──────────────────────────────────────────────
    report = {
        "report_generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "project_name": project_name,
        "environment": env,
        "files": {
            "audio": audio_info,
            "cover": cover_info,
            "background": bg_info,
            "rpp": rpp_info,
            "chapters": chapters_info,
            "layout": layout_info,
            "waveform": waveform_info,
            "preview": preview_info,
            "preview_contact": contact_info,
            "test_output": test_info,
            "full_output": full_info,
        },
        "readiness": {
            "status": "READY" if is_ready else "NOT READY",
            "missing": missing,
            "warnings": warnings,
        },
        "next_commands": [
            "python bookforge.py preview --contact --open",
            "python bookforge.py render-test --overwrite",
            "python bookforge.py render-full  # only after test passes",
        ],
    }

    # Save JSON
    json_path = build / REPORT_JSON
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    ok(f"Report JSON saved: {json_path}")

    # Save Markdown
    md_path = build / REPORT_MD
    lines = []
    lines.append(f"# BookForge Report — {project_name}")
    lines.append(f"")
    lines.append(f"**Generated:** {report['report_generated']}")
    lines.append(f"**Status:** {'✅ READY' if is_ready else '❌ NOT READY'}")
    lines.append(f"")
    lines.append(f"## Environment")
    lines.append(f"")
    lines.append(f"| Item | Value |")
    lines.append(f"|------|-------|")
    lines.append(f"| Python | `{py_exe}` ({py_ver}) |")
    lines.append(f"| ffmpeg | `{ffmpeg_path}` |")
    lines.append(f"| ffprobe | `{ffprobe_path}` |")
    lines.append(f"| Project root | `{Path.cwd()}` |")
    lines.append(f"| Data dir | `{data_dir}` |")
    lines.append(f"| Build dir | `{build}` |")
    lines.append(f"")
    lines.append(f"## Project Files")
    lines.append(f"")
    lines.append(f"### Audio")
    if audio_info.get("exists"):
        lines.append(f"- **Path:** `{audio_info['path']}`")
        lines.append(f"- **Size:** {audio_info.get('size_mb', '?')} MB")
        lines.append(f"- **Duration:** {audio_info.get('duration_str', '?')}")
    else:
        lines.append(f"- ❌ Missing")
    lines.append(f"")

    lines.append(f"### Cover")
    if cover_info.get("exists"):
        lines.append(f"- **Path:** `{cover_info['path']}`")
        lines.append(f"- **Dimensions:** {cover_info.get('width', '?')}×{cover_info.get('height', '?')}")
    else:
        lines.append(f"- ❌ Missing")
    lines.append(f"")

    lines.append(f"### Background")
    if bg_info.get("exists"):
        lines.append(f"- **Path:** `{bg_info['path']}`")
        lines.append(f"- **Dimensions:** {bg_info.get('width', '?')}×{bg_info.get('height', '?')}")
    else:
        lines.append(f"- ⚠️ Not configured (optional)")
    lines.append(f"")

    lines.append(f"### RPP Project")
    if rpp_info.get("exists"):
        lines.append(f"- **Path:** `{rpp_info['path']}`")
        lines.append(f"- **Size:** {rpp_info.get('size_mb', '?')} MB")
    else:
        lines.append(f"- ❌ Missing")
    lines.append(f"")

    lines.append(f"### Chapters")
    if chapters_info.get("exists"):
        lines.append(f"- **Count:** {chapters_info.get('count', '?')}")
        lines.append(f"- **First:** {chapters_info.get('first', '?')}")
        lines.append(f"- **Last:** {chapters_info.get('last', '?')}")
        lines.append(f"- **Total duration:** {chapters_info.get('total_duration_str', '?')}")
    else:
        lines.append(f"- ❌ Missing")
    lines.append(f"")

    lines.append(f"### Layout")
    if layout_info.get("exists"):
        lines.append(f"- **Preset:** {layout_info.get('preset_name', '?')}")
    else:
        lines.append(f"- ❌ Missing")
    lines.append(f"")

    lines.append(f"### Waveform")
    if waveform_info.get("exists"):
        lines.append(f"- **Samples:** {waveform_info.get('sample_count', '?')}")
        lines.append(f"- **Duration:** {seconds_to_timecode(waveform_info.get('duration_seconds', 0)) if waveform_info.get('duration_seconds') else '?'}")
    else:
        lines.append(f"- ⚠️ Not generated")
    lines.append(f"")

    lines.append(f"### Preview")
    if preview_info.get("exists"):
        lines.append(f"- **Dimensions:** {preview_info.get('width', '?')}×{preview_info.get('height', '?')}")
    else:
        lines.append(f"- ⚠️ Not generated")

    lines.append(f"### Contact Sheet")
    if contact_info.get("exists"):
        lines.append(f"- **Dimensions:** {contact_info.get('width', '?')}×{contact_info.get('height', '?')}")
    else:
        lines.append(f"- ⚠️ Not generated")
    lines.append(f"")

    lines.append(f"### Test Output")
    if test_info.get("exists"):
        lines.append(f"- **Size:** {test_info.get('size_mb', '?')} MB")
        lines.append(f"- **Duration:** {test_info.get('duration_seconds', '?')}s")
    else:
        lines.append(f"- ⚠️ Not generated (run `render-test`)")

    lines.append(f"### Full Output")
    if full_info.get("exists"):
        lines.append(f"- **Size:** {full_info.get('size_mb', '?')} MB")
    else:
        lines.append(f"- ⏳ Future step (not yet rendered)")
    lines.append(f"")

    lines.append(f"## Readiness")
    lines.append(f"")
    if is_ready:
        lines.append(f"✅ **READY** — All required files present.")
    else:
        lines.append(f"❌ **NOT READY**")
        lines.append(f"")
        lines.append(f"### Missing items")
        for m in missing:
            lines.append(f"- `{m}`")
    lines.append(f"")
    if warnings:
        lines.append(f"### Warnings")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append(f"")

    lines.append(f"## Next Commands")
    lines.append(f"")
    lines.append(f"1. `python bookforge.py preview --contact --open`")
    lines.append(f"2. `python bookforge.py render-test --overwrite`")
    lines.append(f"3. `python bookforge.py render-full`  (only after test passes)")
    lines.append(f"")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    ok(f"Report MD saved: {md_path}")

    # Print summary
    print()
    print(f"  {'✅ READY' if is_ready else '❌ NOT READY'} — {project_name}")
    if missing:
        print(f"  Missing: {', '.join(missing)}")
    if warnings:
        print(f"  Warnings:")
        for w in warnings:
            print(f"    ⚠️  {w}")
    print()


# ═══════════════════════════════════════════════════════════════════
# Phase 3 — Check Preview
# ═══════════════════════════════════════════════════════════════════

def cmd_check_preview(args: argparse.Namespace) -> None:
    """Programmatic sanity check on preview images."""
    build = Path(args.build_dir) if args.build_dir else build_dir()

    print()
    print(f"  BookForge — Preview QA")
    print(f"  {'=' * 40}")
    print()

    passed = 0
    failed = 0

    def _check(ok_flag: bool, msg: str):
        nonlocal passed, failed
        if ok_flag:
            print(f"  [OK] {msg}")
            passed += 1
        else:
            print(f"  [WARN] {msg}")
            failed += 1

    from PIL import Image, ImageStat

    # 1. preview.png exists
    pp = build / PREVIEW_PNG
    _check(pp.exists(), f"{PREVIEW_PNG} exists")

    # 2. preview_contact.png exists
    cp = build / CONTACT_PNG
    _check(cp.exists(), f"{CONTACT_PNG} exists")

    # 3. preview.png dimensions (if exists)
    if pp.exists():
        try:
            with Image.open(pp) as im:
                pw, ph = im.size
                expected_w, expected_h = 1920, 1080
                _check(pw == expected_w and ph == expected_h,
                       f"preview.png size: {pw}×{ph} (expected {expected_w}×{expected_h})")
        except Exception as e:
            _check(False, f"preview.png open error: {e}")

        # 3b. PNG not empty — check brightness/variance (only if preview exists)
        try:
            with Image.open(pp) as im:
                stat = ImageStat.Stat(im)
                mean = stat.mean[:3]
                var = stat.stddev[:3]
                avg_mean = sum(mean) / 3
                avg_var = sum(var) / 3
                _check(avg_var > 5.0,
                       f"preview.png variance: {avg_var:.1f} (expected > 5.0, image not blank)")
                _check(30 < avg_mean < 250,
                       f"preview.png mean brightness: {avg_mean:.0f} (expected between 30-250, not all-black or all-white)")
        except Exception as e:
            _check(False, f"preview.png stat error: {e}")
    else:
        # No preview.png — still produce a warning but continue
        _check(False, f"{PREVIEW_PNG} exists (N/A)")

    # 4. contact sheet dimensions
    if cp.exists():
        try:
            with Image.open(cp) as im:
                cw, ch = im.size
                # Expect 1920x1080 (2x2 mosaic) or 3840x2160
                reasonable = (cw == 1920 and ch == 1080) or (cw == 3840 and ch == 2160)
                _check(reasonable,
                       f"preview_contact.png size: {cw}×{ch} (expected 1920×1080 or 3840×2160)")
        except Exception as e:
            _check(False, f"preview_contact.png open error: {e}")
    else:
        _check(False, f"preview_contact.png exists (N/A)")

    # 5. Contact sheet — check 4 quadrants are not identical
    if cp.exists():
        try:
            with Image.open(cp) as im:
                cw, ch = im.size
                half_w, half_h = cw // 2, ch // 2
                quadrants = [
                    im.crop((0, 0, half_w, half_h)),
                    im.crop((half_w, 0, cw, half_h)),
                    im.crop((0, half_h, half_w, ch)),
                    im.crop((half_w, half_h, cw, ch)),
                ]
                # Test pairwise differences
                different = 0
                for i in range(4):
                    for j in range(i + 1, 4):
                        q1_stat = ImageStat.Stat(quadrants[i])
                        q2_stat = ImageStat.Stat(quadrants[j])
                        diff = sum(abs(a - b) for a, b in zip(q1_stat.mean, q2_stat.mean))
                        if diff > 10:
                            different += 1
                _check(different >= 2,
                       f"contact quadrants differ: {different}/6 pairs differ (expected ≥ 2)")
        except Exception as e:
            _check(False, f"contact quadrants check error: {e}")

    # 7. Check cover/background files are valid
    config_path = Path(args.config)
    if config_path.exists():
        cfg = load_project_config(config_path)
        for key, label in [("cover", "Cover"), ("background", "Background")]:
            p_str = cfg.get(key, "")
            if p_str and Path(p_str).exists():
                try:
                    with Image.open(Path(p_str)) as im:
                        w, h = im.size
                        _check(True, f"{label} file valid: {im.size}")
                except Exception as e:
                    _check(False, f"{label} file invalid: {e}")
            else:
                _check(False, f"{label} configured but file not found")

    print()
    print(f"  {passed} OK, {failed} WARN")
    print()


# ═══════════════════════════════════════════════════════════════════
# Phase 4 — Render Test Hardening (improved)
# ═══════════════════════════════════════════════════════════════════

def cmd_render_test(args: argparse.Namespace) -> None:
    """Render 60-second test video (hardened)."""
    config_path = Path(args.config)
    build = Path(args.build_dir) if args.build_dir else build_dir()
    ensure_dir(build)

    # 1. Lock check
    if check_lock(build):
        fail("Render lock detected. Another render may be in progress. Use 'clean-temp' if stuck.")

    # 2. Config check
    if not config_path.exists():
        fail("Project config not found. Run 'scan' first.")

    config = load_project_config(config_path)

    # 3. Check audio
    audio_path = config.get("audio", "")
    if not audio_path or not Path(audio_path).exists():
        fail("Audio not found. Run 'scan' first.")

    # 4. Check cover
    cover_path = config.get("cover", "")
    if not cover_path or not Path(cover_path).exists():
        fail("Cover not found. Run 'scan' first.")

    # 5. Check layout
    layout_path = Path(config.get("layout", ""))
    if not layout_path.exists():
        fail(f"Layout not found: {layout_path}. Run 'preset zina-noir' first.")

    layout = load_layout(layout_path)

    # 6. Check chapters
    chapters_path = Path(config.get("chapters", ""))
    if not chapters_path.exists():
        fail(f"Chapters not found: {chapters_path}. Run 'chapters' first.")

    chapters = [Chapter(**{k: v for k, v in c.items() if k in ("title", "start_seconds", "end_seconds", "source", "raw_name", "file", "track")})
                for c in json.loads(chapters_path.read_text(encoding="utf-8"))]
    chapters = normalize_chapters(chapters)
    if not chapters:
        fail("No chapters loaded")

    # 7. Check ffmpeg
    if not shutil.which("ffmpeg"):
        fail("ffmpeg not found in PATH")

    # 8. Check disk space (rough: at least 2 GB free)
    try:
        import ctypes
        free_bytes = ctypes.c_ulonglong(0)
        ctypes.windll.kernel32.GetDiskFreeSpaceExW(
            ctypes.c_wchar_p(str(build)),
            None, None, ctypes.pointer(free_bytes)
        )
        free_gb = free_bytes.value / (1024**3)
        if free_gb < 2.0:
            warn_msg(f"Low disk space: {free_gb:.1f} GB free. Render may fail.")
    except Exception:
        pass  # Can't check on all platforms

    # 9. Quality preset
    quality = getattr(args, 'quality', 'fast_test')
    if quality not in QUALITY_PRESETS:
        quality = 'fast_test'
    qp = QUALITY_PRESETS[quality]

    # 10. Seconds
    max_duration = getattr(args, 'seconds', 60)
    if max_duration <= 0 or max_duration > 3600:
        max_duration = 60

    # 11. Output path
    test_out = build / TEST_MP4
    if test_out.exists():
        if not args.overwrite:
            warn(f"Output already exists: {test_out}")
            info("Use --overwrite to overwrite, or --open-output-folder to view")
            info("Use --seconds N to change duration (default 60)")
            return

    log_path = build / RENDER_TEST_LOG

    # 12. Run render
    create_lock(build)
    try:
        info(f"Render test: {max_duration}s, quality={quality}, output={test_out}")

        success = render_video(
            config=config,
            chapters=chapters,
            layout=layout,
            build_dir=build,
            out_path=test_out,
            max_duration=max_duration,
            log_path=log_path,
        )

        # 13. Write log
        log_lines = [
            f"render_test at {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"  duration: {max_duration}s",
            f"  quality: {quality}",
            f"  output: {test_out}",
            f"  success: {success}",
            "",
        ]
        log_path.write_text("\n".join(log_lines), encoding="utf-8")

        if success:
            ok(f"Test render complete: {test_out}")
            # Run ffprobe on result
            info("Checking output file...")
            probe = _ffprobe_file_info(test_out)
            fmt = probe.get("format", {})
            streams = probe.get("streams", [])
            video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
            audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})

            print()
            print(f"  Output file: {test_out}")
            print(f"  Duration:    {fmt.get('duration', '?')}s")
            print(f"  Size:        {_get_file_size_mb(test_out):.1f} MB")
            print(f"  Video:       {video_stream.get('codec_name', '?')} {video_stream.get('width', '?')}x{video_stream.get('height', '?')} @ {video_stream.get('r_frame_rate', '?')} fps")
            print(f"  Audio:       {audio_stream.get('codec_name', '?')} {audio_stream.get('sample_rate', '?')} Hz")
            print()

            # Update config outputs
            if config_path.exists():
                config["outputs"]["test"] = str(test_out)
                save_project_config(config_path, config)
        else:
            warn("Test render had errors")
            # Append error to log
            with log_path.open("a", encoding="utf-8") as lf:
                lf.write(f"  ERROR: render failed\n")

    except KeyboardInterrupt:
        warn_msg("\nRender cancelled by user (Ctrl+C)")
        with log_path.open("a", encoding="utf-8") as lf:
            lf.write(f"  CANCELLED by user at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        raise
    finally:
        release_lock(build)

    # 14. Open output folder if requested
    if getattr(args, 'open_output_folder', False) and test_out.exists():
        try:
            os.startfile(str(build))
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════
# Phase 5 — Status Improvements
# ═══════════════════════════════════════════════════════════════════

def cmd_status(args: argparse.Namespace) -> None:
    """Show project status with readiness, files, logs, and next command."""
    config_path = Path(args.config)
    build = Path(args.build_dir) if args.build_dir else build_dir()

    print()
    print(f"  {'=' * 50}")
    print(f"  BookForge Engine — Project Status")
    print(f"  {'=' * 50}")
    print()

    if not config_path.exists():
        warn_msg("No project config. Run 'scan' first.")
        return

    config = load_project_config(config_path)
    project_name = config.get("project_name", "Unknown")

    # ── Readiness ────────────────────────────────────────────────
    missing = []
    for key in ["audio", "cover", "rpp"]:
        val = config.get(key, "")
        if not val or not Path(val).exists():
            missing.append(key)

    layout_exists = (build / LAYOUT_FILE).exists()
    if not layout_exists:
        missing.append("layout")

    chapters_path = Path(config.get("chapters", ""))
    if not chapters_path.exists():
        missing.append("chapters")

    is_ready = len(missing) == 0

    if is_ready:
        print(f"  [READY] {project_name}")
    else:
        print(f"  [NOT READY] {project_name}")
        print(f"  Missing: {', '.join(missing)}")
    print()

    # ── Files ─────────────────────────────────────────────────────
    ok("Project files:")

    audio_path = config.get("audio", "")
    if audio_path and Path(audio_path).exists():
        ap = Path(audio_path)
        dur = _ffprobe_duration_safe(ap)
        dur_str = seconds_to_timecode(dur, millis=False) if dur else "?"
        info(f"  Audio: {ap.name} ({ap.stat().st_size / (1024*1024):.1f} MB, {dur_str})")
    else:
        warn_msg("  Audio: missing")

    cover_path = config.get("cover", "")
    if cover_path and Path(cover_path).exists():
        w, h = _get_img_dimensions(Path(cover_path))
        info(f"  Cover: {Path(cover_path).name} ({w}x{h})")
    else:
        warn_msg("  Cover: missing")

    bg_path = config.get("background", "")
    if bg_path and Path(bg_path).exists():
        w, h = _get_img_dimensions(Path(bg_path))
        info(f"  Background: {Path(bg_path).name} ({w}x{h})")
    else:
        info("  Background: not configured (optional)")

    if chapters_path.exists():
        try:
            ch_data = json.loads(chapters_path.read_text(encoding="utf-8"))
            info(f"  Chapters: {len(ch_data)}, no gaps")
        except Exception:
            warn_msg("  Chapters: parse error")
    else:
        warn_msg("  Chapters: missing")

    if layout_exists:
        try:
            lo = json.loads((build / LAYOUT_FILE).read_text(encoding="utf-8"))
            info(f"  Layout: {lo.get('name', 'unknown')}")
        except Exception:
            warn_msg("  Layout: parse error")
    else:
        warn_msg("  Layout: missing")

    wf_path = build / WAVEFORM_FILE
    if wf_path.exists():
        try:
            wf = json.loads(wf_path.read_text(encoding="utf-8"))
            info(f"  Waveform: OK, {wf.get('sample_count', 0)} samples")
        except Exception:
            warn_msg("  Waveform: parse error")
    else:
        warn_msg("  Waveform: not generated")

    pp = build / PREVIEW_PNG
    if pp.exists():
        w, h = _get_img_dimensions(pp)
        info(f"  Preview: {w}x{h}")
    else:
        warn_msg("  Preview: not generated")

    cp = build / CONTACT_PNG
    if cp.exists():
        warn_msg("  Contact: generated (run `check-preview`)")
    else:
        warn_msg("  Contact: not generated")

    # ── Render lock ───────────────────────────────────────────────
    if check_lock(build):
        warn_msg("  Render lock: PRESENT")
        try:
            lock_data = json.loads((build / RENDER_LOCK).read_text())
            info(f"    PID: {lock_data.get('pid', '?')}, started: {time.strftime('%H:%M:%S', time.localtime(lock_data.get('started', 0)))}")
        except Exception:
            pass
    else:
        ok("  Render lock: none")

    # ── Outputs ───────────────────────────────────────────────────
    test_out = build / TEST_MP4
    if test_out.exists():
        info(f"  Test output: {test_out.name} ({_get_file_size_mb(test_out):.1f} MB)")
    else:
        warn_msg("  Test output: not yet generated")

    full_out = build / FULL_MP4
    if full_out.exists():
        info(f"  Full output: {full_out.name} ({_get_file_size_mb(full_out):.1f} MB)")
    else:
        info("  Full output: not yet rendered")

    # ── Last logs ─────────────────────────────────────────────────
    for log_name in [RENDER_TEST_LOG, RENDER_FULL_LOG]:
        lp = build / log_name
        if lp.exists():
            lines = lp.read_text(encoding="utf-8").strip().splitlines()
            tail = lines[-20:] if len(lines) >= 20 else lines
            if tail:
                print(f"  ── {log_name} (last {len(tail)} lines) ──")
                for l in tail:
                    print(f"    {l}")
                print()

    # ── Next command ──────────────────────────────────────────────
    print(f"  ── Suggested next command ──")
    if not is_ready:
        print(f"  python bookforge.py doctor")
    elif not layout_exists:
        print(f"  python bookforge.py preset zina-noir")
    elif not wf_path.exists():
        print(f"  python bookforge.py waveform")
    elif not pp.exists() or not cp.exists():
        print(f"  python bookforge.py preview --contact")
    elif not test_out.exists():
        print(f"  python bookforge.py render-test --overwrite")
    else:
        print(f"  python bookforge.py render-full")
    print()


# ═══════════════════════════════════════════════════════════════════
# Phase 6 — Install Shortcut
# ═══════════════════════════════════════════════════════════════════

SHORTCUT_DIR = Path("D:\\PYTHON\\suviren_q_book_wunderwaffe")
SHORTCUT_PS1 = SHORTCUT_DIR / "Book_Wunderwaffe_CLI.ps1"
SHORTCUT_BAT = SHORTCUT_DIR / "Book_Wunderwaffe_CLI.bat"
SHORTCUT_ICO = SHORTCUT_DIR / "book_wunderwaffe.ico"
SHORTCUT_LNK_NAME = "Book Wunderwaffe 1.0.lnk"
PROJECT_ROOT = Path.cwd().resolve()


def _generate_ico_file(ico_path: Path) -> None:
    """Generate a simple 64x64 .ico file with dark background and cyan/green 'BW' letters."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGBA", (64, 64), (8, 8, 16, 255))
        draw = ImageDraw.Draw(img)
        # Draw a forge/spark motif
        # Center circle
        draw.ellipse([12, 12, 52, 52], fill=(10, 10, 20, 255), outline=(114, 255, 217, 200), width=2)
        # "BW" text
        try:
            font = ImageFont.truetype("arial.ttf", 22)
        except Exception:
            font = ImageFont.load_default()
        draw.text((16, 22), "BW", fill=(114, 255, 217, 255), font=font)
        # Small spark dots
        draw.ellipse([52, 8, 56, 12], fill=(182, 154, 255, 255))
        draw.ellipse([44, 52, 48, 56], fill=(114, 255, 217, 255))
        img.save(ico_path, format="ICO", sizes=[(64, 64)])
        log(f"ICO generated: {ico_path}")
    except Exception as e:
        warn(f"ICO generation failed: {e}")


def _create_shortcut_lnk(ico_path: Optional[Path]) -> None:
    """Create a desktop shortcut that launches the actual web studio."""
    try:
        desktop = Path(os.environ.get("USERPROFILE", "C:\\Users\\Default")) / "Desktop"
        lnk_path = desktop / SHORTCUT_LNK_NAME
        run_bat = (PROJECT_ROOT / "run.bat").resolve()
        if not run_bat.exists():
            warn(f"Studio launcher not found: {run_bat}, cannot create shortcut")
            return
        command_prompt = Path(os.environ.get("COMSPEC", "C:\\Windows\\System32\\cmd.exe")).resolve()

        # Use PowerShell to create the shortcut (available on all Windows 10/11)
        ps_code = f"""
        $ws = New-Object -ComObject WScript.Shell
        $s = $ws.CreateShortcut('{lnk_path}')
        $s.TargetPath = '{command_prompt}'
        $s.Arguments = '/c ""{run_bat}""'
        $s.WorkingDirectory = '{PROJECT_ROOT}'
        $s.Description = 'BOOK WUNDERWAFFE — audiobook studio'
        """
        if ico_path and ico_path.exists():
            ps_code += f"\n        $s.IconLocation = '{ico_path.resolve()}'"
        ps_code += """
        $s.Save()
        """

        subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps_code],
            check=True, capture_output=True, text=True,
        )
        log(f"Shortcut created: {lnk_path}")
    except Exception as e:
        warn(f"Shortcut creation failed: {e}")


def _create_ps1_script(venv_path: Optional[Path]) -> None:
    """Create a compatibility launcher for older shortcuts."""
    ps_content = f"""# BOOK WUNDERWAFFE — Studio Launcher
# Generated by bookforge.py install-shortcut

$ErrorActionPreference = 'Stop'
$projectRoot = '{PROJECT_ROOT}'
$launcher = Join-Path $projectRoot 'run.bat'
if (-not (Test-Path -LiteralPath $launcher)) {{
    throw "BOOK WUNDERWAFFE launcher not found: $launcher"
}}
Set-Location -LiteralPath $projectRoot
& $launcher
exit
"""
    SHORTCUT_PS1.parent.mkdir(parents=True, exist_ok=True)
    SHORTCUT_PS1.write_text(ps_content, encoding="utf-8", newline="\n")
    log(f"PS1 created: {SHORTCUT_PS1}")


def _create_bat_script() -> None:
    """Create a compatibility BAT wrapper for the actual studio launcher."""
    bat_content = f"""@echo off
call "{(PROJECT_ROOT / 'run.bat').resolve()}"
"""
    SHORTCUT_BAT.parent.mkdir(parents=True, exist_ok=True)
    SHORTCUT_BAT.write_text(bat_content, encoding="utf-8", newline="\r\n")
    log(f"BAT created: {SHORTCUT_BAT}")


def cmd_install_shortcut(args: argparse.Namespace) -> None:
    """Install desktop shortcut and launcher scripts."""
    overwrite = getattr(args, 'overwrite', False)
    SHORTCUT_DIR.mkdir(parents=True, exist_ok=True)

    # Check if scripts already exist
    if SHORTCUT_PS1.exists() and not overwrite:
        info(f"Shortcut scripts already exist. Use --overwrite to recreate.")
        return

    # Find venv
    venv_path = PROJECT_ROOT / ".venv"
    if not venv_path.exists():
        # Try parent directory
        for p in [PROJECT_ROOT, PROJECT_ROOT.parent]:
            venv_candidate = p / ".venv"
            if venv_candidate.exists():
                venv_path = venv_candidate
                break

    # Create PS1 script
    _create_ps1_script(venv_path if venv_path.exists() else None)

    # Create BAT script
    _create_bat_script()

    # Generate ICO
    ico_path = SHORTCUT_ICO
    if not ico_path.exists() or overwrite:
        _generate_ico_file(ico_path)

    # Create desktop shortcut
    _create_shortcut_lnk(ico_path if ico_path.exists() else None)

    print()
    ok(f"Shortcut installation complete.")
    info(f"  PS1: {SHORTCUT_PS1}")
    info(f"  BAT: {SHORTCUT_BAT}")
    if ico_path.exists():
        info(f"  ICO: {ico_path}")
    desktop = Path(os.environ.get("USERPROFILE", "C:\\Users\\Default")) / "Desktop"
    lnk = desktop / SHORTCUT_LNK_NAME
    if lnk.exists():
        info(f"  LNK: {lnk}")
    print()


# ── Main CLI ───────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bookforge.py",
        description="BookForge Engine v1 — CLI-first audiobook compositor and renderer for YouTube",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--data", default=DATA_DIR_DEFAULT, help="Data directory (default: data)")
    parser.add_argument("--build-dir", default=None, help="Build directory (default: _suviren_q_build)")
    parser.add_argument("--config", default=PROJECT_CONFIG, help="Project config file (default: bookforge.project.json)")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing outputs")
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # doctor
    p_doctor = sub.add_parser("doctor", help="Validate environment and project readiness")
    p_doctor.set_defaults(func=cmd_doctor)

    # scan
    p_scan = sub.add_parser("scan", help="Scan data directory and auto-discover media files")
    p_scan.set_defaults(func=cmd_scan)

    # chapters
    p_ch = sub.add_parser("chapters", help="Extract chapters from RPP")
    p_ch.add_argument("--rpp-track", default="КНИГА ОЗВУЧКА", help="RPP track name for chapters")
    p_ch.add_argument("--chapter-pattern", default="Глава", help="Substring to detect chapter items")
    p_ch.add_argument("--add-intro", action="store_true", default=True, help="Add Intro chapter from 00:00")
    p_ch.add_argument("--origin", default="project", choices=["project", "first-chapter"])
    p_ch.add_argument("--end-mode", default="next-start", choices=["next-start", "item-end"])
    p_ch.add_argument("--offset", type=float, default=0.0)
    p_ch.add_argument("--min-item-length", type=float, default=1.0)
    p_ch.set_defaults(func=cmd_chapters)

    # preset
    p_ps = sub.add_parser("preset", help="Generate visual layout preset")
    p_ps.add_argument("preset_name", nargs="?", default="zina-noir", help="Preset name (default: zina-noir)")
    p_ps.set_defaults(func=cmd_preset)

    # waveform
    p_wf = sub.add_parser("waveform", help="Generate waveform data from audio")
    p_wf.add_argument("--samples", type=int, default=2000, help="Number of waveform samples (default: 2000)")
    p_wf.set_defaults(func=cmd_waveform)

    # preview
    p_pr = sub.add_parser("preview", help="Render PNG preview")
    p_pr.add_argument("--chapter", type=int, default=None, help="Chapter index to preview")
    p_pr.add_argument("--contact", action="store_true", help="Render 2×2 contact sheet")
    p_pr.add_argument("--open", action="store_true", help="Open preview in viewer")
    p_pr.set_defaults(func=cmd_preview)

    # report
    p_rp = sub.add_parser("report", help="Generate project report (JSON + MD)")
    p_rp.set_defaults(func=cmd_report)

    # check-preview
    p_cp = sub.add_parser("check-preview", help="QA sanity check on preview images")
    p_cp.set_defaults(func=cmd_check_preview)

    # render-test
    p_rt = sub.add_parser("render-test", help="Render test MP4 (default: 60 seconds)")
    p_rt.add_argument("--quality", default="fast_test", choices=["fast_test", "youtube_high"], help="Quality preset (default: fast_test)")
    p_rt.add_argument("--seconds", type=int, default=60, help="Duration in seconds (default: 60)")
    p_rt.add_argument("--open-output-folder", action="store_true", help="Open output folder after render")
    p_rt.set_defaults(func=cmd_render_test)

    # render-full
    p_rf = sub.add_parser("render-full", help="Render full MP4 for YouTube")
    p_rf.add_argument("--force", action="store_true", help="Force render even if output exists")
    p_rf.set_defaults(func=cmd_render_full)

    # status
    p_st = sub.add_parser("status", help="Show project status and outputs")
    p_st.set_defaults(func=cmd_status)

    # install-shortcut
    p_is = sub.add_parser("install-shortcut", help="Install desktop shortcut and launcher scripts")
    p_is.set_defaults(func=cmd_install_shortcut)
    p_is.add_argument("--overwrite", action="store_true", help="Overwrite existing scripts and shortcut")

    # clean-temp
    p_ct = sub.add_parser("clean-temp", help="Remove temporary files and render lock")
    p_ct.set_defaults(func=cmd_clean_temp)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Pass global args to func
    args.data = getattr(args, 'data', DATA_DIR_DEFAULT)
    args.build_dir = getattr(args, 'build_dir', None)
    args.config = getattr(args, 'config', PROJECT_CONFIG)
    args.overwrite = getattr(args, 'overwrite', False)

    args.func(args)


if __name__ == "__main__":
    main()