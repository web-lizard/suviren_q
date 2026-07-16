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

from fastapi import FastAPI, HTTPException, Body, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel


ROOT = Path(__file__).resolve().parent
MAIN_SCRIPT = ROOT / "suviren_q.py"
BUILD_DIR = ROOT / "_suviren_q_build"
DATA_DIR = ROOT / "data"
LAYOUT_PATH = BUILD_DIR / "layout.json"

app = FastAPI(title="BookForge Studio API", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

JOBS: dict[str, dict[str, Any]] = {}


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


def append_job_line(job_id: str, line: str) -> None:
    job = JOBS.get(job_id)
    if not job:
        return
    job["log"].append(line.rstrip("\n"))
    job["updated_at"] = time.time()


def start_job(kind: str, cmd: list[str]) -> str:
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {
        "id": job_id,
        "kind": kind,
        "cmd": cmd,
        "status": "running",
        "returncode": None,
        "progress": 0.0,
        "created_at": time.time(),
        "updated_at": time.time(),
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
        JOBS[job_id]["returncode"] = returncode
        JOBS[job_id]["status"] = "done" if returncode == 0 else "failed"
        JOBS[job_id]["progress"] = 1.0 if returncode == 0 else JOBS[job_id].get("progress", 0)
        append_job_line(job_id, f"[BookForge] job finished with code {returncode}")
    except Exception as exc:
        JOBS[job_id]["status"] = "failed"
        JOBS[job_id]["returncode"] = -1
        JOBS[job_id]["progress"] = 0.0
        append_job_line(job_id, f"[error] {type(exc).__name__}: {exc}")


def file_info(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False, "size": 0}
    return {
        "path": str(path.relative_to(ROOT)),
        "exists": True,
        "size": path.stat().st_size,
        "size_mb": round(path.stat().st_size / (1024 * 1024), 1),
    }


def discover_data_files() -> dict[str, Any]:
    """Scan data/ directory and auto-detect audio, cover, background, rpp."""
    data_dir = DATA_DIR
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
    }

    # Find best audio
    audio_exts = [".mp3", ".wav", ".m4a"]
    found_audio = list(data_dir.glob("*"))
    found_audio = [f for f in found_audio if f.suffix.lower() in audio_exts]
    if found_audio:
        best = max(found_audio, key=lambda f: f.stat().st_size)
        result["audio"] = file_info(best)
    else:
        result["missing"].append("audio (mp3/wav/m4a)")

    # Find cover
    found_cover = [f for f in data_dir.glob("*") if "cover" in f.stem.lower()]
    if found_cover:
        result["cover"] = file_info(found_cover[0])
    else:
        result["missing"].append("cover (image with 'cover' in name)")

    # Find background
    bg_keywords = ["background", "backdrop", "bg"]
    found_bg = [f for f in data_dir.glob("*")
                if any(kw in f.stem.lower() for kw in bg_keywords)]
    if found_bg:
        result["background"] = file_info(found_bg[0])
    else:
        result["warnings"].append("background not found — using dark fallback")

    # Find RPP
    found_rpp = list(data_dir.glob("*.rpp")) + list(data_dir.glob("*.RPP"))
    if found_rpp:
        result["rpp"] = file_info(found_rpp[0])
    else:
        result["missing"].append("RPP project file")

    # Chapters
    chapters_path = BUILD_DIR / "chapters.detected.json"
    if chapters_path.exists():
        try:
            ch_data = json.loads(chapters_path.read_text(encoding="utf-8"))
            result["chapters"] = {
                "path": str(chapters_path.relative_to(ROOT)),
                "exists": True,
                "count": len(ch_data),
                "first": ch_data[0].get("title", "") if ch_data else "",
                "last": ch_data[-1].get("title", "") if ch_data else "",
            }
        except Exception:
            result["warnings"].append("chapters.detected.json corrupted")

    # Derive project name from audio file
    if result["audio"]["exists"]:
        name = Path(result["audio"]["path"]).stem
        # Clean up common suffixes
        result["projectName"] = name.replace("_", " ").replace("-", " ").title()

    # Ready check
    result["ready"] = (
        result["audio"]["exists"]
        and result["cover"]["exists"]
        and result["rpp"]["exists"]
        and result["chapters"]["exists"]
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


# ── Endpoints ────────────────────────────────────────────────────

@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "version": "0.3.0",
        "app": "BookForge Studio",
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
    if not p:
        raise HTTPException(status_code=400, detail="Invalid chapters path")
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        p.write_text(json.dumps(data.chapters, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cannot save chapters: {exc}")
    return {"ok": True, "path": str(p), "count": len(data.chapters)}


# ── Render endpoints ─────────────────────────────────────────────

def build_render_cmd(
    test_mode: bool = False,
) -> list[str]:
    """Build the CLI command for render."""
    project = discover_data_files()
    if not project["ready"]:
        raise HTTPException(status_code=400, detail="Project not ready", detail_info=project["missing"])
    audio = resolve_path(project["audio"]["path"])
    cover = resolve_path(project["cover"]["path"])
    bg = resolve_path(project["background"]["path"]) if project["background"]["exists"] else None
    rpp = resolve_path(project["rpp"]["path"])
    chapters = BUILD_DIR / "chapters.detected.json"
    out_name = "zina_book_youtube_test_60sec.mp4" if test_mode else "zina_book_youtube_full.mp4"
    out = BUILD_DIR / out_name
    cmd = [
        sys.executable,
        str(MAIN_SCRIPT),
        "render",
        "--audio", str(audio),
        "--cover", str(cover),
        "--chapters", str(chapters),
        "--rpp", str(rpp),
        "--rpp-track", "КНИГА ОЗВУЧКА",
        "--chapter-pattern", "Глава",
        "--add-intro",
        "--out", str(out),
        "--fps", "30",
        "--waveform", "ffmpeg",
        "--width", "1920",
        "--height", "1080",
    ]
    if bg:
        cmd += ["--background", str(bg)]
    if test_mode:
        cmd += ["--duration", "60"]
    # Use layout if available
    if LAYOUT_PATH.exists():
        try:
            layout = json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))
            if layout.get("render", {}).get("crf"):
                cmd += ["--crf", str(layout["render"]["crf"])]
        except Exception:
            pass
    return cmd


@app.post("/api/render/test")
def render_test() -> dict[str, Any]:
    """Start a test render job (60 seconds)."""
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    try:
        cmd = build_render_cmd(test_mode=True)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cannot build render command: {exc}")
    job_id = start_job("render-test", cmd)
    return {"job_id": job_id, "kind": "test", "message": "Test render started (60s)"}


@app.post("/api/render/full")
def render_full() -> dict[str, Any]:
    """Start a full render job."""
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    try:
        cmd = build_render_cmd(test_mode=False)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cannot build render command: {exc}")
    job_id = start_job("render-full", cmd)
    return {"job_id": job_id, "kind": "full", "message": "Full render started"}


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
    project = discover_data_files()
    if not project["audio"]["exists"]:
        raise HTTPException(status_code=404, detail="No audio file found")
    audio_path = resolve_path(project["audio"]["path"])
    waveform_path = BUILD_DIR / "waveform.json"
    if waveform_path.exists() and not force:
        try:
            data = json.loads(waveform_path.read_text(encoding="utf-8"))
            return data
        except Exception:
            pass
    # Try to use ffmpeg to get raw PCM samples
    pcm_path = BUILD_DIR / "_waveform_tmp.pcm"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(audio_path),
             "-ac", "1", "-ar", "22050", "-f", "s16le",
             str(pcm_path)],
            capture_output=True, timeout=120, check=True,
        )
        raw = pcm_path.read_bytes()
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
            "duration_sec": round(len(raw_samples) / 22050, 1),
        }
        waveform_path.write_text(json.dumps(result), encoding="utf-8")
        if pcm_path.exists():
            pcm_path.unlink()
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

@app.get("/api/media/{filename}")
def media(filename: str):
    """Serve media files from data/ or root."""
    for base in [DATA_DIR, ROOT]:
        fp = base / filename
        if fp.exists():
            return FileResponse(str(fp))
    raise HTTPException(status_code=404, detail=f"File not found: {filename}")


@app.get("/api/media/data/{filename:path}")
def media_data(filename: str):
    """Serve files specifically from data/ directory."""
    fp = DATA_DIR / filename
    if not fp.exists():
        raise HTTPException(status_code=404, detail=f"File not found in data/: {filename}")
    return FileResponse(str(fp))


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
    print("  BookForge Studio API Server v0.3.0")
    print("  YouTube Audiobook Composer")
    print("=" * 60)
    print(f"  Root:    {ROOT}")
    print(f"  Data:    {DATA_DIR}")
    print(f"  Build:   {BUILD_DIR}")
    print(f"  URL:     http://127.0.0.1:8787")
    print(f"  Docs:    http://127.0.0.1:8787/docs")
    print("=" * 60)
    uvicorn.run(app, host="127.0.0.1", port=8787, log_level="info")