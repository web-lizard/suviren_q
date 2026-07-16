#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
suviren-q: La Queue Souveraine
Audiobook → YouTube video builder with GPU-accelerated rendering.

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
import csv
import json
import math
import multiprocessing
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Optional

APP_NAME = "suviren-q"
APP_TITLE = "suviren-q: La Queue Souveraine"
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
        "cq": 19,
        "b_pyramid": 1,
        "gpu": 0,
        "label": "NVIDIA NVENC",
    },
    "amd_amf": {
        "codec": "h264_amf",
        "check_bin": "clinfo",
        "check_sub": "amd",
        "preset": "quality",
        "rc": "cbr",
        "cq": 20,
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
    _safe_print(f"[suviren-q] {msg}", flush=True)


def warn(msg: str) -> None:
    _safe_print(f"[suviren-q][WARN] {msg}", flush=True)


def fail(msg: str, code: int = 1) -> None:
    _safe_print(f"[suviren-q][ERROR] {msg}", file=sys.stderr, flush=True)
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
            res = subprocess.run(cmd, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
            return res.stdout
        subprocess.run(cmd, check=True)
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
                out = subprocess.run([check], capture_output=True, text=True, timeout=5)
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
        args += ["-b:v", "0"]
        if enc.get("b_pyramid"):
            args += ["-b-pyramid", "1"]
        if enc.get("gpu") is not None:
            args += ["-gpu", str(enc["gpu"])]
    elif codec == "h264_amf":
        args += ["-c:v", "h264_amf"]
        args += ["-quality", enc.get("preset", "quality")]
        args += ["-rc", enc.get("rc", "cbr")]
        args += ["-qp_i", str(enc.get("cq", 20))]
        args += ["-qp_p", str(enc.get("cq", 20))]
    elif codec == "h264_qsv":
        args += ["-c:v", "h264_qsv"]
        args += ["-preset", enc.get("preset", "veryslow")]
        if "global_quality" in enc:
            args += ["-global_quality", str(enc["global_quality"])]

    # Common args
    args += ["-r", str(fps)]
    args += ["-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p"]
    args += ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]
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

        # Try ffprobe bitrate first (fast if available)
        br_cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=bit_rate",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
        br_res = subprocess.run(br_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        br_str = br_res.stdout.strip()
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
        res = subprocess.run(cmd, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
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

    KEY BEHAVIOR (as of Book Wunderwaffe 1.0):
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
) -> None:
    from PIL import Image, ImageDraw, ImageFont

    W, H = width, height

    # Resolve style
    palette = STYLE_PRESETS.get(style, STYLE_PRESETS["deep-purple"])
    bg_color = palette["bg"]
    accent = palette["accent"]
    accent2 = palette["accent2"]
    text_color = palette["text"]
    text_dim = palette["text_dim"]
    progress_bg = palette["progress_bg"]
    wave_color = palette["waveform"]
    title_glow = palette["title_glow"]
    img = Image.new("RGBA", (W, H), bg_color)

    if background and background.exists():
        try:
            bg_img = Image.open(background).convert("RGBA")
            bg_img = bg_img.resize((W, H), Image.LANCZOS)
            img = Image.alpha_composite(img, bg_img)
        except Exception:
            warn(f"Could not load background: {background}")

    draw = ImageDraw.Draw(img)

    # Load fonts
    ff = None
    fb = None
    if font and font.exists():
        try:
            ff = ImageFont.truetype(str(font), size=32)
            fb = ImageFont.truetype(str(font), size=52)
        except Exception:
            pass
    if ff is None:
        try:
            ff = ImageFont.truetype("segoeui.ttf", 32)
        except Exception:
            ff = ImageFont.load_default()
    if fb is None:
        try:
            fb = ImageFont.truetype("segoeui.ttf", 52)
        except Exception:
            fb = ImageFont.load_default()

    # Cover image
    ch = chapters[current_index]
    cover_size = int(H * 0.42)
    cover_x = int(W * 0.04)
    cover_y = int((H - cover_size) // 2 - 20)

    if cover.exists():
        try:
            cv = Image.open(cover).convert("RGBA")
            cv = cv.resize((cover_size, cover_size), Image.LANCZOS)
            # Rounded corners
            r = int(cover_size * 0.03)
            m = Image.new("RGBA", (cover_size, cover_size), (0, 0, 0, 0))
            m_draw = ImageDraw.Draw(m)
            m_draw.rounded_rectangle([(0, 0), (cover_size, cover_size)], radius=r, fill=(255, 255, 255, 255))
            img.paste(cv, (cover_x, cover_y), mask=m)
        except Exception as e:
            warn(f"Could not place cover: {e}")

    # Title
    title_text = ch.title.strip() or f"Chapter {current_index + 1}"
    draw.text((int(W * 0.42), int(H * 0.22)), title_text, fill=text_color, font=fb)

    # Chapter list
    start_y = int(H * 0.38)
    max_visible = 8
    half = max_visible // 2
    start_i = max(0, current_index - half)
    end_i = min(len(chapters), start_i + max_visible)
    if end_i - start_i < max_visible:
        start_i = max(0, end_i - max_visible)

    for i in range(start_i, end_i):
        c = chapters[i]
        y = start_y + (i - start_i) * 42
        is_active = i == current_index
        prefix = f"{i+1:02d}."
        tc = accent if is_active else text_dim
        time_str = seconds_to_timecode(c.start_seconds, millis=False)
        title_str = truncate_text(c.title, 42)
        line = f"{prefix} {title_str}  {time_str}"
        draw.text((int(W * 0.42), y), line, fill=tc, font=ff)

    # Progress bar bottom
    bar_y = H - int(H * 0.08)
    bar_h = int(H * 0.025)
    bar_x = int(W * 0.04)
    bar_w = int(W * 0.92)
    draw.rounded_rectangle([(bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h)], radius=4, fill=progress_bg)
    if len(chapters) > 1:
        progress = current_index / (len(chapters) - 1)
        prog_w = int(bar_w * progress)
        if prog_w > 0:
            draw.rounded_rectangle([(bar_x, bar_y), (bar_x + prog_w, bar_y + bar_h)], radius=4, fill=accent)

    # Waveform bar
    wave_y = H - int(H * 0.20)
    wave_h = int(H * 0.07)
    bar_count = 64
    import random
    rng = random.Random(ch.start_seconds)  # deterministic
    for n in range(bar_count):
        bw = max(3, (int(W * 0.85)) // bar_count - 1)
        bx = int(W * 0.08) + n * (bw + 1)
        bh = max(2, int(wave_h * (0.15 + 0.85 * rng.random())))
        by = wave_y + (wave_h - bh) // 2
        draw.rectangle([(bx, by), (bx + bw, by + bh)], fill=wave_color)

    # Chapter count
    footer = f"Chapter {current_index + 1} / {len(chapters)}"
    draw.text((int(W * 0.04), H - int(H * 0.14)), footer, fill=text_dim, font=ff)

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
    s = str(path.resolve()).replace("\\", "/").replace("'", "'\\''")
    return f"file '{s}'"


# ── GPU-accelerated segment rendering ────────────────────────────

def _render_segment_worker(args: dict[str, Any]) -> dict[str, Any]:
    """Worker for parallel segment rendering (runs in subprocess)."""
    panel = Path(args["panel"])
    audio = Path(args["audio"])
    out = Path(args["out"])
    start = args["start"]
    duration = args["duration"]
    fps = args["fps"]
    width = args["width"]
    height = args["height"]
    dry_run = args.get("dry_run", False)
    gpu_codec = args.get("gpu_codec", "libx264")
    gpu_preset = args.get("gpu_preset", "fast")
    gpu_opts = args.get("gpu_opts", {})

    ensure_dir(out.parent)

    # Build encoder args
    enc: dict[str, Any] = {"codec": gpu_codec, "preset": gpu_preset}
    if gpu_codec == "h264_nvenc":
        enc.update(gpu_opts)
    elif gpu_codec == "h264_amf":
        enc.update(gpu_opts)
    elif gpu_codec == "h264_qsv":
        enc.update(gpu_opts)
    elif gpu_codec == "libx264":
        enc["crf"] = gpu_opts.get("crf", 20)

    enc_args = encoder_ffmpeg_args(enc, width, height, fps)

    # Build filter for waveform if needed
    use_waveform = args.get("waveform", "ffmpeg") == "ffmpeg"
    filter_complex = None
    if use_waveform:
        wave_height = max(110, int(height * 0.14))
        wave_y = height - wave_height - int(height * 0.045)
        filter_complex = (
            f"[0:v]scale={width}:{height},format=rgba[base];"
            f"[1:a]showwaves=s={width}x{wave_height}:mode=cline:rate={fps}:"
            f"colors=0x7fffe0|0xb69aff,format=rgba,colorchannelmixer=aa=0.72[wave];"
            f"[base][wave]overlay=x=0:y={wave_y}:format=auto,format=yuv420p[v]"
        )

    # Build base command
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
        cmd += ["-filter_complex", filter_complex]
        cmd += ["-map", "[v]"]
    else:
        cmd += ["-map", "0:v:0"]

    cmd += ["-map", "1:a:0", "-shortest"]

    # Encoder args (replace -vf if we used filter_complex)
    has_vf = False
    for a in enc_args:
        if a.startswith("-vf="):
            has_vf = True
            break
    if not filter_complex and not has_vf:
        cmd += ["-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p"]

    cmd += enc_args

    if dry_run:
        print(f"[DRY RUN] Would render: {out.name}", flush=True)
        return {"ok": True, "dry_run": True, "out": str(out)}

    try:
        log(f"Rendering segment: {out.name} | {duration:.1f}s | {gpu_codec}")
        t0 = time.time()
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        elapsed = time.time() - t0
        speed = duration / elapsed if elapsed > 0 else 0
        log(f"Segment done: {out.name} | {elapsed:.1f}s | {speed:.1f}x")
        return {"ok": True, "out": str(out), "elapsed": elapsed, "speed": speed}
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr[-500:] if e.stderr else str(e)
        return {"ok": False, "out": str(out), "error": error_msg}


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
    """Render a single segment (legacy direct call, no multiprocessing)."""
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
    """Render segments in parallel using multiprocessing pool."""
    if max_workers is None:
        max_workers = min(multiprocessing.cpu_count(), 4)
    log(f"Parallel rendering with {max_workers} workers")
    with multiprocessing.Pool(processes=max_workers) as pool:
        results = pool.map(_render_segment_worker, segments_args)
    return results


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

    # GPU detection
    gpu_name, gpu_enc = detect_gpu_encoder()
    gpu_codec = gpu_enc["codec"]
    gpu_preset = gpu_enc.get("preset", DEFAULT_PRESET)
    gpu_opts = {k: gpu_enc[k] for k in ("cq", "rc", "b_pyramid", "gpu", "global_quality") if k in gpu_enc}

    log(f"Using encoder: {gpu_enc['label']} ({gpu_codec})")
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

    # Build segment args
    segment_args_list: list[dict[str, Any]] = []
    for i, ch in enumerate(chapters):
        if ch.duration_seconds <= 0.05:
            warn(f"Skipping too short chapter: {ch.title}")
            continue
        panel = panels_dir / f"{i:03d}.png"
        segment = segments_dir / f"{i:03d}.mp4"
        segment_args_list.append({
            "panel": str(panel),
            "audio": str(audio),
            "out": str(segment),
            "start": ch.start_seconds,
            "duration": ch.duration_seconds,
            "fps": args.fps,
            "width": args.width,
            "height": args.height,
            "dry_run": args.dry_run,
            "waveform": args.waveform,
            "gpu_codec": gpu_codec,
            "gpu_preset": gpu_preset,
            "gpu_opts": gpu_opts,
        })

    if not segment_args_list:
        fail("No segments to render")

    # Parallel render
    parallel = getattr(args, "parallel", True)
    if parallel and len(segment_args_list) > 1:
        results = render_segments_parallel(segment_args_list)
    else:
        results = []
        for sargs in segment_args_list:
            r = _render_segment_worker(sargs)
            results.append(r)

    # Collect rendered segments
    rendered_segments: list[Path] = []
    for i, r in enumerate(segment_args_list):
        p = Path(r["out"])
        if p.exists():
            rendered_segments.append(p)
        else:
            warn(f"Segment missing: {p}")

    if not rendered_segments:
        fail("No segments rendered successfully")

    concat_segments(rendered_segments, Path(args.out), bdir / "concat.txt", dry_run=args.dry_run)
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
    p_render.add_argument("--waveform", choices=["static", "ffmpeg"], default="static", help="Audio visualization mode")
    p_render.add_argument("--dry-run", action="store_true")
    p_render.add_argument("--no-parallel", action="store_true", dest="no_parallel", help="Disable parallel segment rendering")
    add_visual_args(p_render)
    p_render.set_defaults(func=cmd_render)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()