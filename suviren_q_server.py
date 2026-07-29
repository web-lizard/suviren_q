#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Book Wunderwaffe Studio API

Provides endpoints for:
  - /api/book-project — data auto-discovery from data/
  - /api/render/test, /api/render/full — render jobs
  - /api/render/status, /api/render/log — job tracking
  - /api/layout — save/load layout.json
  - /api/chapters — chapter management
  - /api/waveform — generate waveform data from audio
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import wave
import zipfile
import struct
import math
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from fastapi import FastAPI, HTTPException, Body, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from bookender.logging import log_event
from bookender.paths import DATABASE_PATH, USER_DATA
from bookender.repository import (
    ProjectNotFoundError,
    ProjectRepository,
)
from bookender.tts import (
    TTS_FAILED_MESSAGE,
    TTS_UNAVAILABLE_MESSAGE,
    TtsService,
    TtsUnavailableError,
)


ROOT = Path(__file__).resolve().parent
MAIN_SCRIPT = ROOT / "suviren_q.py"
BUILD_DIR = ROOT / "_suviren_q_build"
DATA_DIR = ROOT / "data"
LAYOUT_PATH = BUILD_DIR / "layout.json"
EDITOR_PROJECT_PATH = BUILD_DIR / "editor-project.json"
CHAPTERS_PATH = BUILD_DIR / "chapters.detected.json"

APP_NAME = "Book Wunderwaffe Studio"
APP_VERSION = "3.0.0"

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg", ".opus"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}
IMPORT_EXTENSIONS = AUDIO_EXTENSIONS | IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
EXPORT_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}
DEFAULT_RENDER_PRESET = "balanced"
RENDER_RATE_PRESETS_KBPS: dict[str, tuple[int, int]] = {
    "compact": (1200, 192),
    "balanced": (1800, 192),
    "youtube_1080p": (7500, 384),
}

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description=(
        "Local-first audiobook production API for chapter-aware composition, "
        "waveform visualization and reliable FFmpeg export."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5178",
        "http://localhost:5178",
        "http://127.0.0.1:4178",
        "http://localhost:4178",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()
AUDIO_PROBE_CACHE: dict[tuple[str, int, int], dict[str, Any]] = {}
AUDIO_DISCOVERY_CACHE: dict[tuple[str, int, int], float] = {}
PROJECT_REPOSITORY = ProjectRepository()
PROJECT_REPOSITORY.initialize()
TTS_SERVICE = TtsService(PROJECT_REPOSITORY)


def console_python_executable() -> str:
    """Use python.exe for child jobs even when the desktop runs via pythonw.exe."""
    executable = Path(sys.executable)
    if os.name == "nt" and executable.name.lower() == "pythonw.exe":
        console_sibling = executable.with_name("python.exe")
        if console_sibling.is_file():
            return str(console_sibling)
    return str(executable)


def hidden_process_options() -> dict[str, int]:
    """Prevent helper consoles from flashing behind the native Windows GUI."""
    if os.name == "nt":
        return {"creationflags": int(getattr(subprocess, "CREATE_NO_WINDOW", 0))}
    return {}


# ── Request models ───────────────────────────────────────────────

class InspectRequest(BaseModel):
    rpp: str
    audio: str | None = None
    rpp_track: str = "КНИГА ОЗВУЧКА"
    chapter_pattern: str = "Глава"
    add_intro: bool = True
    origin: str = "project"
    offset: float = 0.0


class SaveChaptersRequest(BaseModel):
    path: str = "_suviren_q_build/chapters.manual.json"
    chapters: list[dict[str, Any]]


class ProjectCreateRequest(BaseModel):
    title: str
    author: str = ""
    description: str = ""
    project_kind: str = "book"
    language: str = "ru"
    voice: str = ""
    create_first_chapter: bool = False
    source_project_uuid: str | None = None


class ProjectUpdateRequest(BaseModel):
    title: str | None = None
    author: str | None = None
    description: str | None = None


class ChapterCreateRequest(BaseModel):
    title: str = ""
    content: str = ""


class ChapterUpdateRequest(BaseModel):
    title: str | None = None
    content: str | None = None


class ChapterOrderRequest(BaseModel):
    chapter_ids: list[int]


class TtsSettingsRequest(BaseModel):
    voice: str = ""
    rate: str = "+0%"
    pitch: str = "+0Hz"
    volume: str = "+0%"
    provider: str = "edge-tts"
    extra: dict[str, Any] = {}


class TtsPreviewRequest(TtsSettingsRequest):
    text: str = ""


class AudioAssetUpdateRequest(BaseModel):
    title: str | None = None
    is_active: bool | None = None


class VideoEditionCreateRequest(BaseModel):
    title: str | None = None


# ── Helpers ──────────────────────────────────────────────────────

def resolve_path(value: str | None) -> Path | None:
    if not value:
        return None
    p = Path(value)
    if not p.is_absolute():
        p = ROOT / p
    return p


def is_within(path: Path, parent: Path) -> bool:
    """Return True when path resolves inside parent (or is parent itself)."""
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except (OSError, ValueError):
        return False


def server_path(path: Path) -> str:
    """Return a stable project-relative path for API payloads."""
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return str(path)


def media_url(path: Path) -> str | None:
    if not is_within(path, DATA_DIR):
        return None
    relative = path.resolve().relative_to(DATA_DIR.resolve()).as_posix()
    return f"/api/media/data/{quote(relative, safe='/')}"


def atomic_write_json(path: Path, payload: Any) -> None:
    """Write JSON through a sibling temp file and atomically replace target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return data


def parse_seconds(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    text = str(value).strip().replace(",", ".")
    if not text:
        return None
    try:
        number = float(text)
        return number if math.isfinite(number) else None
    except ValueError:
        pass
    parts = text.split(":")
    try:
        if len(parts) == 3:
            hours, minutes, seconds = (float(part) for part in parts)
            return hours * 3600 + minutes * 60 + seconds
        if len(parts) == 2:
            minutes, seconds = (float(part) for part in parts)
            return minutes * 60 + seconds
    except ValueError:
        return None
    return None


def format_timestamp(seconds: float) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def normalize_editor_chapters(
    chapters: Any,
    *,
    project_duration: float | None = None,
) -> list[dict[str, Any]]:
    """Normalize editor chapter shapes to the format consumed by suviren_q.py."""
    if chapters is None:
        return []
    if not isinstance(chapters, list):
        raise ValueError("chapters must be an array")

    parsed: list[dict[str, Any]] = []
    for index, raw in enumerate(chapters):
        if not isinstance(raw, dict):
            raise ValueError(f"chapter {index + 1} must be an object")

        start = parse_seconds(
            raw.get("start_seconds", raw.get("startSeconds", raw.get("start")))
        )
        if start is None and raw.get("startMs") is not None:
            start_ms = parse_seconds(raw.get("startMs"))
            start = start_ms / 1000 if start_ms is not None else None
        if start is None or start < 0:
            raise ValueError(f"chapter {index + 1} has an invalid start")

        end = parse_seconds(
            raw.get("end_seconds", raw.get("endSeconds", raw.get("end")))
        )
        if end is None and raw.get("endMs") is not None:
            end_ms = parse_seconds(raw.get("endMs"))
            end = end_ms / 1000 if end_ms is not None else None

        duration = parse_seconds(
            raw.get(
                "duration_seconds",
                raw.get("durationSeconds", raw.get("duration")),
            )
        )
        if duration is None and raw.get("durationMs") is not None:
            duration_ms = parse_seconds(raw.get("durationMs"))
            duration = duration_ms / 1000 if duration_ms is not None else None
        if (end is None or end <= start) and duration is not None and duration > 0:
            end = start + duration

        title = str(raw.get("title") or raw.get("name") or raw.get("label") or f"Глава {index + 1}").strip()
        parsed.append({"raw": raw, "source_index": index, "title": title, "start": start, "end": end})

    parsed.sort(key=lambda item: (item["start"], item["source_index"]))
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(parsed):
        start = float(item["start"])
        end = item["end"]
        if (end is None or end <= start) and index + 1 < len(parsed):
            next_start = float(parsed[index + 1]["start"])
            if next_start > start:
                end = next_start
        if (end is None or end <= start) and project_duration is not None and project_duration > start:
            end = project_duration
        if end is None or end <= start:
            raise ValueError(f"chapter {item['source_index'] + 1} has no valid end or duration")

        end = float(end)
        raw = dict(item["raw"])
        raw.update({
            "title": item["title"],
            "start": format_timestamp(start),
            "end": format_timestamp(end),
            "start_seconds": round(start, 3),
            "end_seconds": round(end, 3),
            "duration_seconds": round(end - start, 3),
            "source": str(raw.get("source") or "editor"),
        })
        normalized.append(raw)
    return normalized


def load_editor_project() -> dict[str, Any] | None:
    try:
        return read_json_object(EDITOR_PROJECT_PATH)
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def resolve_editor_server_path(value: Any) -> Path | None:
    """Resolve an editor material path while preventing paths outside the project."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = unquote(value.strip())
    media_prefix = "/api/media/data/"
    if text.startswith(media_prefix):
        text = f"data/{text[len(media_prefix):]}"
    candidate = Path(text)
    candidates = [candidate] if candidate.is_absolute() else [ROOT / candidate]
    if not candidate.is_absolute() and text.replace("\\", "/").startswith("projects/"):
        candidates.insert(0, USER_DATA / candidate)
    projects_root = (USER_DATA / "projects").resolve()
    for item in candidates:
        try:
            resolved = item.resolve()
        except OSError:
            continue
        if (
            (is_within(resolved, ROOT) or is_within(resolved, projects_root))
            and resolved.is_file()
        ):
            return resolved
    return None


def append_job_line(job_id: str, line: str) -> None:
    job = JOBS.get(job_id)
    if not job:
        return
    job["log"].append(line.rstrip("\n"))
    job["updated_at"] = time.time()


def start_job(kind: str, cmd: list[str], *, output: Path | None = None) -> str:
    with JOBS_LOCK:
        active_render = next(
            (
                job for job in JOBS.values()
                if job["kind"] in ("render-test", "render-full") and job["status"] == "running"
            ),
            None,
        )
        if kind in ("render-test", "render-full") and active_render:
            raise HTTPException(
                status_code=409,
                detail={"message": "A render is already running", "job_id": active_render["id"]},
            )
        job_id = uuid.uuid4().hex[:12]
        output_path = output.resolve() if output else None
        JOBS[job_id] = {
            "id": job_id,
            "kind": kind,
            "cmd": cmd,
            "status": "running",
            "returncode": None,
            "progress": 0.0,
            "created_at": time.time(),
            "updated_at": time.time(),
            "output": server_path(output_path) if output_path else None,
            "download_url": (
                f"/api/exports/{quote(output_path.name, safe='')}" if output_path else None
            ),
            "output_exists": False,
            "output_size": 0,
            "log": [
                f"[Wunderwaffe] job started: {kind}",
                "[cmd] " + " ".join(f'"{x}"' if " " in x else x for x in cmd),
            ],
        }
    thread = threading.Thread(target=run_job, args=(job_id, cmd), daemon=True)
    thread.start()
    return job_id


def run_job(job_id: str, cmd: list[str]) -> None:
    try:
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            **hidden_process_options(),
        )
        assert proc.stdout is not None
        total_segments = 0
        completed_segments = 0
        for line in proc.stdout:
            append_job_line(job_id, line)
            plan_match = re.search(r"Rendering\s+(\d+)\s+of\s+\d+\s+panels", line)
            if plan_match:
                total_segments = max(1, int(plan_match.group(1)))
                JOBS[job_id]["progress"] = max(JOBS[job_id].get("progress", 0.0), 0.04)
                continue
            panel_match = re.search(r"Drawing panel\s+(\d+)/", line)
            if panel_match and total_segments:
                panel_index = min(total_segments, int(panel_match.group(1)))
                JOBS[job_id]["progress"] = max(
                    JOBS[job_id].get("progress", 0.0),
                    0.04 + 0.08 * panel_index / total_segments,
                )
                continue
            if "Rendering segment" in line and total_segments:
                JOBS[job_id]["progress"] = max(JOBS[job_id].get("progress", 0.0), 0.12)
                continue
            if "Segment done:" in line:
                completed_segments += 1
                denominator = max(total_segments, completed_segments)
                JOBS[job_id]["progress"] = max(
                    JOBS[job_id].get("progress", 0.0),
                    min(0.95, 0.12 + 0.83 * completed_segments / denominator),
                )
                continue
            if "Concat list:" in line:
                JOBS[job_id]["progress"] = max(JOBS[job_id].get("progress", 0.0), 0.97)
        returncode = proc.wait()
        job = JOBS[job_id]
        output_value = job.get("output")
        output_path = resolve_path(output_value) if output_value else None
        output_exists = bool(
            returncode == 0
            and output_path
            and output_path.is_file()
            and output_path.stat().st_size > 0
        )
        job["returncode"] = returncode
        job["output_exists"] = output_exists
        job["output_size"] = output_path.stat().st_size if output_exists and output_path else 0
        job["status"] = "done" if returncode == 0 and (not output_path or output_exists) else "failed"
        job["progress"] = 1.0 if job["status"] == "done" else job.get("progress", 0)
        job["updated_at"] = time.time()
        if returncode == 0 and output_path and not output_exists:
            append_job_line(job_id, f"[error] expected output was not created: {output_path}")
        append_job_line(job_id, f"[Wunderwaffe] job finished with code {returncode}")
    except Exception as exc:
        JOBS[job_id]["status"] = "failed"
        JOBS[job_id]["returncode"] = -1
        JOBS[job_id]["progress"] = 0.0
        append_job_line(job_id, f"[error] {type(exc).__name__}: {exc}")


def file_info(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False, "size": 0}
    info = {
        "path": server_path(path),
        "exists": True,
        "size": path.stat().st_size,
        "size_mb": round(path.stat().st_size / (1024 * 1024), 1),
    }
    url = media_url(path)
    if url:
        info["url"] = url
    return info


def media_record(path: Path, kind: str) -> dict[str, Any]:
    info = file_info(path)
    return {
        "id": server_path(path),
        "name": path.name,
        "kind": kind,
        "serverPath": server_path(path),
        **info,
    }


def quick_audio_duration(path: Path) -> float | None:
    """Return a cached finite duration for safe auto-selection, without decoding."""
    try:
        stat = path.stat()
    except OSError:
        return None
    cache_key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns)
    cached = AUDIO_DISCOVERY_CACHE.get(cache_key)
    if cached is not None:
        return cached or None
    try:
        probe = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "a:0",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=2,
            **hidden_process_options(),
        )
        duration = parse_seconds(probe.stdout.strip()) if probe.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        duration = None
    value = duration if duration is not None and duration > 0 else 0.0
    if len(AUDIO_DISCOVERY_CACHE) >= 64:
        AUDIO_DISCOVERY_CACHE.clear()
    AUDIO_DISCOVERY_CACHE[cache_key] = value
    return value or None


def discover_data_files() -> dict[str, Any]:
    """Scan data/ and expose legacy selections plus editor media collections."""
    data_dir = DATA_DIR
    files = sorted(
        (path for path in data_dir.iterdir() if path.is_file()),
        key=lambda path: path.name.casefold(),
    ) if data_dir.exists() else []
    audio_files = [path for path in files if path.suffix.lower() in AUDIO_EXTENSIONS]
    image_files = [path for path in files if path.suffix.lower() in IMAGE_EXTENSIONS]
    video_files = [path for path in files if path.suffix.lower() in VIDEO_EXTENSIONS]

    result = {
        "projectName": "",
        "dataDir": str(data_dir),
        "audio": file_info(data_dir / "zinaida.mp3"),
        "cover": file_info(data_dir / "zina-cover.png"),
        "background": file_info(data_dir / "background.png"),
        "rpp": file_info(data_dir / "ЗИНА. Книга.rpp"),
        "chapters": {"path": "", "exists": False, "count": 0, "first": "", "last": ""},
        "ready": False,
        "missing": [],
        "warnings": [],
        "audios": [media_record(path, "audio") for path in audio_files],
        "images": [media_record(path, "image") for path in image_files],
        "videos": [media_record(path, "video") for path in video_files],
    }
    result["materials"] = result["audios"] + result["images"] + result["videos"]
    result["video"] = file_info(video_files[0]) if video_files else {
        "path": "", "exists": False, "size": 0
    }

    # Find the longest probeable master. Files above 2 GiB remain available in
    # the material library, but are not auto-selected: several MP3 parsers fail
    # at that boundary and a broken giant file used to make startup unusable.
    if audio_files:
        auto_candidates = [
            path for path in audio_files
            if path.stat().st_size < 2 * 1024 ** 3 and ".tmp_probe" not in path.name
        ]
        probed = [
            (duration, path)
            for path in auto_candidates
            if (duration := quick_audio_duration(path)) is not None
        ]
        best = max(probed, key=lambda item: item[0])[1] if probed else max(
            auto_candidates or audio_files,
            key=lambda path: path.stat().st_size,
        )
        result["audio"] = file_info(best)
        oversized = [path.name for path in audio_files if path.stat().st_size >= 2 * 1024 ** 3]
        if oversized:
            result["warnings"].append(
                "audio files above 2 GiB were kept in the library but skipped for automatic selection"
            )
    else:
        result["missing"].append("audio")

    # Find cover
    cover_keywords = ("cover", "облож")
    found_cover = [
        path for path in image_files
        if any(keyword in path.stem.casefold() for keyword in cover_keywords)
    ]
    if not found_cover and image_files:
        found_cover = [image_files[0]]
        result["warnings"].append("cover keyword not found — using the first image")
    if found_cover:
        result["cover"] = file_info(found_cover[0])
    else:
        result["missing"].append("cover")

    # Find background
    bg_keywords = ["background", "backdrop", "bg"]
    found_bg = [path for path in image_files
                if any(keyword in path.stem.casefold() for keyword in bg_keywords)]
    if found_bg:
        result["background"] = file_info(found_bg[0])
    else:
        result["warnings"].append("background not found — using dark fallback")

    # Find RPP
    found_rpp = [path for path in files if path.suffix.lower() == ".rpp"]
    if found_rpp:
        result["rpp"] = file_info(found_rpp[0])
    else:
        result["warnings"].append("RPP project not found — saved editor chapters will be used")

    # Chapters
    chapters_path = CHAPTERS_PATH
    if chapters_path.exists():
        try:
            ch_data = json.loads(chapters_path.read_text(encoding="utf-8"))
            if isinstance(ch_data, dict):
                ch_data = ch_data.get("chapters", [])
            if not isinstance(ch_data, list):
                raise ValueError("chapters must be an array")
            result["chapters"] = {
                "path": str(chapters_path.relative_to(ROOT)),
                "exists": True,
                "count": len(ch_data),
                "first": ch_data[0].get("title", "") if ch_data else "",
                "last": ch_data[-1].get("title", "") if ch_data else "",
            }
            if not ch_data:
                result["missing"].append("chapters")
        except Exception:
            result["warnings"].append("chapters.detected.json corrupted")
            result["missing"].append("chapters")
    else:
        result["missing"].append("chapters")

    # Prefer the book project name over technical render suffixes in audio names.
    if result["rpp"]["exists"] or result["audio"]["exists"]:
        source_path = result["rpp"]["path"] if result["rpp"]["exists"] else result["audio"]["path"]
        name = Path(source_path).stem
        # Clean up common suffixes
        result["projectName"] = name.replace("_", " ").replace("-", " ").title()

    # Ready check
    result["ready"] = (
        result["audio"]["exists"]
        and result["cover"]["exists"]
        and result["chapters"]["exists"]
        and result["chapters"]["count"] > 0
    )

    return result


def get_default_layout() -> dict:
    """Return the default Book Wunderwaffe Studio composition layout."""
    return {
        "scene": {"width": 1920, "height": 1080, "fps": 30},
        "objects": {
            "background": {
                "x": 0, "y": 0, "width": 1920, "height": 1080,
                "opacity": 1.0, "visible": True, "locked": False,
                "fit": "cover"
            },
            "cover": {
                "x": 120, "y": 120, "width": 480, "height": 480,
                "opacity": 0.95, "visible": True, "locked": False,
                "borderRadius": 16
            },
            "currentChapterTitle": {
                "x": 680, "y": 140, "width": 1100, "height": 60,
                "fontSize": 42, "fontWeight": 700,
                "color": "#e0daf5", "opacity": 1.0, "visible": True,
                "textAlign": "left"
            },
            "bookTitle": {
                "x": 680, "y": 200, "width": 1100, "height": 36,
                "fontSize": 24, "fontWeight": 400,
                "color": "#7b68ee", "opacity": 0.85, "visible": True,
                "textAlign": "left"
            },
            "authorBrand": {
                "x": 680, "y": 260, "width": 600, "height": 28,
                "fontSize": 16, "fontWeight": 300,
                "color": "#7a74a0", "opacity": 0.7, "visible": True,
                "textAlign": "left",
                "text": "Monsieur Souveraineté"
            },
            "waveform": {
                "x": 80, "y": 720, "width": 1760, "height": 120,
                "opacity": 0.6, "visible": True, "locked": False,
                "style": "bars", "barWidth": 4, "barGap": 2,
                "color": "#00e5a0", "bgColor": "rgba(0,229,160,0.08)",
                "progressColor": "#7b68ee"
            },
            "progressBar": {
                "x": 80, "y": 870, "width": 1760, "height": 6,
                "opacity": 0.8, "visible": True,
                "color": "#7b68ee", "bgColor": "#1e1e32",
                "borderRadius": 3
            },
            "chapterList": {
                "x": 680, "y": 320, "width": 1100, "height": 300,
                "opacity": 0.0, "visible": False, "fontSize": 16,
                "color": "#ddd8f0"
            }
        },
        "render": {
            "quality": "youtube_high",
            "crf": 18,
            "audioBitrate": "192k",
            "pixelFormat": "yuv420p",
            "codec": "h264"
        },
        "colors": {
            "accent": "#7b68ee",
            "accent2": "#00e5a0",
            "bg": "#0b0b15",
            "text": "#ddd8f0",
            "textDim": "#7a74a0",
            "chapterActive": "#7b68ee"
        }
    }


def editor_role_id(project: dict[str, Any] | None, key: str) -> Any:
    if not project:
        return None
    if project.get(key) not in (None, ""):
        return project.get(key)
    roles = project.get("roles")
    if isinstance(roles, dict):
        return roles.get(key)
    return None


def editor_role_path(
    project: dict[str, Any] | None,
    role_key: str,
    allowed_extensions: set[str],
) -> Path | None:
    role_id = editor_role_id(project, role_key)
    if role_id in (None, "") or not project:
        return None
    materials = project.get("materials", [])
    if not isinstance(materials, list):
        return None
    for material in materials:
        if not isinstance(material, dict):
            continue
        material_id = material.get("id", material.get("assetId", material.get("materialId")))
        if str(material_id) != str(role_id):
            continue
        path = resolve_editor_server_path(material.get("serverPath", material.get("server_path")))
        if path and path.suffix.lower() in allowed_extensions:
            return path
        return None
    return None


def existing_discovered_path(project: dict[str, Any], key: str) -> Path | None:
    value = project.get(key)
    if not isinstance(value, dict) or not value.get("exists"):
        return None
    path = resolve_path(str(value.get("path", "")))
    return path.resolve() if path and path.is_file() and is_within(path, ROOT) else None


def load_chapter_payload(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or CHAPTERS_PATH
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("chapters", [])
    if not isinstance(data, list):
        raise ValueError("chapters file must contain an array")
    return normalize_editor_chapters(data)


def get_export_inputs() -> dict[str, Any]:
    """Resolve export roles from editor project, then fall back per role."""
    discovered = discover_data_files()
    editor = load_editor_project()
    warnings: list[str] = []
    if EDITOR_PROJECT_PATH.is_file() and editor is None:
        warnings.append("editor-project.json is invalid; using discovery fallback")

    role_specs = {
        "audio": ("audioAssetId", AUDIO_EXTENSIONS),
        "video": ("videoAssetId", VIDEO_EXTENSIONS),
        "cover": ("coverAssetId", IMAGE_EXTENSIONS),
        "background": ("backgroundAssetId", IMAGE_EXTENSIONS),
    }
    selected: dict[str, Path | None] = {}
    selected_from: dict[str, str | None] = {}
    for name, (role_key, extensions) in role_specs.items():
        path = editor_role_path(editor, role_key, extensions)
        if path:
            selected[name] = path
            selected_from[name] = "editor-project"
            continue
        if editor_role_id(editor, role_key) not in (None, ""):
            warnings.append(f"{role_key} does not reference a usable material; using discovery fallback")
        fallback = existing_discovered_path(discovered, name)
        selected[name] = fallback
        selected_from[name] = "discovery" if fallback else None

    if selected.get("video"):
        warnings.append(
            "Видео работает в синхронном предпросмотре; текущий FFmpeg-экспорт "
            "использует статический фон, обложку, главы и аудио."
        )
    if editor and editor.get("scenes"):
        warnings.append(
            "Покадровые сцены пока не переносятся в MP4; экспорт использует "
            "сохранённую геометрию текущей композиции."
        )

    chapters: list[dict[str, Any]] = []
    try:
        chapters = load_chapter_payload()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        warnings.append(f"chapters are invalid: {exc}")

    return {
        **selected,
        "chapters": CHAPTERS_PATH if chapters else None,
        "chapter_items": chapters,
        "selected_from": selected_from,
        "editor_project_exists": EDITOR_PROJECT_PATH.is_file(),
        "editor_chapters_explicit": bool(
            editor
            and isinstance(editor.get("chapters"), list)
            and editor.get("chapters")
        ),
        "warnings": warnings,
        "discovered": discovered,
    }


def clipped_test_chapters(chapters: list[dict[str, Any]], seconds: float = 60.0) -> Path:
    """Persist a render-safe chapter window whose total span is at most seconds."""
    if not chapters:
        raise ValueError("No chapters available for test export")
    window_start = 0.0
    window_end = seconds
    clipped: list[dict[str, Any]] = []
    cursor = window_start
    for chapter in chapters:
        start = max(float(chapter["start_seconds"]), window_start, cursor)
        end = min(float(chapter["end_seconds"]), window_end)
        if end <= start:
            if float(chapter["start_seconds"]) >= window_end:
                break
            continue
        item = dict(chapter)
        item.update({
            "start": format_timestamp(start),
            "end": format_timestamp(end),
            "start_seconds": round(start, 3),
            "end_seconds": round(end, 3),
            "duration_seconds": round(end - start, 3),
        })
        clipped.append(item)
        cursor = end
        if end >= window_end:
            break
    if not clipped:
        raise ValueError("No chapters overlap the 60-second test window")
    path = BUILD_DIR / "chapters.test-60s.json"
    atomic_write_json(path, clipped)
    return path


def export_output_path(test_mode: bool) -> Path:
    filename = "zina_book_youtube_test_60sec.mp4" if test_mode else "zina_book_youtube_full.mp4"
    return BUILD_DIR / filename


def probe_audio_for_export(
    audio_path: Path,
    ffprobe: str | None,
    ffmpeg: str | None,
) -> dict[str, Any]:
    """Bounded ffprobe + short decode check, cached by file identity."""
    try:
        stat = audio_path.stat()
    except OSError as exc:
        return {
            "ok": False,
            "duration": None,
            "durationOk": False,
            "decodeOk": False,
            "error": f"Cannot stat audio file: {exc}",
        }
    cache_key = (str(audio_path.resolve()), stat.st_size, stat.st_mtime_ns)
    cached = AUDIO_PROBE_CACHE.get(cache_key)
    if cached is not None:
        return dict(cached)

    result: dict[str, Any] = {
        "ok": False,
        "duration": None,
        "durationOk": False,
        "decodeOk": False,
        "error": "",
    }
    if not ffprobe or not ffmpeg:
        result["error"] = "ffprobe and ffmpeg are required to validate audio"
        return result

    try:
        duration_proc = subprocess.run(
            [
                ffprobe,
                "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(audio_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            **hidden_process_options(),
        )
    except subprocess.TimeoutExpired:
        result["error"] = "ffprobe timed out after 8 seconds; audio may be damaged or too large"
    except OSError as exc:
        result["error"] = f"ffprobe could not start: {exc}"
    else:
        duration = parse_seconds(duration_proc.stdout.strip()) if duration_proc.returncode == 0 else None
        if duration is None or not math.isfinite(duration) or duration <= 0:
            stderr = (duration_proc.stderr or "").strip().replace("\r", " ").replace("\n", " ")
            result["error"] = (
                f"ffprobe could not read a finite audio duration"
                + (f": {stderr[:400]}" if stderr else "")
            )
        else:
            result["duration"] = round(duration, 3)
            result["durationOk"] = True

    if result["durationOk"]:
        try:
            decode_proc = subprocess.run(
                [
                    ffmpeg,
                    "-v", "error",
                    "-i", str(audio_path),
                    "-map", "0:a:0",
                    "-t", "0.25",
                    "-f", "null",
                    "-",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8,
                **hidden_process_options(),
            )
        except subprocess.TimeoutExpired:
            result["error"] = "ffmpeg decode probe timed out after 8 seconds"
        except OSError as exc:
            result["error"] = f"ffmpeg decode probe could not start: {exc}"
        else:
            if decode_proc.returncode == 0:
                result["decodeOk"] = True
            else:
                stderr = (decode_proc.stderr or "").strip().replace("\r", " ").replace("\n", " ")
                result["error"] = "ffmpeg could not decode the start of the audio"
                if stderr:
                    result["error"] += f": {stderr[:400]}"

    result["ok"] = bool(result["durationOk"] and result["decodeOk"])
    if len(AUDIO_PROBE_CACHE) >= 32:
        AUDIO_PROBE_CACHE.clear()
    AUDIO_PROBE_CACHE[cache_key] = dict(result)
    return result


def export_readiness_payload() -> dict[str, Any]:
    inputs = get_export_inputs()
    missing: list[str] = []
    warnings = list(inputs["warnings"])
    errors: list[str] = []
    for key in ("audio", "cover", "chapters"):
        if not inputs.get(key):
            missing.append(key)

    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg:
        missing.append("ffmpeg")
    if not ffprobe:
        missing.append("ffprobe")

    audio_probe: dict[str, Any] | None = None
    audio_path = inputs.get("audio")
    if audio_path and ffmpeg and ffprobe:
        audio_probe = probe_audio_for_export(audio_path, ffprobe, ffmpeg)
        if not audio_probe["ok"]:
            missing.append("audio-decodable")
            errors.append(
                "Selected audio cannot be exported: "
                + (audio_probe.get("error") or "duration/decode probe failed")
            )

    if audio_probe and audio_probe["ok"] and inputs["chapter_items"]:
        audio_duration = float(audio_probe["duration"])
        ordered_chapters = sorted(inputs["chapter_items"], key=lambda item: float(item["start_seconds"]))
        first_chapter_start = float(ordered_chapters[0]["start_seconds"])
        if first_chapter_start > 0.25:
            missing.append("chapters-start-after-audio")
            errors.append(
                f"First chapter starts at {format_timestamp(first_chapter_start)}; "
                "the chapter map must cover the audio from 00:00:00"
            )
        for previous, current in zip(ordered_chapters, ordered_chapters[1:]):
            gap = float(current["start_seconds"]) - float(previous["end_seconds"])
            if gap > 0.25:
                missing.append("chapters-have-gaps")
                errors.append(
                    f"Chapter gap of {gap:.1f}s before {current['title']}"
                )
                break
            if gap < -0.25:
                missing.append("chapters-have-overlaps")
                errors.append(
                    f"Chapter overlap of {abs(gap):.1f}s before {current['title']}"
                )
                break
        last_chapter_end = max(
            float(chapter["end_seconds"]) for chapter in inputs["chapter_items"]
        )
        duration_delta = audio_duration - last_chapter_end
        if last_chapter_end > audio_duration + 5.0:
            missing.append("chapters-outside-audio")
            errors.append(
                f"Chapters end at {format_timestamp(last_chapter_end)}, "
                f"but audio ends at {format_timestamp(audio_duration)}"
            )
        elif duration_delta > 5.0:
            message = (
                f"Chapters end {duration_delta:.1f}s before the audio "
                f"({format_timestamp(last_chapter_end)} vs {format_timestamp(audio_duration)})"
            )
            missing.append("chapters-duration-mismatch")
            errors.append(message + "; extend or refresh the chapter map")

    try:
        import PIL
        pillow_version = PIL.__version__
    except ImportError:
        pillow_version = None
        missing.append("Pillow")

    assets: dict[str, Any] = {}
    for key in ("audio", "video", "cover", "background"):
        path = inputs.get(key)
        assets[key] = {
            **(file_info(path) if path else {"path": "", "exists": False, "size": 0}),
            "selectedFrom": inputs["selected_from"].get(key),
        }
    assets["chapters"] = {
        "path": server_path(CHAPTERS_PATH),
        "exists": bool(inputs.get("chapters")),
        "count": len(inputs["chapter_items"]),
    }
    if audio_probe and assets["audio"]["exists"]:
        assets["audio"]["duration"] = audio_probe.get("duration")

    project = load_editor_project() or {}
    render_preset = str(project.get("renderPreset") or DEFAULT_RENDER_PRESET)
    if render_preset not in RENDER_RATE_PRESETS_KBPS:
        render_preset = DEFAULT_RENDER_PRESET
    video_kbps, audio_kbps = RENDER_RATE_PRESETS_KBPS[render_preset]
    render_duration = float((audio_probe or {}).get("duration") or 0.0)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    free_bytes = int(shutil.disk_usage(BUILD_DIR).free)

    def storage_estimate(seconds: float) -> dict[str, Any]:
        seconds = max(0.0, float(seconds))
        video_bytes = seconds * video_kbps * 1000 / 8
        audio_bytes = seconds * audio_kbps * 1000 / 8
        final_bytes = video_bytes + audio_bytes
        # Peak export keeps chapter segments, their concatenated video and the
        # final muxed MP4 at the same time. Include room for panels/container
        # overhead so a long render does not die at the finish line.
        peak_bytes = int((video_bytes * 3 + audio_bytes + 128 * 1024**2) * 1.08)
        return {
            "seconds": seconds,
            "finalBytes": int(final_bytes),
            "peakBytes": peak_bytes,
            "freeBytes": free_bytes,
            "enough": free_bytes >= peak_bytes,
        }

    render_estimate = {
        "preset": render_preset,
        "videoKbps": video_kbps,
        "audioKbps": audio_kbps,
        "full": storage_estimate(render_duration),
        "test": storage_estimate(min(60.0, render_duration)),
    }
    missing = list(dict.fromkeys(missing))
    return {
        "ready": not missing,
        "missing": missing,
        "warnings": warnings,
        "errors": errors,
        "assets": assets,
        "editorProject": {
            "exists": inputs["editor_project_exists"],
            "path": server_path(EDITOR_PROJECT_PATH),
        },
        "tools": {
            "ffmpeg": ffmpeg,
            "ffprobe": ffprobe,
            "pillow": pillow_version,
        },
        "audioProbe": audio_probe,
        "renderEstimate": render_estimate,
    }


# ── Endpoints ────────────────────────────────────────────────────

def project_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ProjectNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, TtsUnavailableError):
        return HTTPException(status_code=503, detail=TTS_UNAVAILABLE_MESSAGE)
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    if str(exc) == TTS_FAILED_MESSAGE:
        return HTTPException(status_code=502, detail=TTS_FAILED_MESSAGE)
    log_event("project_api_error", error=repr(exc))
    return HTTPException(
        status_code=500, detail="Не удалось выполнить операцию с проектом."
    )


def safe_book_export_name(value: Any, fallback: str) -> str:
    name = re.sub(r'[\x00-\x1f<>:"/\\|?*]+', "_", str(value or ""))
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:100].rstrip(" .") or fallback


def chapter_export_text(chapter: dict[str, Any], position: int) -> str:
    title = str(chapter.get("title") or f"Глава {position}")
    content = str(chapter.get("content") or "").strip()
    return f"{title}\r\n{'=' * len(title)}\r\n\r\n{content}\r\n"


def complete_book_export_text(project: dict[str, Any]) -> str:
    book = project.get("book") or {}
    title = str(book.get("title") or project.get("title") or "Книга")
    author = str(book.get("author") or project.get("author") or "").strip()
    description = str(
        book.get("description") or project.get("description") or ""
    ).strip()
    sections = [title, "=" * len(title)]
    if author:
        sections.extend(["", f"Автор: {author}"])
    if description:
        sections.extend(["", description])
    for position, chapter in enumerate(project.get("chapters") or [], 1):
        chapter_title = chapter.get("title") or f"Глава {position}"
        sections.extend(
            [
                "",
                "",
                f"Глава {position}. {chapter_title}",
                "-" * 48,
                "",
                str(chapter.get("content") or "").strip(),
            ]
        )
    return "\ufeff" + "\r\n".join(sections).rstrip() + "\r\n"


def project_export_media_path(
    project: dict[str, Any], relative_path: Any
) -> Path | None:
    if not relative_path:
        return None
    project_root = (USER_DATA / str(project["project_folder"])).resolve()
    path = (USER_DATA / str(relative_path)).resolve()
    if not is_within(path, project_root) or not path.is_file():
        return None
    return path


def create_book_export(
    project_uuid: str,
    *,
    mode: str,
    chapter_id: int | None = None,
    include_media: bool = True,
) -> tuple[Path, str]:
    project = PROJECT_REPOSITORY.get_project(project_uuid, include_details=True)
    if not project.get("book"):
        raise ValueError("У этого проекта нет текстовой книги.")
    chapters = project.get("chapters") or []
    if not chapters:
        raise ValueError("В книге пока нет глав для экспорта.")

    title = safe_book_export_name(
        project["book"].get("title") or project.get("title"),
        "Книга",
    )
    project_root = (USER_DATA / str(project["project_folder"])).resolve()
    export_dir = (project_root / "exports").resolve()
    if not is_within(export_dir, project_root):
        raise ValueError("Некорректный каталог экспорта проекта.")
    export_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")

    if mode == "complete":
        output = export_dir / f"{title} — вся книга — {stamp}.txt"
        output.write_text(complete_book_export_text(project), encoding="utf-8")
        return output, "text/plain; charset=utf-8"

    if mode == "chapter":
        chapter = next(
            (item for item in chapters if int(item["id"]) == int(chapter_id or 0)),
            None,
        )
        if chapter is None:
            raise ValueError("Выбранная глава не найдена.")
        position = chapters.index(chapter) + 1
        chapter_name = safe_book_export_name(chapter.get("title"), f"Глава {position}")
        output = export_dir / f"{position:03d} — {chapter_name} — {stamp}.txt"
        output.write_text(
            "\ufeff" + chapter_export_text(chapter, position),
            encoding="utf-8",
        )
        return output, "text/plain; charset=utf-8"

    if mode != "chapters":
        raise ValueError("Неизвестный режим экспорта книги.")

    output = export_dir / f"{title} — по главам — {stamp}.zip"
    active_audio: dict[int, dict[str, Any]] = {}
    for asset in project.get("audio_assets") or []:
        chapter_key = int(asset.get("chapter_id") or 0)
        current = active_audio.get(chapter_key)
        rank = (
            int(bool(asset.get("is_active"))),
            int(asset.get("version_number") or 0),
            int(asset.get("id") or 0),
        )
        current_rank = (
            int(bool(current and current.get("is_active"))),
            int((current or {}).get("version_number") or 0),
            int((current or {}).get("id") or 0),
        )
        if chapter_key and (current is None or rank > current_rank):
            active_audio[chapter_key] = asset

    chapter_images: dict[int, dict[str, Any]] = {}
    for asset in project.get("visual_assets") or []:
        chapter_key = int(asset.get("chapter_id") or 0)
        if asset.get("asset_type") != "chapter-image" or not chapter_key:
            continue
        current = chapter_images.get(chapter_key)
        if current is None or int(asset["id"]) > int(current["id"]):
            chapter_images[chapter_key] = asset

    manifest_chapters = []
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
        archive.writestr(
            "00 - О книге.txt",
            complete_book_export_text({**project, "chapters": []}).encode("utf-8"),
        )
        for position, chapter in enumerate(chapters, 1):
            chapter_name = safe_book_export_name(
                chapter.get("title"), f"Глава {position}"
            )
            folder = f"{position:03d} - {chapter_name}"
            archive.writestr(
                f"{folder}/{position:03d} - {chapter_name}.txt",
                ("\ufeff" + chapter_export_text(chapter, position)).encode("utf-8"),
            )
            manifest_item: dict[str, Any] = {
                "position": position,
                "chapter_id": int(chapter["id"]),
                "title": chapter.get("title") or f"Глава {position}",
            }
            if include_media:
                audio = active_audio.get(int(chapter["id"]))
                audio_path = project_export_media_path(
                    project, audio.get("file_path") if audio else None
                )
                if audio_path:
                    audio_name = f"Озвучка{audio_path.suffix.lower()}"
                    archive.write(audio_path, f"{folder}/{audio_name}")
                    manifest_item["audio"] = f"{folder}/{audio_name}"
                image = chapter_images.get(int(chapter["id"]))
                image_path = project_export_media_path(
                    project, image.get("file_path") if image else None
                )
                if image_path:
                    image_name = f"Изображение{image_path.suffix.lower()}"
                    archive.write(image_path, f"{folder}/{image_name}")
                    manifest_item["image"] = f"{folder}/{image_name}"
            manifest_chapters.append(manifest_item)
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "project_uuid": project_uuid,
                    "title": project["book"].get("title") or project.get("title"),
                    "author": project["book"].get("author") or project.get("author"),
                    "chapter_count": len(chapters),
                    "includes_media": include_media,
                    "chapters": manifest_chapters,
                },
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8"),
        )
    return output, "application/zip"


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "version": APP_VERSION,
        "app": APP_NAME,
        "root": str(ROOT),
        "python": sys.executable,
        "main_script_exists": MAIN_SCRIPT.exists(),
        "build_dir": str(BUILD_DIR),
        "database": str(DATABASE_PATH),
        "database_integrity": PROJECT_REPOSITORY.database.integrity_check(),
        "tts": TTS_SERVICE.dependency_status(),
    }


@app.get("/api/projects")
def list_bookender_projects(
    search: str = Query(""),
    kind: str | None = Query(None),
    include_archived: bool = Query(False),
) -> dict[str, Any]:
    return {
        "projects": PROJECT_REPOSITORY.list_projects(
            search=search,
            kind=kind,
            include_archived=include_archived,
        ),
        "active_project_uuid": PROJECT_REPOSITORY.active_project_uuid(),
    }


@app.post("/api/projects")
def create_bookender_project(data: ProjectCreateRequest) -> dict[str, Any]:
    try:
        if data.source_project_uuid:
            return PROJECT_REPOSITORY.duplicate_project(data.source_project_uuid)
        return PROJECT_REPOSITORY.create_project(
            title=data.title,
            author=data.author,
            description=data.description,
            project_kind=data.project_kind,
            language=data.language,
            voice=data.voice,
            create_first_chapter=data.create_first_chapter,
        )
    except Exception as exc:
        raise project_http_error(exc) from exc


@app.get("/api/projects/{project_uuid}")
def get_bookender_project(project_uuid: str) -> dict[str, Any]:
    try:
        return PROJECT_REPOSITORY.get_project(project_uuid, include_details=True)
    except Exception as exc:
        raise project_http_error(exc) from exc


@app.post("/api/projects/{project_uuid}/open")
def open_bookender_project(project_uuid: str) -> dict[str, Any]:
    try:
        return PROJECT_REPOSITORY.open_project(project_uuid)
    except Exception as exc:
        raise project_http_error(exc) from exc


@app.patch("/api/projects/{project_uuid}")
def update_bookender_project(
    project_uuid: str, data: ProjectUpdateRequest
) -> dict[str, Any]:
    try:
        return PROJECT_REPOSITORY.update_project(
            project_uuid,
            title=data.title,
            author=data.author,
            description=data.description,
        )
    except Exception as exc:
        raise project_http_error(exc) from exc


@app.post("/api/projects/{project_uuid}/archive")
def archive_bookender_project(
    project_uuid: str, archived: bool = Body(True, embed=True)
) -> dict[str, Any]:
    try:
        PROJECT_REPOSITORY.archive_project(project_uuid, archived)
        return {"ok": True, "archived": archived}
    except Exception as exc:
        raise project_http_error(exc) from exc


@app.post("/api/projects/{project_uuid}/duplicate")
def duplicate_bookender_project(project_uuid: str) -> dict[str, Any]:
    try:
        return PROJECT_REPOSITORY.duplicate_project(project_uuid)
    except Exception as exc:
        raise project_http_error(exc) from exc


@app.post("/api/projects/{project_uuid}/backup")
def backup_bookender_project(project_uuid: str) -> dict[str, Any]:
    try:
        destination = PROJECT_REPOSITORY.backup_project(project_uuid)
        return {"ok": True, "path": str(destination)}
    except Exception as exc:
        raise project_http_error(exc) from exc


@app.get("/api/projects/{project_uuid}/book-export")
def export_bookender_project(
    project_uuid: str,
    mode: str = Query("complete"),
    chapter_id: int | None = Query(None),
    include_media: bool = Query(True),
):
    try:
        output, media_type = create_book_export(
            project_uuid,
            mode=mode,
            chapter_id=chapter_id,
            include_media=include_media,
        )
        return FileResponse(
            str(output),
            media_type=media_type,
            filename=output.name,
        )
    except Exception as exc:
        raise project_http_error(exc) from exc


@app.post("/api/projects/{project_uuid}/book")
def create_project_book_part(
    project_uuid: str,
    title: str | None = Body(None),
    language: str = Body("ru"),
) -> dict[str, Any]:
    try:
        return PROJECT_REPOSITORY.create_book_part(
            project_uuid, title=title, language=language
        )
    except Exception as exc:
        raise project_http_error(exc) from exc


@app.post("/api/projects/{project_uuid}/chapters")
def create_project_chapter(
    project_uuid: str, data: ChapterCreateRequest
) -> dict[str, Any]:
    try:
        return PROJECT_REPOSITORY.create_chapter(
            project_uuid, title=data.title, content=data.content
        )
    except Exception as exc:
        raise project_http_error(exc) from exc


@app.patch("/api/projects/{project_uuid}/chapters/{chapter_id}")
def update_project_chapter(
    project_uuid: str, chapter_id: int, data: ChapterUpdateRequest
) -> dict[str, Any]:
    try:
        return PROJECT_REPOSITORY.update_chapter(
            project_uuid,
            chapter_id,
            title=data.title,
            content=data.content,
        )
    except Exception as exc:
        raise project_http_error(exc) from exc


@app.post("/api/projects/{project_uuid}/chapters/reorder")
def reorder_project_chapters(
    project_uuid: str, data: ChapterOrderRequest
) -> dict[str, Any]:
    try:
        PROJECT_REPOSITORY.reorder_chapters(project_uuid, data.chapter_ids)
        return {"ok": True, "chapter_ids": data.chapter_ids}
    except Exception as exc:
        raise project_http_error(exc) from exc


@app.delete("/api/projects/{project_uuid}/chapters/{chapter_id}")
def archive_project_chapter(project_uuid: str, chapter_id: int) -> dict[str, Any]:
    try:
        PROJECT_REPOSITORY.archive_chapter(project_uuid, chapter_id)
        return {"ok": True, "archived": True}
    except Exception as exc:
        raise project_http_error(exc) from exc


@app.put("/api/projects/{project_uuid}/tts-settings")
def update_project_tts(
    project_uuid: str, data: TtsSettingsRequest
) -> dict[str, Any]:
    try:
        settings = TTS_SERVICE.normalize_settings(data.model_dump())
        return PROJECT_REPOSITORY.update_tts_settings(
            project_uuid, settings
        )
    except Exception as exc:
        raise project_http_error(exc) from exc


@app.get("/api/tts/status")
def tts_status() -> dict[str, Any]:
    return TTS_SERVICE.dependency_status()


@app.get("/api/tts/voices")
def tts_voices(refresh: bool = Query(False)) -> dict[str, Any]:
    try:
        voices = TTS_SERVICE.list_voices(refresh=refresh)
        return {"voices": voices, "count": len(voices)}
    except Exception as exc:
        raise project_http_error(exc) from exc


@app.post("/api/projects/{project_uuid}/tts-preview")
def preview_project_voice(
    project_uuid: str, data: TtsPreviewRequest
) -> dict[str, Any]:
    try:
        return TTS_SERVICE.preview(project_uuid, data.text, data.model_dump())
    except Exception as exc:
        raise project_http_error(exc) from exc


@app.post("/api/projects/{project_uuid}/chapters/{chapter_id}/tts")
def narrate_project_chapter(
    project_uuid: str, chapter_id: int
) -> dict[str, Any]:
    try:
        return TTS_SERVICE.queue_chapter(project_uuid, chapter_id)
    except Exception as exc:
        raise project_http_error(exc) from exc


@app.post("/api/projects/{project_uuid}/tts")
def narrate_project_book(project_uuid: str) -> dict[str, Any]:
    try:
        jobs = TTS_SERVICE.queue_book(project_uuid)
        return {"jobs": jobs, "queued": len(jobs)}
    except Exception as exc:
        raise project_http_error(exc) from exc


@app.post("/api/projects/{project_uuid}/video-audio/master")
def build_project_video_audio_master(project_uuid: str) -> dict[str, Any]:
    try:
        return TTS_SERVICE.build_video_master(project_uuid)
    except Exception as exc:
        raise project_http_error(exc) from exc


@app.get("/api/projects/{project_uuid}/tts-jobs")
def list_project_tts_jobs(project_uuid: str) -> dict[str, Any]:
    try:
        return {"jobs": TTS_SERVICE.list_jobs(project_uuid)}
    except Exception as exc:
        raise project_http_error(exc) from exc


@app.get("/api/tts-jobs/{job_uuid}")
def get_project_tts_job(job_uuid: str) -> dict[str, Any]:
    try:
        return TTS_SERVICE.get_job(job_uuid)
    except Exception as exc:
        raise project_http_error(exc) from exc


@app.patch("/api/projects/{project_uuid}/audio/{asset_id}")
def update_project_audio_asset(
    project_uuid: str, asset_id: int, data: AudioAssetUpdateRequest
) -> dict[str, Any]:
    try:
        return PROJECT_REPOSITORY.update_audio_asset(
            project_uuid,
            asset_id,
            title=data.title,
            is_active=data.is_active,
        )
    except Exception as exc:
        raise project_http_error(exc) from exc


@app.delete("/api/projects/{project_uuid}/audio/{asset_id}")
def delete_project_audio_asset(project_uuid: str, asset_id: int) -> dict[str, Any]:
    try:
        return PROJECT_REPOSITORY.delete_audio_asset(project_uuid, asset_id)
    except Exception as exc:
        raise project_http_error(exc) from exc


@app.post("/api/projects/{project_uuid}/audio/{asset_id}/open-folder")
def open_project_audio_folder(project_uuid: str, asset_id: int) -> dict[str, Any]:
    try:
        project = PROJECT_REPOSITORY.get_project(project_uuid, include_details=True)
        asset = next(
            (item for item in project["audio_assets"] if item["id"] == asset_id),
            None,
        )
        if asset is None or str(asset["file_path"]).startswith("external:"):
            raise ProjectNotFoundError(f"{project_uuid}/audio/{asset_id}")
        projects_root = (USER_DATA / "projects").resolve()
        path = (USER_DATA / asset["file_path"]).resolve()
        if not is_within(path, projects_root) or not path.is_file():
            raise ProjectNotFoundError(f"{project_uuid}/audio/{asset_id}")
        if os.name == "nt":
            os.startfile(str(path.parent))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(path.parent)])
        return {"opened": True}
    except Exception as exc:
        raise project_http_error(exc) from exc


@app.post("/api/tts/open-log")
def open_tts_log() -> dict[str, Any]:
    log_path = (USER_DATA / "logs" / "bookender.log").resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.touch(exist_ok=True)
    try:
        if os.name == "nt":
            os.startfile(str(log_path))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(log_path)])
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail="Не удалось открыть технический лог."
        ) from exc
    return {"opened": True, "path": str(log_path)}


@app.post("/api/projects/{project_uuid}/video-editions")
def create_project_video_edition(
    project_uuid: str, data: VideoEditionCreateRequest
) -> dict[str, Any]:
    try:
        return PROJECT_REPOSITORY.create_video_edition(
            project_uuid, title=data.title
        )
    except Exception as exc:
        raise project_http_error(exc) from exc


@app.get("/api/projects/{project_uuid}/video-editions/{edition_id}")
def get_project_video_edition(
    project_uuid: str, edition_id: int
) -> dict[str, Any]:
    try:
        return PROJECT_REPOSITORY.get_video_edition(project_uuid, edition_id)
    except Exception as exc:
        raise project_http_error(exc) from exc


@app.put("/api/projects/{project_uuid}/video-editions/{edition_id}")
def save_project_video_edition(
    project_uuid: str,
    edition_id: int,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    try:
        return PROJECT_REPOSITORY.save_video_edition(
            project_uuid, payload, edition_id=edition_id
        )
    except Exception as exc:
        raise project_http_error(exc) from exc


@app.get("/api/book-project")
def book_project() -> dict[str, Any]:
    """Main data auto-discovery endpoint."""
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    data = discover_data_files()
    return data


@app.get("/api/editor-project")
def get_editor_project(
    project_uuid: str | None = Query(None),
    edition_id: int | None = Query(None),
) -> dict[str, Any]:
    """Return a SQLite video edition, falling back to the recovery JSON."""
    if project_uuid:
        try:
            edition = PROJECT_REPOSITORY.get_video_edition(
                project_uuid, edition_id
            )
            return {
                "exists": True,
                "storage": "sqlite",
                "project_uuid": project_uuid,
                "edition_id": edition["id"],
                "project": edition["settings"],
            }
        except ProjectNotFoundError:
            return {
                "exists": False,
                "storage": "sqlite",
                "project_uuid": project_uuid,
                "project": {"schemaVersion": 2, "materials": [], "chapters": []},
            }
    if not EDITOR_PROJECT_PATH.exists():
        return {
            "exists": False,
            "path": server_path(EDITOR_PROJECT_PATH),
            "project": {"version": 1, "materials": [], "chapters": []},
        }
    try:
        project = read_json_object(EDITOR_PROJECT_PATH)
        return {
            "exists": True,
            "path": server_path(EDITOR_PROJECT_PATH),
            "project": project or {"version": 1, "materials": [], "chapters": []},
        }
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Cannot read editor project: {exc}")


@app.post("/api/editor-project")
def save_editor_project(
    payload: dict[str, Any] = Body(...),
    project_uuid: str | None = Query(None),
    edition_id: int | None = Query(None),
) -> dict[str, Any]:
    """Save canonical SQLite state plus the active renderer compatibility file."""
    project = dict(payload)
    project_duration = parse_seconds(
        project.get(
            "duration_seconds",
            project.get("durationSeconds", project.get("audioDuration")),
        )
    )
    if project_duration is None and project.get("durationMs") is not None:
        duration_ms = parse_seconds(project.get("durationMs"))
        project_duration = duration_ms / 1000 if duration_ms is not None else None
    materials_by_id = {
        str(material.get("id")): material
        for material in project.get("materials", [])
        if isinstance(material, dict) and material.get("id") is not None
    }
    enriched_chapters: list[Any] = []
    for raw_chapter in project.get("chapters", []):
        if not isinstance(raw_chapter, dict):
            enriched_chapters.append(raw_chapter)
            continue
        chapter = dict(raw_chapter)
        image_id = chapter.get("imageAssetId")
        material = materials_by_id.get(str(image_id)) if image_id is not None else None
        image_path = resolve_editor_server_path(
            material.get("serverPath") if material else None
        )
        if image_path:
            chapter["image_path"] = str(image_path)
        else:
            chapter.pop("image_path", None)
        enriched_chapters.append(chapter)
    try:
        chapters = normalize_editor_chapters(
            enriched_chapters,
            project_duration=project_duration,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    project["chapters"] = chapters
    try:
        atomic_write_json(CHAPTERS_PATH, chapters)
        atomic_write_json(EDITOR_PROJECT_PATH, project)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Cannot save editor project: {exc}")
    result = {
        "ok": True,
        "path": server_path(EDITOR_PROJECT_PATH),
        "chaptersPath": server_path(CHAPTERS_PATH),
        "chapterCount": len(chapters),
        "project": project,
    }
    if project_uuid:
        try:
            edition = PROJECT_REPOSITORY.save_video_edition(
                project_uuid, project, edition_id=edition_id
            )
            result.update(
                {
                    "storage": "sqlite",
                    "project_uuid": project_uuid,
                    "edition_id": edition["id"],
                }
            )
        except Exception as exc:
            raise project_http_error(exc) from exc
    else:
        result["storage"] = "compatibility_json"
    return result


@app.post("/api/book-project/refresh-chapters")
def refresh_chapters() -> dict[str, Any]:
    """Force re-extract chapters from RPP."""
    data = discover_data_files()
    rpp_path = resolve_path(data["rpp"]["path"]) if data["rpp"]["exists"] else None
    if not rpp_path:
        raise HTTPException(status_code=400, detail="No RPP file found")
    audio_path = resolve_path(data["audio"]["path"]) if data["audio"]["exists"] else None
    cmd = [
        console_python_executable(),
        str(MAIN_SCRIPT),
        "inspect-rpp",
        "--rpp", str(rpp_path),
        "--rpp-track", "КНИГА ОЗВУЧКА",
        "--chapter-pattern", "Глава",
        "--origin", "project",
        "--add-intro",
    ]
    if audio_path:
        cmd += ["--audio", str(audio_path)]
    try:
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        result = subprocess.run(
            cmd, cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", env=env, timeout=60,
            **hidden_process_options(),
        )
        chapters_path = BUILD_DIR / "chapters.detected.json"
        chapters = []
        if chapters_path.exists():
            chapters = json.loads(chapters_path.read_text(encoding="utf-8"))
        return {
            "ok": result.returncode == 0,
            "count": len(chapters),
            "chapters": chapters,
            "log": result.stdout + result.stderr,
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Refresh chapters timed out")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Refresh chapters failed: {exc}")


@app.get("/api/chapters")
def get_chapters() -> dict[str, Any]:
    """Return chapters from chapters.detected.json."""
    path = BUILD_DIR / "chapters.detected.json"
    if not path.exists():
        return {"exists": False, "chapters": [], "count": 0}
    try:
        chapters = json.loads(path.read_text(encoding="utf-8"))
        return {"exists": True, "count": len(chapters), "chapters": chapters}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cannot read chapters: {exc}")


@app.post("/api/save-chapters")
def save_chapters(data: SaveChaptersRequest) -> dict[str, Any]:
    p = resolve_path(data.path)
    if not p or not is_within(p, BUILD_DIR) or p.suffix.lower() != ".json":
        raise HTTPException(status_code=400, detail="Chapters path must be a JSON file inside the build directory")
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        atomic_write_json(p, data.chapters)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cannot save chapters: {exc}")
    return {"ok": True, "path": str(p), "count": len(data.chapters)}


# ── Render endpoints ─────────────────────────────────────────────

def build_render_cmd(
    test_mode: bool = False,
) -> list[str]:
    """Build a command using only arguments supported by suviren_q.py render."""
    inputs = get_export_inputs()
    missing = [key for key in ("audio", "cover", "chapters") if not inputs.get(key)]
    if missing:
        raise HTTPException(
            status_code=400,
            detail={"message": "Project is not ready for export", "missing": missing},
        )
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    audio: Path = inputs["audio"]
    cover: Path = inputs["cover"]
    background: Path | None = inputs["background"]
    # Keep the complete chapter list even for a 60-second test. This preserves
    # previous/next chapter context and lets the in-frame progress bar use the
    # same full-project duration as the editor.
    chapters = CHAPTERS_PATH
    out = export_output_path(test_mode)
    editor_project = load_editor_project() or {}
    editor_theme = str(editor_project.get("theme") or "amber")
    render_preset = str(editor_project.get("renderPreset") or DEFAULT_RENDER_PRESET)
    if render_preset not in RENDER_RATE_PRESETS_KBPS:
        render_preset = DEFAULT_RENDER_PRESET
    render_style = {
        "amber": "obsidian",
        "violet": "deep-purple",
        "mono": "mono",
    }.get(editor_theme, "obsidian")
    cmd = [
        console_python_executable(),
        str(MAIN_SCRIPT),
        "render",
        "--audio", str(audio),
        "--cover", str(cover),
        "--chapters", str(chapters),
        "--out", str(out),
        "--fps", "30",
        "--waveform", "ffmpeg",
        "--width", "1920",
        "--height", "1080",
        "--style", render_style,
        "--bitrate-preset", render_preset,
    ]
    if EDITOR_PROJECT_PATH.is_file():
        cmd += ["--editor-project", str(EDITOR_PROJECT_PATH)]
    if test_mode:
        cmd += ["--max-duration", "60"]
    if background:
        cmd += ["--background", str(background)]
    return cmd


@app.get("/api/export/readiness")
def export_readiness() -> dict[str, Any]:
    """Fast, non-rendering validation of export inputs and local tools."""
    return export_readiness_payload()


def require_export_ready(*, test_mode: bool) -> dict[str, Any]:
    readiness = export_readiness_payload()
    if not readiness["ready"]:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Project is not ready for export",
                "missing": readiness["missing"],
                "errors": readiness["errors"],
                "warnings": readiness["warnings"],
            },
        )
    storage = readiness["renderEstimate"]["test" if test_mode else "full"]
    if not storage["enough"]:
        required_gib = storage["peakBytes"] / 1024**3
        free_gib = storage["freeBytes"] / 1024**3
        raise HTTPException(
            status_code=507,
            detail={
                "message": (
                    f"Недостаточно места для выбранного профиля: "
                    f"нужно около {required_gib:.1f} ГБ, свободно {free_gib:.1f} ГБ"
                ),
                "missing": ["disk-space"],
            },
        )
    return readiness


@app.post("/api/render/test")
def render_test() -> dict[str, Any]:
    """Start a test render job (60 seconds)."""
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    require_export_ready(test_mode=True)
    try:
        cmd = build_render_cmd(test_mode=True)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cannot build render command: {exc}")
    output = export_output_path(True)
    job_id = start_job("render-test", cmd, output=output)
    job = JOBS[job_id]
    return {
        "job_id": job_id,
        "kind": "test",
        "message": "Test render started (60s)",
        "output": job["output"],
        "download_url": job["download_url"],
    }


@app.post("/api/render/full")
def render_full() -> dict[str, Any]:
    """Start a full render job."""
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    require_export_ready(test_mode=False)
    try:
        cmd = build_render_cmd(test_mode=False)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cannot build render command: {exc}")
    output = export_output_path(False)
    job_id = start_job("render-full", cmd, output=output)
    job = JOBS[job_id]
    return {
        "job_id": job_id,
        "kind": "full",
        "message": "Full render started",
        "output": job["output"],
        "download_url": job["download_url"],
    }


@app.get("/api/render/status")
def render_status() -> dict[str, Any]:
    """Return status of all render jobs (latest first)."""
    render_jobs = [
        j for j in JOBS.values()
        if j["kind"] in ("render-test", "render-full")
    ]
    render_jobs.sort(key=lambda j: j["created_at"], reverse=True)
    latest = render_jobs[0] if render_jobs else None
    return {
        "has_jobs": bool(render_jobs),
        "active": any(j["status"] == "running" for j in render_jobs),
        "latest": latest,
        "jobs": render_jobs[:5],
    }


@app.get("/api/render/log")
def render_log(max_lines: int = Query(100, ge=10, le=5000)) -> list[str]:
    """Return the log of the latest render job."""
    render_jobs = [
        j for j in JOBS.values()
        if j["kind"] in ("render-test", "render-full")
    ]
    render_jobs.sort(key=lambda j: j["created_at"], reverse=True)
    if not render_jobs:
        return ["[Wunderwaffe] No render jobs yet"]
    latest = render_jobs[0]
    return latest["log"][-max_lines:]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/jobs")
def list_jobs() -> list[dict[str, Any]]:
    return sorted(JOBS.values(), key=lambda j: j["created_at"], reverse=True)[:20]


# ── Waveform ─────────────────────────────────────────────────────

@app.get("/api/waveform")
def get_waveform(
    samples: int = Query(2000, ge=100, le=10000),
    force: bool = Query(False),
) -> dict[str, Any]:
    """Generate downsampled waveform data from audio file."""
    inputs = get_export_inputs()
    audio_path = inputs.get("audio")
    if not audio_path or not audio_path.is_file():
        raise HTTPException(status_code=404, detail="No audio file found")
    waveform_path = BUILD_DIR / "waveform.json"
    stat = audio_path.stat()
    chapter_duration = max(
        (float(item.get("end_seconds", 0) or 0) for item in inputs.get("chapter_items", [])),
        default=0.0,
    )
    cache_key = (
        f"{server_path(audio_path)}:{stat.st_size}:{stat.st_mtime_ns}:"
        f"{samples}:{chapter_duration:.3f}:envelope-v3"
    )
    if waveform_path.exists() and not force:
        try:
            data = json.loads(waveform_path.read_text(encoding="utf-8"))
            if data.get("cacheKey") == cache_key:
                return data
        except Exception:
            pass
    # Decode directly to a deliberately tiny sample rate. Even a 16-hour book
    # stays small instead of producing gigabytes of temporary 22 kHz PCM.
    duration_hint = max(quick_audio_duration(audio_path) or 0.0, chapter_duration)
    try:
        # If a damaged/giant container cannot be probed and has no chapter
        # timeline, stay at a bounded rate instead of buffering hundreds of MB.
        sample_rate = (
            max(8, min(4000, math.ceil(samples / max(duration_hint, 1.0))))
            if duration_hint > 0
            else max(8, min(64, math.ceil(samples / 60)))
        )
        process = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(audio_path), "-vn",
             "-af",
             f"aformat=channel_layouts=mono,aresample=8000,"
             f"aeval=abs(val(0)),aresample={sample_rate}",
             "-ac", "1",
             "-f", "s16le", "pipe:1"],
            capture_output=True, timeout=120, check=True,
            **hidden_process_options(),
        )
        raw = process.stdout
        if len(raw) % 2:
            raw = raw[:-1]
        if not raw:
            raise ValueError("FFmpeg returned no waveform samples")
        raw_samples = list(struct.unpack(f"<{len(raw)//2}h", raw))
        # Downsample the rectified envelope into peak/RMS buckets. Picking one
        # raw PCM value per bucket often lands near a zero crossing and makes
        # long spoken-word recordings look almost flat.
        bucket_count = min(samples, len(raw_samples))
        downsampled = []
        for index in range(bucket_count):
            start = index * len(raw_samples) // bucket_count
            end = (index + 1) * len(raw_samples) // bucket_count
            bucket = raw_samples[start:end]
            if not bucket:
                continue
            peak = max(abs(value) for value in bucket)
            rms = math.sqrt(sum(value * value for value in bucket) / len(bucket))
            downsampled.append(peak * 0.72 + rms * 0.28)
        # A percentile reference keeps one unusually loud transient from
        # flattening the remaining 16 hours of speech.
        ordered = sorted(downsampled)
        reference = ordered[min(len(ordered) - 1, round(len(ordered) * 0.98))] if ordered else 1
        reference = max(1.0, reference)
        normalized = [round(min(1.0, value / reference), 4) for value in downsampled]
        result = {
            "samples": normalized,
            "count": len(normalized),
            "max": round(reference, 2),
            "duration_sec": round(duration_hint or len(raw_samples) / sample_rate, 1),
            "cacheKey": cache_key,
        }
        atomic_write_json(waveform_path, result)
        return result
    except FileNotFoundError:
        # ffmpeg not found — generate synthetic waveform
        return generate_synthetic_waveform(
            audio_path, samples, cache_key=cache_key, duration_hint=duration_hint
        )
    except subprocess.CalledProcessError:
        # ffmpeg failed — fallback
        return generate_synthetic_waveform(
            audio_path, samples, cache_key=cache_key, duration_hint=duration_hint
        )
    except Exception as exc:
        # Fallback
        return generate_synthetic_waveform(
            audio_path, samples, cache_key=cache_key, duration_hint=duration_hint
        )


def generate_synthetic_waveform(
    audio_path: Path,
    samples: int,
    *,
    cache_key: str = "",
    duration_hint: float = 0.0,
) -> dict[str, Any]:
    """Generate synthetic waveform data when ffmpeg is unavailable."""
    import random
    random.seed(42)
    # Try to get duration from ffprobe
    duration_sec = duration_hint
    if duration_sec <= 0:
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "format=duration", "-of", "csv=p=0",
                 str(audio_path)],
                capture_output=True, text=True, timeout=30,
                **hidden_process_options(),
            )
            if result.returncode == 0 and result.stdout.strip():
                duration_sec = float(result.stdout.strip())
        except Exception:
            pass
    # Generate envelope-shaped random data (like a real waveform)
    n = samples
    data = []
    for i in range(n):
        t = i / n
        envelope = math.sin(t * math.pi) * 0.8 + 0.2
        noise = random.random() * 0.5 + 0.1
        data.append(round(envelope * noise, 4))
    max_val = max(data) if data else 1
    data = [round(v / max_val, 4) for v in data]
    result = {
        "samples": data,
        "count": len(data),
        "max": round(max_val, 2),
        "duration_sec": round(duration_sec, 1),
        "synthetic": True,
    }
    if cache_key:
        result["cacheKey"] = cache_key
    waveform_path = BUILD_DIR / "waveform.json"
    atomic_write_json(waveform_path, result)
    return result


# ── Layout ───────────────────────────────────────────────────────

@app.get("/api/layout")
def api_get_layout():
    if not LAYOUT_PATH.exists():
        # Return default layout
        return {"exists": False, "path": str(LAYOUT_PATH), "layout": get_default_layout()}
    try:
        return {
            "exists": True,
            "path": str(LAYOUT_PATH),
            "layout": json.loads(LAYOUT_PATH.read_text(encoding="utf-8")),
        }
    except Exception as exc:
        return {"exists": False, "path": str(LAYOUT_PATH), "layout": get_default_layout(), "error": str(exc)}


@app.post("/api/layout")
def api_save_layout(payload: dict = Body(...)):
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    LAYOUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "path": str(LAYOUT_PATH)}


@app.post("/api/layout/reset")
def api_reset_layout(target: str = "default"):
    """Reset layout to default or book style."""
    layout = get_default_layout()
    if target == "book":
        # Adjust for current book style (customize based on data)
        project = discover_data_files()
        layout["objects"]["bookTitle"] = layout["objects"].get("bookTitle", {})
        layout["objects"]["bookTitle"]["text"] = project.get("projectName", "Книга")
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    LAYOUT_PATH.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "path": str(LAYOUT_PATH), "target": target}


# ── Media ────────────────────────────────────────────────────────

def upload_filename_from_request(request: Request, query_filename: str | None) -> str | None:
    if query_filename:
        return query_filename
    header_name = request.headers.get("x-filename") or request.headers.get("x-file-name")
    if header_name:
        return unquote(header_name)
    disposition = request.headers.get("content-disposition", "")
    encoded = re.search(r"filename\*=UTF-8''([^;]+)", disposition, flags=re.IGNORECASE)
    if encoded:
        return unquote(encoded.group(1).strip())
    plain = re.search(r'filename="?([^";]+)"?', disposition, flags=re.IGNORECASE)
    return plain.group(1).strip() if plain else None


def sanitize_upload_filename(value: str) -> str:
    raw_name = unquote(value).replace("\\", "/").rsplit("/", 1)[-1].strip()
    suffix = Path(raw_name).suffix.lower()
    if suffix not in IMPORT_EXTENSIONS:
        allowed = ", ".join(sorted(IMPORT_EXTENSIONS))
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported media extension '{suffix or '(none)'}'. Allowed: {allowed}",
        )
    stem = raw_name[:-len(suffix)] if suffix else raw_name
    stem = re.sub(r'[\x00-\x1f<>:"/\\|?*]+', "_", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" .")
    if not stem:
        stem = "media"
    stem = stem[:140].rstrip(" .") or "media"
    if stem.casefold() in {
        "con", "prn", "aux", "nul",
        *(f"com{number}" for number in range(1, 10)),
        *(f"lpt{number}" for number in range(1, 10)),
    }:
        stem = f"_{stem}"
    return f"{stem}{suffix}"


def publish_upload_to(
    temp_path: Path, preferred_name: str, destination_dir: Path
) -> Path:
    """Publish a completed temp upload without ever replacing an existing file."""
    destination_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(preferred_name).stem
    suffix = Path(preferred_name).suffix
    attempt = 1
    while True:
        filename = preferred_name if attempt == 1 else f"{stem}-{attempt}{suffix}"
        candidate = destination_dir / filename
        try:
            os.link(temp_path, candidate)
            return candidate
        except FileExistsError:
            attempt += 1
            continue
        except OSError:
            # Filesystems without hard-link support still get exclusive creation.
            try:
                with candidate.open("xb") as target, temp_path.open("rb") as source:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
                    target.flush()
                    os.fsync(target.fileno())
                return candidate
            except FileExistsError:
                attempt += 1
                continue
            except Exception:
                try:
                    candidate.unlink()
                except FileNotFoundError:
                    pass
                raise


def publish_upload(temp_path: Path, preferred_name: str) -> Path:
    return publish_upload_to(temp_path, preferred_name, DATA_DIR)


@app.put("/api/projects/{project_uuid}/chapters/{chapter_id}/image")
async def upload_project_chapter_image(
    project_uuid: str,
    chapter_id: int,
    request: Request,
    filename: str | None = Query(default=None),
) -> dict[str, Any]:
    requested_name = upload_filename_from_request(request, filename)
    if not requested_name:
        raise HTTPException(status_code=400, detail="Не указано имя изображения.")
    safe_name = sanitize_upload_filename(requested_name)
    if Path(safe_name).suffix.lower() not in IMAGE_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail="Для главы можно выбрать PNG, JPG, WEBP, BMP или GIF.",
        )
    try:
        project = PROJECT_REPOSITORY.get_project(project_uuid, include_details=False)
        PROJECT_REPOSITORY.get_chapter(project_uuid, chapter_id)
    except Exception as exc:
        raise project_http_error(exc) from exc
    image_dir = (USER_DATA / project["project_folder"] / "images").resolve()
    project_root = (USER_DATA / project["project_folder"]).resolve()
    if not is_within(image_dir, project_root):
        raise HTTPException(status_code=400, detail="Некорректная папка проекта.")
    temp_path = image_dir / f".upload-{uuid.uuid4().hex}.part"
    size = 0
    try:
        image_dir.mkdir(parents=True, exist_ok=True)
        with temp_path.open("xb") as handle:
            async for chunk in request.stream():
                if not chunk:
                    continue
                handle.write(chunk)
                size += len(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if size == 0:
            raise HTTPException(status_code=400, detail="Файл изображения пуст.")
        destination = publish_upload_to(
            temp_path,
            f"chapter-{chapter_id}-{safe_name}",
            image_dir,
        )
    finally:
        temp_path.unlink(missing_ok=True)
    relative_path = destination.relative_to(USER_DATA).as_posix()
    try:
        asset = PROJECT_REPOSITORY.add_chapter_visual_asset(
            project_uuid,
            chapter_id,
            file_path=relative_path,
            title=Path(safe_name).stem,
            metadata={"size": size, "original_filename": requested_name},
        )
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise project_http_error(exc) from exc
    return {
        "ok": True,
        "asset": asset,
        "size": size,
        "serverPath": relative_path,
        "url": f"/api/project-media/{quote(relative_path, safe='/')}",
    }


@app.delete("/api/projects/{project_uuid}/chapters/{chapter_id}/image")
def delete_project_chapter_image(
    project_uuid: str, chapter_id: int
) -> dict[str, Any]:
    try:
        return PROJECT_REPOSITORY.remove_chapter_visual_asset(
            project_uuid, chapter_id
        )
    except Exception as exc:
        raise project_http_error(exc) from exc


@app.put("/api/media/import")
async def import_media(request: Request, filename: str | None = Query(default=None)) -> dict[str, Any]:
    """Stream a raw request body into data/ and publish it under a unique name."""
    requested_name = upload_filename_from_request(request, filename)
    if not requested_name:
        raise HTTPException(
            status_code=400,
            detail="A filename query parameter, X-Filename header, or Content-Disposition filename is required",
        )
    safe_name = sanitize_upload_filename(requested_name)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = DATA_DIR / f".upload-{uuid.uuid4().hex}.part"
    size = 0
    try:
        with temp_path.open("xb") as handle:
            async for chunk in request.stream():
                if not chunk:
                    continue
                handle.write(chunk)
                size += len(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if size == 0:
            raise HTTPException(status_code=400, detail="Uploaded media body is empty")
        destination = publish_upload(temp_path, safe_name)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass

    suffix = destination.suffix.lower()
    kind = "audio" if suffix in AUDIO_EXTENSIONS else "image" if suffix in IMAGE_EXTENSIONS else "video"
    return {
        "ok": True,
        "filename": destination.name,
        "kind": kind,
        "size": size,
        "serverPath": server_path(destination),
        "url": media_url(destination),
    }

@app.get("/api/media/{filename}")
def media(filename: str):
    """Legacy single-component media route, restricted to data/."""
    fp = (DATA_DIR / filename).resolve()
    if is_within(fp, DATA_DIR) and fp.is_file():
        return FileResponse(str(fp))
    raise HTTPException(status_code=404, detail=f"File not found: {filename}")


@app.get("/api/media/data/{filename:path}")
def media_data(filename: str):
    """Serve files specifically from data/ directory."""
    fp = (DATA_DIR / filename).resolve()
    if not is_within(fp, DATA_DIR) or not fp.is_file():
        raise HTTPException(status_code=404, detail=f"File not found in data/: {filename}")
    return FileResponse(str(fp))


@app.get("/api/project-media/{filename:path}")
def project_media(filename: str):
    """Serve project-owned media while preventing path traversal."""
    path = (USER_DATA / filename).resolve()
    projects_root = (USER_DATA / "projects").resolve()
    if not is_within(path, projects_root) or not path.is_file():
        raise HTTPException(status_code=404, detail="Project media not found")
    return FileResponse(str(path))


@app.get("/api/exports/{filename}")
def download_export(filename: str):
    """Download a finished render from the build root without path traversal."""
    if Path(filename).name != filename or filename in {"", ".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid export filename")
    if Path(filename).suffix.lower() not in EXPORT_EXTENSIONS:
        raise HTTPException(status_code=404, detail="Export not found")
    path = (BUILD_DIR / filename).resolve()
    if not is_within(path, BUILD_DIR) or path.parent != BUILD_DIR.resolve() or not path.is_file():
        raise HTTPException(status_code=404, detail="Export not found")
    media_types = {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".mkv": "video/x-matroska",
        ".webm": "video/webm",
    }
    return FileResponse(
        str(path),
        media_type=media_types.get(path.suffix.lower(), "application/octet-stream"),
        filename=path.name,
    )


# ── Build files ──────────────────────────────────────────────────

@app.get("/api/build-files")
def build_files() -> dict[str, Any]:
    result = []
    if BUILD_DIR.exists():
        for p in sorted(BUILD_DIR.rglob("*")):
            if p.is_file():
                result.append({"path": str(p.relative_to(ROOT)), "size": p.stat().st_size})
    return {"files": result}


# ── Legacy /api/inputs ───────────────────────────────────────────

@app.get("/api/inputs")
def api_render_inputs():
    """Legacy — redirects to /api/book-project."""
    return discover_data_files()


# ── Entry ────────────────────────────────────────────────────────

if __name__ == "__main__":
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    import uvicorn
    print("=" * 60)
    print(f"  {APP_NAME} API Server v{APP_VERSION}")
    print("  Local-first Audiobook Production Suite")
    print("=" * 60)
    print(f"  Root:    {ROOT}")
    print(f"  Data:    {DATA_DIR}")
    print(f"  Build:   {BUILD_DIR}")
    print(f"  URL:     http://127.0.0.1:8787")
    print(f"  Docs:    http://127.0.0.1:8787/docs")
    print("=" * 60)
    uvicorn.run(app, host="127.0.0.1", port=8787, log_level="info")
