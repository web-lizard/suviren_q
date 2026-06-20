#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
suviren-q: La Queue Souveraine
MVP CLI for audiobook YouTube video assembly from audio + cover + REAPER RPP chapters.

Commands:
  install      - check/install Python deps and ffmpeg availability
  inspect-rpp  - inspect REAPER .rpp and extract chapter timings
  preview      - render PNG panels only
  render       - render MP4 segments and concat final video

Python 3.10+
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Optional

APP_NAME = "suviren-q"
APP_TITLE = "suviren-q: La Queue Souveraine"
BUILD_DIR_NAME = "_suviren_q_build"
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
DEFAULT_FPS = 30


# -----------------------------
# Logging
# -----------------------------

def log(msg: str) -> None:
    print(f"[suviren-q] {msg}")


def warn(msg: str) -> None:
    print(f"[suviren-q][WARN] {msg}")


def fail(msg: str, code: int = 1) -> None:
    print(f"[suviren-q][ERROR] {msg}", file=sys.stderr)
    raise SystemExit(code)


# -----------------------------
# Models
# -----------------------------

@dataclass
class Chapter:
    title: str
    start_seconds: float
    end_seconds: float
    source: str = "manual"
    raw_name: str = ""
    file: str = ""
    track: str = ""

    @property
    def duration_seconds(self) -> float:
        return max(0.0, self.end_seconds - self.start_seconds)

    def to_json(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "start": seconds_to_timecode(self.start_seconds, millis=True),
            "end": seconds_to_timecode(self.end_seconds, millis=True),
            "start_seconds": round(self.start_seconds, 3),
            "end_seconds": round(self.end_seconds, 3),
            "duration_seconds": round(self.duration_seconds, 3),
            "source": self.source,
            "raw_name": self.raw_name,
            "file": self.file,
            "track": self.track,
        }


@dataclass
class RppItem:
    track: str
    position: float
    length: float
    name: str = ""
    file: str = ""
    line: int = 0

    @property
    def end(self) -> float:
        return self.position + self.length

    def to_json(self) -> dict[str, Any]:
        return {
            "track": self.track,
            "position": round(self.position, 6),
            "length": round(self.length, 6),
            "end": round(self.end, 6),
            "name": self.name,
            "file": self.file,
            "line": self.line,
        }


@dataclass
class RppMarker:
    kind: str
    position: float
    name: str = ""
    end: Optional[float] = None
    raw: str = ""
    line: int = 0

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RppTrack:
    name: str
    line: int
    items: list[RppItem]

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "line": self.line,
            "items_count": len(self.items),
            "items": [it.to_json() for it in self.items],
        }


@dataclass
class RppReport:
    path: str
    tracks: list[RppTrack]
    markers: list[RppMarker]
    regions: list[RppMarker]

    def to_json(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "tracks_count": len(self.tracks),
            "markers_count": len(self.markers),
            "regions_count": len(self.regions),
            "items_count": sum(len(t.items) for t in self.tracks),
            "tracks": [t.to_json() for t in self.tracks],
            "markers": [m.to_json() for m in self.markers],
            "regions": [r.to_json() for r in self.regions],
        }


# -----------------------------
# Generic helpers
# -----------------------------

def build_dir(base: Optional[Path] = None) -> Path:
    base = base or Path.cwd()
    d = base / BUILD_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def seconds_to_timecode(seconds: float, millis: bool = False) -> str:
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms >= 1000:
        s += 1
        ms -= 1000
    if s >= 60:
        m += 1
        s -= 60
    if m >= 60:
        h += 1
        m -= 60
    if millis:
        return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"
    return f"{h:02d}:{m:02d}:{s:02d}"


def parse_time_value(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return 0.0
    if re.fullmatch(r"-?\d+(?:\.\d+)?", s):
        return float(s)
    # HH:MM:SS(.mmm) or MM:SS(.mmm)
    parts = s.split(":")
    try:
        if len(parts) == 3:
            h = int(parts[0])
            m = int(parts[1])
            sec = float(parts[2].replace(",", "."))
            return h * 3600 + m * 60 + sec
        if len(parts) == 2:
            m = int(parts[0])
            sec = float(parts[1].replace(",", "."))
            return m * 60 + sec
    except Exception:
        pass
    raise ValueError(f"Cannot parse time value: {value!r}")


def run_cmd(cmd: list[str], *, dry_run: bool = False) -> None:
    printable = " ".join(quote_for_log(x) for x in cmd)
    log(printable)
    if dry_run:
        return
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError:
        fail(f"Command not found: {cmd[0]}")
    except subprocess.CalledProcessError as e:
        fail(f"Command failed with exit code {e.returncode}: {printable}")


def quote_for_log(s: str) -> str:
    if not s:
        return '""'
    if re.search(r"\s|[()\[\]{}'\";]", s):
        return '"' + s.replace('"', '\\"') + '"'
    return s


def which_or_none(name: str) -> Optional[str]:
    return shutil.which(name)


def check_binary(name: str, required: bool = True) -> Optional[str]:
    found = which_or_none(name)
    if found:
        log(f"{name}: {found}")
        return found
    msg = f"{name} not found in PATH"
    if required:
        fail(msg)
    warn(msg)
    return None


def ensure_pillow(auto_install: bool = False) -> None:
    try:
        import PIL  # noqa: F401
        log("Pillow: installed")
        return
    except Exception:
        pass
    if not auto_install:
        fail("Pillow is not installed. Run: python -m pip install pillow")
    log("Installing Pillow via pip...")
    run_cmd([sys.executable, "-m", "pip", "install", "pillow"])
    try:
        import PIL  # noqa: F401
        log("Pillow: installed")
    except Exception:
        fail("Pillow installation failed. Try manually: python -m pip install pillow")


# -----------------------------
# ffprobe
# -----------------------------

def ffprobe_duration(path: Path) -> Optional[float]:
    if not path.exists():
        warn(f"Audio not found for duration check: {path}")
        return None
    check_binary("ffprobe", required=True)
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        res = subprocess.run(cmd, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
        value = res.stdout.strip()
        if not value:
            return None
        dur = float(value)
        log(f"Audio duration: {seconds_to_timecode(dur, millis=True)} ({dur:.3f}s)")
        return dur
    except Exception as e:
        warn(f"Could not read audio duration via ffprobe: {e}")
        return None


# -----------------------------
# Chapter JSON / CSV
# -----------------------------

def load_chapters(path: Path) -> list[Chapter]:
    if not path.exists():
        fail(f"Chapters file not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = data.get("chapters", [])
        chapters = []
        for row in data:
            title = str(row.get("title") or row.get("name") or "Без названия").strip()
            start = row.get("start_seconds", row.get("start", 0))
            end = row.get("end_seconds", row.get("end", 0))
            chapters.append(Chapter(
                title=title,
                start_seconds=parse_time_value(start),
                end_seconds=parse_time_value(end),
                source=str(row.get("source", "json")),
                raw_name=str(row.get("raw_name", "")),
                file=str(row.get("file", "")),
                track=str(row.get("track", "")),
            ))
        return normalize_chapters(chapters)
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            chapters = []
            for row in reader:
                title = str(row.get("title") or row.get("name") or "Без названия").strip()
                start = row.get("start_seconds") or row.get("start") or 0
                end = row.get("end_seconds") or row.get("end") or 0
                chapters.append(Chapter(title=title, start_seconds=parse_time_value(start), end_seconds=parse_time_value(end), source="csv"))
            return normalize_chapters(chapters)
    fail(f"Unsupported chapters format: {path.suffix}. Use .json or .csv")


def normalize_chapters(chapters: list[Chapter]) -> list[Chapter]:
    clean = []
    for ch in chapters:
        if ch.end_seconds <= ch.start_seconds:
            warn(f"Skipping chapter with invalid duration: {ch.title}")
            continue
        clean.append(ch)
    clean.sort(key=lambda c: c.start_seconds)
    return clean


def save_chapters(path: Path, chapters: list[Chapter]) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps([c.to_json() for c in chapters], ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Saved chapters: {path}")


def save_youtube_chapters(path: Path, chapters: list[Chapter]) -> None:
    lines = []
    for ch in chapters:
        lines.append(f"{seconds_to_timecode(ch.start_seconds)} {ch.title}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"Saved YouTube chapters TXT: {path}")


# -----------------------------
# REAPER RPP parser
# -----------------------------

def strip_reaper_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1]
    return s.replace('\\"', '"')


def extract_quoted_or_token(rest: str) -> str:
    rest = rest.strip()
    if not rest:
        return ""
    if rest.startswith('"'):
        # REAPER strings are usually simple quoted strings. Escaped quotes are rare here.
        out = []
        escaped = False
        for ch in rest[1:]:
            if escaped:
                out.append(ch)
                escaped = False
            elif ch == "\\":
                # Keep backslashes in Windows paths, unless they escape a quote.
                escaped = True
                out.append(ch)
            elif ch == '"':
                break
            else:
                out.append(ch)
        return "".join(out).strip()
    return rest.split()[0].strip()


def parse_name_line(line: str) -> Optional[str]:
    m = re.match(r"^\s*NAME\s+(.+?)\s*$", line)
    if not m:
        return None
    return strip_reaper_quotes(m.group(1))


def parse_file_line(line: str) -> Optional[str]:
    m = re.match(r"^\s*FILE\s+(.+?)\s*(?:\d+)?\s*$", line)
    if not m:
        return None
    return extract_quoted_or_token(m.group(1))


def parse_marker_line(line: str, line_no: int) -> Optional[RppMarker]:
    s = line.strip()
    if not s.startswith("MARKER"):
        return None
    # Common forms vary. We safely parse first number as position and quoted name if present.
    # Examples usually contain: MARKER id pos "name" ...
    parts = re.findall(r'"[^"]*"|\S+', s)
    if len(parts) < 3:
        return None
    pos = None
    for token in parts[1:]:
        token_clean = token.strip('"')
        if re.fullmatch(r"-?\d+(?:\.\d+)?", token_clean):
            # First numeric token after marker id is often id, second is position.
            if pos is None:
                pos = token_clean
            else:
                pos = token_clean
                break
    if pos is None:
        return None
    name = ""
    for token in parts:
        if token.startswith('"') and token.endswith('"'):
            name = strip_reaper_quotes(token)
            break
    # Region detection is intentionally conservative. Some RPP versions store marker/region flags differently.
    # If a line contains REGION literally or has an obvious extra end value, it goes to regions.
    kind = "region" if "REGION" in s.upper() else "marker"
    return RppMarker(kind=kind, position=safe_float(pos), name=name, raw=s, line=line_no)


def parse_rpp(path: Path) -> RppReport:
    if not path.exists():
        fail(f"RPP file not found: {path}")
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    tracks: list[RppTrack] = []
    markers: list[RppMarker] = []
    regions: list[RppMarker] = []

    current_track: Optional[RppTrack] = None
    in_item = False
    item_depth = 0
    item_line = 0
    item_position: Optional[float] = None
    item_length: Optional[float] = None
    item_name = ""
    item_file = ""

    for line_no, line in enumerate(lines, start=1):
        stripped = line.strip()

        marker = parse_marker_line(line, line_no)
        if marker:
            if marker.kind == "region":
                regions.append(marker)
            else:
                markers.append(marker)

        if stripped.startswith("<TRACK"):
            current_track = RppTrack(name=f"TRACK_{len(tracks)+1}", line=line_no, items=[])
            tracks.append(current_track)
            in_item = False
            item_depth = 0
            continue

        if current_track and not in_item:
            name = parse_name_line(line)
            if name is not None and current_track.name.startswith("TRACK_"):
                current_track.name = name
                continue

        if current_track and stripped == "<ITEM":
            in_item = True
            item_depth = 1
            item_line = line_no
            item_position = None
            item_length = None
            item_name = ""
            item_file = ""
            continue

        if current_track and in_item:
            # Parse only the first item NAME, before/inside source this normally remains stable.
            if item_position is None:
                m = re.match(r"^\s*POSITION\s+(-?\d+(?:\.\d+)?)", line)
                if m:
                    item_position = float(m.group(1))
                    continue
            if item_length is None:
                m = re.match(r"^\s*LENGTH\s+(-?\d+(?:\.\d+)?)", line)
                if m:
                    item_length = float(m.group(1))
                    continue
            if not item_name:
                name = parse_name_line(line)
                if name is not None:
                    item_name = name
                    continue
            if not item_file:
                file_value = parse_file_line(line)
                if file_value is not None:
                    item_file = file_value
                    continue

            if stripped.startswith("<") and stripped != "<ITEM":
                item_depth += 1
            elif stripped == ">":
                item_depth -= 1
                if item_depth <= 0:
                    if item_position is not None and item_length is not None:
                        current_track.items.append(RppItem(
                            track=current_track.name,
                            position=item_position,
                            length=item_length,
                            name=item_name,
                            file=item_file,
                            line=item_line,
                        ))
                    else:
                        warn(f"Skipped ITEM without POSITION/LENGTH near line {item_line}")
                    in_item = False
                    item_depth = 0

    return RppReport(path=str(path), tracks=tracks, markers=markers, regions=regions)


def clean_chapter_title(name: str) -> str:
    title = Path(name.replace("\\", "/")).name
    title = re.sub(r"\.(mp3|wav|m4a|flac|aac|ogg)$", "", title, flags=re.I)
    title = re.sub(r"^\s*\d+\s*[-_.–—]+\s*", "", title).strip()
    return title or name.strip() or "Без названия"


def chapter_score(item: RppItem, pattern: str) -> int:
    hay = f"{item.track}\n{item.name}\n{item.file}".lower()
    p = pattern.lower().strip()
    score = 0
    if p and p in hay:
        score += 100
    if "глава" in hay:
        score += 80
    if "chapter" in hay:
        score += 60
    if re.search(r"(^|\D)\d{1,3}\s*[-_.–—]+\s*(глава|chapter)", hay):
        score += 40
    if item.length >= 60:
        score += 20
    if item.length >= 300:
        score += 20
    if any(x in hay for x in ["music", "музык", "zino", "logic", "smiley", "glitch", "bump", "theme"]):
        score -= 70
    return score


def detect_chapters_from_rpp(
    report: RppReport,
    *,
    audio_duration: Optional[float] = None,
    rpp_track: str = "КНИГА ОЗВУЧКА",
    chapter_pattern: str = "Глава",
    offset: float = 0.0,
    origin: str = "project",
    add_intro: bool = False,
    end_mode: str = "next-start",
    min_item_length: float = 30.0,
) -> list[Chapter]:
    # MVP priority for this project: items on a chosen track.
    track_filter = (rpp_track or "").lower().strip()
    pattern = (chapter_pattern or "").lower().strip()

    items: list[RppItem] = []
    for tr in report.tracks:
        if track_filter and track_filter not in tr.name.lower():
            continue
        for item in tr.items:
            hay = f"{item.name}\n{item.file}".lower()
            if pattern and pattern not in hay:
                continue
            if item.length < min_item_length:
                continue
            items.append(item)

    if not items:
        warn("No chapter items found by track/pattern. Falling back to scored item candidates.")
        candidates: list[tuple[int, RppItem]] = []
        for tr in report.tracks:
            for item in tr.items:
                if item.length < min_item_length:
                    continue
                score = chapter_score(item, chapter_pattern)
                if score >= 80:
                    candidates.append((score, item))
        candidates.sort(key=lambda x: (-x[0], x[1].position))
        items = [it for _, it in candidates]

    if not items:
        warn("No item-based chapters found. Trying markers.")
        return detect_chapters_from_markers(report.markers, audio_duration=audio_duration, offset=offset)

    items.sort(key=lambda i: i.position)
    base_shift = 0.0
    if origin == "first-chapter":
        base_shift = -items[0].position
        log(f"Origin first-chapter: applying base shift {base_shift:.3f}s")
    total_shift = base_shift + offset
    if abs(offset) > 0.0001:
        log(f"Manual offset: {offset:.3f}s")

    chapters: list[Chapter] = []

    if add_intro and origin == "project":
        intro_end = max(0.0, items[0].position + total_shift)
        if intro_end > 1.0:
            chapters.append(Chapter(
                title="Вступление",
                start_seconds=0.0,
                end_seconds=intro_end,
                source="rpp:intro-gap",
                track=items[0].track,
            ))

    for idx, item in enumerate(items):
        start = item.position + total_shift
        if end_mode == "item-end":
            end = item.end + total_shift
        else:
            if idx + 1 < len(items):
                end = items[idx + 1].position + total_shift
            else:
                end = item.end + total_shift
                if audio_duration is not None and audio_duration > start:
                    # If audio is rendered from project start, use full audio end if it is close or later.
                    if origin == "project":
                        end = min(audio_duration, max(end, item.end + total_shift))
                    else:
                        end = min(audio_duration, end)
        start = max(0.0, start)
        end = max(start + 0.01, end)
        title_src = item.name or item.file
        chapters.append(Chapter(
            title=clean_chapter_title(title_src),
            start_seconds=start,
            end_seconds=end,
            source="rpp:item",
            raw_name=item.name,
            file=item.file,
            track=item.track,
        ))

    return normalize_chapters(chapters)


def detect_chapters_from_markers(markers: list[RppMarker], *, audio_duration: Optional[float], offset: float = 0.0) -> list[Chapter]:
    good = [m for m in markers if m.name and ("глава" in m.name.lower() or "chapter" in m.name.lower())]
    good.sort(key=lambda m: m.position)
    chapters: list[Chapter] = []
    for i, m in enumerate(good):
        start = max(0.0, m.position + offset)
        if i + 1 < len(good):
            end = max(start + 0.01, good[i + 1].position + offset)
        else:
            end = audio_duration if audio_duration and audio_duration > start else start + 60.0
        chapters.append(Chapter(title=clean_chapter_title(m.name), start_seconds=start, end_seconds=end, source="rpp:marker"))
    return normalize_chapters(chapters)


def analyze_chapter_gaps(chapters: list[Chapter]) -> list[dict[str, Any]]:
    gaps = []
    for prev, nxt in zip(chapters, chapters[1:]):
        gap = nxt.start_seconds - prev.end_seconds
        if abs(gap) > 0.001:
            gaps.append({
                "after": prev.title,
                "before": nxt.title,
                "gap_seconds": round(gap, 3),
                "kind": "gap" if gap > 0 else "overlap",
            })
    return gaps


# -----------------------------
# Pillow panels
# -----------------------------

def import_pillow():
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
        return Image, ImageDraw, ImageFont, ImageFilter, ImageOps
    except Exception:
        fail("Pillow is required. Run: python suviren_q.py install")


def find_font(preferred: Optional[Path] = None) -> Optional[Path]:
    candidates = []
    if preferred:
        candidates.append(preferred)
    env_font = os.environ.get("SUVIREN_Q_FONT")
    if env_font:
        candidates.append(Path(env_font))
    if sys.platform.startswith("win"):
        candidates.extend([
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("C:/Windows/Fonts/segoeui.ttf"),
            Path("C:/Windows/Fonts/calibri.ttf"),
            Path("C:/Windows/Fonts/tahoma.ttf"),
        ])
    candidates.extend([
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        Path("/Library/Fonts/Arial Unicode.ttf"),
    ])
    for c in candidates:
        if c and c.exists():
            return c
    return None


def load_font(size: int, preferred: Optional[Path] = None, bold: bool = False):
    _, _, ImageFont, _, _ = import_pillow()
    font_path = find_font(preferred)
    if font_path:
        # Try a bold sibling on Linux if requested.
        if bold and font_path.name == "DejaVuSans.ttf":
            bold_path = font_path.with_name("DejaVuSans-Bold.ttf")
            if bold_path.exists():
                font_path = bold_path
        try:
            return ImageFont.truetype(str(font_path), size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def fit_text(draw, text: str, font_path: Optional[Path], max_width: int, start_size: int, min_size: int = 24, bold: bool = False):
    for size in range(start_size, min_size - 1, -2):
        font = load_font(size, font_path, bold=bold)
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return font
    return load_font(min_size, font_path, bold=bold)


def wrap_text(draw, text: str, font, max_width: int, max_lines: int = 3) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines = []
    current = ""
    for w in words:
        candidate = w if not current else current + " " + w
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = w
            if len(lines) >= max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    if words and len(lines) == max_lines:
        full = " ".join(words)
        if " ".join(lines) != full:
            last = lines[-1]
            while last and draw.textbbox((0, 0), last + "...", font=font)[2] > max_width:
                last = last[:-1].rstrip()
            lines[-1] = last + "..."
    return lines


def cover_crop(img, size: tuple[int, int]):
    Image, _, _, _, ImageOps = import_pillow()
    return ImageOps.fit(img.convert("RGB"), size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))


def background_fill(width: int, height: int, background: Optional[Path]):
    Image, ImageDraw, _, ImageFilter, ImageOps = import_pillow()
    if background and background.exists():
        bg = Image.open(background)
        bg = ImageOps.fit(bg.convert("RGB"), (width, height), method=Image.Resampling.LANCZOS)
        bg = bg.filter(ImageFilter.GaussianBlur(radius=3))
        overlay = Image.new("RGBA", (width, height), (3, 6, 10, 135))
        bg = bg.convert("RGBA")
        bg.alpha_composite(overlay)
        return bg.convert("RGB")

    # Procedural dark cyber background, no generated external images.
    img = Image.new("RGB", (width, height), (5, 9, 12))
    draw = ImageDraw.Draw(img, "RGBA")
    for y in range(height):
        t = y / max(1, height - 1)
        r = int(4 + 10 * t)
        g = int(8 + 22 * t)
        b = int(13 + 26 * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b, 255))
    # Neon fog rectangles/circles.
    for i in range(12):
        x = int(width * ((i * 137) % 997) / 997)
        y = int(height * ((i * 241) % 887) / 887)
        rad = 180 + (i % 5) * 65
        color = (0, 210, 155, 18) if i % 2 == 0 else (180, 70, 210, 14)
        draw.ellipse((x - rad, y - rad, x + rad, y + rad), fill=color)
    # Grid lines.
    for x in range(0, width, 96):
        draw.line([(x, 0), (x, height)], fill=(60, 255, 200, 18), width=1)
    for y in range(0, height, 96):
        draw.line([(0, y), (width, y)], fill=(60, 255, 200, 14), width=1)
    return img.filter(ImageFilter.GaussianBlur(radius=0.2))


def draw_decorative_wave(draw, x: int, y: int, w: int, h: int, progress: float, accent=(52, 255, 189, 220)) -> None:
    # Deterministic pseudo waveform, enough for MVP static panels.
    mid = y + h // 2
    bars = 120
    gap = 3
    bw = max(2, (w - gap * (bars - 1)) // bars)
    active_bars = int(bars * max(0.0, min(1.0, progress)))
    for i in range(bars):
        phase = i * 0.45
        amp = 0.25 + 0.55 * abs(math.sin(phase) * math.cos(i * 0.13))
        amp *= 0.72 + 0.28 * abs(math.sin(i * 0.91))
        bh = int(h * amp)
        bx = x + i * (bw + gap)
        if bx > x + w:
            break
        color = accent if i <= active_bars else (120, 145, 150, 90)
        draw.rounded_rectangle((bx, mid - bh // 2, bx + bw, mid + bh // 2), radius=2, fill=color)


def draw_panel(
    out_path: Path,
    *,
    chapters: list[Chapter],
    current_index: int,
    cover: Path,
    background: Optional[Path] = None,
    font: Optional[Path] = None,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    title: str = "Интимный протокол",
    subtitle: str = "Фригидная программистка Зина",
) -> None:
    Image, ImageDraw, _, ImageFilter, _ = import_pillow()
    ensure_dir(out_path.parent)

    canvas = background_fill(width, height, background).convert("RGBA")
    draw = ImageDraw.Draw(canvas, "RGBA")

    # Global vignette.
    vignette = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    vd = ImageDraw.Draw(vignette, "RGBA")
    vd.rectangle((0, 0, width, height), fill=(0, 0, 0, 48))
    canvas.alpha_composite(vignette)
    draw = ImageDraw.Draw(canvas, "RGBA")

    margin = 72
    cover_size = 650
    cover_x = margin
    cover_y = 155
    right_x = cover_x + cover_size + 70
    right_w = width - right_x - margin

    # Panels
    draw.rounded_rectangle((40, 40, width - 40, height - 40), radius=42, fill=(2, 6, 9, 105), outline=(80, 255, 205, 90), width=2)
    draw.rounded_rectangle((cover_x - 26, cover_y - 26, cover_x + cover_size + 26, cover_y + cover_size + 26), radius=38, fill=(0, 0, 0, 120), outline=(70, 255, 190, 110), width=3)

    # Cover
    if cover.exists():
        cov = Image.open(cover)
        cov = cover_crop(cov, (cover_size, cover_size)).convert("RGBA")
        shadow = Image.new("RGBA", (cover_size + 36, cover_size + 36), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow, "RGBA")
        sd.rounded_rectangle((18, 18, cover_size + 18, cover_size + 18), radius=28, fill=(0, 0, 0, 190))
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=18))
        canvas.alpha_composite(shadow, (cover_x - 18, cover_y - 18))
        mask = Image.new("L", (cover_size, cover_size), 0)
        md = ImageDraw.Draw(mask)
        md.rounded_rectangle((0, 0, cover_size, cover_size), radius=26, fill=255)
        canvas.alpha_composite(cov, (cover_x, cover_y), mask)
    else:
        draw.rounded_rectangle((cover_x, cover_y, cover_x + cover_size, cover_y + cover_size), radius=26, fill=(12, 25, 31, 255))
        f = load_font(42, font, bold=True)
        draw.text((cover_x + 50, cover_y + cover_size // 2 - 30), "COVER NOT FOUND", font=f, fill=(255, 210, 210, 255))

    current = chapters[current_index]
    small = load_font(28, font)
    label = load_font(34, font, bold=True)
    title_font = fit_text(draw, current.title, font, right_w, 62, 34, bold=True)
    book_font = load_font(48, font, bold=True)
    sub_font = load_font(30, font)

    # Header
    draw.text((right_x, 84), title, font=book_font, fill=(238, 255, 246, 255))
    draw.text((right_x, 140), subtitle, font=sub_font, fill=(145, 255, 216, 210))

    # Now playing block
    np_y = 230
    draw.rounded_rectangle((right_x, np_y, right_x + right_w, np_y + 235), radius=28, fill=(0, 12, 15, 168), outline=(45, 240, 185, 120), width=2)
    draw.text((right_x + 34, np_y + 26), "СЕЙЧАС ИГРАЕТ", font=label, fill=(81, 255, 197, 255))
    lines = wrap_text(draw, current.title, title_font, right_w - 68, max_lines=2)
    yy = np_y + 78
    for line in lines:
        draw.text((right_x + 34, yy), line, font=title_font, fill=(245, 255, 250, 255))
        yy += int(title_font.size * 1.12) if hasattr(title_font, "size") else 56
    time_line = f"{seconds_to_timecode(current.start_seconds)} - {seconds_to_timecode(current.end_seconds)}  |  {seconds_to_timecode(current.duration_seconds)}"
    draw.text((right_x + 34, np_y + 188), time_line, font=small, fill=(190, 214, 214, 230))

    # Contents block
    toc_y = 500
    toc_h = 395
    draw.rounded_rectangle((right_x, toc_y, right_x + right_w, toc_y + toc_h), radius=28, fill=(0, 8, 12, 145), outline=(90, 255, 205, 80), width=2)
    draw.text((right_x + 34, toc_y + 24), "ОГЛАВЛЕНИЕ", font=label, fill=(238, 255, 246, 245))

    max_rows = 9
    start_i = max(0, current_index - 4)
    if start_i + max_rows > len(chapters):
        start_i = max(0, len(chapters) - max_rows)
    row_y = toc_y + 78
    row_h = 32
    row_font = load_font(25, font)
    current_font = load_font(26, font, bold=True)
    for i in range(start_i, min(len(chapters), start_i + max_rows)):
        ch = chapters[i]
        is_cur = i == current_index
        if is_cur:
            draw.rounded_rectangle((right_x + 24, row_y - 7, right_x + right_w - 24, row_y + row_h + 7), radius=15, fill=(38, 255, 185, 48), outline=(64, 255, 198, 120), width=1)
        prefix = "▶ " if is_cur else "  "
        row_text = f"{prefix}{ch.title}"
        use_font = current_font if is_cur else row_font
        max_text_w = right_w - 210
        while draw.textbbox((0, 0), row_text, font=use_font)[2] > max_text_w and len(row_text) > 8:
            row_text = row_text[:-2].rstrip() + "..."
        fill = (245, 255, 250, 255) if is_cur else (182, 210, 207, 215)
        draw.text((right_x + 40, row_y), row_text, font=use_font, fill=fill)
        draw.text((right_x + right_w - 150, row_y), seconds_to_timecode(ch.start_seconds), font=row_font, fill=(139, 180, 178, 205))
        row_y += 37

    # Bottom waveform/progress
    wave_x = margin
    wave_y = 930
    wave_w = width - margin * 2
    wave_h = 84
    draw.rounded_rectangle((wave_x, wave_y - 22, wave_x + wave_w, wave_y + wave_h + 22), radius=28, fill=(0, 8, 10, 155), outline=(55, 255, 195, 80), width=2)
    progress = (current_index + 1) / max(1, len(chapters))
    draw_decorative_wave(draw, wave_x + 34, wave_y, wave_w - 68, wave_h, progress=progress)
    draw.text((wave_x + 34, wave_y - 50), f"{current_index + 1}/{len(chapters)}", font=small, fill=(150, 255, 218, 225))

    # Footer brand
    brand_font = load_font(24, font)
    draw.text((width - margin - 360, height - 58), "suviren-q / La Queue Souveraine", font=brand_font, fill=(115, 165, 160, 170))

    canvas.convert("RGB").save(out_path, quality=95)


# -----------------------------
# Rendering
# -----------------------------

def render_panels(
    chapters: list[Chapter],
    *,
    cover: Path,
    background: Optional[Path],
    font: Optional[Path],
    out_dir: Path,
    count: Optional[int] = None,
    only_index: Optional[int] = None,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
) -> list[Path]:
    ensure_pillow(auto_install=False)
    ensure_dir(out_dir)
    indices: list[int]
    if only_index is not None:
        indices = [max(0, min(len(chapters) - 1, only_index))]
    else:
        n = len(chapters) if count is None or count <= 0 else min(len(chapters), count)
        indices = list(range(n))
    paths: list[Path] = []
    for i in indices:
        out = out_dir / f"{i:03d}.png"
        log(f"Drawing panel {i+1}/{len(chapters)}: {chapters[i].title}")
        draw_panel(out, chapters=chapters, current_index=i, cover=cover, background=background, font=font, width=width, height=height)
        paths.append(out)
    return paths


def concat_file_line(path: Path) -> str:
    # ffmpeg concat demuxer likes forward slashes. Single quotes need escaping.
    s = str(path.resolve()).replace("\\", "/").replace("'", "'\\''")
    return f"file '{s}'"


def render_segment(
    *,
    panel: Path,
    audio: Path,
    out: Path,
    start: float,
    duration: float,
    fps: int,
    width: int,
    height: int,
    dry_run: bool = False,
    waveform: str = "static",
) -> None:
    ensure_dir(out.parent)

    if waveform == "ffmpeg":
        wave_height = max(110, int(height * 0.14))
        wave_y = height - wave_height - int(height * 0.045)

        filter_complex = (
            f"[0:v]scale={width}:{height},format=rgba[base];"
            f"[1:a]showwaves=s={width}x{wave_height}:mode=cline:rate={fps}:"
            f"colors=0x7fffe0|0xb69aff,format=rgba,colorchannelmixer=aa=0.72[wave];"
            f"[base][wave]overlay=x=0:y={wave_y}:format=auto,format=yuv420p[v]"
        )

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-framerate", str(fps),
            "-i", str(panel),
            "-ss", f"{start:.3f}",
            "-t", f"{duration:.3f}",
            "-i", str(audio),
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-map", "1:a:0",
            "-shortest",
            "-r", str(fps),
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "20",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            str(out),
        ]
        run_cmd(cmd, dry_run=dry_run)
        return

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-framerate", str(fps),
        "-i", str(panel),
        "-ss", f"{start:.3f}",
        "-t", f"{duration:.3f}",
        "-i", str(audio),
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-shortest",
        "-vf", f"scale={width}:{height},format=yuv420p",
        "-r", str(fps),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-tune", "stillimage",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        str(out),
    ]
    run_cmd(cmd, dry_run=dry_run)


def concat_segments(segments: list[Path], out: Path, concat_txt: Path, *, dry_run: bool = False) -> None:
    ensure_dir(out.parent if out.parent != Path("") else Path.cwd())
    concat_txt.write_text("\n".join(concat_file_line(p) for p in segments) + "\n", encoding="utf-8")
    log(f"Concat list: {concat_txt}")
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_txt),
        "-c", "copy",
        "-movflags", "+faststart",
        str(out),
    ]
    run_cmd(cmd, dry_run=dry_run)


# -----------------------------
# Commands
# -----------------------------

def cmd_install(args: argparse.Namespace) -> None:
    log(APP_TITLE)
    log("Install/check mode")
    ensure_pillow(auto_install=True)
    ffmpeg = check_binary("ffmpeg", required=False)
    ffprobe = check_binary("ffprobe", required=False)
    if not ffmpeg or not ffprobe:
        warn("ffmpeg/ffprobe are required for render and audio duration.")
        if sys.platform.startswith("win"):
            print("\nWindows quick install options:")
            print("  winget install Gyan.FFmpeg")
            print("or download ffmpeg and add its bin folder to PATH.")
        else:
            print("\nLinux/macOS quick install options:")
            print("  sudo apt install ffmpeg")
            print("  brew install ffmpeg")
    ensure_dir(build_dir())
    log("Install/check finished")


def cmd_inspect_rpp(args: argparse.Namespace) -> None:
    rpp = Path(args.rpp)
    out_base = Path(args.build_dir) if args.build_dir else Path.cwd()
    bdir = build_dir(out_base)
    audio_duration = ffprobe_duration(Path(args.audio)) if args.audio else None

    report = parse_rpp(rpp)
    report_path = bdir / "rpp_report.json"
    report_path.write_text(json.dumps(report.to_json(), ensure_ascii=False, indent=2), encoding="utf-8")

    log(f"RPP: {rpp}")
    log(f"Tracks: {len(report.tracks)}")
    for tr in report.tracks:
        log(f"  track: {tr.name} | items: {len(tr.items)} | line: {tr.line}")
    log(f"Markers: {len(report.markers)}")
    log(f"Regions: {len(report.regions)}")
    log(f"Report saved: {report_path}")

    chapters = detect_chapters_from_rpp(
        report,
        audio_duration=audio_duration,
        rpp_track=args.rpp_track,
        chapter_pattern=args.chapter_pattern,
        offset=args.offset,
        origin=args.origin,
        add_intro=args.add_intro,
        end_mode=args.end_mode,
        min_item_length=args.min_item_length,
    )
    if not chapters:
        fail("No chapters detected. Try --rpp-track or --chapter-pattern, or inspect rpp_report.json")

    chapters_path = bdir / "chapters.detected.json"
    save_chapters(chapters_path, chapters)
    save_youtube_chapters(bdir / "youtube_chapters.txt", chapters)

    log("Detected chapters:")
    for i, ch in enumerate(chapters, start=1):
        print(f"  {i:02d}. {seconds_to_timecode(ch.start_seconds, millis=True)} - {seconds_to_timecode(ch.end_seconds, millis=True)} | {ch.title}")

    gaps = analyze_chapter_gaps(chapters)
    if gaps:
        warn(f"Found {len(gaps)} gaps/overlaps after normalization. See rpp_report.json/chapters.detected.json")
        for g in gaps[:12]:
            print(f"  {g['kind']}: {g['gap_seconds']}s | {g['after']} -> {g['before']}")
    else:
        log("No gaps between generated chapter intervals")

    total_start = chapters[0].start_seconds
    total_end = chapters[-1].end_seconds
    log(f"Chapter timeline: {seconds_to_timecode(total_start, millis=True)} - {seconds_to_timecode(total_end, millis=True)}")
    if audio_duration is not None:
        diff = audio_duration - total_end
        if abs(diff) > 2.0:
            warn(f"Audio duration differs from last chapter end by {diff:.3f}s")
        else:
            log("Audio duration is close to last chapter end")


def cmd_preview(args: argparse.Namespace) -> None:
    chapters = load_chapters(Path(args.chapters))
    if not chapters:
        fail("No chapters loaded")
    out_base = Path(args.build_dir) if args.build_dir else Path.cwd()
    bdir = build_dir(out_base)
    panels_dir = ensure_dir(bdir / "panels")
    paths = render_panels(
        chapters,
        cover=Path(args.cover),
        background=Path(args.background) if args.background else None,
        font=Path(args.font) if args.font else None,
        out_dir=panels_dir,
        count=args.count,
        only_index=args.index,
        width=args.width,
        height=args.height,
    )
    log("Preview panels created:")
    for p in paths:
        print(f"  {p}")


def cmd_render(args: argparse.Namespace) -> None:
    check_binary("ffmpeg", required=True)
    check_binary("ffprobe", required=True)
    ensure_pillow(auto_install=False)

    audio = Path(args.audio)
    if not audio.exists():
        fail(f"Audio not found: {audio}")
    cover = Path(args.cover)
    if not cover.exists():
        fail(f"Cover not found: {cover}")

    if args.chapters:
        chapters = load_chapters(Path(args.chapters))
    elif args.rpp:
        audio_duration = ffprobe_duration(audio)
        report = parse_rpp(Path(args.rpp))
        chapters = detect_chapters_from_rpp(
            report,
            audio_duration=audio_duration,
            rpp_track=args.rpp_track,
            chapter_pattern=args.chapter_pattern,
            offset=args.offset,
            origin=args.origin,
            add_intro=args.add_intro,
            end_mode=args.end_mode,
            min_item_length=args.min_item_length,
        )
    else:
        fail("Render requires --chapters or --rpp")

    if not chapters:
        fail("No chapters for render")

    out_base = Path(args.build_dir) if args.build_dir else Path.cwd()
    bdir = build_dir(out_base)
    save_chapters(bdir / "chapters.used.json", chapters)
    save_youtube_chapters(bdir / "youtube_chapters.txt", chapters)

    panels_dir = ensure_dir(bdir / "panels")
    segments_dir = ensure_dir(bdir / "segments")

    log(f"Rendering {len(chapters)} panels")
    render_panels(
        chapters,
        cover=cover,
        background=Path(args.background) if args.background else None,
        font=Path(args.font) if args.font else None,
        out_dir=panels_dir,
        count=None,
        only_index=None,
        width=args.width,
        height=args.height,
    )

    segments: list[Path] = []
    for i, ch in enumerate(chapters):
        if ch.duration_seconds <= 0.05:
            warn(f"Skipping too short chapter: {ch.title}")
            continue
        panel = panels_dir / f"{i:03d}.png"
        segment = segments_dir / f"{i:03d}.mp4"
        log(f"Rendering segment {i+1}/{len(chapters)}: {ch.title} | {seconds_to_timecode(ch.duration_seconds, millis=True)}")
        render_segment(
            panel=panel,
            audio=audio,
            out=segment,
            start=ch.start_seconds,
            duration=ch.duration_seconds,
            fps=args.fps,
            width=args.width,
            height=args.height,
            dry_run=args.dry_run,
            waveform=args.waveform,
        )
        segments.append(segment)

    if not segments:
        fail("No segments rendered")
    concat_segments(segments, Path(args.out), bdir / "concat.txt", dry_run=args.dry_run)
    log(f"Done: {args.out}")


# -----------------------------
# CLI
# -----------------------------

def add_rpp_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--rpp", required=True, help="Path to REAPER .rpp project")
    p.add_argument("--audio", help="Optional final audio file to compare duration")
    p.add_argument("--rpp-track", default="КНИГА ОЗВУЧКА", help="Track name/substr to use as chapter source")
    p.add_argument("--chapter-pattern", default="Глава", help="Substring to detect chapter items")
    p.add_argument("--offset", type=float, default=0.0, help="Manual timing shift in seconds")
    p.add_argument("--origin", choices=["project", "first-chapter"], default="project", help="Timing origin: project timeline or first detected chapter")
    p.add_argument("--add-intro", action="store_true", help="Add intro chapter from 00:00 to first chapter start, only with --origin project")
    p.add_argument("--end-mode", choices=["next-start", "item-end"], default="next-start", help="Chapter end from next item start or item end")
    p.add_argument("--min-item-length", type=float, default=30.0, help="Ignore shorter RPP items")
    p.add_argument("--build-dir", help="Base dir for _suviren_q_build")


def add_visual_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--cover", required=True, help="Square cover image")
    p.add_argument("--background", help="Optional 16:9 background image")
    p.add_argument("--font", help="Optional TTF font with Cyrillic")
    p.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    p.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    p.add_argument("--build-dir", help="Base dir for _suviren_q_build")


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        prog="suviren_q.py",
        description="suviren-q: audiobook YouTube video builder from REAPER RPP chapters",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_install = sub.add_parser("install", help="Install/check Python deps and ffmpeg")
    p_install.set_defaults(func=cmd_install)

    p_inspect = sub.add_parser("inspect-rpp", help="Inspect REAPER .rpp and save chapters.detected.json")
    add_rpp_args(p_inspect)
    p_inspect.set_defaults(func=cmd_inspect_rpp)

    p_preview = sub.add_parser("preview", help="Draw PNG panels without rendering video")
    p_preview.add_argument("--chapters", required=True, help="chapters JSON/CSV")
    add_visual_args(p_preview)
    p_preview.add_argument("--count", type=int, default=3, help="How many panels to render, 0 means all")
    p_preview.add_argument("--index", type=int, help="Render only one chapter panel by zero-based index")
    p_preview.set_defaults(func=cmd_preview)

    p_render = sub.add_parser("render", help="Render final MP4")
    p_render.add_argument("--audio", required=True, help="MP3/WAV/M4A audiobook audio")
    p_render.add_argument("--chapters", help="chapters JSON/CSV. If omitted, use --rpp extraction")
    p_render.add_argument("--rpp", help="Optional REAPER .rpp if chapters are not provided")
    p_render.add_argument("--rpp-track", default="КНИГА ОЗВУЧКА")
    p_render.add_argument("--chapter-pattern", default="Глава")
    p_render.add_argument("--offset", type=float, default=0.0)
    p_render.add_argument("--origin", choices=["project", "first-chapter"], default="project")
    p_render.add_argument("--add-intro", action="store_true")
    p_render.add_argument("--end-mode", choices=["next-start", "item-end"], default="next-start")
    p_render.add_argument("--min-item-length", type=float, default=30.0)
    p_render.add_argument("--out", required=True, help="Output MP4")
    p_render.add_argument("--fps", type=int, default=DEFAULT_FPS)
    p_render.add_argument("--waveform", choices=["static", "ffmpeg"], default="static", help="Audio visualization mode")
    p_render.add_argument("--dry-run", action="store_true")
    add_visual_args(p_render)
    p_render.set_defaults(func=cmd_render)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
