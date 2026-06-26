
<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'

const apiOk = ref(false)
const jobLog = ref([])
const jobStatus = ref('idle')
const chapters = ref([])
const buildFiles = ref([])
const lastError = ref('')
const selectedObjectId = ref('nowPlaying')
const selectedChapterIndex = ref(0)
const logOpen = ref(false)
const advancedOpen = ref(false)
const coverPreviewUrl = ref('')
const backgroundPreviewUrl = ref('')
const audioPreviewUrl = ref('')
const layoutStatus = ref('layout not saved')
const audioEl = ref(null)
const isPlaying = ref(false)
const currentTime = ref(0)
const audioDuration = ref(0)
const playerStatus = ref('audio not loaded')

const form = reactive({
  rpp: '\u0437\u0438\u043d\u0430 \u043a\u043d\u0438\u0433\u0430 \u0432\u0441\u0442\u0443\u043f\u043b\u0435\u043d\u0438\u0435.rpp',
  rpp_track: '\u041a\u041d\u0418\u0413\u0410 \u041e\u0417\u0412\u0423\u0427\u041a\u0410',
  chapter_pattern: '\u0413\u043b\u0430\u0432\u0430',
  add_intro: true,
  origin: 'project',
  offset: 0,
  audio: 'book.mp3',
  cover: 'cover.png',
  background: '',
  chapters: '_suviren_q_build/chapters.detected.json',
  out: 'intimny_protokol_video.mp4',
  font: '',
  theme: 'cyber-zina',
  waveform: 'ffmpeg'
})

const scene = reactive({
  width: 1920,
  height: 1080,
  zoom: 0.55
})

const objects = reactive([
  {
    id: 'background',
    label: 'Background',
    type: 'background',
    visible: true,
    locked: true,
    x: 0,
    y: 0,
    w: 1,
    h: 1,
    zIndex: 0,
    opacity: 1
  },
  {
    id: 'cover',
    label: 'Cover',
    type: 'image',
    visible: true,
    locked: false,
    x: 0.08,
    y: 0.24,
    w: 0.28,
    h: 0.50,
    zIndex: 20,
    source: 'cover.png',
    radius: 0.04,
    opacity: 1
  },
  {
    id: 'bookTitle',
    label: 'Book title',
    type: 'text',
    visible: true,
    locked: false,
    x: 0.43,
    y: 0.18,
    w: 0.46,
    h: 0.09,
    zIndex: 30,
    text: 'Intimate Protocol',
    fontSize: 28,
    opacity: 0.78
  },
  {
    id: 'nowPlaying',
    label: 'Now playing',
    type: 'text',
    visible: true,
    locked: false,
    x: 0.43,
    y: 0.245,
    w: 0.47,
    h: 0.18,
    zIndex: 40,
    text: '{{chapter.title}}',
    fontSize: 42,
    opacity: 1
  },
  {
    id: 'chapterList',
    label: 'Chapter list',
    type: 'chapterList',
    visible: true,
    locked: false,
    x: 0.43,
    y: 0.535,
    w: 0.46,
    h: 0.22,
    zIndex: 45,
    visibleCount: 5,
    opacity: 1
  },
  {
    id: 'waveform',
    label: 'Waveform',
    type: 'waveform',
    visible: true,
    locked: false,
    x: 0.43,
    y: 0.80,
    w: 0.47,
    h: 0.075,
    zIndex: 50,
    opacity: 0.82
  },
  {
    id: 'progress',
    label: 'Progress',
    type: 'progress',
    visible: true,
    locked: false,
    x: 0.08,
    y: 0.91,
    w: 0.82,
    h: 0.018,
    zIndex: 60,
    opacity: 0.9
  }
])

const statusLabel = computed(() => {
  if (jobStatus.value === 'running') return 'Running'
  if (jobStatus.value === 'done') return 'Done'
  if (jobStatus.value === 'failed') return 'Failed'
  return 'Idle'
})

const selectedObject = computed(() => {
  return objects.find(item => item.id === selectedObjectId.value) || objects[0]
})

const objectWarning = computed(() => {
  const obj = selectedObject.value
  if (!obj) return ''
  if (obj.x < 0 || obj.y < 0 || obj.x + obj.w > 1 || obj.y + obj.h > 1) {
    return 'Object is outside stage bounds'
  }
  if (obj.w < 0.03 || obj.h < 0.03) {
    return 'Object is too small'
  }
  return ''
})

const selectedChapter = computed(() => {
  return chapters.value[selectedChapterIndex.value] || null
})

const totalStart = computed(() => {
  if (!chapters.value.length) return 0
  return getStartSeconds(chapters.value[0])
})

const totalEnd = computed(() => {
  if (!chapters.value.length) return 1
  return Math.max(...chapters.value.map(ch => getEndSeconds(ch)))
})

const totalDuration = computed(() => Math.max(1, totalEnd.value - totalStart.value))

const timelineSegments = computed(() => {
  return chapters.value.map((ch, index) => {
    const duration = Math.max(1, getEndSeconds(ch) - getStartSeconds(ch))
    return {
      chapter: ch,
      index,
      duration,
      width: Math.max(2, duration / totalDuration.value * 100)
    }
  })
})

const visibleChapters = computed(() => {
  if (!chapters.value.length) return []
  const count = Number(getObject('chapterList')?.visibleCount || 6)
  const half = Math.floor(count / 2)
  const start = Math.max(0, selectedChapterIndex.value - half)
  const end = Math.min(chapters.value.length, start + count)
  return chapters.value.slice(start, end).map((chapter, localIndex) => ({
    chapter,
    index: start + localIndex
  }))
})

const currentChapterProgress = computed(() => {
  const ch = selectedChapter.value
  if (!ch) return 0.08
  const dur = Math.max(1, getEndSeconds(ch) - getStartSeconds(ch))
  if (audioPreviewUrl.value && currentTime.value > 0) {
    const local = Math.max(0, Math.min(dur, currentTime.value - getStartSeconds(ch)))
    return Math.min(1, Math.max(0.02, local / dur))
  }
  return Math.min(1, Math.max(0.06, 30 / dur))
})

const playbackPercent = computed(() => {
  const t = Math.max(0, currentTime.value - totalStart.value)
  return Math.max(0, Math.min(100, (t / totalDuration.value) * 100))
})

const playerClock = computed(() => {
  return `${formatClock(currentTime.value)} / ${formatClock(audioDuration.value || totalDuration.value)}`
})

function getObject(id) {
  return objects.find(item => item.id === id)
}

function selectObject(id) {
  selectedObjectId.value = id
}

function toggleVisible(obj) {
  obj.visible = !obj.visible
}

function toggleLocked(obj) {
  obj.locked = !obj.locked
}

function parseTimeToSeconds(value) {
  if (value === undefined || value === null || value === '') return 0
  if (typeof value === 'number') return value

  const text = String(value).trim().replace(',', '.')
  if (!text) return 0

  const parts = text.split(':').map(x => x.trim())
  if (parts.length === 3) return Number(parts[0]) * 3600 + Number(parts[1]) * 60 + Number(parts[2])
  if (parts.length === 2) return Number(parts[0]) * 60 + Number(parts[1])

  const n = Number(text)
  return Number.isFinite(n) ? n : 0
}

function getStartSeconds(ch) {
  if (!ch) return 0
  if (ch.start_seconds !== undefined && ch.start_seconds !== null) return Number(ch.start_seconds)
  return parseTimeToSeconds(ch.start)
}

function getEndSeconds(ch) {
  if (!ch) return 0
  if (ch.end_seconds !== undefined && ch.end_seconds !== null) return Number(ch.end_seconds)
  return parseTimeToSeconds(ch.end)
}

function formatClock(value, withMs = false) {
  const n = Math.max(0, Number(value) || 0)
  const h = Math.floor(n / 3600)
  const m = Math.floor((n % 3600) / 60)
  const s = Math.floor(n % 60)
  const base = [h, m, s].map(x => String(x).padStart(2, '0')).join(':')
  if (!withMs) return base
  const ms = Math.round((n - Math.floor(n)) * 1000)
  return `${base}.${String(ms).padStart(3, '0')}`
}

function shortTitle(title) {
  return String(title || '').replace(/^0+\d+\s*-\s*/i, '').replace(/\.mp3$/i, '')
}

function objectStyle(obj) {
  return {
    left: `${obj.x * 100}%`,
    top: `${obj.y * 100}%`,
    width: `${obj.w * 100}%`,
    height: `${obj.h * 100}%`,
    zIndex: obj.zIndex,
    opacity: obj.visible ? obj.opacity : 0,
    pointerEvents: obj.visible ? 'auto' : 'none'
  }
}

function backgroundObjectStyle(obj) {
  const base = objectStyle(obj)
  if (!backgroundPreviewUrl.value) return base

  return {
    ...base,
    backgroundImage: `linear-gradient(135deg, rgba(8, 8, 18, 0.24), rgba(8, 15, 28, 0.34)), url("${backgroundPreviewUrl.value}")`,
    backgroundSize: 'cover',
    backgroundPosition: 'center'
  }
}

function pickAsset(kind, event) {
  const file = event?.target?.files?.[0]
  if (!file) return

  const url = URL.createObjectURL(file)

  if (kind === 'cover') {
    if (coverPreviewUrl.value) URL.revokeObjectURL(coverPreviewUrl.value)
    coverPreviewUrl.value = url
    form.cover = file.name
    const cover = getObject('cover')
    if (cover) cover.source = file.name
  }

  if (kind === 'background') {
    if (backgroundPreviewUrl.value) URL.revokeObjectURL(backgroundPreviewUrl.value)
    backgroundPreviewUrl.value = url
    form.background = file.name
  }

  if (kind === 'audio') {
    if (audioPreviewUrl.value) URL.revokeObjectURL(audioPreviewUrl.value)
    audioPreviewUrl.value = url
    form.audio = file.name
    currentTime.value = 0
    audioDuration.value = 0
    isPlaying.value = false
    playerStatus.value = 'audio loaded'
  }
}

function clonePlain(value) {
  return JSON.parse(JSON.stringify(value))
}

function buildLayoutPayload() {
  return {
    version: 1,
    savedAt: new Date().toISOString(),
    scene: clonePlain(scene),
    objects: clonePlain(objects),
    assets: {
      cover: form.cover,
      background: form.background,
      audio: form.audio,
      chapters: form.chapters
    },
    render: {
      out: form.out,
      waveform: form.waveform,
      theme: form.theme
    }
  }
}

function applyLayout(layout) {
  if (!layout) return

  if (layout.scene) {
    Object.assign(scene, layout.scene)
  }

  if (Array.isArray(layout.objects) && layout.objects.length > 0) {
    objects.splice(0, objects.length, ...layout.objects)
  } else if (Array.isArray(layout.objects) && layout.objects.length === 0) {
    layoutStatus.value = 'ignored empty layout objects'
  }

  if (layout.assets) {
    form.cover = layout.assets.cover ?? form.cover
    form.background = layout.assets.background ?? form.background
    form.audio = layout.assets.audio ?? form.audio
    form.chapters = layout.assets.chapters ?? form.chapters
  }

  if (layout.render) {
    form.out = layout.render.out ?? form.out
    form.waveform = layout.render.waveform ?? form.waveform
    form.theme = layout.render.theme ?? form.theme
  }

  if (!objects.find(item => item.id === selectedObjectId.value)) {
    selectedObjectId.value = objects[0]?.id || ''
  }
}

async function loadLayout(options = {}) {
  const silent = Boolean(options.silent)
  try {
    const data = await apiGet('/api/layout')
    if (data.exists && data.layout) {
      applyLayout(data.layout)
      layoutStatus.value = 'layout.json loaded'
    } else {
      layoutStatus.value = 'no layout.json yet'
    }
  } catch (err) {
    layoutStatus.value = 'layout load failed'
    if (!silent) lastError.value = String(err)
  }
}

async function saveLayout() {
  try {
    const data = await apiPost('/api/layout', buildLayoutPayload())
    layoutStatus.value = data.ok ? 'layout.json saved' : 'layout save failed'
    await loadBuildFiles()
  } catch (err) {
    layoutStatus.value = 'layout save failed'
    lastError.value = String(err)
  }
}

function renderTextObject(obj) {
  if (obj.text === '{{chapter.title}}') {
    return selectedChapter.value ? shortTitle(selectedChapter.value.title) : 'Select chapter'
  }
  return obj.text
}

function titleFitClass(obj) {
  if (!obj || obj.id !== 'nowPlaying') return ''
  const len = renderTextObject(obj).length
  if (len > 58) return 'title-long'
  if (len > 34) return 'title-medium'
  return 'title-short'
}

function textObjectStyle(obj) {
  const baseSize = Number(obj.fontSize || 24)
  const base = {
    ...objectStyle(obj),
    fontSize: baseSize + 'px',
    '--text-fit-size': baseSize + 'px',
    '--text-lines': '2'
  }

  if (!obj || obj.type !== 'text' || obj.id !== 'nowPlaying') {
    return base
  }

  const len = renderTextObject(obj).length
  let size = 42
  let lines = 2

  if (len > 82) {
    size = 20
    lines = 3
  } else if (len > 66) {
    size = 24
    lines = 3
  } else if (len > 50) {
    size = 28
    lines = 3
  } else if (len > 36) {
    size = 32
    lines = 2
  } else if (len > 24) {
    size = 36
    lines = 2
  }

  return {
    ...objectStyle(obj),
    fontSize: size + 'px',
    '--text-fit-size': size + 'px',
    '--text-lines': String(lines)
  }
}

function selectChapter(index) {
  selectedChapterIndex.value = Math.max(0, Math.min(index, chapters.value.length - 1))
}

function syncChapterFromTime(seconds) {
  if (!chapters.value.length) return
  const found = chapters.value.findIndex(ch => {
    return seconds >= getStartSeconds(ch) && seconds < getEndSeconds(ch)
  })
  if (found >= 0 && found !== selectedChapterIndex.value) {
    selectedChapterIndex.value = found
  }
}

function seekToSeconds(seconds) {
  const safe = Math.max(0, Number(seconds) || 0)
  currentTime.value = safe
  syncChapterFromTime(safe)

  if (audioEl.value && audioPreviewUrl.value) {
    audioEl.value.currentTime = safe
  }
}

function seekToChapter(index) {
  selectChapter(index)
  const ch = chapters.value[selectedChapterIndex.value]
  if (ch) seekToSeconds(getStartSeconds(ch))
}

function onAudioLoaded() {
  audioDuration.value = Number(audioEl.value?.duration || 0)
  playerStatus.value = 'ready'
}

function onAudioTimeUpdate() {
  if (!audioEl.value) return
  currentTime.value = Number(audioEl.value.currentTime || 0)
  syncChapterFromTime(currentTime.value)
}

function onAudioEnded() {
  isPlaying.value = false
  playerStatus.value = 'ended'
}

async function togglePlayback() {
  if (!audioPreviewUrl.value || !audioEl.value) {
    playerStatus.value = 'pick audio first'
    return
  }

  try {
    if (isPlaying.value) {
      audioEl.value.pause()
      isPlaying.value = false
      playerStatus.value = 'paused'
    } else {
      await audioEl.value.play()
      isPlaying.value = true
      playerStatus.value = 'playing'
    }
  } catch (err) {
    isPlaying.value = false
    playerStatus.value = 'playback blocked'
    lastError.value = String(err)
  }
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
    await apiGet('/api/health')
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
    if (selectedChapterIndex.value >= chapters.value.length) selectedChapterIndex.value = 0
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
  logOpen.value = true

  try {
    const data = await apiPost(endpoint, payload)
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
    font: form.font || null,
    waveform: form.waveform
  })
}

function resetLayout() {
  selectedObjectId.value = 'nowPlaying'
}

watch(selectedChapterIndex, () => {
  if (!selectedChapter.value && chapters.value.length) selectedChapterIndex.value = 0
})

onMounted(async () => {
  await checkApi()
  await loadChapters()
  await loadBuildFiles()
  await loadLayout({ silent: true })
})
</script>

<template>
  <main class="sq-editor" :data-theme="form.theme">
    <header class="sq-topbar">
      <div class="sq-brand">
        <div class="sq-logo">Q</div>
        <div>
          <div class="sq-kicker">suviren-q</div>
          <h1>Scene Editor</h1>
        </div>
      </div>

      <div class="sq-actions">
        <div class="sq-status" :class="{ ok: apiOk, bad: !apiOk }">
          <span></span>
          API {{ apiOk ? 'online' : 'offline' }}
        </div>
        <button @click="advancedOpen = !advancedOpen">Project</button>
        <button @click="loadLayout()">Load layout</button>
        <button @click="saveLayout">Save layout</button>
        <button @click="runInspect">Extract</button>
        <button @click="runPreview">Preview</button>
        <button class="primary" @click="runRender">Render</button>
      </div>
    </header>

    <section class="sq-workspace">
      <aside class="sq-panel sq-layers">
        <div class="panel-head">
          <div>
            <div class="sq-kicker">Layers</div>
            <h2>Scene objects</h2>
          </div>
          <button class="tiny" @click="resetLayout">Reset</button>
        </div>

        <div class="layer-list">
          <button
            v-for="obj in [...objects].sort((a, b) => b.zIndex - a.zIndex)"
            :key="obj.id"
            class="layer-row"
            :class="{ active: selectedObjectId === obj.id, muted: !obj.visible }"
            @click="selectObject(obj.id)"
          >
            <span class="layer-eye" @click.stop="toggleVisible(obj)">{{ obj.visible ? 'ON' : 'OFF' }}</span>
            <span class="layer-name">{{ obj.label }}</span>
            <span class="layer-lock" @click.stop="toggleLocked(obj)">{{ obj.locked ? 'LOCK' : '' }}</span>
          </button>
        </div>

        <div class="asset-card asset-loader">
          <div class="sq-kicker">Assets</div>

          <div class="asset-slot">
            <div>
              <strong>Cover</strong>
              <small>{{ form.cover || 'not set' }}</small>
            </div>
            <label class="file-pick">
              Pick
              <input type="file" accept="image/*" @change="pickAsset('cover', $event)" />
            </label>
          </div>

          <div class="asset-slot">
            <div>
              <strong>Background</strong>
              <small>{{ form.background || 'not set' }}</small>
            </div>
            <label class="file-pick">
              Pick
              <input type="file" accept="image/*" @change="pickAsset('background', $event)" />
            </label>
          </div>

          <div class="asset-slot">
            <div>
              <strong>Audio</strong>
              <small>{{ form.audio || 'not set' }}</small>
            </div>
            <label class="file-pick">
              Pick
              <input type="file" accept="audio/*" @change="pickAsset('audio', $event)" />
            </label>
          </div>

          <div class="asset-slot passive">
            <div>
              <strong>Chapters</strong>
              <small>{{ form.chapters || 'not set' }}</small>
            </div>
          </div>
        </div>

        <div class="asset-card layout-state">
          <div class="sq-kicker">Layout</div>
          <strong>{{ layoutStatus }}</strong>
          <small>_suviren_q_build/layout.json</small>
        </div>

        <div class="asset-card">
          <div class="sq-kicker">Current chapter</div>
          <strong>{{ selectedChapter ? shortTitle(selectedChapter.title) : 'No chapter loaded' }}</strong>
          <small>{{ selectedChapter ? formatClock(getStartSeconds(selectedChapter)) : '00:00:00' }}</small>
        </div>

        <div class="asset-card small">
          <div class="sq-kicker">Files</div>
          <div v-for="file in buildFiles.slice(0, 4)" :key="file.path" class="file-row">
            <span>{{ file.path }}</span>
            <em>{{ Math.round(file.size / 1024) }} KB</em>
          </div>
          <div v-if="!buildFiles.length" class="empty">No build files yet.</div>
        </div>
      </aside>

      <section class="sq-main">
        <div class="stage-head">
          <div>
            <div class="sq-kicker">Stage / scene canvas</div>
            <h2>{{ selectedObject ? selectedObject.label : 'No selection' }}</h2>
          </div>
          <div class="stage-meta">
            <span>{{ chapters.length }} chapters</span>
            <span>{{ formatClock(totalDuration) }}</span>
            <span>{{ statusLabel }}</span>
          </div>
        </div>

        <div class="stage-wrap">
          <div class="stage" :style="{ aspectRatio: scene.width + ' / ' + scene.height }">
            <template v-for="obj in [...objects].sort((a, b) => a.zIndex - b.zIndex)" :key="obj.id">
              <button
                v-if="obj.visible && obj.type === 'background'"
                class="stage-object stage-bg"
                :class="{ selected: selectedObjectId === obj.id, locked: obj.locked }"
                :style="backgroundObjectStyle(obj)"
                @click.stop="selectObject(obj.id)"
              ></button>

              <button
                v-if="obj.visible && obj.type === 'image'"
                class="stage-object stage-cover"
                :class="{ selected: selectedObjectId === obj.id, locked: obj.locked }"
                :style="objectStyle(obj)"
                @click.stop="selectObject(obj.id)"
              >
                <img v-if="coverPreviewUrl" :src="coverPreviewUrl" alt="Cover preview" />
                <template v-else>
                  <span class="cover-tag">INTIMATE PROTOCOL</span>
                  <strong>ZINA</strong>
                  <span>AUDIOBOOK</span>
                </template>
              </button>

              <button
                v-if="obj.visible && obj.type === 'text'"
                class="stage-object stage-text"
                :class="[
                  { selected: selectedObjectId === obj.id, locked: obj.locked, big: obj.id === 'nowPlaying' },
                  titleFitClass(obj)
                ]"
                :style="textObjectStyle(obj)"
                @click.stop="selectObject(obj.id)"
              >
                <span class="text-content">{{ renderTextObject(obj) }}</span>
              </button>

              <button
                v-if="obj.visible && obj.type === 'chapterList'"
                class="stage-object stage-chapters"
                :class="{ selected: selectedObjectId === obj.id, locked: obj.locked }"
                :style="objectStyle(obj)"
                @click.stop="selectObject(obj.id)"
              >
                <div
                  v-for="item in visibleChapters"
                  :key="item.index"
                  class="chapter-line"
                  :class="{ active: item.index === selectedChapterIndex }"
                >
                  <b>{{ String(item.index + 1).padStart(2, '0') }}</b>
                  <span>{{ shortTitle(item.chapter.title) }}</span>
                  <em>{{ formatClock(getStartSeconds(item.chapter)) }}</em>
                </div>
              </button>

              <button
                v-if="obj.visible && obj.type === 'waveform'"
                class="stage-object stage-wave"
                :class="{ selected: selectedObjectId === obj.id, locked: obj.locked }"
                :style="objectStyle(obj)"
                @click.stop="selectObject(obj.id)"
              >
                <i v-for="n in 56" :key="n" :style="{ '--i': n }"></i>
              </button>

              <button
                v-if="obj.visible && obj.type === 'progress'"
                class="stage-object stage-progress"
                :class="{ selected: selectedObjectId === obj.id, locked: obj.locked }"
                :style="objectStyle(obj)"
                @click.stop="selectObject(obj.id)"
              >
                <span :style="{ width: (currentChapterProgress * 100) + '%' }"></span>
              </button>
            </template>
          </div>
        </div>
      </section>

      <aside class="sq-panel sq-props">
        <div class="panel-head">
          <div>
            <div class="sq-kicker">Properties</div>
            <h2>{{ selectedObject.label }}</h2>
          </div>
        </div>

        <div v-if="objectWarning" class="prop-warning">
          {{ objectWarning }}
        </div>

        <label class="checkline">
          <input type="checkbox" v-model="selectedObject.visible" />
          <span>Visible</span>
        </label>

        <label class="checkline">
          <input type="checkbox" v-model="selectedObject.locked" />
          <span>Locked</span>
        </label>

        <div class="grid-2">
          <label>
            <span>X</span>
            <input type="number" step="0.001" min="0" max="1" v-model.number="selectedObject.x" />
          </label>
          <label>
            <span>Y</span>
            <input type="number" step="0.001" min="0" max="1" v-model.number="selectedObject.y" />
          </label>
          <label>
            <span>W</span>
            <input type="number" step="0.001" min="0.01" max="1" v-model.number="selectedObject.w" />
          </label>
          <label>
            <span>H</span>
            <input type="number" step="0.001" min="0.01" max="1" v-model.number="selectedObject.h" />
          </label>
        </div>

        <label>
          <span>Opacity</span>
          <input type="number" step="0.01" min="0" max="1" v-model.number="selectedObject.opacity" />
        </label>

        <label v-if="selectedObject.type === 'text'">
          <span>Text</span>
          <textarea v-model="selectedObject.text"></textarea>
        </label>

        <label v-if="selectedObject.type === 'text'">
          <span>Font size</span>
          <input type="number" min="8" max="140" v-model.number="selectedObject.fontSize" />
        </label>

        <label v-if="selectedObject.type === 'image'">
          <span>Source</span>
          <input v-model="selectedObject.source" />
        </label>

        <label v-if="selectedObject.type === 'chapterList'">
          <span>Visible count</span>
          <input type="number" min="1" max="12" v-model.number="selectedObject.visibleCount" />
        </label>

        <div class="advanced" v-if="advancedOpen">
          <div class="sq-kicker">Advanced project settings</div>

          <label>
            <span>RPP</span>
            <input v-model="form.rpp" />
          </label>
          <label>
            <span>Chapter track</span>
            <input v-model="form.rpp_track" />
          </label>
          <label>
            <span>Chapter pattern</span>
            <input v-model="form.chapter_pattern" />
          </label>
          <label>
            <span>Audio</span>
            <input v-model="form.audio" />
          </label>
          <label>
            <span>Cover</span>
            <input v-model="form.cover" />
          </label>
          <label>
            <span>Chapters JSON</span>
            <input v-model="form.chapters" />
          </label>
          <label>
            <span>Output MP4</span>
            <input v-model="form.out" />
          </label>
        </div>
      </aside>
    </section>

    <section class="sq-timeline">
      <audio
        ref="audioEl"
        v-if="audioPreviewUrl"
        :src="audioPreviewUrl"
        preload="metadata"
        @loadedmetadata="onAudioLoaded"
        @timeupdate="onAudioTimeUpdate"
        @ended="onAudioEnded"
      ></audio>

      <div class="timeline-head">
        <div>
          <div class="sq-kicker">Timeline</div>
          <h2>Timeline</h2>
        </div>
        <div class="player-strip">
          <button class="play-button" @click="togglePlayback">{{ isPlaying ? 'Pause' : 'Play' }}</button>
          <span>{{ playerClock }}</span>
          <em>{{ playerStatus }}</em>
        </div>

        <div class="timeline-controls">
          <button @click="seekToChapter(Math.max(0, selectedChapterIndex - 1))">Prev chapter</button>
          <button @click="seekToChapter(Math.min(chapters.length - 1, selectedChapterIndex + 1))">Next chapter</button>
          <button @click="loadChapters">Reload chapters</button>
          <button @click="logOpen = !logOpen">Log</button>
        </div>
      </div>

      <div class="ruler">
        <span>00:00:00</span>
        <span>{{ formatClock(totalDuration / 4) }}</span>
        <span>{{ formatClock(totalDuration / 2) }}</span>
        <span>{{ formatClock(totalDuration * 0.75) }}</span>
        <span>{{ formatClock(totalDuration) }}</span>
      </div>

      <div class="track-shell">
        <div class="track-labels">
          <div>Scene</div>
          <div>Chapters</div>
          <div>Audio</div>
        </div>

        <div class="tracks">
          <div class="playhead" :style="{ left: playbackPercent + '%' }"></div>
          <div class="track scene-track">
            <button
              v-for="obj in objects.filter(item => item.type !== 'background')"
              :key="obj.id"
              class="scene-clip"
              :class="{ active: selectedObjectId === obj.id, muted: !obj.visible }"
              @click="selectObject(obj.id)"
            >
              {{ obj.label }}
            </button>
          </div>

          <div class="track chapter-track">
            <button
              v-for="seg in timelineSegments"
              :key="seg.index"
              class="chapter-clip"
              :class="{ active: seg.index === selectedChapterIndex }"
              :style="{ width: seg.width + '%' }"
              @click="seekToChapter(seg.index)"
              :title="shortTitle(seg.chapter.title)"
            >
              {{ seg.index + 1 }}
            </button>
          </div>

          <div class="track audio-track">
            <div
              v-for="seg in timelineSegments"
              :key="'audio' + seg.index"
              class="audio-clip"
              :style="{ width: seg.width + '%' }"
            ></div>
          </div>
        </div>
      </div>
    </section>

    <section class="sq-log" v-if="logOpen">
      <div v-if="lastError" class="error">{{ lastError }}</div>
      <pre>{{ jobLog.length ? jobLog.join('\n') : 'Ready.' }}</pre>
    </section>
  </main>
</template>
