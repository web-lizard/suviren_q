#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
install_suviren_q_ui.py

Installs a local Vue interface for suviren-q.

Creates:
- suviren_q_server.py
- ui/package.json
- ui/index.html
- ui/vite.config.js
- ui/src/main.js
- ui/src/App.vue
- ui/src/style.css
- helper .bat launchers

The Vue UI talks to local FastAPI backend.
The backend runs existing suviren_q.py commands as jobs.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
MAIN_SCRIPT = ROOT / "suviren_q.py"
SERVER_SCRIPT = ROOT / "suviren_q_server.py"
UI_DIR = ROOT / "ui"
SRC_DIR = UI_DIR / "src"
LOCAL_DIR = ROOT / "_suviren_q_local"
REQ_FILE = ROOT / "requirements.txt"
GITIGNORE_FILE = ROOT / ".gitignore"


PY_DEPS = [
    "fastapi>=0.115.0",
    "uvicorn>=0.30.0",
]

NPM_PACKAGE_JSON = r"""
{
  "name": "suviren-q-ui",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite --host 127.0.0.1 --port 5178",
    "build": "vite build",
    "preview": "vite preview --host 127.0.0.1 --port 4178"
  },
  "dependencies": {
    "vue": "^3.5.0"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^6.0.0",
    "vite": "^7.0.0"
  }
}
"""

VITE_CONFIG = r"""
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '127.0.0.1',
    port: 5178,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8787',
        changeOrigin: true
      }
    }
  }
})
"""

INDEX_HTML = r"""
<!doctype html>
<html lang="ru">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>suviren-q - La Queue Souveraine</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.js"></script>
  </body>
</html>
"""

MAIN_JS = r"""
import { createApp } from 'vue'
import App from './App.vue'
import './style.css'

createApp(App).mount('#app')
"""

SERVER_PY = r'''
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


class RenderRequest(BaseModel):
    audio: str
    cover: str
    chapters: str = "_suviren_q_build/chapters.detected.json"
    out: str = "intimny_protokol_video.mp4"
    background: str | None = None
    font: str | None = None


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

    job_id = start_job("render", cmd)
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


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
'''

APP_VUE = r"""
<script setup>
import { computed, onMounted, reactive, ref } from 'vue'

const apiOk = ref(false)
const apiInfo = ref(null)
const activeJob = ref(null)
const jobLog = ref([])
const jobStatus = ref('idle')
const chapters = ref([])
const buildFiles = ref([])
const lastError = ref('')

const form = reactive({
  rpp: 'зина книга вступление.rpp',
  rpp_track: 'КНИГА ОЗВУЧКА',
  chapter_pattern: 'Глава',
  add_intro: true,
  origin: 'project',
  offset: 0,
  audio: 'book.mp3',
  cover: 'cover.png',
  background: '',
  chapters: '_suviren_q_build/chapters.detected.json',
  out: 'intimny_protokol_video.mp4',
  font: ''
})

const statusLabel = computed(() => {
  if (jobStatus.value === 'running') return 'Выполняется'
  if (jobStatus.value === 'done') return 'Готово'
  if (jobStatus.value === 'failed') return 'Ошибка'
  return 'Ожидание'
})

const chapterCount = computed(() => chapters.value.length)

function prettySeconds(value) {
  if (value === undefined || value === null) return '—'
  const n = Number(value)
  if (Number.isNaN(n)) return String(value)
  const h = Math.floor(n / 3600)
  const m = Math.floor((n % 3600) / 60)
  const s = Math.floor(n % 60)
  return [h, m, s].map(x => String(x).padStart(2, '0')).join(':')
}

async function apiGet(url) {
  const res = await fetch(url)
  if (!res.ok) throw new Error(await res.text())
  return await res.json()
}

async function apiPost(url, payload) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
  if (!res.ok) throw new Error(await res.text())
  return await res.json()
}

async function checkApi() {
  try {
    const data = await apiGet('/api/health')
    apiInfo.value = data
    apiOk.value = true
    lastError.value = ''
  } catch (err) {
    apiOk.value = false
    lastError.value = String(err)
  }
}

async function loadChapters() {
  try {
    const data = await apiGet('/api/chapters?path=' + encodeURIComponent(form.chapters))
    chapters.value = data.chapters || []
  } catch (err) {
    lastError.value = String(err)
  }
}

async function loadBuildFiles() {
  try {
    const data = await apiGet('/api/build-files')
    buildFiles.value = data.files || []
  } catch (err) {
    lastError.value = String(err)
  }
}

async function startJob(endpoint, payload) {
  lastError.value = ''
  jobLog.value = []
  jobStatus.value = 'running'

  try {
    const data = await apiPost(endpoint, payload)
    activeJob.value = data.job_id
    pollJob(data.job_id)
  } catch (err) {
    jobStatus.value = 'failed'
    lastError.value = String(err)
  }
}

async function pollJob(jobId) {
  try {
    const data = await apiGet('/api/jobs/' + jobId)
    jobStatus.value = data.status
    jobLog.value = data.log || []

    if (data.status === 'running') {
      setTimeout(() => pollJob(jobId), 900)
    } else {
      await loadChapters()
      await loadBuildFiles()
    }
  } catch (err) {
    jobStatus.value = 'failed'
    lastError.value = String(err)
  }
}

function runInspect() {
  startJob('/api/inspect-rpp', {
    rpp: form.rpp,
    audio: form.audio || null,
    rpp_track: form.rpp_track,
    chapter_pattern: form.chapter_pattern,
    add_intro: form.add_intro,
    origin: form.origin,
    offset: Number(form.offset || 0)
  })
}

function runPreview() {
  startJob('/api/preview', {
    cover: form.cover,
    chapters: form.chapters,
    background: form.background || null,
    font: form.font || null
  })
}

function runRender() {
  startJob('/api/render', {
    audio: form.audio,
    cover: form.cover,
    chapters: form.chapters,
    out: form.out,
    background: form.background || null,
    font: form.font || null
  })
}

onMounted(async () => {
  await checkApi()
  await loadChapters()
  await loadBuildFiles()
})
</script>

<template>
  <main class="shell">
    <section class="hero">
      <div>
        <div class="kicker">suviren-q</div>
        <h1>La Queue Souveraine</h1>
        <p class="subtitle">
          Локальный редактор видеокниг: REAPER → главы → панель → MP4.
        </p>
      </div>

      <div class="api-pill" :class="{ ok: apiOk, bad: !apiOk }">
        <span class="dot"></span>
        API: {{ apiOk ? 'живой' : 'не отвечает' }}
      </div>
    </section>

    <section class="grid">
      <div class="card control-card">
        <div class="card-head">
          <h2>1. Тайминги из REAPER</h2>
          <span class="badge">RPP parser</span>
        </div>

        <label>
          <span>RPP проект</span>
          <input v-model="form.rpp" />
        </label>

        <div class="two">
          <label>
            <span>Дорожка глав</span>
            <input v-model="form.rpp_track" />
          </label>

          <label>
            <span>Паттерн главы</span>
            <input v-model="form.chapter_pattern" />
          </label>
        </div>

        <div class="two">
          <label>
            <span>Начало таймлайна</span>
            <select v-model="form.origin">
              <option value="project">От начала проекта</option>
              <option value="first-chapter">От первой главы</option>
            </select>
          </label>

          <label>
            <span>Offset, сек.</span>
            <input v-model="form.offset" type="number" step="0.001" />
          </label>
        </div>

        <label class="check">
          <input v-model="form.add_intro" type="checkbox" />
          <span>Добавить Вступление до первой главы</span>
        </label>

        <button class="primary" @click="runInspect">Извлечь главы</button>
      </div>

      <div class="card control-card">
        <div class="card-head">
          <h2>2. Ассеты и видео</h2>
          <span class="badge green">Render</span>
        </div>

        <label>
          <span>Аудиокнига</span>
          <input v-model="form.audio" />
        </label>

        <label>
          <span>Обложка</span>
          <input v-model="form.cover" />
        </label>

        <label>
          <span>Фон, опционально</span>
          <input v-model="form.background" />
        </label>

        <label>
          <span>Шрифт TTF, опционально</span>
          <input v-model="form.font" />
        </label>

        <label>
          <span>Карта глав</span>
          <input v-model="form.chapters" />
        </label>

        <label>
          <span>Итоговый MP4</span>
          <input v-model="form.out" />
        </label>

        <div class="button-row">
          <button @click="runPreview">PNG preview</button>
          <button class="primary" @click="runRender">Собрать MP4</button>
        </div>
      </div>

      <div class="card visual-card">
        <div class="card-head">
          <h2>Визуализация озвучки</h2>
          <span class="badge violet">Voice</span>
        </div>

        <div class="player-mock">
          <div class="cover-mock">
            <div class="cover-glow"></div>
            <div class="cover-title">ЗИНА</div>
          </div>

          <div class="now">
            <div class="kicker">СЕЙЧАС ИГРАЕТ</div>
            <h3>{{ chapters[0]?.title || 'Глава будет здесь' }}</h3>
            <p>Панель для YouTube: обложка, текущая глава, оглавление, живая волна голоса.</p>

            <div class="wave">
              <span v-for="n in 42" :key="n" :style="{ '--i': n }"></span>
            </div>
          </div>
        </div>

        <p class="hint">
          Сейчас это UI-превью. Следующий патч добавит настоящий ffmpeg showwaves в итоговый MP4.
        </p>
      </div>

      <div class="card chapters-card">
        <div class="card-head">
          <h2>Оглавление</h2>
          <span class="badge">{{ chapterCount }} глав</span>
        </div>

        <div v-if="!chapters.length" class="empty">
          Пока нет карты глав. Нажми “Извлечь главы”.
        </div>

        <div v-else class="chapter-list">
          <div v-for="(ch, index) in chapters.slice(0, 14)" :key="index" class="chapter-row">
            <span class="chapter-num">{{ String(index + 1).padStart(2, '0') }}</span>
            <span class="chapter-title">{{ ch.title }}</span>
            <span class="chapter-time">{{ ch.start || prettySeconds(ch.start_seconds) }}</span>
          </div>

          <div v-if="chapters.length > 14" class="more">
            + ещё {{ chapters.length - 14 }}
          </div>
        </div>
      </div>

      <div class="card terminal-card">
        <div class="card-head">
          <h2>Журнал</h2>
          <span class="badge" :class="{ green: jobStatus === 'done', red: jobStatus === 'failed' }">
            {{ statusLabel }}
          </span>
        </div>

        <div v-if="lastError" class="error">{{ lastError }}</div>

        <pre class="terminal">{{ jobLog.length ? jobLog.join('\n') : 'Готов к работе. API должен быть запущен на 127.0.0.1:8787.' }}</pre>
      </div>

      <div class="card files-card">
        <div class="card-head">
          <h2>Сборочные файлы</h2>
          <span class="badge">{{ buildFiles.length }}</span>
        </div>

        <div v-if="!buildFiles.length" class="empty">Пока пусто.</div>

        <div v-else class="file-list">
          <div v-for="file in buildFiles.slice(0, 12)" :key="file.path" class="file-row">
            <span>{{ file.path }}</span>
            <small>{{ Math.round(file.size / 1024) }} KB</small>
          </div>
        </div>
      </div>
    </section>
  </main>
</template>
"""

STYLE_CSS = r"""
:root {
  color-scheme: dark;
  font-family:
    Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
    "Segoe UI", sans-serif;
  background: #05050b;
  color: #f6f0ff;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  min-width: 1100px;
  min-height: 100vh;
  background:
    radial-gradient(circle at 18% 8%, rgba(123, 80, 255, 0.3), transparent 28%),
    radial-gradient(circle at 82% 20%, rgba(0, 255, 185, 0.14), transparent 24%),
    linear-gradient(135deg, #05050b 0%, #111022 44%, #080813 100%);
}

button,
input,
select {
  font: inherit;
}

.shell {
  padding: 28px;
}

.hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 24px;
  padding: 26px 28px;
  border: 1px solid rgba(203, 180, 255, 0.16);
  border-radius: 28px;
  background:
    linear-gradient(135deg, rgba(24, 18, 46, 0.92), rgba(10, 12, 25, 0.82)),
    repeating-linear-gradient(45deg, rgba(255,255,255,0.03) 0 1px, transparent 1px 9px);
  box-shadow: 0 24px 90px rgba(0, 0, 0, 0.38);
}

.kicker {
  font-size: 12px;
  letter-spacing: 0.22em;
  text-transform: uppercase;
  color: #7fffe0;
}

h1 {
  margin: 4px 0 0;
  font-size: 48px;
  line-height: 1;
  letter-spacing: -0.04em;
}

h2 {
  margin: 0;
  font-size: 18px;
}

h3 {
  margin: 6px 0 8px;
  font-size: 27px;
  line-height: 1.05;
}

.subtitle {
  margin: 12px 0 0;
  color: #b8b0d7;
}

.api-pill {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 148px;
  padding: 12px 16px;
  border-radius: 999px;
  background: rgba(255,255,255,0.06);
  color: #f6e7ff;
  border: 1px solid rgba(255,255,255,0.12);
}

.api-pill .dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #ff456a;
  box-shadow: 0 0 18px #ff456a;
}

.api-pill.ok .dot {
  background: #63ffc8;
  box-shadow: 0 0 18px #63ffc8;
}

.grid {
  display: grid;
  grid-template-columns: 1.04fr 1.04fr 1.2fr;
  gap: 18px;
}

.card {
  border: 1px solid rgba(203, 180, 255, 0.13);
  border-radius: 24px;
  padding: 20px;
  background: rgba(12, 13, 27, 0.78);
  box-shadow: 0 18px 70px rgba(0,0,0,0.28);
  backdrop-filter: blur(18px);
}

.control-card {
  min-height: 440px;
}

.visual-card,
.chapters-card,
.terminal-card,
.files-card {
  min-height: 320px;
}

.terminal-card {
  grid-column: span 2;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 18px;
}

.badge {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 5px 10px;
  border-radius: 999px;
  background: rgba(174, 135, 255, 0.14);
  color: #d9c6ff;
  font-size: 12px;
  border: 1px solid rgba(174, 135, 255, 0.25);
}

.badge.green {
  background: rgba(68, 255, 190, 0.12);
  color: #7fffe0;
  border-color: rgba(68, 255, 190, 0.24);
}

.badge.violet {
  background: rgba(255, 67, 196, 0.12);
  color: #ffb8ed;
  border-color: rgba(255, 67, 196, 0.24);
}

.badge.red {
  background: rgba(255, 62, 103, 0.14);
  color: #ff9aad;
}

label {
  display: block;
  margin-bottom: 12px;
}

label span {
  display: block;
  margin-bottom: 6px;
  color: #a99fc6;
  font-size: 13px;
}

input,
select {
  width: 100%;
  height: 42px;
  padding: 0 13px;
  border: 1px solid rgba(212, 191, 255, 0.15);
  border-radius: 13px;
  outline: none;
  color: #fff;
  background: rgba(5, 6, 13, 0.7);
}

input:focus,
select:focus {
  border-color: rgba(127, 255, 224, 0.55);
  box-shadow: 0 0 0 3px rgba(127, 255, 224, 0.08);
}

.two {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.check {
  display: flex;
  align-items: center;
  gap: 10px;
}

.check input {
  width: 18px;
  height: 18px;
}

.check span {
  margin: 0;
}

.button-row {
  display: flex;
  gap: 10px;
  margin-top: 16px;
}

button {
  min-height: 44px;
  padding: 0 17px;
  border: 1px solid rgba(255,255,255,0.12);
  border-radius: 14px;
  color: #f7f2ff;
  background: rgba(255,255,255,0.08);
  cursor: pointer;
  transition: transform 0.16s ease, border-color 0.16s ease, background 0.16s ease;
}

button:hover {
  transform: translateY(-1px);
  background: rgba(255,255,255,0.12);
  border-color: rgba(127, 255, 224, 0.35);
}

button.primary {
  background: linear-gradient(135deg, #7b50ff, #1ed6b1);
  border: 0;
  font-weight: 700;
}

.player-mock {
  display: grid;
  grid-template-columns: 170px 1fr;
  gap: 18px;
  align-items: stretch;
}

.cover-mock {
  position: relative;
  min-height: 238px;
  border-radius: 22px;
  overflow: hidden;
  background:
    radial-gradient(circle at 40% 18%, rgba(255,255,255,0.14), transparent 32%),
    linear-gradient(145deg, #180a30, #34103a 48%, #0d1627);
  border: 1px solid rgba(255,255,255,0.12);
  display: flex;
  align-items: end;
  justify-content: center;
  padding: 20px;
}

.cover-glow {
  position: absolute;
  inset: 16px;
  border-radius: 18px;
  background: linear-gradient(135deg, rgba(127,255,224,0.15), rgba(255,67,196,0.16));
  filter: blur(16px);
}

.cover-title {
  position: relative;
  font-size: 34px;
  font-weight: 900;
  letter-spacing: 0.09em;
}

.now {
  padding: 16px;
  border-radius: 22px;
  background: rgba(255,255,255,0.045);
  border: 1px solid rgba(255,255,255,0.08);
}

.now p,
.hint {
  color: #b8b0d7;
}

.wave {
  display: flex;
  align-items: center;
  gap: 5px;
  height: 86px;
  margin-top: 18px;
  padding: 0 10px;
  border-radius: 18px;
  background: linear-gradient(180deg, rgba(127,255,224,0.1), rgba(123,80,255,0.08));
  overflow: hidden;
}

.wave span {
  width: 5px;
  height: calc(16px + (var(--i) % 11) * 5px);
  border-radius: 999px;
  background: linear-gradient(180deg, #7fffe0, #c4a7ff);
  animation: wave 1.08s ease-in-out infinite;
  animation-delay: calc(var(--i) * -0.045s);
  box-shadow: 0 0 14px rgba(127,255,224,0.45);
}

@keyframes wave {
  0%, 100% {
    transform: scaleY(0.45);
    opacity: 0.62;
  }
  50% {
    transform: scaleY(1.28);
    opacity: 1;
  }
}

.chapter-list,
.file-list {
  display: grid;
  gap: 8px;
}

.chapter-row,
.file-row {
  display: grid;
  grid-template-columns: 44px 1fr 88px;
  gap: 10px;
  align-items: center;
  min-height: 36px;
  padding: 8px 10px;
  border-radius: 12px;
  background: rgba(255,255,255,0.045);
  color: #e8e0ff;
}

.file-row {
  grid-template-columns: 1fr 70px;
}

.chapter-num,
.chapter-time,
.file-row small {
  color: #8eeed8;
  font-size: 12px;
}

.chapter-title {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.more,
.empty {
  padding: 14px;
  border-radius: 14px;
  background: rgba(255,255,255,0.04);
  color: #a99fc6;
}

.terminal {
  min-height: 250px;
  max-height: 430px;
  overflow: auto;
  margin: 0;
  padding: 16px;
  border-radius: 18px;
  background: #05060d;
  color: #82f7d8;
  border: 1px solid rgba(127,255,224,0.12);
  white-space: pre-wrap;
  font-size: 13px;
  line-height: 1.5;
}

.error {
  margin-bottom: 10px;
  padding: 12px;
  border-radius: 14px;
  background: rgba(255, 62, 103, 0.12);
  color: #ff9aad;
  border: 1px solid rgba(255, 62, 103, 0.22);
}
"""

def print_header(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def print_ok(text: str) -> None:
    print(f"[OK] {text}")


def print_warn(text: str) -> None:
    print(f"[WARN] {text}")


def normalize_cmd(cmd: list[str | Path]) -> list[str | Path]:
    if os.name == "nt" and cmd:
        first = str(cmd[0])
        found = None

        if Path(first).exists():
            found = first
        else:
            found = shutil.which(first)

        if found:
            found_path = Path(found)

            # Windows/npm case: shutil.which may return "npm" without .cmd.
            if found_path.suffix == "":
                cmd_candidate = Path(str(found_path) + ".cmd")
                bat_candidate = Path(str(found_path) + ".bat")
                if cmd_candidate.exists():
                    found_path = cmd_candidate
                elif bat_candidate.exists():
                    found_path = bat_candidate

            suffix = found_path.suffix.lower()
            if suffix in (".cmd", ".bat"):
                comspec = os.environ.get("ComSpec", "C:\\Windows\\System32\\cmd.exe")
                return [Path(comspec), "/c", found_path, *cmd[1:]]

            return [found_path, *cmd[1:]]

    return cmd


def run(cmd: list[str | Path], cwd: Path = ROOT, check: bool = True) -> subprocess.CompletedProcess:
    cmd = normalize_cmd(cmd)
    print()
    print("[run] " + " ".join(f'"{str(x)}"' if " " in str(x) else str(x) for x in cmd))
    return subprocess.run([str(x) for x in cmd], cwd=str(cwd), check=check)


def run_capture(cmd: list[str | Path], cwd: Path = ROOT) -> subprocess.CompletedProcess:
    cmd = normalize_cmd(cmd)
    return subprocess.run(
        [str(x) for x in cmd],
        cwd=str(cwd),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def write_file(path: Path, content: str, force: bool = False) -> None:
    if path.exists() and not force:
        print_warn(f"Exists, not overwritten: {path.relative_to(ROOT)}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8", newline="\n")
    print_ok(f"Wrote {path.relative_to(ROOT)}")


def append_unique(path: Path, lines: list[str]) -> None:
    current = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    current_lines = set(x.strip() for x in current.splitlines())
    add = [x for x in lines if x.strip() and x.strip() not in current_lines]
    if not add:
        print_ok(f"{path.name} already ok")
        return
    with path.open("a", encoding="utf-8", newline="\n") as f:
        if current and not current.endswith("\n"):
            f.write("\n")
        for line in add:
            f.write(line + "\n")
    print_ok(f"Updated {path.name}")


def check_base() -> None:
    print_header("1. Base check")

    if not MAIN_SCRIPT.exists():
        raise SystemExit(f"suviren_q.py not found: {MAIN_SCRIPT}")

    print_ok("Found suviren_q.py")

    if not VENV_PY.exists():
        raise SystemExit(
            ".venv not found. Run first installer before UI installer:\n"
            "python install_suviren_q.py"
        )

    print_ok(f"Found venv Python: {VENV_PY}")


def install_python_deps() -> None:
    print_header("2. Python API deps")

    append_unique(REQ_FILE, PY_DEPS)
    run([VENV_PY, "-m", "pip", "install", *PY_DEPS])
    print_ok("FastAPI backend deps ready")


def check_node() -> bool:
    print_header("3. Node / npm check")

    node = shutil.which("node")
    npm = shutil.which("npm")

    if not node or not npm:
        print_warn("Node.js/npm not found in PATH.")
        print("Install Node.js LTS, restart terminal, then run this installer again.")
        return False

    node_v = run_capture(["node", "--version"])
    npm_v = run_capture(["npm", "--version"])

    print_ok(f"node: {node_v.stdout.strip()}")
    print_ok(f"npm: {npm_v.stdout.strip()}")
    return True


def write_backend_and_ui(force: bool) -> None:
    print_header("4. Writing backend and Vue UI")

    write_file(SERVER_SCRIPT, SERVER_PY, force=force)
    write_file(UI_DIR / "package.json", NPM_PACKAGE_JSON, force=force)
    write_file(UI_DIR / "index.html", INDEX_HTML, force=force)
    write_file(UI_DIR / "vite.config.js", VITE_CONFIG, force=force)
    write_file(SRC_DIR / "main.js", MAIN_JS, force=force)
    write_file(SRC_DIR / "App.vue", APP_VUE, force=force)
    write_file(SRC_DIR / "style.css", STYLE_CSS, force=force)


def install_npm(skip_npm: bool, node_ok: bool) -> None:
    print_header("5. NPM install")

    if skip_npm:
        print_warn("Skipped npm install because --skip-npm was used.")
        return

    if not node_ok:
        print_warn("Skipped npm install because Node/npm are unavailable.")
        return

    run(["npm", "install"], cwd=UI_DIR)
    print_ok("Vue dependencies installed")


def write_helpers(force: bool) -> None:
    print_header("6. Helper launchers")

    LOCAL_DIR.mkdir(parents=True, exist_ok=True)

    api_bat = r"""
@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo Starting suviren-q API at http://127.0.0.1:8787
.\.venv\Scripts\python.exe suviren_q_server.py
pause
"""

    vue_bat = r"""
@echo off
chcp 65001 >nul
cd /d "%~dp0..\ui"
echo Starting suviren-q Vue UI at http://127.0.0.1:5178
npm run dev
pause
"""

    all_bat = r"""
@echo off
chcp 65001 >nul
cd /d "%~dp0.."
start "suviren-q API" "%~dp0sq_start_api.bat"
timeout /t 2 /nobreak >nul
start "suviren-q Vue" "%~dp0sq_start_vue.bat"
echo Open UI:
echo http://127.0.0.1:5178
pause
"""

    write_file(LOCAL_DIR / "sq_start_api.bat", api_bat, force=force)
    write_file(LOCAL_DIR / "sq_start_vue.bat", vue_bat, force=force)
    write_file(LOCAL_DIR / "sq_start_ui.bat", all_bat, force=force)


def update_gitignore() -> None:
    print_header("7. .gitignore")

    append_unique(GITIGNORE_FILE, [
        "node_modules/",
        "ui/node_modules/",
        "ui/dist/",
        ".env",
        ".env.local",
    ])


def smoke_test() -> None:
    print_header("8. Smoke test")

    proc = run_capture([VENV_PY, "-m", "py_compile", SERVER_SCRIPT])
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr)
        raise SystemExit("suviren_q_server.py syntax check failed")

    print_ok("suviren_q_server.py syntax ok")

    if (UI_DIR / "package.json").exists():
        print_ok("ui/package.json exists")


def next_steps() -> None:
    print_header("NEXT STEPS")

    print("Start API:")
    print(r"  .\_suviren_q_local\sq_start_api.bat")
    print()
    print("Start Vue UI:")
    print(r"  .\_suviren_q_local\sq_start_vue.bat")
    print()
    print("Or start both:")
    print(r"  .\_suviren_q_local\sq_start_ui.bat")
    print()
    print("Open:")
    print("  http://127.0.0.1:5178")
    print()
    print("Then press in UI:")
    print("  1. Извлечь главы")
    print("  2. PNG preview")
    print("  3. Собрать MP4")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Overwrite generated UI/backend files.")
    parser.add_argument("--skip-npm", action="store_true", help="Do not run npm install.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    print_header("suviren-q UI installer")
    print(f"Root: {ROOT}")

    check_base()
    install_python_deps()
    node_ok = check_node()
    write_backend_and_ui(force=args.force)
    install_npm(skip_npm=args.skip_npm, node_ok=node_ok)
    write_helpers(force=args.force)
    update_gitignore()
    smoke_test()
    next_steps()

    print()
    print_ok("UI installer finished.")


if __name__ == "__main__":
    main()