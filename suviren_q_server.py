#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
suviren_q_server.py → BookForge Studio API Server

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
import struct
import math
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from fastapi import FastAPI, HTTPException, Body, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel


ROOT = Path(__file__).resolve().parent
MAIN_SCRIPT = ROOT / "suviren_q.py"
BUILD_DIR = ROOT / "_suviren_q_build"
DATA_DIR = ROOT / "data"
LAYOUT_PATH = BUILD_DIR / "layout.json"
EDITOR_PROJECT_PATH = BUILD_DIR / "editor-project.json"
CHAPTERS_PATH = BUILD_DIR / "chapters.detected.json"

APP_NAME = "BOOK WUNDERWAFFE"
APP_VERSION = "1.0.0"

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg", ".opus"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}
IMPORT_EXTENSIONS = AUDIO_EXTENSIONS | IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
EXPORT_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}

app = FastAPI(title=APP_NAME, version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5178",
        "http://localhost:5178",
        "http://127.0.0.1:4178",
        "http://localhost:4178",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["*"],
)

JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()
AUDIO_PROBE_CACHE: dict[tuple[str, int, int], dict[str, Any]] = {}
AUDIO_DISCOVERY_CACHE: dict[tuple[str, int, int], float] = {}


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
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    if not is_within(resolved, ROOT) or not resolved.is_file():
        return None
    return resolved


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
                f"[BookForge] job started: {kind}",
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
        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            append_job_line(job_id, line)
            if "Rendering segment" in line:
                JOBS[job_id]["progress"] = min(0.99, JOBS[job_id].get("progress", 0) + 0.01)
        returncode = proc.wait()
        job = JOBS[job_id]
        output_value = job.get("output")
        output_path = resolve_path(output_value) if output_value else None
        output_exists = bool(returncode == 0 and output_path and output_path.is_file())
        job["returncode"] = returncode
        job["output_exists"] = output_exists
        job["output_size"] = output_path.stat().st_size if output_exists and output_path else 0
        job["status"] = "done" if returncode == 0 and (not output_path or output_exists) else "failed"
        job["progress"] = 1.0 if job["status"] == "done" else job.get("progress", 0)
        job["updated_at"] = time.time()
        if returncode == 0 and output_path and not output_exists:
            append_job_line(job_id, f"[error] expected output was not created: {output_path}")
        append_job_line(job_id, f"[BookForge] job finished with code {returncode}")
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
    """Return the default BookForge Studio composition layout."""
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
    if editor and (editor.get("scenes") or editor.get("layers")):
        warnings.append(
            "Позиции слоёв и покадровые сцены пока не переносятся в MP4: "
            "экспорт использует стабильный статический шаблон рендера."
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
    }


# ── Endpoints ────────────────────────────────────────────────────

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
    }


@app.get("/api/book-project")
def book_project() -> dict[str, Any]:
    """Main data auto-discovery endpoint."""
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    data = discover_data_files()
    return data


@app.get("/api/editor-project")
def get_editor_project() -> dict[str, Any]:
    """Return the persisted editor document, or an empty compatible document."""
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
def save_editor_project(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Atomically save editor state and its normalized renderer chapter file."""
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
    try:
        chapters = normalize_editor_chapters(
            project.get("chapters", []),
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
    return {
        "ok": True,
        "path": server_path(EDITOR_PROJECT_PATH),
        "chaptersPath": server_path(CHAPTERS_PATH),
        "chapterCount": len(chapters),
        "project": project,
    }


@app.post("/api/book-project/refresh-chapters")
def refresh_chapters() -> dict[str, Any]:
    """Force re-extract chapters from RPP."""
    data = discover_data_files()
    rpp_path = resolve_path(data["rpp"]["path"]) if data["rpp"]["exists"] else None
    if not rpp_path:
        raise HTTPException(status_code=400, detail="No RPP file found")
    audio_path = resolve_path(data["audio"]["path"]) if data["audio"]["exists"] else None
    cmd = [
        sys.executable,
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
    chapters = (
        clipped_test_chapters(inputs["chapter_items"], seconds=60.0)
        if test_mode
        else CHAPTERS_PATH
    )
    out = export_output_path(test_mode)
    editor_theme = str((load_editor_project() or {}).get("theme") or "amber")
    render_style = {
        "amber": "obsidian",
        "violet": "deep-purple",
        "mono": "mono",
    }.get(editor_theme, "obsidian")
    cmd = [
        sys.executable,
        str(MAIN_SCRIPT),
        "render",
        "--audio", str(audio),
        "--cover", str(cover),
        "--chapters", str(chapters),
        "--out", str(out),
        "--fps", "30",
        "--waveform", "static",
        "--width", "1920",
        "--height", "1080",
        "--style", render_style,
    ]
    if background:
        cmd += ["--background", str(background)]
    return cmd


@app.get("/api/export/readiness")
def export_readiness() -> dict[str, Any]:
    """Fast, non-rendering validation of export inputs and local tools."""
    return export_readiness_payload()


def require_export_ready() -> dict[str, Any]:
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
    return readiness


@app.post("/api/render/test")
def render_test() -> dict[str, Any]:
    """Start a test render job (60 seconds)."""
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    require_export_ready()
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
    require_export_ready()
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
        return ["[BookForge] No render jobs yet"]
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
    audio_path = get_export_inputs().get("audio")
    if not audio_path or not audio_path.is_file():
        raise HTTPException(status_code=404, detail="No audio file found")
    waveform_path = BUILD_DIR / "waveform.json"
    stat = audio_path.stat()
    cache_key = f"{server_path(audio_path)}:{stat.st_size}:{stat.st_mtime_ns}:{samples}"
    if waveform_path.exists() and not force:
        try:
            data = json.loads(waveform_path.read_text(encoding="utf-8"))
            if data.get("cacheKey") == cache_key:
                return data
        except Exception:
            pass
    # Decode directly to a deliberately tiny sample rate. Even a 16-hour book
    # stays below 1 MB instead of producing gigabytes of temporary 22 kHz PCM.
    try:
        duration_hint = quick_audio_duration(audio_path) or 0.0
        sample_rate = max(8, min(4000, math.ceil(samples / max(duration_hint, 1.0))))
        process = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(audio_path), "-vn",
             "-ac", "1", "-ar", str(sample_rate), "-f", "s16le", "pipe:1"],
            capture_output=True, timeout=120, check=True,
        )
        raw = process.stdout
        if len(raw) % 2:
            raw = raw[:-1]
        if not raw:
            raise ValueError("FFmpeg returned no waveform samples")
        raw_samples = list(struct.unpack(f"<{len(raw)//2}h", raw))
        # Downsample
        step = max(1, len(raw_samples) // samples)
        downsampled = [abs(raw_samples[i]) for i in range(0, len(raw_samples), step)]
        # Normalize to 0-1
        max_val = max(downsampled) if downsampled else 1
        normalized = [round(v / max_val, 4) for v in downsampled]
        # Limit to requested samples
        normalized = normalized[:samples]
        result = {
            "samples": normalized,
            "count": len(normalized),
            "max": round(max_val, 2),
            "duration_sec": round(duration_hint or len(raw_samples) / sample_rate, 1),
            "cacheKey": cache_key,
        }
        atomic_write_json(waveform_path, result)
        return result
    except FileNotFoundError:
        # ffmpeg not found — generate synthetic waveform
        return generate_synthetic_waveform(audio_path, samples)
    except subprocess.CalledProcessError:
        # ffmpeg failed — fallback
        return generate_synthetic_waveform(audio_path, samples)
    except Exception as exc:
        # Fallback
        return generate_synthetic_waveform(audio_path, samples)


def generate_synthetic_waveform(audio_path: Path, samples: int) -> dict[str, Any]:
    """Generate synthetic waveform data when ffmpeg is unavailable."""
    import random
    random.seed(42)
    # Try to get duration from ffprobe
    duration_sec = 0
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration", "-of", "csv=p=0",
             str(audio_path)],
            capture_output=True, text=True, timeout=30,
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
    waveform_path = BUILD_DIR / "waveform.json"
    waveform_path.parent.mkdir(parents=True, exist_ok=True)
    waveform_path.write_text(json.dumps(result), encoding="utf-8")
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


def publish_upload(temp_path: Path, preferred_name: str) -> Path:
    """Publish a completed temp upload without ever replacing an existing file."""
    stem = Path(preferred_name).stem
    suffix = Path(preferred_name).suffix
    attempt = 1
    while True:
        filename = preferred_name if attempt == 1 else f"{stem}-{attempt}{suffix}"
        candidate = DATA_DIR / filename
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
    print("  YouTube Audiobook Composer")
    print("=" * 60)
    print(f"  Root:    {ROOT}")
    print(f"  Data:    {DATA_DIR}")
    print(f"  Build:   {BUILD_DIR}")
    print(f"  URL:     http://127.0.0.1:8787")
    print(f"  Docs:    http://127.0.0.1:8787/docs")
    print("=" * 60)
    uvicorn.run(app, host="127.0.0.1", port=8787, log_level="info")
