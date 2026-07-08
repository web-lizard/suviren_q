#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
suviren_q_server.py

Minimal local API server for suviren-q.
Runs suviren_q.py CLI commands as background jobs.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


ROOT = Path(__file__).resolve().parent
MAIN_SCRIPT = ROOT / "suviren_q.py"
BUILD_DIR = ROOT / "_suviren_q_build"

app = FastAPI(title="suviren-q API", version="0.2.0")

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


class RenderRequest(BaseModel):
    audio: str
    cover: str
    chapters: str | None = None
    rpp: str | None = None
    rpp_track: str = "КНИГА ОЗВУЧКА"
    chapter_pattern: str = "Глава"
    add_intro: bool = True
    origin: str = "project"
    offset: float = 0.0
    out: str = "suviren_q_output.mp4"
    background: str | None = None
    font: str | None = None
    waveform: str = "ffmpeg"
    fps: int = 30
    width: int = 1920
    height: int = 1080
    no_parallel: bool = False


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
            f"[suviren-q] job started: {kind}",
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
            # Parse progress from log lines like "Rendering segment 3/12"
            if "Rendering segment" in line:
                JOBS[job_id]["progress"] = min(0.99, JOBS[job_id].get("progress", 0) + 0.01)
        returncode = proc.wait()
        JOBS[job_id]["returncode"] = returncode
        JOBS[job_id]["status"] = "done" if returncode == 0 else "failed"
        JOBS[job_id]["progress"] = 1.0 if returncode == 0 else JOBS[job_id].get("progress", 0)
        append_job_line(job_id, f"[suviren-q] job finished with code {returncode}")
    except Exception as exc:
        JOBS[job_id]["status"] = "failed"
        JOBS[job_id]["returncode"] = -1
        JOBS[job_id]["progress"] = 0.0
        append_job_line(job_id, f"[error] {type(exc).__name__}: {exc}")


# ── Health ───────────────────────────────────────────────────────

@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "version": "0.2.0",
        "root": str(ROOT),
        "python": sys.executable,
        "main_script_exists": MAIN_SCRIPT.exists(),
        "build_dir": str(BUILD_DIR),
    }


@app.get("/api/defaults")
def defaults() -> dict[str, Any]:
    return {
        "rpp": "зина книга вступление.rpp",
        "rpp_track": "КНИГА ОЗВУЧКА",
        "chapter_pattern": "Глава",
        "cover": "cover.png",
        "background": "",
        "audio": "book.mp3",
        "out": "suviren_q_output.mp4",
    }


# ── Inspect RPP ──────────────────────────────────────────────────

@app.post("/api/inspect-rpp")
def inspect_rpp(data: InspectRequest) -> dict[str, str]:
    if not MAIN_SCRIPT.exists():
        raise HTTPException(status_code=500, detail="suviren_q.py not found")
    cmd = [
        sys.executable,
        str(MAIN_SCRIPT),
        "inspect-rpp",
        "--rpp", str(resolve_path(data.rpp)),
        "--rpp-track", data.rpp_track,
        "--chapter-pattern", data.chapter_pattern,
        "--origin", data.origin,
    ]
    if data.audio:
        cmd += ["--audio", str(resolve_path(data.audio))]
    if data.add_intro:
        cmd.append("--add-intro")
    if data.offset:
        cmd += ["--offset", str(data.offset)]
    job_id = start_job("inspect-rpp", cmd)
    return {"job_id": job_id}


# ── Render ────────────────────────────────────────────────────────

@app.post("/api/render")
def render(data: RenderRequest) -> dict[str, str]:
    if not MAIN_SCRIPT.exists():
        raise HTTPException(status_code=500, detail="suviren_q.py not found")
    cmd = [
        sys.executable,
        str(MAIN_SCRIPT),
        "render",
        "--audio", str(resolve_path(data.audio)),
        "--cover", str(resolve_path(data.cover)),
        "--out", str(resolve_path(data.out)),
        "--fps", str(data.fps),
        "--waveform", data.waveform,
        "--width", str(data.width),
        "--height", str(data.height),
    ]
    if data.chapters:
        cmd += ["--chapters", str(resolve_path(data.chapters))]
    if data.rpp:
        cmd += ["--rpp", str(resolve_path(data.rpp))]
        cmd += ["--rpp-track", data.rpp_track]
        cmd += ["--chapter-pattern", data.chapter_pattern]
        if data.add_intro:
            cmd.append("--add-intro")
        if data.offset:
            cmd += ["--offset", str(data.offset)]
    if data.background:
        cmd += ["--background", str(resolve_path(data.background))]
    if data.font:
        cmd += ["--font", str(resolve_path(data.font))]
    if data.no_parallel:
        cmd.append("--no-parallel")
    job_id = start_job("render", cmd)
    return {"job_id": job_id}


# ── Job status ────────────────────────────────────────────────────

@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ── Chapters ──────────────────────────────────────────────────────

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


@app.get("/api/chapters")
def get_chapters(path: str = "_suviren_q_build/chapters.detected.json") -> dict[str, Any]:
    p = resolve_path(path)
    if not p or not p.exists():
        return {"exists": False, "path": str(p), "chapters": []}
    try:
        chapters = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cannot read chapters: {exc}")
    return {"exists": True, "path": str(p), "count": len(chapters), "chapters": chapters}


# ── Build files ──────────────────────────────────────────────────

@app.get("/api/build-files")
def build_files() -> dict[str, Any]:
    result = []
    if BUILD_DIR.exists():
        for p in sorted(BUILD_DIR.rglob("*")):
            if p.is_file():
                result.append({"path": str(p.relative_to(ROOT)), "size": p.stat().st_size})
    return {"files": result}


# ── Layout (for stage editor, simplified) ────────────────────────

BUILD_DIR_LAYOUT = BUILD_DIR
LAYOUT_PATH = BUILD_DIR_LAYOUT / "layout.json"

@app.get("/api/layout")
def api_get_layout():
    if not LAYOUT_PATH.exists():
        return {"exists": False, "path": str(LAYOUT_PATH), "layout": None}
    try:
        return {"exists": True, "path": str(LAYOUT_PATH), "layout": json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))}
    except Exception as exc:
        return {"exists": False, "path": str(LAYOUT_PATH), "layout": None, "error": str(exc)}


@app.post("/api/layout")
def api_save_layout(payload: dict = Body(...)):
    BUILD_DIR_LAYOUT.mkdir(parents=True, exist_ok=True)
    LAYOUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "path": str(LAYOUT_PATH)}


# ── Inputs status (simplified render console replacement) ────────

@app.get("/api/inputs")
def api_render_inputs():
    """Check what input files are available for rendering."""
    audio_candidates = ["book.wav", "book.mp3", "book_from_chapters.mp3"]
    cover_candidates = ["cover.png", "cover.jpg", "cover.jpeg", "cover.webp"]
    chapters_path = BUILD_DIR / "chapters.detected.json"

    audio = next((p for p in [ROOT / c for c in audio_candidates] if p.exists()), None)
    cover = next((p for p in [ROOT / c for c in cover_candidates] if p.exists()), None)
    chapters_exist = chapters_path.exists()

    return {
        "ready": bool(audio and cover and chapters_exist),
        "audio": str(audio) if audio else None,
        "cover": str(cover) if cover else None,
        "chapters": {
            "path": str(chapters_path),
            "exists": chapters_exist,
        },
        "missing": [
            label for label, ok in [
                ("audio (book.wav/book.mp3)", bool(audio)),
                ("cover (cover.png)", bool(cover)),
                ("chapters.detected.json", chapters_exist),
            ]
            if not ok
        ],
    }


# ── Entry ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    print("suviren-q API v0.2.0 at http://127.0.0.1:8787")
    print(f"Project root: {ROOT}")
    uvicorn.run(app, host="127.0.0.1", port=8787)