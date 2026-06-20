#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
suviren_q_server.py

Local API server for suviren-q Vue UI.
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

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


ROOT = Path(__file__).resolve().parent
MAIN_SCRIPT = ROOT / "suviren_q.py"
BUILD_DIR = ROOT / "_suviren_q_build"

app = FastAPI(title="suviren-q API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5178",
        "http://localhost:5178",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

JOBS: dict[str, dict[str, Any]] = {}


class InspectRequest(BaseModel):
    rpp: str
    audio: str | None = None
    rpp_track: str = "КНИГА ОЗВУЧКА"
    chapter_pattern: str = "Глава"
    add_intro: bool = True
    origin: str = "project"
    offset: float = 0.0


class PreviewRequest(BaseModel):
    cover: str
    chapters: str = "_suviren_q_build/chapters.detected.json"
    background: str | None = None
    font: str | None = None
    waveform: str = "static"


class RenderRequest(BaseModel):
    audio: str
    cover: str
    chapters: str = "_suviren_q_build/chapters.detected.json"
    out: str = "intimny_protokol_video.mp4"
    background: str | None = None
    font: str | None = None
    waveform: str = "static"



class SaveChaptersRequest(BaseModel):
    path: str = "_suviren_q_build/chapters.manual.json"
    chapters: list[dict[str, Any]]

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

        returncode = proc.wait()
        JOBS[job_id]["returncode"] = returncode
        JOBS[job_id]["status"] = "done" if returncode == 0 else "failed"
        append_job_line(job_id, f"[suviren-q] job finished with code {returncode}")

    except Exception as exc:
        JOBS[job_id]["status"] = "failed"
        JOBS[job_id]["returncode"] = -1
        append_job_line(job_id, f"[error] {type(exc).__name__}: {exc}")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
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
        "chapters": "_suviren_q_build/chapters.detected.json",
        "cover": "cover.png",
        "background": "",
        "audio": "book.mp3",
        "out": "intimny_protokol_video.mp4",
    }


@app.post("/api/inspect-rpp")
def inspect_rpp(data: InspectRequest) -> dict[str, str]:
    if not MAIN_SCRIPT.exists():
        raise HTTPException(status_code=500, detail="suviren_q.py not found")

    cmd = [
        sys.executable,
        str(MAIN_SCRIPT),
        "inspect-rpp",
        "--rpp",
        str(resolve_path(data.rpp)),
        "--rpp-track",
        data.rpp_track,
        "--chapter-pattern",
        data.chapter_pattern,
        "--origin",
        data.origin,
    ]

    if data.audio:
        cmd += ["--audio", str(resolve_path(data.audio))]

    if data.add_intro:
        cmd.append("--add-intro")

    if data.offset:
        cmd += ["--offset", str(data.offset)]

    job_id = start_job("inspect-rpp", cmd)
    return {"job_id": job_id}


@app.post("/api/preview")
def preview(data: PreviewRequest) -> dict[str, str]:
    if not MAIN_SCRIPT.exists():
        raise HTTPException(status_code=500, detail="suviren_q.py not found")

    cmd = [
        sys.executable,
        str(MAIN_SCRIPT),
        "preview",
        "--cover",
        str(resolve_path(data.cover)),
        "--chapters",
        str(resolve_path(data.chapters)),
    ]

    if data.background:
        cmd += ["--background", str(resolve_path(data.background))]

    if data.font:
        cmd += ["--font", str(resolve_path(data.font))]

    job_id = start_job("preview", cmd)
    return {"job_id": job_id}


@app.post("/api/render")
def render(data: RenderRequest) -> dict[str, str]:
    if not MAIN_SCRIPT.exists():
        raise HTTPException(status_code=500, detail="suviren_q.py not found")

    cmd = [
        sys.executable,
        str(MAIN_SCRIPT),
        "render",
        "--audio",
        str(resolve_path(data.audio)),
        "--cover",
        str(resolve_path(data.cover)),
        "--chapters",
        str(resolve_path(data.chapters)),
        "--out",
        str(resolve_path(data.out)),
    ]

    if data.background:
        cmd += ["--background", str(resolve_path(data.background))]

    if data.font:
        cmd += ["--font", str(resolve_path(data.font))]

    if data.waveform:
        cmd += ["--waveform", data.waveform]

    job_id = start_job("render", cmd)
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job



@app.post("/api/save-chapters")
def save_chapters(data: SaveChaptersRequest) -> dict[str, Any]:
    p = resolve_path(data.path)
    if not p:
        raise HTTPException(status_code=400, detail="Invalid chapters path")

    p.parent.mkdir(parents=True, exist_ok=True)

    try:
        p.write_text(
            json.dumps(data.chapters, ensure_ascii=False, indent=2),
            encoding="utf-8",
            newline="\n",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cannot save chapters: {exc}")

    return {
        "ok": True,
        "path": str(p),
        "count": len(data.chapters),
    }

@app.get("/api/chapters")
def get_chapters(path: str = "_suviren_q_build/chapters.detected.json") -> dict[str, Any]:
    p = resolve_path(path)
    if not p or not p.exists():
        return {"exists": False, "path": str(p), "chapters": []}

    try:
        chapters = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cannot read chapters: {exc}")

    return {
        "exists": True,
        "path": str(p),
        "count": len(chapters),
        "chapters": chapters,
    }


@app.get("/api/build-files")
def build_files() -> dict[str, Any]:
    result = []
    if BUILD_DIR.exists():
        for p in sorted(BUILD_DIR.rglob("*")):
            if p.is_file():
                result.append({
                    "path": str(p.relative_to(ROOT)),
                    "size": p.stat().st_size,
                })
    return {"files": result}


if __name__ == "__main__":
    import uvicorn

    print("suviren-q API starting at http://127.0.0.1:8787")
    print(f"Project root: {ROOT}")
    uvicorn.run(app, host="127.0.0.1", port=8787)
