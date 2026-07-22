#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BOOK WUNDERWAFFE Studio — Local-first Audiobook Production Suite.

Chapter-aware audiobook composition and reliable GPU/CPU video rendering.

Commands:
  install          - check/install Python deps and ffmpeg availability
  inspect-rpp      - inspect REAPER .rpp and extract chapter timings
  preview          - render PNG panels only
  render           - render MP4 segments and concat final video
  serve            - start the API server

Python 3.10+
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Optional

APP_NAME = "book-wunderwaffe-studio"
APP_VERSION = "1.1.0"
APP_TITLE = f"BOOK WUNDERWAFFE Studio {APP_VERSION}"
BUILD_DIR_NAME = "_suviren_q_build"
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
DEFAULT_FPS = 30

# ── GPU encoder map ──────────────────────────────────────────────
GPU_ENCODERS: dict[str, dict[str, Any]] = {
    "nvidia_nvenc": {
        "codec": "h264_nvenc",
        "check_bin": "nvidia-smi",
        "preset": "p7",
        "tune": "hq",
        "rc": "vbr",
        "cq": 23,
        "b_pyramid": 1,
        "gpu": 0,
        "label": "NVIDIA NVENC",
    },
    "amd_amf": {
        "codec": "h264_amf",
        "check_bin": "clinfo",
        "check_sub": "amd",
        "preset": "quality",
        "rc": "vbr_peak",
        "cq": 23,
        "gpu": 0,
        "label": "AMD AMF",
    },
    "intel_qsv": {
        "codec": "h264_qsv",
        "check_bin": "vainfo",
        "preset": "veryslow",
        "global_quality": 20,
        "gpu": 0,
        "label": "Intel QSV",
    },
}

DEFAULT_PRESET = "fast"      # fallback software preset


# ── Logging ──────────────────────────────────────────────────────

# Fix Windows console encoding for Russian/Cyrillic output
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass


def _safe_print(text: str, file=None, flush: bool = False) -> None:
    """Print with fallback for Windows console encoding issues."""
    out = file or sys.stdout
    try:
        print(text, file=out, flush=flush)
    except UnicodeEncodeError:
        out.buffer.write(text.encode('utf-8', errors='replace') + b'\n')
        out.buffer.flush()


def log(msg: str) -> None:
    _safe_print(f"[Wunderwaffe] {msg}", flush=True)


def warn(msg: str) -> None:
    _safe_print(f"[Wunderwaffe][WARN] {msg}", flush=True)


def fail(msg: str, code: int = 1) -> None:
    _safe_print(f"[Wunderwaffe][ERROR] {msg}", file=sys.stderr, flush=True)
    raise SystemExit(code)


# ── Models ───────────────────────────────────────────────────────

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


# ── Generic helpers ──────────────────────────────────────────────

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


def run_cmd(cmd: list[str], *, dry_run: bool = False, capture: bool = False) -> Optional[str]:
    printable = " ".join(quote_for_log(x) for x in cmd)
    log(printable)
    if dry_run:
        return None
    try:
        if capture:
            res = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                **hidden_process_options(),
            )
            return res.stdout
        subprocess.run(cmd, check=True, **hidden_process_options())
        return None
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


def hidden_process_options() -> dict[str, int]:
    """Keep FFmpeg/helper processes invisible behind the Windows desktop GUI."""
    if os.name == "nt":
        return {"creationflags": int(getattr(subprocess, "CREATE_NO_WINDOW", 0))}
    return {}


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


# ── GPU detection ────────────────────────────────────────────────

def detect_gpu_encoder() -> tuple[str, dict[str, Any]]:
    """Auto-detect best GPU encoder; fallback to software libx264."""
    for enc_name, enc in GPU_ENCODERS.items():
        check = shutil.which(enc["check_bin"])
        if not check:
            continue
        if enc_name == "nvidia_nvenc":
            # nvidia-smi exists → NVENC
            log(f"GPU encoder detected: {enc['label']}")
            return enc_name, enc
        if enc_name == "amd_amf":
            # clinfo exists → check for AMD
            try:
                out = subprocess.run(
                    [check],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    **hidden_process_options(),
                )
                if "amd" in out.stdout.lower() or "amd" in out.stderr.lower():
                    log(f"GPU encoder detected: {enc['label']}")
                    return enc_name, enc
            except Exception:
                continue
        if enc_name == "intel_qsv":
            log(f"GPU encoder detected: {enc['label']}")
            return enc_name, enc

    log("No GPU encoder detected; using software libx264")
    return "software", {
        "codec": "libx264",
        "preset": DEFAULT_PRESET,
        "crf": 20,
        "label": "Software (libx264)",
    }


def encoder_ffmpeg_args(
    enc: dict[str, Any],
    width: int,
    height: int,
    fps: int,
    *,
    include_video_filter: bool = True,
    include_audio: bool = True,
) -> list[str]:
    """Build encoder-specific ffmpeg arguments."""
    codec = enc["codec"]
    args: list[str] = []

    if codec == "libx264":
        args += ["-c:v", "libx264", "-preset", enc.get("preset", DEFAULT_PRESET)]
        args += ["-crf", str(enc.get("crf", 20))]
    elif codec == "h264_nvenc":
        args += ["-c:v", "h264_nvenc"]
        args += ["-preset", enc.get("preset", "p7")]
        args += ["-rc", enc.get("rc", "vbr")]
        args += ["-cq", str(enc.get("cq", 19))]
        args += ["-b:v", "1800k", "-maxrate", "3500k", "-bufsize", "7000k"]
        if enc.get("b_pyramid"):
            args += ["-b-pyramid", "1"]
        if enc.get("gpu") is not None:
            args += ["-gpu", str(enc["gpu"])]
    elif codec == "h264_amf":
        args += ["-c:v", "h264_amf"]
        args += ["-quality", enc.get("preset", "quality")]
        args += ["-rc", enc.get("rc", "cbr")]
        args += ["-b:v", "1800k", "-maxrate", "3500k", "-bufsize", "7000k"]
    elif codec == "h264_qsv":
        args += ["-c:v", "h264_qsv"]
        args += ["-preset", enc.get("preset", "veryslow")]
        if "global_quality" in enc:
            args += ["-global_quality", str(enc["global_quality"])]

    # Common args
    args += ["-r", str(fps)]
    if include_video_filter:
        args += ["-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p"]
    if include_audio:
        args += ["-c:a", "aac", "-b:a", "192k"]
    args += ["-movflags", "+faststart"]
    return args


# ── ffprobe ──────────────────────────────────────────────────────

def _ffmpeg_parse_duration(path: Path) -> Optional[float]:
    """Parse Duration line from ffmpeg -i (works on all file sizes)."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    try:
        # ffmpeg -i writes Duration to stderr, exit code may be 1 (no output specified)
        cmd = [ffmpeg, "-v", "info", "-i", str(path), "-f", "null", "-"]
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            **hidden_process_options(),
        )
        # Duration line format: "Duration: HH:MM:SS.xx, start: ..."
        out = res.stderr or ""
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", out)
        if m:
            h, mn, s = m.group(1), m.group(2), m.group(3)
            dur = float(h) * 3600 + float(mn) * 60 + float(s)
            log(f"Audio duration: {seconds_to_timecode(dur, millis=True)} ({dur:.3f}s)")
            return dur
        # If Duration not found, maybe the file is corrupt
        warn(f"Could not find Duration in ffmpeg -i output for {path.name}")
        return None
    except subprocess.TimeoutExpired:
        warn(f"ffmpeg -i timed out for {path.name} (120s)")
        return None
    except FileNotFoundError:
        return None
    except Exception as e:
        warn(f"ffmpeg -i failed: {e}")
        return None


def _estimate_duration_from_bitrate(path: Path) -> Optional[float]:
    """Estimate duration from file size and average bitrate (last resort).

    For very large mp3 files (>1.5 GB) where ffprobe/ffmpeg fail to parse
    VBR headers, we estimate duration from file size assuming ~320 kbps
    (high-quality VBR mp3). The expected 15:48:50 → 56930s × 320000/8 ≈ 2.28 GB.
    """
    try:
        size_bytes = path.stat().st_size
        if size_bytes <= 0:
            return None

        bitrate: float = 320000  # default for high-quality VBR mp3

        # Probing malformed >2 GB MP3 files may never return. For those files
        # the size-based fallback is both safer and more predictable.
        br_str = ""
        if size_bytes <= 1_500_000_000:
            br_cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=bit_rate",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ]
            try:
                br_res = subprocess.run(
                    br_cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=5,
                    **hidden_process_options(),
                )
                br_str = br_res.stdout.strip()
            except subprocess.TimeoutExpired:
                warn(f"ffprobe bitrate timed out for {path.name}; using size estimate")
        if br_str and br_str != "N/A" and br_str != "0":
            if br_str != "N/A":
                bitrate = float(br_str)

        # For very large files (>1.5 GB) where bitrate can't be read, use 320k
        if size_bytes > 1_500_000_000 and (not br_str or br_str in ("N/A", "0")):
            bitrate = 320000

        dur = size_bytes / (bitrate / 8)
        if 3600 < dur < 200000:  # Sanity: 1h to 55h
            log(f"Audio duration (estimated at {int(bitrate/1000)}kbps): {seconds_to_timecode(dur, millis=True)} ({dur:.3f}s)")
            return dur
        return None
    except Exception:
        return None


def ffprobe_duration(path: Path) -> Optional[float]:
    if not path.exists():
        warn(f"Audio not found for duration check: {path}")
        return None
    check_binary("ffprobe", required=True)

    # Method 1: ffprobe format=duration (fast, but may fail on huge mp3 >2GB)
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
        res = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            **hidden_process_options(),
        )
        value = res.stdout.strip()
        if value and value != "N/A":
            dur = float(value)
            log(f"Audio duration: {seconds_to_timecode(dur, millis=True)} ({dur:.3f}s)")
            return dur
    except Exception:
        pass

    # Method 2: ffmpeg -i Duration parsing (reliable for all mp3 sizes)
    dur = _ffmpeg_parse_duration(path)
    if dur is not None:
        return dur

    # Method 3: estimate from size / bitrate (last resort)
    dur = _estimate_duration_from_bitrate(path)
    if dur is not None:
        return dur

    warn(f"Could not determine duration for {path.name}")
    return None


# ── Chapter JSON / CSV ───────────────────────────────────────────

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


# ── REAPER RPP parser ────────────────────────────────────────────

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
        out = []
        escaped = False
        for ch in rest[1:]:
            if escaped:
                out.append(ch)
                escaped = False
            elif ch == '\\':
                escaped = True
            elif ch == '"':
                break
            else:
                out.append(ch)
        return "".join(out)
    return rest.split()[0]


def _rpp_read_text_safe(path: Path) -> str:
    """Read RPP file trying multiple encodings since REAPER uses system locale."""
    for enc in ["utf-8-sig", "utf-8", "cp1251", "cp866", "latin-1"]:
        try:
            return path.read_text(encoding=enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    # ultimate fallback
    warn(f"Cannot decode {path} with known encodings; using latin-1 with replacement")
    return path.read_text(encoding="latin-1", errors="replace")


def parse_rpp(path: Path) -> RppReport:
    if not path.exists():
        fail(f"RPP file not found: {path}")
    log(f"Parsing RPP: {path}")

    tracks: list[RppTrack] = []
    markers: list[RppMarker] = []
    regions: list[RppMarker] = []
    current_track: Optional[RppTrack] = None
    current_item: Optional[RppItem] = None

    # Stack-based nesting depth.
    # REAPER RPP uses <tag> ... > for blocks.
    # <TRACK increments from 0→1, <ITEM 1→2, other blocks go deeper.
    # > decrements. When depth returns to 1, item closes; to 0, track closes.
    depth = 0
    item_depth = -1   # depth at which the current ITEM was opened
    track_depth = -1  # depth at which the current TRACK was opened

    raw = _rpp_read_text_safe(path)
    lines = raw.splitlines()

    for line_no, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue

        # Count opening '<' tags (non-closing ones)
        open_count = 0
        idx = 0
        while idx < len(stripped):
            if stripped[idx] == '<' and not stripped.startswith("-->", idx):
                # check it's not the start of a closing tag (aka standalone ">")
                open_count += 1
                idx += 1
            else:
                idx += 1

        # Closing '>' on its own line – depth decrement
        if stripped == ">":
            depth -= 1
            # ITEM closes when depth drops *below* the level it was opened at
            # (e.g. item at depth=2 → SOURCE at depth=3 → '>' back to depth=2 → another '>' to depth=1 closes ITEM)
            if current_item is not None and depth < item_depth:
                current_item = None
                item_depth = -1
            # TRACK closes when depth drops below track_depth
            if current_track is not None and depth < track_depth:
                current_track = None
                track_depth = -1
                item_depth = -1
                current_item = None
            depth = max(0, depth)
            continue

        # Opening tags: increment depth for each '<' found
        if open_count > 0:
            depth += open_count

        # Track open
        if re.match(r"^\s*<TRACK\b", stripped):
            current_track = RppTrack(name="", line=line_no, items=[])
            tracks.append(current_track)
            current_item = None
            item_depth = -1
            track_depth = depth
            # Check inline attributes
            m = re.search(r'NAME\s+"([^"]*)"', line)
            if m:
                current_track.name = m.group(1)
            continue

        # ITEM open (only inside a track)
        if re.match(r"^\s*<ITEM\b", stripped) and current_track is not None:
            current_item = RppItem(track=current_track.name, position=0.0, length=0.0, line=line_no)
            current_track.items.append(current_item)
            item_depth = depth
            # Check inline attributes
            m = re.search(r'POSITION\s+([\d.]+)', line)
            if m:
                current_item.position = float(m.group(1))
            m = re.search(r'LENGTH\s+([\d.]+)', line)
            if m:
                current_item.length = float(m.group(1))
            m = re.search(r'NAME\s+"([^"]*)"', line)
            if m:
                current_item.name = m.group(1)
            continue

        # Properties inside current contexts
        if current_item is not None:
            if re.match(r"^\s*NAME\s", stripped):
                m = re.search(r'NAME\s+(.+)', stripped)
                if m:
                    current_item.name = strip_reaper_quotes(m.group(1))
            elif re.match(r"^\s*POSITION\s", stripped):
                m = re.search(r'POSITION\s+([\d.]+)', stripped)
                if m:
                    current_item.position = float(m.group(1))
            elif re.match(r"^\s*LENGTH\s", stripped):
                m = re.search(r'LENGTH\s+([\d.]+)', stripped)
                if m:
                    current_item.length = float(m.group(1))
            elif re.match(r"^\s*FILE\s", stripped):
                parts = stripped.split(None, 1)
                if len(parts) >= 2:
                    current_item.file = extract_quoted_or_token(parts[1])

        if current_track is not None and current_item is None:
            # Track-level properties (when not inside an ITEM)
            if re.match(r"^\s*NAME\s", stripped):
                m = re.search(r'NAME\s+(.+)', stripped)
                if m:
                    name_val = strip_reaper_quotes(m.group(1))
                    if name_val:
                        current_track.name = name_val

        # MARKER line (only at top level depth <= 1)
        if depth <= 1 and re.match(r"^\s*(MARKER|MARKER_LENGTH|REGION)\s", stripped):
            parts = stripped.split()
            if len(parts) >= 3 and parts[1].isdigit():
                kind = parts[2]
                pos = 0.0
                name = ""
                for part in parts[3:]:
                    mm = re.match(r"([\d.]+)", part)
                    if mm:
                        pos = float(mm.group(1))
                    else:
                        name = extract_quoted_or_token(part)
                if parts[0].startswith("REGION") and len(parts) >= 4:
                    end_pos = 0.0
                    for part in parts[4:]:
                        mm = re.match(r"([\d.]+)", part)
                        if mm and end_pos == 0.0:
                            end_pos = float(mm.group(1))
                        else:
                            name = extract_quoted_or_token(part)
                    regions.append(RppMarker(kind=kind, position=pos, name=name, end=end_pos, raw=stripped, line=line_no))
                else:
                    markers.append(RppMarker(kind=kind, position=pos, name=name, raw=stripped, line=line_no))

    # Debug
    log(f"RPP: {path.name}")
    log(f"Tracks: {len(tracks)}")
    for i, t in enumerate(tracks):
        log(f"  track {i}: '{t.name}' | items: {len(t.items)} | line: {t.line}")
    log(f"Markers: {len(markers)}")
    log(f"Regions: {len(regions)}")

    return RppReport(
        path=str(path),
        tracks=tracks,
        markers=markers,
        regions=regions,
    )


# ── Chapter detection from RPP ───────────────────────────────────

# Mapping of known latin slugs to readable Russian titles
_KNOWN_SLUG_TITLES: dict[str, str] = {
    "glava_17_arhitekturnoe_nasilie": "Глава 17. Архитектурное насилие",
    "glava_18_altar_musora": "Глава 18. Алтарь мусора",
    "glava_24_krov_i_zhelezo": "Глава 24. Кровь и железо",
    "glava_29_zheltyy_drug": "Глава 29. Жёлтый друг",
    "glava_30_nauchnaya_sestra": "Глава 30. Научная сестра",
    "epilog_idempotentnost_i_impotentnost": "Эпилог. Идемпотентность и импотентность",
}

def _normalize_item_title(name: str, file: str) -> str:
    """Normalize item name or source file basename to readable chapter title."""
    # Use item NAME if present and meaningful
    if name and name.strip():
        raw = name.strip()
        # Remove leading number prefix: "002 - ", "003 - " or "037_" etc.
        raw = re.sub(r'^\d+\s*[-–—]\s*', '', raw)
        # Also strip leading number with underscore: "037_"
        raw = re.sub(r'^\d+_', '', raw)
        # Remove file extension if any
        raw = re.sub(r'\.(mp3|wav|flac|ogg|aac|wma)$', '', raw, flags=re.IGNORECASE)
        # Strip leading "Media" prefix if present
        raw = re.sub(r'^Media[\\/]?', '', raw, flags=re.IGNORECASE)
        raw = raw.strip()
        # Check known slug mapping
        if raw in _KNOWN_SLUG_TITLES:
            return _KNOWN_SLUG_TITLES[raw]
        if raw:
            return raw

    # Fallback to source file basename
    if file:
        basename = Path(file).stem  # "019_glava_17_arhitekturnoe_nasilie" or "002 - Глава 0. Ложное срабатывание"
        # Remove leading number prefix: "019_" or "037_"
        basename = re.sub(r'^\d+_', '', basename)
        # Try known slug mapping first
        if basename in _KNOWN_SLUG_TITLES:
            return _KNOWN_SLUG_TITLES[basename]
        # Generic latin slug → readable
        # Replace underscores with spaces
        readable = basename.replace('_', ' ')
        # Remove leading digits with space or dash
        readable = re.sub(r'^\d+\s*[-–—]\s*', '', readable)
        readable = readable.strip()
        if readable:
            return readable

    return "Unknown Chapter"


def detect_chapters_from_rpp(
    report: RppReport,
    audio_duration: Optional[float] = None,
    rpp_track: str = "КНИГА ОЗВУЧКА",
    chapter_pattern: str = "Глава",
    offset: float = 0.0,
    origin: str = "project",
    add_intro: bool = True,
    end_mode: str = "next-start",
    min_item_length: float = 1.0,
) -> list[Chapter]:
    """
    Extract chapters from a specific RPP track.

    KEY BEHAVIOR (as of BOOK WUNDERWAFFE Studio 1.1):
    - Uses ALL items from the specified track (NOT filtered by chapter_pattern).
    - Chapter_pattern is ignored; we take every item on the book track.
    - Items are sorted by POSITION.
    - If the first item starts after > 0.5 sec, a synthetic "Вступление от автора" segment is created.
    - End mode uses "next-start" by default (interval mode) to avoid gaps.
    - Title normalization handles both Cyrillic (Глава N. Name) and latin slugs.
    """
    track: Optional[RppTrack] = None
    for t in report.tracks:
        if rpp_track.lower() in t.name.lower():
            track = t
            break
    if not track:
        warn(f"Track '{rpp_track}' not found. Trying fallback: first track with items.")
        for t in report.tracks:
            if len(t.items) >= 5:
                track = t
                break
    if not track:
        fail(f"No suitable track found with items matching '{rpp_track}'")

    log(f"Using track: '{track.name}' ({len(track.items)} items)")

    # Use ALL items from this track regardless of name
    items = sorted(track.items, key=lambda it: it.position)

    # Check if the first item has meaningful content at position 0
    # Items that are voice/audio before the first book item
    first_book_item = items[0] if items else None

    chapters: list[Chapter] = []

    # --- SYNTHETIC INTRO ---
    # If the first book track item starts after 0.5 sec, create synthetic intro
    if first_book_item and first_book_item.position > 0.5:
        intro_start = 0.0
        intro_end = first_book_item.position
        intro = Chapter(
            title="Вступление от автора",
            start_seconds=0.0,
            end_seconds=intro_end,
            source="synthetic_intro",
            raw_name="",
            file="",
            track="",
        )
        chapters.append(intro)
        log(f"Synthetic intro: 00:00:00.000 → {_sec_to_ts(intro_end)}")
    
    # --- BOOK TRACK ITEMS ---
    for i, it in enumerate(items):
        title = _normalize_item_title(it.name, it.file)
        start = it.position + offset
        if end_mode == "next-start" and i + 1 < len(items):
            end = items[i + 1].position + offset
        else:
            end = it.end + offset
        chapters.append(Chapter(
            title=title,
            start_seconds=max(0.0, start),
            end_seconds=max(0.0, end),
            source="rpp",
            raw_name=it.name,
            file=it.file,
            track=it.track,
        ))

    # Shift timeline origin
    if origin == "first-chapter" and chapters:
        shift = chapters[0].start_seconds
        for ch in chapters:
            ch.start_seconds = max(0.0, ch.start_seconds - shift)
            ch.end_seconds = max(0.0, ch.end_seconds - shift)

    # Ensure last chapter extends to audio duration
    if audio_duration is not None and chapters:
        last = chapters[-1]
        if last.end_seconds < audio_duration:
            if audio_duration - last.end_seconds < 600:
                last.end_seconds = audio_duration
            else:
                warn("Audio is much longer than last chapter, not extending")

    chapters = normalize_chapters(chapters)

    # Log summary
    log(f"Detected {len(chapters)} chapters from RPP")
    if chapters:
        log(f"  First segment: {chapters[0].title} @ {_sec_to_ts(chapters[0].start_seconds)}")
        log(f"  Last segment:  {chapters[-1].title} @ {_sec_to_ts(chapters[-1].start_seconds)} → {_sec_to_ts(chapters[-1].end_seconds)}")
    
    return chapters


def _sec_to_ts(sec: float) -> str:
    """Convert seconds to HH:MM:SS.xxx format."""
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


# ── Style presets ───────────────────────────────────────────────

STYLE_PRESETS: dict[str, dict[str, Any]] = {
    "deep-purple": {
        "label": "Deep Purple",
        "bg": (20, 18, 28),
        "accent": (140, 60, 180),
        "accent2": (180, 80, 220),
        "text": (220, 220, 240),
        "text_dim": (140, 140, 160),
        "progress_bg": (40, 38, 48),
        "waveform": (60, 55, 75),
        "title_glow": True,
    },
    "obsidian": {
        "label": "Obsidian",
        "bg": (16, 16, 18),
        "accent": (255, 165, 0),
        "accent2": (255, 200, 50),
        "text": (230, 230, 235),
        "text_dim": (120, 120, 130),
        "progress_bg": (35, 35, 40),
        "waveform": (55, 55, 60),
        "title_glow": False,
    },
    "emerald": {
        "label": "Emerald",
        "bg": (10, 22, 18),
        "accent": (60, 210, 130),
        "accent2": (100, 230, 170),
        "text": (210, 230, 220),
        "text_dim": (120, 150, 140),
        "progress_bg": (25, 45, 38),
        "waveform": (35, 65, 55),
        "title_glow": False,
    },
    "rose": {
        "label": "Rose",
        "bg": (26, 14, 18),
        "accent": (220, 80, 120),
        "accent2": (240, 120, 160),
        "text": (230, 215, 220),
        "text_dim": (150, 120, 130),
        "progress_bg": (48, 30, 36),
        "waveform": (68, 50, 56),
        "title_glow": True,
    },
    "ocean": {
        "label": "Ocean",
        "bg": (10, 18, 30),
        "accent": (60, 160, 220),
        "accent2": (100, 200, 255),
        "text": (210, 220, 235),
        "text_dim": (110, 140, 165),
        "progress_bg": (22, 38, 55),
        "waveform": (35, 55, 75),
        "title_glow": False,
    },
    "mono": {
        "label": "Monochrome",
        "bg": (20, 20, 22),
        "accent": (180, 180, 190),
        "accent2": (220, 220, 230),
        "text": (200, 200, 210),
        "text_dim": (120, 120, 130),
        "progress_bg": (40, 40, 44),
        "waveform": (55, 55, 60),
        "title_glow": False,
    },
    "midnight": {
        "label": "Midnight",
        "bg": (8, 8, 14),
        "accent": (100, 80, 220),
        "accent2": (140, 120, 255),
        "text": (200, 200, 220),
        "text_dim": (90, 90, 120),
        "progress_bg": (22, 22, 38),
        "waveform": (35, 35, 55),
        "title_glow": True,
    },
}

# ── Panel drawing ────────────────────────────────────────────────

def rgb_or_default(color: Optional[str], default: tuple[int, int, int] = (20, 20, 30)) -> tuple[int, ...]:
    if not color:
        return default
    try:
        c = color.lstrip("#")
        if len(c) == 6:
            return tuple(int(c[i:i+2], 16) for i in (0, 2, 4))
        if len(c) == 3:
            return tuple(int(c[i]*2, 16) for i in range(3))
    except Exception:
        pass
    return default


def truncate_text(text: str, max_len: int = 40) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


TELEGRAM_CHANNEL_URL = "https://t.me/temple_of_lizard"


def _panel_font(font_path: Optional[Path], size: int, *, bold: bool = False):
    """Load a scalable Cyrillic font for a panel at the requested size."""
    from PIL import ImageFont

    candidates: list[Path | str] = []
    if font_path and font_path.exists():
        candidates.append(font_path)

    fonts_dir = Path(os.environ.get("SystemRoot", "C:\\Windows")) / "Fonts"
    if bold:
        candidates.extend((fonts_dir / "segoeuib.ttf", fonts_dir / "arialbd.ttf"))
    else:
        candidates.extend((fonts_dir / "segoeui.ttf", fonts_dir / "arial.ttf"))

    for candidate in candidates:
        try:
            if isinstance(candidate, Path) and not candidate.exists():
                continue
            return ImageFont.truetype(str(candidate), size=max(1, int(size)))
        except Exception:
            continue

    try:
        return ImageFont.load_default(size=max(1, int(size)))
    except TypeError:
        return ImageFont.load_default()


def _panel_text_width(draw: Any, text: str, font: Any) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return max(0, bbox[2] - bbox[0])


def _wrap_panel_text(draw: Any, text: str, font: Any, max_width: int) -> list[str]:
    """Greedy pixel-based wrap that never discards text, including long words."""
    words = " ".join(text.split()).split(" ")
    if not words or words == [""]:
        return [""]

    lines: list[str] = []
    current = ""
    for raw_word in words:
        word = raw_word
        candidate = f"{current} {word}".strip()
        if current and _panel_text_width(draw, candidate, font) <= max_width:
            current = candidate
            continue
        if not current and _panel_text_width(draw, word, font) <= max_width:
            current = word
            continue
        if current:
            lines.append(current)
            current = ""

        # A single token may still be wider than the box. Split it by glyphs,
        # preserving every character instead of truncating it with an ellipsis.
        while word and _panel_text_width(draw, word, font) > max_width:
            lo, hi = 1, len(word)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if _panel_text_width(draw, word[:mid], font) <= max_width:
                    lo = mid
                else:
                    hi = mid - 1
            split_at = max(1, lo)
            lines.append(word[:split_at])
            word = word[split_at:]
        current = word

    if current:
        lines.append(current)
    return lines or [""]


def _fit_panel_title(
    draw: Any,
    text: str,
    font_path: Optional[Path],
    max_width: int,
    max_height: int,
    *,
    max_size: int,
    min_size: int,
    max_lines: int = 3,
) -> tuple[Any, str, int, tuple[int, int]]:
    """Return the largest font and full wrapped text that fit the title box."""
    fallback: Optional[tuple[Any, str, int, tuple[int, int]]] = None
    smallest = max(10, min_size)
    for size in range(max_size, 9, -2):
        fnt = _panel_font(font_path, size, bold=True)
        lines = _wrap_panel_text(draw, text, fnt, max_width)
        spacing = max(2, round(size * 0.12))
        rendered = "\n".join(lines)
        bbox = draw.multiline_textbbox((0, 0), rendered, font=fnt, spacing=spacing)
        dims = (max(0, bbox[2] - bbox[0]), max(0, bbox[3] - bbox[1]))
        fallback = (fnt, rendered, spacing, dims)
        if len(lines) <= max_lines and dims[0] <= max_width and dims[1] <= max_height:
            return fallback
        if size <= smallest and dims[1] <= max_height:
            # Below the preferred minimum we only continue when the full title
            # still needs more room. No text is removed at the minimum size.
            continue
    assert fallback is not None
    return fallback


def _fit_panel_side_font(
    draw: Any,
    texts: list[str],
    font_path: Optional[Path],
    max_width: int,
    *,
    max_size: int,
    min_size: int = 10,
) -> Any:
    """Use one consistent size for both neighbouring chapter lines."""
    for size in range(max_size, min_size - 1, -1):
        fnt = _panel_font(font_path, size)
        if all(_panel_text_width(draw, value, fnt) <= max_width for value in texts):
            return fnt
    return _panel_font(font_path, min_size)


def _draw_panel_text_top(
    draw: Any,
    xy: tuple[int, int],
    text: str,
    *,
    font: Any,
    fill: tuple[int, ...],
    spacing: int = 4,
) -> None:
    """Draw text with xy referring to its visible top-left, not its ascender."""
    bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=spacing)
    draw.multiline_text(
        (xy[0] - bbox[0], xy[1] - bbox[1]),
        text,
        font=font,
        fill=fill,
        spacing=spacing,
    )


def _glitch_panel_background(source: Any, *, seed: int) -> Any:
    """Add stable, low-alpha cyan/magenta channel slices to a background."""
    import random
    from PIL import Image

    base = source.convert("RGBA")
    width, height = base.size
    rgb = source.convert("RGB")
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    rng = random.Random(seed)
    scale = max(0.5, min(width / 1920, height / 1080))

    for band_index in range(7):
        band_h = max(2, round(rng.randint(3, 10) * scale))
        y = rng.randint(0, max(0, height - band_h))
        shift = round(rng.choice((-1, 1)) * rng.randint(4, 14) * scale)
        shift = shift or 1
        if shift > 0:
            band = rgb.crop((0, y, width - shift, y + band_h))
            dest = (shift, y)
        else:
            band = rgb.crop((-shift, y, width, y + band_h))
            dest = (0, y)

        red, green, blue = band.split()
        zero = Image.new("L", band.size, 0)
        alpha = Image.new("L", band.size, rng.randint(15, 29))
        if band_index % 2:
            shifted = Image.merge("RGBA", (red, zero, blue, alpha))
        else:
            shifted = Image.merge("RGBA", (zero, green, blue, alpha))
        layer.alpha_composite(shifted, dest=dest)

    return Image.alpha_composite(base, layer)


def _prepare_panel_background(
    background: Optional[Path],
    size: tuple[int, int],
    bg_color: tuple[int, int, int],
    *,
    glitch: bool = True,
) -> Any:
    """Aspect-fill and softly grade the photographic panel background."""
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps

    width, height = size
    base = Image.new("RGBA", size, (*bg_color, 255))
    if not background or not background.exists():
        return base

    try:
        with Image.open(background) as opened:
            fitted = ImageOps.fit(
                opened.convert("RGB"),
                size,
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
        scale = max(0.5, min(width / 1920, height / 1080))
        fitted = fitted.filter(ImageFilter.GaussianBlur(radius=1.8 * scale))
        fitted = ImageEnhance.Color(fitted).enhance(0.76)
        fitted = ImageEnhance.Brightness(fitted).enhance(0.57)
        if glitch:
            return _glitch_panel_background(
                fitted,
                seed=0x54454D50 ^ (width << 8) ^ height,
            )
        return fitted.convert("RGBA")
    except Exception as exc:
        warn(f"Could not load background: {background} ({exc})")
        return base


def _draw_telegram_qr(img: Any, font_path: Optional[Path], accent: tuple[int, int, int]) -> Any:
    """Draw a scan-safe QR and decorate only the card outside its quiet zone."""
    import qrcode
    from PIL import Image, ImageDraw, ImageFilter
    from qrcode.constants import ERROR_CORRECT_H

    width, height = img.size
    scale = max(0.5, min(width / 1920, height / 1080))
    card_w = max(132, round(width * 0.108))
    card_x = width - round(width * 0.042) - card_w
    card_y = round(height * 0.038)
    pad = max(8, round(12 * scale))
    qr_side = card_w - 2 * pad
    label_h = max(42, round(53 * scale))
    card_h = qr_side + label_h + 2 * pad
    radius = max(8, round(14 * scale))

    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_H,
        box_size=8,
        border=4,
    )
    qr.add_data(TELEGRAM_CHANNEL_URL)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="#17131d", back_color="#f4efe7").convert("RGBA")
    qr_img = qr_img.resize((qr_side, qr_side), Image.Resampling.NEAREST)

    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(
        (card_x, card_y + round(8 * scale), card_x + card_w, card_y + card_h + round(8 * scale)),
        radius=radius,
        fill=(0, 0, 0, 145),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=max(5, round(14 * scale))))
    img = Image.alpha_composite(img, shadow)

    card = Image.new("RGBA", img.size, (0, 0, 0, 0))
    card_draw = ImageDraw.Draw(card)
    card_draw.rounded_rectangle(
        (card_x, card_y, card_x + card_w, card_y + card_h),
        radius=radius,
        fill=(15, 13, 19, 224),
        outline=(255, 255, 255, 34),
        width=max(1, round(scale)),
    )
    line_margin = round(card_w * 0.16)
    card_draw.line(
        (card_x + line_margin, card_y, card_x + card_w - line_margin, card_y),
        fill=(*accent, 220),
        width=max(1, round(2 * scale)),
    )
    card.alpha_composite(qr_img, dest=(card_x + pad, card_y + pad))

    label_x = card_x + pad
    label_y = card_y + pad + qr_side + max(7, round(8 * scale))
    label_font = _panel_font(font_path, max(10, round(14 * scale)), bold=True)
    handle_font = _panel_font(font_path, max(9, round(11 * scale)))
    _draw_panel_text_top(
        card_draw,
        (label_x, label_y),
        "TELEGRAM",
        font=label_font,
        fill=(*accent, 255),
    )
    _draw_panel_text_top(
        card_draw,
        (label_x, label_y + max(17, round(20 * scale))),
        "@temple_of_lizard",
        font=handle_font,
        fill=(244, 239, 231, 158),
    )
    return Image.alpha_composite(img, card)


def draw_panel(
    out: Path,
    chapters: list[Chapter],
    current_index: int,
    cover: Path,
    background: Optional[Path] = None,
    font: Optional[Path] = None,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    style: str = "deep-purple",
    animated_visuals: bool = False,
    timeline_duration: Optional[float] = None,
    editor_project: Optional[dict[str, Any]] = None,
) -> None:
    from PIL import Image, ImageDraw, ImageFilter, ImageOps

    W, H = width, height

    # Resolve style
    palette = STYLE_PRESETS.get(style, STYLE_PRESETS["deep-purple"])
    bg_color = palette["bg"]
    accent = palette["accent"]
    accent2 = palette["accent2"]
    project_data = editor_project if isinstance(editor_project, dict) else {}
    project_layers = project_data.get("layers") if isinstance(project_data.get("layers"), dict) else {}

    def layer_config(layer_id: str) -> dict[str, Any]:
        value = project_layers.get(layer_id)
        return value if isinstance(value, dict) else {}

    def layer_pixel(config: dict[str, Any], key: str, default: float, extent: int) -> int:
        try:
            value = float(config.get(key, default))
        except (TypeError, ValueError):
            value = default
        return round(extent * max(0.0, value) / 100.0)

    cover_config = layer_config("cover")
    title_config = layer_config("title")
    visualizer_config = layer_config("visualizer")
    cover_visible = cover_config.get("visible", True) is not False
    title_visible = title_config.get("visible", True) is not False
    visualizer_visible = visualizer_config.get("visible", True) is not False

    text_color = rgb_or_default(title_config.get("color"), palette["text"])
    text_dim = palette["text_dim"]
    title_glow = palette["title_glow"]
    img = _prepare_panel_background(
        background,
        (W, H),
        bg_color,
        glitch=project_data.get("glitch", True) is not False,
    )
    scale = max(0.5, min(W / 1920, H / 1080))

    # Cover image
    ch = chapters[current_index]
    cover_x = layer_pixel(cover_config, "x", 7.0, W)
    cover_y = layer_pixel(cover_config, "y", 17.0, H)
    cover_w = max(32, layer_pixel(cover_config, "w", 27.0, W))
    cover_h = max(32, layer_pixel(cover_config, "h", 66.0, H))

    if cover_visible and cover.exists():
        try:
            with Image.open(cover) as opened:
                cv = ImageOps.fit(
                    opened.convert("RGBA"),
                    (cover_w, cover_h),
                    method=Image.Resampling.LANCZOS,
                    centering=(0.5, 0.5),
                )
            radius = max(8, round(17 * scale))
            mask = Image.new("L", (cover_w, cover_h), 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                (0, 0, cover_w - 1, cover_h - 1),
                radius=radius,
                fill=255,
            )

            shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(shadow).rounded_rectangle(
                (
                    cover_x,
                    cover_y + round(10 * scale),
                    cover_x + cover_w,
                    cover_y + cover_h + round(10 * scale),
                ),
                radius=radius,
                fill=(0, 0, 0, 165),
            )
            shadow = shadow.filter(ImageFilter.GaussianBlur(radius=max(6, round(20 * scale))))
            img = Image.alpha_composite(img, shadow)

            cover_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            cover_layer.paste(cv, (cover_x, cover_y), mask)
            cover_draw = ImageDraw.Draw(cover_layer)
            cover_draw.rounded_rectangle(
                (cover_x, cover_y, cover_x + cover_w - 1, cover_y + cover_h - 1),
                radius=radius,
                outline=(*accent, 118),
                width=max(1, round(2 * scale)),
            )
            img = Image.alpha_composite(img, cover_layer)
        except Exception as e:
            warn(f"Could not place cover: {e}")

    # Previous/current/next chapter stack. Neighbours live on a transparent
    # layer so alpha=128 remains a real 50% after the final RGB conversion.
    title_text = ch.title.strip() or f"Chapter {current_index + 1}"
    title_x = layer_pixel(title_config, "x", 39.0, W)
    title_y = layer_pixel(title_config, "y", 23.0, H)
    title_w = max(64, layer_pixel(title_config, "w", 54.0, W))
    title_h = max(48, layer_pixel(title_config, "h", 31.0, H))
    title_pad_x = max(12, round(title_w * 0.025))
    available_w = title_w - 2 * title_pad_x

    text_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    text_draw = ImageDraw.Draw(text_layer)
    previous = chapters[current_index - 1] if current_index > 0 else None
    following = chapters[current_index + 1] if current_index + 1 < len(chapters) else None
    side_values = []
    if previous:
        side_values.append(f"{current_index:02d}  {previous.title.strip()}")
    if following:
        side_values.append(f"{current_index + 2:02d}  {following.title.strip()}")

    side_font = _fit_panel_side_font(
        text_draw,
        side_values,
        font,
        available_w,
        max_size=max(14, round(25 * scale)),
    )
    side_bbox = text_draw.textbbox((0, 0), "Др", font=side_font)
    side_h = max(1, side_bbox[3] - side_bbox[1])
    side_count = int(previous is not None) + int(following is not None)
    stack_gap = max(7, round(15 * scale))
    current_max_h = max(
        1,
        title_h - side_count * side_h - side_count * stack_gap,
    )
    try:
        configured_title_size = float(title_config.get("fontSize", 48))
    except (TypeError, ValueError):
        configured_title_size = 48.0
    current_font, current_text, current_spacing, current_dims = _fit_panel_title(
        text_draw,
        title_text,
        font,
        available_w,
        current_max_h,
        max_size=max(18, round(configured_title_size * scale)),
        min_size=max(18, round(28 * scale)),
        max_lines=3,
    )
    stack_h = current_dims[1] + side_count * (side_h + stack_gap)
    cursor_y = title_y + max(0, (title_h - stack_h) // 2)

    def draw_side(chapter_number: int, value: str, y: int) -> None:
        prefix = f"{chapter_number:02d}"
        prefix_w = _panel_text_width(text_draw, f"{prefix}  ", side_font)
        _draw_panel_text_top(
            text_draw,
            (title_x + title_pad_x, y),
            prefix,
            font=side_font,
            fill=(*accent, 128),
        )
        _draw_panel_text_top(
            text_draw,
            (title_x + title_pad_x + prefix_w, y),
            value,
            font=side_font,
            fill=(*text_color, 128),
        )

    if previous:
        draw_side(current_index, previous.title.strip(), cursor_y)
        cursor_y += side_h + stack_gap

    if title_glow:
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow)
        _draw_panel_text_top(
            glow_draw,
            (title_x + title_pad_x, cursor_y),
            current_text,
            font=current_font,
            fill=(*accent2, 52),
            spacing=current_spacing,
        )
        glow = glow.filter(ImageFilter.GaussianBlur(radius=max(2, round(5 * scale))))
        text_layer = Image.alpha_composite(glow, text_layer)
        text_draw = ImageDraw.Draw(text_layer)

    _draw_panel_text_top(
        text_draw,
        (title_x + title_pad_x, cursor_y),
        current_text,
        font=current_font,
        fill=(*text_color, 255),
        spacing=current_spacing,
    )
    cursor_y += current_dims[1] + stack_gap

    if following:
        draw_side(current_index + 2, following.title.strip(), cursor_y)

    if title_visible:
        img = Image.alpha_composite(img, text_layer)

    chrome_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(chrome_layer)

    # Visualizer geometry mirrors the Vue composition layer. During video
    # export FFmpeg paints the audio-reactive curve over this quiet grid;
    # PNG previews retain a deterministic fallback line.
    wave_x = layer_pixel(visualizer_config, "x", 38.0, W)
    wave_y = layer_pixel(visualizer_config, "y", 59.0, H)
    wave_w = max(64, layer_pixel(visualizer_config, "w", 56.0, W))
    wave_h = max(48, layer_pixel(visualizer_config, "h", 23.0, H))
    wave_mid = wave_y + wave_h // 2
    if visualizer_visible:
        for row in range(1, 5):
            grid_y = wave_y + round(wave_h * row / 5)
            draw.line(
                (wave_x, grid_y, wave_x + wave_w, grid_y),
                fill=(255, 255, 255, 19),
                width=max(1, round(scale)),
            )
        draw.line(
            (wave_x, wave_mid, wave_x + wave_w, wave_mid),
            fill=(*accent, 54),
            width=max(1, round(scale)),
        )

    if visualizer_visible and not animated_visuals:
        import random

        rng = random.Random(ch.start_seconds)
        points = []
        point_count = 96
        for n in range(point_count):
            bx = wave_x + round(n * wave_w / max(1, point_count - 1))
            amplitude = 0.08 + 0.66 * rng.random() ** 2
            by = wave_y + round(wave_h * (0.82 - amplitude * 0.64))
            points.append((bx, by))
        if len(points) > 1:
            draw.line(points, fill=(*accent, 236), width=max(2, round(2 * scale)), joint="curve")

    # The scene progress rail is intentionally thin, like the Vue preview.
    # Only the neutral rail and total time are baked into panels. The moving
    # fill/current time are generated per frame by FFmpeg.
    total_duration = max(
        0.001,
        float(timeline_duration or max((item.end_seconds for item in chapters), default=0.0)),
    )
    progress_label_x = round(W * 0.398)
    progress_bar_x = round(W * 0.455)
    progress_bar_y = round(H * 0.944)
    progress_bar_w = round(W * 0.435)
    progress_bar_h = max(2, round(2 * scale))
    draw.rounded_rectangle(
        (
            progress_bar_x,
            progress_bar_y,
            progress_bar_x + progress_bar_w,
            progress_bar_y + progress_bar_h,
        ),
        radius=progress_bar_h,
        fill=(255, 255, 255, 34),
    )
    if not animated_visuals:
        progress = max(0.0, min(1.0, ch.start_seconds / total_duration))
        progress_width = round(progress_bar_w * progress)
        if progress_width > 0:
            draw.rounded_rectangle(
                (
                    progress_bar_x,
                    progress_bar_y,
                    progress_bar_x + progress_width,
                    progress_bar_y + progress_bar_h,
                ),
                radius=progress_bar_h,
                fill=(*accent, 238),
            )

    time_font = _panel_font(font, max(10, round(15 * scale)))
    time_y = progress_bar_y - max(5, round(8 * scale))
    if not animated_visuals:
        _draw_panel_text_top(
            draw,
            (progress_label_x, time_y),
            seconds_to_timecode(ch.start_seconds, millis=False),
            font=time_font,
            fill=(*text_dim, 180),
        )
    total_label = seconds_to_timecode(total_duration, millis=False)
    total_width = _panel_text_width(draw, total_label, time_font)
    _draw_panel_text_top(
        draw,
        (round(W * 0.947) - total_width, time_y),
        total_label,
        font=time_font,
        fill=(*text_dim, 180),
    )

    img = Image.alpha_composite(img, chrome_layer)

    # QR is deliberately last: its modules and quiet zone must never be blurred
    # or displaced by the background glitch treatment.
    img = _draw_telegram_qr(img, font, accent)

    # Save
    img.convert("RGB").save(out, "PNG")
    log(f"Panel saved: {out}")


def render_panels(
    chapters: list[Chapter],
    cover: Path,
    background: Optional[Path],
    font: Optional[Path],
    out_dir: Path,
    count: Optional[int] = None,
    only_index: Optional[int] = None,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    style: str = "deep-purple",
    animated_visuals: bool = False,
    timeline_duration: Optional[float] = None,
    editor_project: Optional[dict[str, Any]] = None,
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
        draw_panel(
            out,
            chapters=chapters,
            current_index=i,
            cover=cover,
            background=background,
            font=font,
            width=width,
            height=height,
            style=style,
            animated_visuals=animated_visuals,
            timeline_duration=timeline_duration,
            editor_project=editor_project,
        )
        paths.append(out)
    return paths


def concat_file_line(path: Path) -> str:
    s = str(path.resolve()).replace("\\", "/").replace("'", "'\\''")
    return f"file '{s}'"


# ── GPU-accelerated segment rendering ────────────────────────────

def _render_segment_worker(args: dict[str, Any]) -> dict[str, Any]:
    """Render one chapter with live visuals and a safe CPU fallback."""
    panel = Path(args["panel"])
    audio = Path(args["audio"])
    out = Path(args["out"])
    start = float(args["start"])
    duration = float(args["duration"])
    fps = int(args["fps"])
    width = int(args["width"])
    height = int(args["height"])
    dry_run = bool(args.get("dry_run", False))
    gpu_codec = str(args.get("gpu_codec", "libx264"))
    gpu_preset = str(args.get("gpu_preset", "fast"))
    gpu_opts = dict(args.get("gpu_opts", {}))
    style = str(args.get("style", "deep-purple"))
    include_audio = bool(args.get("include_audio", True))
    timeline_duration = max(duration, float(args.get("timeline_duration") or duration))
    visualizer = dict(args.get("visualizer") or {})

    ensure_dir(out.parent)

    def percent_pixel(key: str, default: float, extent: int) -> int:
        try:
            value = float(visualizer.get(key, default))
        except (TypeError, ValueError):
            value = default
        return round(extent * max(0.0, value) / 100.0)

    animated_visuals = args.get("waveform", "ffmpeg") == "ffmpeg"
    waveform_visible = animated_visuals and visualizer.get("visible", True) is not False
    palette = STYLE_PRESETS.get(style, STYLE_PRESETS["deep-purple"])
    accent = tuple(palette["accent"])
    accent2 = tuple(palette["accent2"])
    accent_hex = "".join(f"{channel:02x}" for channel in accent)
    accent2_hex = "".join(f"{channel:02x}" for channel in accent2)

    filter_parts: list[str] = [f"[0:v]scale={width}:{height},setsar=1,format=rgba[base]"]
    current_label = "base"

    if waveform_visible:
        wave_x = percent_pixel("x", 38.0, width)
        wave_y = percent_pixel("y", 59.0, height)
        wave_w = max(64, percent_pixel("w", 56.0, width))
        wave_h = max(48, percent_pixel("h", 23.0, height))
        filter_parts.extend(
            [
                "[1:a]asetpts=PTS-STARTPTS,asplit=2[wave_fill_audio][wave_line_audio]",
                (
                    f"[wave_fill_audio]showwaves=s={wave_w}x{wave_h}:mode=cline:rate={fps}:"
                    f"colors=0x{accent2_hex}:scale=sqrt:draw=full,format=rgba,"
                    "colorkey=0x000000:0.05:0.0,colorchannelmixer=aa=0.18[wave_fill]"
                ),
                (
                    f"[wave_line_audio]showwaves=s={wave_w}x{wave_h}:mode=p2p:rate={fps}:"
                    f"colors=0x{accent_hex}:scale=sqrt:draw=full,format=rgba,"
                    "colorkey=0x000000:0.05:0.0,colorchannelmixer=aa=0.96[wave_line]"
                ),
                (
                    f"[base][wave_fill]overlay=x={wave_x}:y={wave_y}:"
                    "shortest=0:eof_action=pass:repeatlast=0:format=auto[with_wave_fill]"
                ),
                (
                    f"[with_wave_fill][wave_line]overlay=x={wave_x}:y={wave_y}:"
                    "shortest=0:eof_action=pass:repeatlast=0:format=auto[with_wave]"
                ),
            ]
        )
        current_label = "with_wave"

    if animated_visuals:
        scale = max(0.5, min(width / 1920, height / 1080))
        progress_x = round(width * 0.455)
        progress_y = round(height * 0.944)
        progress_w = max(64, round(width * 0.435))
        progress_h = max(2, round(2 * scale))
        progress_expression = (
            f"-{progress_w}+{progress_w}*({start:.6f}+t)/{timeline_duration:.6f}"
        )
        filter_parts.extend(
            [
                (
                    f"color=c=black@0.0:s={progress_w}x{progress_h}:"
                    f"r={fps}:d={duration:.6f},format=rgba[progress_canvas]"
                ),
                (
                    f"color=c=0x{accent_hex}@0.96:s={progress_w}x{progress_h}:"
                    f"r={fps}:d={duration:.6f},format=rgba[progress_fill]"
                ),
                (
                    f"[progress_canvas][progress_fill]overlay=x='{progress_expression}':"
                    "y=0:eval=frame:shortest=1:eof_action=pass[progress_local]"
                ),
                (
                    f"[{current_label}][progress_local]overlay=x={progress_x}:"
                    f"y={progress_y}:shortest=1:eof_action=pass[with_progress]"
                ),
            ]
        )
        current_label = "with_progress"

        font_value = args.get("font")
        font_path = Path(font_value) if font_value else Path(os.environ.get("SystemRoot", "C:\\Windows")) / "Fonts" / "segoeui.ttf"
        if font_path.is_file():
            escaped_font = str(font_path.resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
            time_x = round(width * 0.398)
            time_y = progress_y - max(7, round(10 * scale))
            time_size = max(10, round(15 * scale))
            filter_parts.append(
                f"[{current_label}]drawtext=fontfile='{escaped_font}':"
                f"text='%{{pts\\:hms\\:{start:.6f}}}':"
                f"fontcolor=white@0.44:fontsize={time_size}:x={time_x}:y={time_y}:"
                "fix_bounds=1[with_time]"
            )
            current_label = "with_time"

    filter_complex: Optional[str] = None
    if animated_visuals:
        filter_parts.append(f"[{current_label}]format=yuv420p[v]")
        filter_complex = ";".join(filter_parts)

    def make_encoder(codec: str, preset: str, options: dict[str, Any]) -> dict[str, Any]:
        encoder: dict[str, Any] = {"codec": codec, "preset": preset}
        encoder.update(options)
        if codec == "libx264":
            encoder["crf"] = options.get("crf", 22)
        return encoder

    attempts = [(gpu_codec, gpu_preset, gpu_opts)]
    if gpu_codec != "libx264":
        attempts.append(("libx264", "fast", {"crf": 22}))

    last_error = "unknown encoder error"
    for attempt_index, (codec, preset, options) in enumerate(attempts):
        encoder_args = encoder_ffmpeg_args(
            make_encoder(codec, preset, options),
            width,
            height,
            fps,
            include_video_filter=filter_complex is None,
            include_audio=include_audio,
        )
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-framerate", str(fps),
            "-i", str(panel),
            "-ss", f"{start:.3f}",
            "-t", f"{duration:.3f}",
            "-i", str(audio),
        ]
        if filter_complex:
            cmd += ["-filter_complex", filter_complex, "-map", "[v]"]
        else:
            cmd += ["-map", "0:v:0"]
        if include_audio:
            cmd += ["-map", "1:a:0", "-shortest"]
        else:
            cmd += ["-an", "-t", f"{duration:.6f}"]
        cmd += [*encoder_args, str(out)]

        if dry_run:
            print(f"[DRY RUN] Would render: {out.name} ({codec})", flush=True)
            return {"ok": True, "dry_run": True, "out": str(out), "encoder": codec}

        try:
            fallback_note = " (CPU fallback)" if attempt_index else ""
            log(f"Rendering segment: {out.name} | {duration:.1f}s | {codec}{fallback_note}")
            started = time.time()
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                **hidden_process_options(),
            )
            elapsed = time.time() - started
            speed = duration / elapsed if elapsed > 0 else 0
            log(f"Segment done: {out.name} | {elapsed:.1f}s | {speed:.1f}x | {codec}")
            return {
                "ok": True,
                "out": str(out),
                "elapsed": elapsed,
                "speed": speed,
                "encoder": codec,
            }
        except subprocess.CalledProcessError as exc:
            last_error = (exc.stderr or str(exc))[-1200:]
            if attempt_index + 1 < len(attempts):
                warn(f"{codec} failed for {out.name}; retrying safely with libx264")
            else:
                warn(f"Segment failed: {out.name} | {last_error}")

    return {"ok": False, "out": str(out), "error": last_error}


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
    gpu_codec: str = "libx264",
    gpu_preset: str = "fast",
    gpu_opts: Optional[dict[str, Any]] = None,
) -> None:
    """Render a single segment (legacy direct call, no worker pool)."""
    args = {
        "panel": str(panel),
        "audio": str(audio),
        "out": str(out),
        "start": start,
        "duration": duration,
        "fps": fps,
        "width": width,
        "height": height,
        "dry_run": dry_run,
        "waveform": waveform,
        "gpu_codec": gpu_codec,
        "gpu_preset": gpu_preset,
        "gpu_opts": gpu_opts or {},
    }
    result = _render_segment_worker(args)
    if not result.get("ok"):
        if "error" in result:
            fail(f"Segment render failed: {result['error']}")
        else:
            fail("Segment render failed")


def render_segments_parallel(
    segments_args: list[dict[str, Any]],
    max_workers: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Render segments concurrently without spawning visible Python consoles."""
    if max_workers is None:
        # Two workers keep GPU/decoder pressure predictable for multi-hour,
        # multi-gigabyte audiobook masters.
        max_workers = min(os.cpu_count() or 1, 2)
    log(f"Parallel rendering with {max_workers} workers")
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="render") as pool:
        return list(pool.map(_render_segment_worker, segments_args))


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


def mux_master_audio(
    video: Path,
    audio: Path,
    out: Path,
    *,
    start: float = 0.0,
    duration: float,
    dry_run: bool = False,
) -> None:
    """Attach the master once, avoiding AAC priming gaps at chapter joins."""
    ensure_dir(out.parent if out.parent != Path("") else Path.cwd())
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video),
        "-ss", f"{max(0.0, start):.6f}",
        "-i", str(audio),
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-t", f"{duration:.6f}",
        "-shortest",
        "-movflags", "+faststart",
        str(out),
    ]
    run_cmd(cmd, dry_run=dry_run)


def validate_render_output(
    out: Path,
    *,
    expected_duration: float,
    width: int,
    height: int,
    fps: int,
    dry_run: bool = False,
) -> None:
    """Reject empty, truncated or structurally invalid final exports."""
    if dry_run:
        return
    if not out.is_file() or out.stat().st_size <= 0:
        fail(f"Final render is missing or empty: {out}")
    ffprobe = check_binary("ffprobe", required=True)
    assert ffprobe is not None
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v", "error",
                "-show_streams",
                "-show_format",
                "-of", "json",
                str(out),
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            **hidden_process_options(),
        )
        payload = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        fail(f"Final render failed ffprobe validation: {exc}")

    streams = payload.get("streams") if isinstance(payload, dict) else None
    if not isinstance(streams, list):
        fail("Final render has no readable streams")
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio_stream = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if not video or not audio_stream:
        fail("Final render must contain both video and audio streams")
    if (int(video.get("width") or 0), int(video.get("height") or 0)) != (width, height):
        fail(
            f"Final render resolution mismatch: {video.get('width')}x{video.get('height')} "
            f"instead of {width}x{height}"
        )
    if video.get("codec_name") != "h264" or audio_stream.get("codec_name") != "aac":
        fail(
            "Final render codec mismatch: expected H.264/AAC, got "
            f"{video.get('codec_name')}/{audio_stream.get('codec_name')}"
        )
    if video.get("pix_fmt") != "yuv420p":
        fail(f"Final render pixel format is not yuv420p: {video.get('pix_fmt')}")

    rate = str(video.get("avg_frame_rate") or "0/1")
    try:
        numerator, denominator = rate.split("/", 1)
        actual_fps = float(numerator) / max(float(denominator), 1.0)
    except (TypeError, ValueError, ZeroDivisionError):
        actual_fps = 0.0
    if abs(actual_fps - fps) > 0.02:
        fail(f"Final render frame rate mismatch: {actual_fps:.3f} instead of {fps}")

    format_data = payload.get("format") if isinstance(payload.get("format"), dict) else {}
    try:
        actual_duration = float(format_data.get("duration"))
    except (TypeError, ValueError):
        actual_duration = 0.0
    tolerance = max(0.35, 3.0 / max(1, fps))
    if actual_duration <= 0 or abs(actual_duration - expected_duration) > tolerance:
        fail(
            f"Final render duration mismatch: {actual_duration:.3f}s instead of "
            f"{expected_duration:.3f}s"
        )
    log(
        f"Validated MP4: H.264/AAC | {width}x{height} | "
        f"{actual_fps:.3f} fps | {actual_duration:.3f}s"
    )


# ── Progress callback type ──────────────────────────────────────
RenderProgressCb = Optional[callable]

# ── Commands ─────────────────────────────────────────────────────

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
    editor_project = load_editor_project_config(getattr(args, "editor_project", None))
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
        style=args.style,
        editor_project=editor_project,
    )
    log("Preview panels created:")
    for p in paths:
        print(f"  {p}")


def analyze_chapter_gaps(chapters: list[Chapter]) -> list[dict[str, Any]]:
    gaps = []
    for i in range(len(chapters) - 1):
        gap = chapters[i + 1].start_seconds - chapters[i].end_seconds
        if abs(gap) > 0.05:
            kind = "overlap" if gap < 0 else "gap"
            gaps.append({
                "kind": kind,
                "gap_seconds": round(gap, 3),
                "after": chapters[i].title,
                "before": chapters[i + 1].title,
                "after_index": i,
                "before_index": i + 1,
            })
    return gaps


def load_editor_project_config(path_value: Optional[str]) -> dict[str, Any]:
    """Load optional Vue editor state without making CLI rendering depend on it."""
    if not path_value:
        return {}
    path = Path(path_value)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            return value
        warn(f"Editor project is not a JSON object: {path}")
    except Exception as exc:
        warn(f"Could not load editor project {path}: {exc}")
    return {}


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
    for previous, current in zip(chapters, chapters[1:]):
        if current.start_seconds <= previous.start_seconds + 0.001:
            fail(
                "Chapter starts must be strictly increasing: "
                f"'{previous.title}' and '{current.title}'"
            )

    editor_project = load_editor_project_config(getattr(args, "editor_project", None))
    timeline_duration = max((chapter.end_seconds for chapter in chapters), default=0.0)
    project_duration_value = editor_project.get(
        "duration_seconds",
        editor_project.get("durationSeconds", editor_project.get("audioDuration")),
    )
    if project_duration_value is None and editor_project.get("durationMs") is not None:
        project_duration_value = safe_float(str(editor_project.get("durationMs"))) / 1000.0
    project_duration = safe_float(str(project_duration_value)) if project_duration_value is not None else 0.0
    if math.isfinite(project_duration) and project_duration > 0.05:
        if abs(project_duration - timeline_duration) > 1.0 / max(1, args.fps):
            warn(
                f"Using editor audio duration {project_duration:.3f}s instead of "
                f"chapter tail {timeline_duration:.3f}s"
            )
        timeline_duration = project_duration
    max_duration = getattr(args, "max_duration", None)
    render_end = timeline_duration
    if max_duration is not None:
        render_end = min(render_end, max(0.0, float(max_duration)))
    if render_end <= 0.05:
        fail("Render duration is too short")
    render_count = sum(1 for chapter in chapters if chapter.start_seconds < render_end - 0.001)
    timing_anomalies = analyze_chapter_gaps(chapters)
    if timing_anomalies:
        warn(
            f"Normalizing {len(timing_anomalies)} chapter gap/overlap boundaries "
            "to marker starts so video stays aligned with the master audio"
        )

    out_base = Path(args.build_dir) if args.build_dir else Path.cwd()
    bdir = build_dir(out_base)
    save_chapters(bdir / "chapters.used.json", chapters)
    save_youtube_chapters(bdir / "youtube_chapters.txt", chapters)

    panels_dir = ensure_dir(bdir / "panels")
    segments_dir = ensure_dir(bdir / "segments")

    # GPU detection
    gpu_name, gpu_enc = detect_gpu_encoder()
    gpu_codec = gpu_enc["codec"]
    gpu_preset = gpu_enc.get("preset", DEFAULT_PRESET)
    gpu_opts = {k: gpu_enc[k] for k in ("cq", "rc", "b_pyramid", "gpu", "global_quality") if k in gpu_enc}

    log(f"Using encoder: {gpu_enc['label']} ({gpu_codec})")
    log(f"Rendering {render_count} of {len(chapters)} panels")

    render_panels(
        chapters,
        cover=cover,
        background=Path(args.background) if args.background else None,
        font=Path(args.font) if args.font else None,
        out_dir=panels_dir,
        count=render_count,
        only_index=None,
        width=args.width,
        height=args.height,
        style=args.style,
        animated_visuals=args.waveform == "ffmpeg",
        timeline_duration=timeline_duration,
        editor_project=editor_project,
    )

    # Build segment args
    segment_args_list: list[dict[str, Any]] = []
    project_layers = editor_project.get("layers") if isinstance(editor_project.get("layers"), dict) else {}
    visualizer_config = project_layers.get("visualizer") if isinstance(project_layers.get("visualizer"), dict) else {}
    for i, ch in enumerate(chapters):
        if ch.start_seconds >= render_end - 0.001:
            break
        # Chapter start markers are the source of truth. Using each stored
        # end independently could omit or duplicate time when a hand-edited
        # map contains a gap/overlap, then desynchronise every later title.
        segment_start = 0.0 if i == 0 else ch.start_seconds
        next_start = chapters[i + 1].start_seconds if i + 1 < len(chapters) else render_end
        segment_end = min(render_end, next_start)
        segment_duration = segment_end - segment_start
        if segment_duration <= 0:
            fail(f"Chapter has no renderable duration: {ch.title}")
        if segment_duration < 1.0 / max(1, args.fps):
            if not segment_args_list:
                fail(f"First chapter is shorter than one video frame: {ch.title}")
            warn(f"Merging sub-frame chapter into previous panel: {ch.title}")
            segment_args_list[-1]["duration"] += segment_duration
            continue
        panel = panels_dir / f"{i:03d}.png"
        segment = segments_dir / f"{i:03d}.mp4"
        segment_args_list.append({
            "panel": str(panel),
            "audio": str(audio),
            "out": str(segment),
            "start": segment_start,
            "duration": segment_duration,
            "fps": args.fps,
            "width": args.width,
            "height": args.height,
            "dry_run": args.dry_run,
            "waveform": args.waveform,
            "style": args.style,
            "timeline_duration": timeline_duration,
            "visualizer": visualizer_config,
            "font": args.font,
            "include_audio": False,
            "gpu_codec": gpu_codec,
            "gpu_preset": gpu_preset,
            "gpu_opts": gpu_opts,
        })

    if not segment_args_list:
        fail("No segments to render")

    # Parallel render
    parallel = not getattr(args, "no_parallel", False)
    if parallel and len(segment_args_list) > 1:
        results = render_segments_parallel(segment_args_list)
    else:
        results = []
        for sargs in segment_args_list:
            r = _render_segment_worker(sargs)
            results.append(r)

    # A missing chapter must never be silently removed: doing so would shift
    # every later title against the continuous master audio.
    failures = [result for result in results if not result.get("ok")]
    if failures:
        first = failures[0]
        fail(
            f"Render aborted: {len(failures)} of {len(results)} segments failed. "
            f"First error: {first.get('error', 'unknown encoder error')}"
        )

    # Direct H.264 concat is only safe when every segment comes from one
    # encoder family. If a single GPU segment required CPU fallback, rebuild
    # the complete set with libx264 so SPS/profile/extradata stay consistent.
    used_encoders = {str(result.get("encoder")) for result in results}
    if len(used_encoders) > 1:
        warn(
            "Mixed GPU/CPU segment output detected; rebuilding every segment "
            "with libx264 for a safe final concat"
        )
        cpu_args = [
            {
                **segment_args,
                "gpu_codec": "libx264",
                "gpu_preset": "fast",
                "gpu_opts": {"crf": 22},
            }
            for segment_args in segment_args_list
        ]
        if parallel and len(cpu_args) > 1:
            results = render_segments_parallel(cpu_args)
        else:
            results = [_render_segment_worker(segment_args) for segment_args in cpu_args]
        failures = [result for result in results if not result.get("ok")]
        if failures:
            fail(
                f"CPU safety rebuild failed for {len(failures)} of "
                f"{len(results)} segments: {failures[0].get('error', 'unknown error')}"
            )

    # Collect rendered segments
    rendered_segments: list[Path] = []
    for result in results:
        p = Path(result["out"])
        if result.get("ok") and (args.dry_run or (p.exists() and p.stat().st_size > 0)):
            rendered_segments.append(p)
        else:
            detail = result.get("error", "output file is missing or empty")
            warn(f"Segment failed: {p} | {detail}")

    if not rendered_segments:
        fail("No segments rendered successfully")
    if len(rendered_segments) != len(segment_args_list):
        fail(
            f"Render aborted: expected {len(segment_args_list)} segment files, "
            f"got {len(rendered_segments)}"
        )

    video_only = bdir / "video_only.mp4"
    concat_segments(rendered_segments, video_only, bdir / "concat.txt", dry_run=args.dry_run)
    output_duration = sum(float(item["duration"]) for item in segment_args_list)
    mux_master_audio(
        video_only,
        audio,
        Path(args.out),
        start=float(segment_args_list[0]["start"]),
        duration=output_duration,
        dry_run=args.dry_run,
    )
    validate_render_output(
        Path(args.out),
        expected_duration=output_duration,
        width=args.width,
        height=args.height,
        fps=args.fps,
        dry_run=args.dry_run,
    )
    log(f"Done: {args.out}")


# ── CLI ──────────────────────────────────────────────────────────

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
    p.add_argument("--style", choices=list(STYLE_PRESETS.keys()), default="deep-purple",
                    help="Visual theme for panel rendering")
    p.add_argument("--editor-project", help="Optional Vue editor-project.json for layer parity")
    p.add_argument("--build-dir", help="Base dir for _suviren_q_build")


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        prog="book-wunderwaffe",
        description="BOOK WUNDERWAFFE Studio — local-first audiobook production suite",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {APP_VERSION}")
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

    p_render = sub.add_parser("render", help="Render final MP4 with GPU acceleration")
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
    p_render.add_argument("--waveform", choices=["static", "ffmpeg"], default="ffmpeg", help="Audio visualization mode")
    p_render.add_argument("--max-duration", type=float, help="Render only the first N seconds while keeping full chapter context")
    p_render.add_argument("--dry-run", action="store_true")
    p_render.add_argument("--no-parallel", action="store_true", dest="no_parallel", help="Disable parallel segment rendering")
    add_visual_args(p_render)
    p_render.set_defaults(func=cmd_render)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()