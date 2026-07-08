<script setup>
// suviren-q v2 — минималистичный мастер 3 шага
import { ref, reactive, computed, watch, onMounted } from 'vue'

const API = 'http://127.0.0.1:8787'

const step = ref(1) // 1=inspect, 2=preview, 3=render

// ── Files ────────────────────────────────────────────────────────
const rppPath = ref('зина книга вступление.rpp')
const audioPath = ref('book.mp3')
const coverPath = ref('cover.png')
const backgroundPath = ref('')
const outPath = ref('suviren_q_output.mp4')
const addIntro = ref(true)
const origin = ref('project')
const rppTrack = ref('КНИГА ОЗВУЧКА')
const chapterPattern = ref('Глава')

// ── State ───────────────────────────────────────────────────────-
const chapters = ref([])
const jobId = ref('')
const jobLog = ref([])
const jobStatus = ref('idle')
const jobProgress = ref(0)
const serverOk = ref(false)
const errorMsg = ref('')

// ── Defaults ────────────────────────────────────────────────────-
onMounted(async () => {
  try {
    const res = await fetch(`${API}/api/health`)
    const data = await res.json()
    serverOk.value = data.ok
    if (serverOk.value) {
      const def = await fetch(`${API}/api/defaults`).then(r => r.json())
      if (def.rpp) rppPath.value = def.rpp
      if (def.cover) coverPath.value = def.cover
      if (def.audio) audioPath.value = def.audio
      if (def.out) outPath.value = def.out
    }
  } catch {
    serverOk.value = false
    errorMsg.value = 'API server not running. Start with: python suviren_q_server.py'
  }
})

// ── Step 1: Inspect ─────────────────────────────────────────────
const inspecting = ref(false)

async function doInspect() {
  inspecting.value = true
  errorMsg.value = ''
  try {
    const res = await fetch(`${API}/api/inspect-rpp`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        rpp: rppPath.value,
        audio: audioPath.value,
        rpp_track: rppTrack.value,
        chapter_pattern: chapterPattern.value,
        add_intro: addIntro.value,
        origin: origin.value,
      }),
    })
    const data = await res.json()
    if (data.job_id) {
      jobId.value = data.job_id
      await pollJob()
    }
  } catch (e) {
    errorMsg.value = `Inspect failed: ${e}`
  }
  inspecting.value = false
}

async function pollJob() {
  while (true) {
    try {
      const res = await fetch(`${API}/api/jobs/${jobId.value}`)
      const data = await res.json()
      jobLog.value = data.log?.slice(-30) || []
      jobStatus.value = data.status
      jobProgress.value = data.progress || 0
      if (data.status === 'done') {
        // Load chapters
        const chRes = await fetch(`${API}/api/chapters`)
        const chData = await chRes.json()
        if (chData.exists) {
          chapters.value = chData.chapters
          step.value = 2
        }
        return
      }
      if (data.status === 'failed') {
        errorMsg.value = `Inspect failed (exit ${data.returncode})`
        return
      }
    } catch { /* retry */ }
    await new Promise(r => setTimeout(r, 1000))
  }
}

// ── Step 2: Preview & Chapters ─────────────────────────────────
const chapterStatus = computed(() => {
  return chapters.value.length ? `${chapters.value.length} chapters detected` : 'No chapters'
})

// ── Step 3: Render ─────────────────────────────────────────────-
const rendering = ref(false)

async function doRender() {
  rendering.value = true
  errorMsg.value = ''
  jobProgress.value = 0
  try {
    const res = await fetch(`${API}/api/render`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        audio: audioPath.value,
        cover: coverPath.value,
        background: backgroundPath.value || undefined,
        chapters: '_suviren_q_build/chapters.detected.json',
        out: outPath.value,
        rpp_track: rppTrack.value,
        chapter_pattern: chapterPattern.value,
        add_intro: addIntro.value,
        origin: origin.value,
        waveform: 'ffmpeg',
      }),
    })
    const data = await res.json()
    if (data.job_id) {
      jobId.value = data.job_id
      await pollRenderJob()
    }
  } catch (e) {
    errorMsg.value = `Render failed: ${e}`
  }
  rendering.value = false
}

async function pollRenderJob() {
  while (true) {
    try {
      const res = await fetch(`${API}/api/jobs/${jobId.value}`)
      const data = await res.json()
      jobLog.value = data.log?.slice(-30) || []
      jobStatus.value = data.status
      jobProgress.value = data.progress || 0
      if (data.status === 'done' || data.status === 'failed') {
        return
      }
    } catch { /* retry */ }
    await new Promise(r => setTimeout(r, 1000))
  }
}

// ── Format timecode ────────────────────────────────────────────-
function fmtTime(sec) {
  if (sec == null) return ''
  sec = Math.max(0, sec)
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = Math.floor(sec % 60)
  return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
}
</script>

<template>
  <div class="app">
    <header class="header">
      <h1 class="logo">suviren-q</h1>
      <span v-if="serverOk" class="badge badge-ok">API connected</span>
      <span v-else class="badge badge-err">API offline</span>
    </header>

    <!-- Step indicator -->
    <div class="steps">
      <div :class="['step', { active: step >= 1, done: step > 1 }]" @click="step = 1">1. Inspect RPP</div>
      <div :class="['step', { active: step >= 2, done: step > 2 }]" @click="step >= 2 && (step = 2)">2. Preview</div>
      <div :class="['step', { active: step >= 3, done: step > 3 }]" @click="step >= 3 && (step = 3)">3. Render</div>
    </div>

    <!-- Step 1: Inspect -->
    <div v-if="step === 1" class="panel">
      <div class="form">
        <label>RPP file <input v-model="rppPath" placeholder="project.rpp" /></label>
        <label>Audio file <input v-model="audioPath" placeholder="book.mp3" /></label>
        <label>Cover image <input v-model="coverPath" placeholder="cover.png" /></label>
        <label>Background (optional) <input v-model="backgroundPath" placeholder="bg.png" /></label>
        <label>Output MP4 <input v-model="outPath" placeholder="output.mp4" /></label>
        <label>RPP Track <input v-model="rppTrack" /></label>
        <label>Chapter pattern <input v-model="chapterPattern" /></label>
        <label class="checkbox-label">
          <input v-model="addIntro" type="checkbox" /> Add intro chapter
        </label>
      </div>
      <button class="btn" :disabled="inspecting" @click="doInspect">
        {{ inspecting ? 'Inspecting…' : '🔍 Inspect RPP' }}
      </button>
      <div v-if="inspecting" class="log-box">
        <div v-for="line in jobLog" :key="line">{{ line }}</div>
      </div>
    </div>

    <!-- Step 2: Preview -->
    <div v-if="step === 2" class="panel">
      <div class="status-line">{{ chapterStatus }}</div>
      <div class="chapter-list" v-if="chapters.length">
        <div class="ch-row ch-header">
          <span>#</span><span>Title</span><span>Start</span><span>End</span><span>Duration</span>
        </div>
        <div v-for="(ch, i) in chapters" :key="i" class="ch-row">
          <span>{{ i + 1 }}</span>
          <span class="ch-title">{{ ch.title }}</span>
          <span>{{ fmtTime(ch.start_seconds) }}</span>
          <span>{{ fmtTime(ch.end_seconds) }}</span>
          <span>{{ fmtTime(ch.duration_seconds) }}</span>
        </div>
      </div>
      <div class="btn-row">
        <button class="btn" @click="step = 1">← Back</button>
        <button class="btn btn-primary" @click="step = 3">Render →</button>
      </div>
    </div>

    <!-- Step 3: Render -->
    <div v-if="step === 3" class="panel">
      <div class="status-line">Ready to render {{ chapters.length }} chapters</div>

      <div class="progress-bar" v-if="rendering">
        <div class="progress-fill" :style="{ width: (jobProgress * 100) + '%' }"></div>
      </div>

      <div v-if="jobStatus === 'done'" class="done-box">
        ✅ Render complete! Output: {{ outPath }}
      </div>

      <div class="btn-row">
        <button class="btn" @click="step = 2">← Back</button>
        <button class="btn btn-primary" :disabled="rendering" @click="doRender">
          {{ rendering ? 'Rendering…' : '🎬 Render Video' }}
        </button>
      </div>

      <div v-if="rendering || jobStatus === 'done' || jobStatus === 'failed'" class="log-box">
        <div v-for="line in jobLog" :key="line">{{ line }}</div>
      </div>
    </div>

    <!-- Error -->
    <div v-if="errorMsg" class="error">{{ errorMsg }}</div>
  </div>
</template>

<style>
/* ── Reset & Base ────────────────────────────────────────────────── */
*,
*::before,
*::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

:root {
  --bg: #0d0d14;
  --surface: #161622;
  --surface2: #1e1e32;
  --border: #2a2a44;
  --text: #c8c8e0;
  --text-dim: #808098;
  --accent: #8c52ff;
  --accent2: #6a2be0;
  --green: #3dd68c;
  --red: #e05555;
  --radius: 8px;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  display: flex;
  justify-content: center;
}

.app {
  width: 100%;
  max-width: 720px;
  padding: 20px;
}

/* ── Header ──────────────────────────────────────────────────────── */
.header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 24px;
}

.logo {
  font-size: 22px;
  font-weight: 700;
  letter-spacing: -0.5px;
  background: linear-gradient(135deg, var(--accent), var(--accent2));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.badge {
  font-size: 11px;
  padding: 2px 10px;
  border-radius: 999px;
  text-transform: uppercase;
  font-weight: 600;
  letter-spacing: 0.5px;
}
.badge-ok { background: #1a3a2a; color: var(--green); }
.badge-err { background: #3a1a1a; color: var(--red); }

/* ── Steps ────────────────────────────────────────────────────────── */
.steps {
  display: flex;
  gap: 0;
  margin-bottom: 20px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}
.step {
  flex: 1;
  text-align: center;
  padding: 10px 8px;
  cursor: default;
  font-size: 13px;
  font-weight: 500;
  background: var(--surface);
  color: var(--text-dim);
  border-right: 1px solid var(--border);
  transition: background 0.15s, color 0.15s;
}
.step:last-child { border-right: none; }
.step.active {
  background: var(--surface2);
  color: var(--accent);
}
.step.done {
  background: #1a2a2a;
  color: var(--green);
  cursor: pointer;
}
.step.done:hover {
  background: #1e3232;
}

/* ── Panel ────────────────────────────────────────────────────────── */
.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
}

.form {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 16px;
}
.form label {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 12px;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.form input {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 10px;
  color: var(--text);
  font-size: 14px;
  outline: none;
  transition: border 0.15s;
}
.form input:focus {
  border-color: var(--accent);
}
.checkbox-label {
  flex-direction: row !important;
  align-items: center;
  gap: 8px !important;
  font-size: 13px !important;
  text-transform: none !important;
  color: var(--text) !important;
}

/* ── Buttons ──────────────────────────────────────────────────────── */
.btn {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text);
  padding: 10px 18px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}
.btn:hover:not(:disabled) {
  background: #2a2a4a;
  border-color: var(--accent);
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.btn-primary {
  background: linear-gradient(135deg, var(--accent), var(--accent2));
  border-color: transparent;
  color: #fff;
}
.btn-primary:hover:not(:disabled) {
  filter: brightness(1.1);
}
.btn-row {
  display: flex;
  gap: 10px;
  margin-top: 16px;
}

/* ── Status ───────────────────────────────────────────────────────── */
.status-line {
  font-size: 13px;
  color: var(--text-dim);
  margin-bottom: 12px;
}
.done-box {
  background: #1a3a2a;
  border: 1px solid var(--green);
  border-radius: var(--radius);
  padding: 12px 16px;
  color: var(--green);
  font-weight: 500;
  margin-top: 12px;
}

/* ── Chapter List ─────────────────────────────────────────────────── */
.chapter-list {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}
.ch-row {
  display: grid;
  grid-template-columns: 36px 1fr 72px 72px 72px;
  padding: 6px 10px;
  font-size: 12px;
  border-bottom: 1px solid var(--border);
  align-items: center;
}
.ch-row:last-child { border-bottom: none; }
.ch-header {
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-size: 10px;
  background: var(--surface2);
}
.ch-title {
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ── Progress ─────────────────────────────────────────────────────── */
.progress-bar {
  background: var(--bg);
  border-radius: 999px;
  height: 6px;
  overflow: hidden;
  margin: 12px 0;
}
.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--accent), var(--green));
  transition: width 0.5s;
  border-radius: 999px;
}

/* ── Log ──────────────────────────────────────────────────────────── */
.log-box {
  background: var(--bg);
  border-radius: var(--radius);
  padding: 12px 14px;
  margin-top: 12px;
  max-height: 200px;
  overflow-y: auto;
  font-family: 'Fira Code', 'Cascadia Code', monospace;
  font-size: 11px;
  line-height: 1.6;
  color: var(--text-dim);
}
.log-box div:first-child { color: var(--text); }

/* ── Error ────────────────────────────────────────────────────────── */
.error {
  background: #3a1a1a;
  border: 1px solid var(--red);
  border-radius: var(--radius);
  padding: 12px 16px;
  color: var(--red);
  margin-top: 12px;
  font-size: 13px;
}
</style>