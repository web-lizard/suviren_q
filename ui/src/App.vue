<template>
  <!-- Loading state -->
  <div class="bf-app" v-if="loading">
    <div class="bf-loading">
      <div class="bf-spinner"></div>
      <div class="bf-loading-text">BookForge Studio</div>
      <div class="bf-loading-sub">YouTube Audiobook Composer</div>
      <div class="bf-loading-status" v-if="loadMsg">{{ loadMsg }}</div>
    </div>
  </div>

  <!-- Main console -->
  <div class="bf-app" v-else>
    <!-- Top bar -->
    <header class="bf-topbar">
      <div class="bf-brand">
        <span class="bf-logo-icon">◈</span>
        <span class="bf-title">BookForge Studio</span>
        <span class="bf-subtitle">YouTube Audiobook Composer</span>
      </div>
      <div class="bf-topbar-right">
        <span class="bf-api-dot" :class="apiOk ? 'bf-ok' : 'bf-bad'" :title="apiOk ? 'API OK' : 'API Error'"></span>
        <span class="bf-version">v0.3</span>
      </div>
    </header>

    <div class="bf-body">
      <!-- Left: Scene preview (large 16:9) -->
      <div class="bf-scene-area">
        <div class="bf-scene" ref="sceneEl" @mousedown="onSceneMouseDown">
          <!-- Background layer -->
          <div class="bf-layer bf-layer-bg" :style="bgStyle"></div>

          <!-- Cover layer -->
          <div class="bf-layer bf-layer-cover"
               v-if="coverUrl"
               :style="coverStyle"
               :class="{ 'bf-dragging': draggingObj === 'cover', 'bf-selected': selectedObj === 'cover' }"
               @mousedown.stop="onObjMouseDown('cover', $event)">
            <img :src="coverUrl" class="bf-cover-img" />
          </div>

          <!-- Current chapter title -->
          <div class="bf-layer bf-layer-title"
               :style="titleStyle"
               :class="{ 'bf-dragging': draggingObj === 'currentChapterTitle', 'bf-selected': selectedObj === 'currentChapterTitle' }"
               @mousedown.stop="onObjMouseDown('currentChapterTitle', $event)">
            {{ currentChapterTitle }}
          </div>

          <!-- Book title -->
          <div class="bf-layer bf-layer-booktitle"
               :style="bookTitleStyle"
               :class="{ 'bf-dragging': draggingObj === 'bookTitle', 'bf-selected': selectedObj === 'bookTitle' }"
               @mousedown.stop="onObjMouseDown('bookTitle', $event)">
            {{ projectName }}
          </div>

          <!-- Author brand -->
          <div class="bf-layer bf-layer-author"
               :style="authorStyle"
               :class="{ 'bf-dragging': draggingObj === 'authorBrand', 'bf-selected': selectedObj === 'authorBrand' }"
               @mousedown.stop="onObjMouseDown('authorBrand', $event)">
            Monsieur Souveraineté
          </div>

          <!-- Waveform -->
          <div class="bf-layer bf-layer-waveform"
               :style="waveformStyle"
               :class="{ 'bf-dragging': draggingObj === 'waveform', 'bf-selected': selectedObj === 'waveform' }"
               @mousedown.stop="onObjMouseDown('waveform', $event)">
            <div class="bf-wave-bars" ref="waveformEl">
              <div v-for="(s, i) in waveformSamples" :key="i"
                   class="bf-wave-bar"
                   :style="{
                     height: (s * 100) + '%',
                     background: i / waveformSamples.length <= progressPct / 100
                       ? layout.objects.waveform.progressColor
                       : layout.objects.waveform.color,
                     width: layout.objects.waveform.barWidth + 'px',
                     marginRight: layout.objects.waveform.barGap + 'px'
                   }">
              </div>
            </div>
          </div>

          <!-- Progress bar -->
          <div class="bf-layer bf-layer-progress"
               :style="progressBarStyle"
               :class="{ 'bf-dragging': draggingObj === 'progressBar', 'bf-selected': selectedObj === 'progressBar' }"
               @mousedown.stop="onObjMouseDown('progressBar', $event)">
            <div class="bf-progress-track">
              <div class="bf-progress-fill" :style="{ width: progressPct + '%' }"></div>
            </div>
          </div>

          <!-- Scene time overlay -->
          <div class="bf-scene-time">{{ formatTime(currentTime) }} / {{ formatTime(duration) }}</div>
        </div>

        <!-- Audio player bar under scene -->
        <div class="bf-player-bar">
          <audio ref="audioEl" :src="audioUrl" @timeupdate="onTime" @loadedmetadata="onMeta" @ended="onEnded"></audio>
          <button class="bf-btn-icon" @click="seek(-15)" title="Назад 15с">⏪</button>
          <button class="bf-btn-icon bf-btn-play" @click="togglePlay">
            {{ playing ? '⏸' : '▶' }}
          </button>
          <button class="bf-btn-icon" @click="seek(15)" title="Вперёд 15с">⏩</button>
          <div class="bf-progress-click" @click="seekClick">
            <div class="bf-progress-bar">
              <div class="bf-progress-fill-slim" :style="{ width: progressPct + '%' }"></div>
            </div>
          </div>
          <span class="bf-time">{{ formatTime(currentTime) }}</span>
        </div>

        <!-- Timeline chapters -->
        <div class="bf-timeline" v-if="chapters.length">
          <div class="bf-timeline-label">Главы</div>
          <div class="bf-timeline-chips">
            <button v-for="(ch, i) in chapters.slice(0, 12)" :key="i"
                    class="bf-chip"
                    :class="{ 'bf-chip-active': i === currentChapterIdx }"
                    @click="playChapter(i)">
              {{ ch.title.length > 30 ? ch.title.slice(0, 28) + '…' : ch.title }}
            </button>
            <button v-if="chapters.length > 12" class="bf-chip bf-chip-more" @click="showAllChapters = !showAllChapters">
              {{ showAllChapters ? '▲ Свернуть' : '▼ Ещё ' + (chapters.length - 12) }}
            </button>
          </div>
        </div>
      </div>

      <!-- Right panel: Status cards + actions -->
      <div class="bf-panel">
        <!-- Project status cards -->
        <div class="bf-status-cards">
          <div class="bf-card" :class="audioOk ? 'bf-card-ok' : 'bf-card-missing'">
            <div class="bf-card-icon">{{ audioOk ? '🎵' : '🔇' }}</div>
            <div class="bf-card-body">
              <div class="bf-card-label">Audio</div>
              <div class="bf-card-value">{{ audioName || '—' }}</div>
              <div class="bf-card-sub" v-if="audioSize">{{ audioSize }} MB</div>
            </div>
          </div>

          <div class="bf-card" :class="coverOk ? 'bf-card-ok' : 'bf-card-missing'">
            <div class="bf-card-icon">{{ coverOk ? '🖼️' : '⛔' }}</div>
            <div class="bf-card-body">
              <div class="bf-card-label">Cover</div>
              <div class="bf-card-value">{{ coverName || '—' }}</div>
            </div>
          </div>

          <div class="bf-card" :class="bgOk ? 'bf-card-ok' : 'bf-card-warn'">
            <div class="bf-card-icon">{{ bgOk ? '🌆' : '🌑' }}</div>
            <div class="bf-card-body">
              <div class="bf-card-label">Background</div>
              <div class="bf-card-value">{{ bgName || 'Fallback' }}</div>
            </div>
          </div>

          <div class="bf-card" :class="rppOk ? 'bf-card-ok' : 'bf-card-missing'">
            <div class="bf-card-icon">{{ rppOk ? '📄' : '📭' }}</div>
            <div class="bf-card-body">
              <div class="bf-card-label">RPP / Chapters</div>
              <div class="bf-card-value">{{ chapterCount }}{{ chapterCount ? ' глав' : '' }}</div>
            </div>
          </div>
        </div>

        <!-- Overall status -->
        <div class="bf-status-banner" :class="projectReady ? 'bf-ready' : 'bf-not-ready'">
          <span v-if="projectReady">✓ Ready for render</span>
          <span v-else>⚠ Missing: {{ missing.join(', ') }}</span>
        </div>

        <!-- Main action buttons -->
        <div class="bf-actions">
          <button class="bf-btn bf-btn-primary bf-btn-test"
                  :disabled="!projectReady || renderRunning"
                  @click="startTestRender">
            <span class="bf-btn-label">Test Render 60 sec</span>
            <span class="bf-btn-icon-small">⚡</span>
          </button>

          <button class="bf-btn bf-btn-primary bf-btn-full"
                  :disabled="!projectReady || renderRunning"
                  @click="startFullRender">
            <span class="bf-btn-label">Full Render</span>
            <span class="bf-btn-icon-small">🎬</span>
          </button>
        </div>

        <!-- Render status -->
        <div class="bf-render-status" v-if="renderStatus">
          <div class="bf-render-bar">
            <div class="bf-render-fill" :style="{ width: (renderProgress * 100) + '%' }"></div>
          </div>
          <div class="bf-render-text">{{ renderStatus }}</div>
          <button class="bf-btn bf-btn-sm" v-if="renderLog.length" @click="showLog = !showLog">
            {{ showLog ? 'Скрыть лог' : 'Показать лог' }}
          </button>
          <div class="bf-render-log" v-if="showLog">
            <div v-for="(line, i) in renderLog.slice(-20)" :key="i" class="bf-log-line">{{ line }}</div>
          </div>
        </div>

        <!-- Secondary actions -->
        <div class="bf-secondary-actions">
          <button class="bf-btn bf-btn-sm" @click="refreshChapters" :disabled="!rppOk">🔄 Refresh chapters</button>
          <button class="bf-btn bf-btn-sm" @click="openAdvanced">⚙️ Advanced Editor</button>
          <button class="bf-btn bf-btn-sm" @click="showLayoutDialog = !showLayoutDialog">📐 Layout</button>
        </div>

        <!-- Layout dialog -->
        <div class="bf-layout-dialog" v-if="showLayoutDialog">
          <div class="bf-layout-title">Layout Presets</div>
          <button class="bf-btn bf-btn-sm" @click="resetLayout('default')">Reset to BookForge default</button>
          <button class="bf-btn bf-btn-sm" @click="resetLayout('book')">Reset to current book style</button>
          <button class="bf-btn bf-btn-sm" @click="saveLayout">💾 Save layout</button>
          <button class="bf-btn bf-btn-sm" @click="loadLayout">📂 Load layout</button>
        </div>
      </div>
    </div>

    <!-- Status bar -->
    <footer class="bf-statusbar">
      <span>{{ projectName || 'BookForge Studio' }}</span>
      <span>{{ statusMsg }}</span>
      <span>{{ chapterCount }} глав · {{ formatTime(duration) }} · BookForge Studio v0.3</span>
    </footer>
  </div>
</template>

<script>
import { ref, computed, onMounted, nextTick, reactive } from 'vue'

const API = 'http://127.0.0.1:8787/api'

// Default layout
const DEFAULT_LAYOUT = {
  scene: { width: 1920, height: 1080, fps: 30 },
  objects: {
    background: { x: 0, y: 0, width: 1920, height: 1080, opacity: 1.0, visible: true, fit: 'cover' },
    cover: { x: 120, y: 80, width: 460, height: 460, opacity: 0.95, visible: true, borderRadius: 16 },
    currentChapterTitle: { x: 660, y: 100, width: 1140, height: 60, fontSize: 44, fontWeight: 700, color: '#e0daf5', opacity: 1.0, textAlign: 'left' },
    bookTitle: { x: 660, y: 165, width: 1140, height: 36, fontSize: 26, fontWeight: 400, color: '#7b68ee', opacity: 0.85, textAlign: 'left' },
    authorBrand: { x: 660, y: 210, width: 600, height: 26, fontSize: 16, fontWeight: 300, color: '#7a74a0', opacity: 0.7, textAlign: 'left', text: 'Monsieur Souveraineté' },
    waveform: { x: 60, y: 700, width: 1800, height: 130, opacity: 0.5, visible: true, barWidth: 4, barGap: 2, color: '#00e5a0', bgColor: 'rgba(0,229,160,0.08)', progressColor: '#7b68ee' },
    progressBar: { x: 60, y: 860, width: 1800, height: 5, opacity: 0.8, visible: true, color: '#7b68ee', bgColor: '#1e1e32', borderRadius: 3 },
    chapterList: { x: 660, y: 260, width: 1140, height: 300, opacity: 0.0, visible: false, fontSize: 16, color: '#ddd8f0' },
  },
  render: { quality: 'youtube_high', crf: 18, audioBitrate: '192k', pixelFormat: 'yuv420p', codec: 'h264' },
  colors: { accent: '#7b68ee', accent2: '#00e5a0', bg: '#0b0b15', text: '#ddd8f0', textDim: '#7a74a0', chapterActive: '#7b68ee' },
}

export default {
  name: 'App',
  setup() {
    // Data state
    const project = ref({})
    const chapters = ref([])
    const layout = ref(JSON.parse(JSON.stringify(DEFAULT_LAYOUT)))
    const waveformSamples = ref([])
    const showAllChapters = ref(false)
    const showLayoutDialog = ref(false)
    const showLog = ref(false)

    // Loading state
    const loading = ref(true)
    const loadMsg = ref('')
    const apiOk = ref(false)

    // Player state
    const audioEl = ref(null)
    const sceneEl = ref(null)
    const waveformEl = ref(null)
    const currentTime = ref(0)
    const duration = ref(0)
    const playing = ref(false)

    // Drag state
    const draggingObj = ref(null)
    const dragStart = ref({ x: 0, y: 0, objX: 0, objY: 0 })
    const selectedObj = ref(null)

    // Render state
    const renderRunning = ref(false)
    const renderProgress = ref(0)
    const renderStatus = ref('')
    const renderLog = ref([])
    const pollTimer = ref(null)

    // Computed
    const audioUrl = computed(() => {
      const a = project.value.audio
      if (a && a.exists) return `${API}/media/${a.path}`
      return ''
    })
    const coverUrl = computed(() => {
      const c = project.value.cover
      if (c && c.exists) return `${API}/media/${c.path}`
      return ''
    })
    const bgUrl = computed(() => {
      const b = project.value.background
      if (b && b.exists) return `${API}/media/${b.path}`
      return ''
    })

    const audioOk = computed(() => project.value.audio?.exists)
    const coverOk = computed(() => project.value.cover?.exists)
    const bgOk = computed(() => project.value.background?.exists)
    const rppOk = computed(() => project.value.rpp?.exists)
    const projectReady = computed(() => project.value.ready)
    const missing = computed(() => project.value.missing || [])
    const projectName = computed(() => project.value.projectName || '')
    const chapterCount = computed(() => chapters.value.length)
    const audioName = computed(() => {
      const a = project.value.audio
      return a ? (a.path || '').split('/').pop() || (a.path || '').split('\\').pop() : ''
    })
    const audioSize = computed(() => project.value.audio?.size_mb)
    const coverName = computed(() => {
      const c = project.value.cover
      return c ? (c.path || '').split('/').pop() || (c.path || '').split('\\').pop() : ''
    })
    const bgName = computed(() => {
      const b = project.value.background
      return b ? (b.path || '').split('/').pop() || (b.path || '').split('\\').pop() : ''
    })

    const progressPct = computed(() => {
      if (!duration.value) return 0
      return (currentTime.value / duration.value) * 100
    })

    const currentChapterIdx = computed(() => {
      const t = currentTime.value
      let idx = chapters.value.length - 1
      for (let i = 0; i < chapters.value.length; i++) {
        const ch = chapters.value[i]
        const start = ch.start_seconds || 0
        const end = ch.end_seconds || 999999
        if (t >= start && t < end) { idx = i; break }
        if (t < start) { idx = Math.max(0, i - 1); break }
      }
      return idx
    })

    const currentChapterTitle = computed(() => {
      const ch = chapters.value[currentChapterIdx.value]
      return ch ? ch.title : 'Загрузка...'
    })

    // Scene object styles
    function objStyle(name) {
      const obj = layout.value.objects[name]
      if (!obj) return {}
      // Scale from 1920x1080 to scene container size
      const sw = sceneWidth.value
      const sh = sceneHeight.value
      const sx = sw / 1920
      const sy = sh / 1080
      return {
        left: (obj.x * sx) + 'px',
        top: (obj.y * sy) + 'px',
        width: (obj.width * sx) + 'px',
        height: (obj.height * sy) + 'px',
        opacity: obj.opacity ?? 1,
        display: obj.visible !== false ? 'block' : 'none',
      }
    }

    const sceneWidth = ref(0)
    const sceneHeight = ref(0)

    function updateSceneSize() {
      if (!sceneEl.value) return
      sceneWidth.value = sceneEl.value.clientWidth
      sceneHeight.value = sceneEl.value.clientHeight
    }

    const bgStyle = computed(() => {
      const s = objStyle('background')
      if (bgUrl.value) {
        s.backgroundImage = `url(${bgUrl.value})`
        s.backgroundSize = 'cover'
        s.backgroundPosition = 'center'
      } else {
        s.background = 'radial-gradient(ellipse at 50% 40%, rgba(123,104,238,0.12), transparent 60%), linear-gradient(145deg, #0b0b15, #14142a, #0b0b15)'
      }
      return s
    })

    const coverStyle = computed(() => {
      const s = objStyle('cover')
      const br = layout.value.objects.cover.borderRadius || 16
      const sw = sceneWidth.value / 1920
      s.borderRadius = (br * sw) + 'px'
      s.overflow = 'hidden'
      return s
    })

    const titleStyle = computed(() => {
      const s = objStyle('currentChapterTitle')
      const obj = layout.value.objects.currentChapterTitle
      const sw = sceneWidth.value / 1920
      s.fontSize = (obj.fontSize * sw) + 'px'
      s.fontWeight = obj.fontWeight
      s.color = obj.color
      s.textAlign = obj.textAlign || 'left'
      s.whiteSpace = 'nowrap'
      s.overflow = 'hidden'
      s.textOverflow = 'ellipsis'
      return s
    })

    const bookTitleStyle = computed(() => {
      const s = objStyle('bookTitle')
      const obj = layout.value.objects.bookTitle
      const sw = sceneWidth.value / 1920
      s.fontSize = (obj.fontSize * sw) + 'px'
      s.fontWeight = obj.fontWeight
      s.color = obj.color
      s.textAlign = obj.textAlign || 'left'
      s.whiteSpace = 'nowrap'
      s.overflow = 'hidden'
      s.textOverflow = 'ellipsis'
      return s
    })

    const authorStyle = computed(() => {
      const s = objStyle('authorBrand')
      const obj = layout.value.objects.authorBrand
      const sw = sceneWidth.value / 1920
      s.fontSize = (obj.fontSize * sw) + 'px'
      s.fontWeight = obj.fontWeight
      s.color = obj.color
      s.textAlign = obj.textAlign || 'left'
      return s
    })

    const waveformStyle = computed(() => {
      const s = objStyle('waveform')
      s.display = 'flex'
      s.alignItems = 'center'
      return s
    })

    const progressBarStyle = computed(() => {
      const s = objStyle('progressBar')
      const obj = layout.value.objects.progressBar
      s.borderRadius = (obj.borderRadius || 3) + 'px'
      return s
    })

    const statusMsg = ref('Готово')

    // ── API helpers ──
    async function apiGet(url) {
      const res = await fetch(url)
      if (!res.ok) throw new Error(await res.text())
      return await res.json()
    }

    async function apiPost(url, payload) {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload || {})
      })
      if (!res.ok) throw new Error(await res.text())
      return await res.json()
    }

    function formatTime(sec) {
      if (!sec || !isFinite(sec)) return '00:00'
      const n = Math.max(0, Math.floor(sec))
      const m = Math.floor(n / 60)
      const s = n % 60
      return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
    }

    // ── Player ──
    function togglePlay() {
      const el = audioEl.value
      if (!el) return
      if (el.paused) { el.play().catch(() => {}); playing.value = true }
      else { el.pause(); playing.value = false }
    }

    function seek(offset) {
      const el = audioEl.value
      if (!el) return
      el.currentTime = Math.max(0, Math.min(el.currentTime + offset, duration.value))
    }

    function seekClick(e) {
      const bar = e.currentTarget
      if (!bar) return
      const rect = bar.getBoundingClientRect()
      const pct = (e.clientX - rect.left) / rect.width
      const el = audioEl.value
      if (el && duration.value) el.currentTime = pct * duration.value
    }

    function onTime() {
      const el = audioEl.value
      if (el) currentTime.value = el.currentTime
    }

    function onMeta() {
      const el = audioEl.value
      if (el) duration.value = el.duration || 0
    }

    function onEnded() { playing.value = false }

    function playChapter(i) {
      const ch = chapters.value[i]
      if (!ch) return
      const start = ch.start_seconds || 0
      const el = audioEl.value
      if (el) { el.currentTime = start; el.play().catch(() => {}); playing.value = true }
    }

    // ── Drag ──
    function onSceneMouseDown(e) {
      if (!draggingObj.value) {
        selectedObj.value = null
        return
      }
    }

    function onObjMouseDown(name, e) {
      selectedObj.value = name
      draggingObj.value = name
      const obj = layout.value.objects[name]
      if (!obj) return
      dragStart.value = { x: e.clientX, y: e.clientY, objX: obj.x, objY: obj.y }

      const onMove = (ev) => {
        const sw = sceneWidth.value / 1920
        const sh = sceneHeight.value / 1080
        const dx = (ev.clientX - dragStart.value.x) / sw
        const dy = (ev.clientY - dragStart.value.y) / sh
        layout.value.objects[name].x = Math.max(0, Math.min(1920 - obj.width, dragStart.value.objX + dx))
        layout.value.objects[name].y = Math.max(0, Math.min(1080 - obj.height, dragStart.value.objY + dy))
        // Snap to edges/center
        const snap = 10
        if (Math.abs(layout.value.objects[name].x) < snap) layout.value.objects[name].x = 0
        if (Math.abs(layout.value.objects[name].y) < snap) layout.value.objects[name].y = 0
        if (Math.abs(1920 - obj.width - layout.value.objects[name].x) < snap) layout.value.objects[name].x = 1920 - obj.width
        if (Math.abs(1080 - obj.height - layout.value.objects[name].y) < snap) layout.value.objects[name].y = 1080 - obj.height
      }
      const onUp = () => {
        draggingObj.value = null
        document.removeEventListener('mousemove', onMove)
        document.removeEventListener('mouseup', onUp)
      }
      document.addEventListener('mousemove', onMove)
      document.addEventListener('mouseup', onUp)
    }

    // ── Layout ──
    async function saveLayout() {
      try {
        await apiPost(`${API}/layout`, layout.value)
        statusMsg.value = 'Layout saved'
      } catch (err) {
        statusMsg.value = 'Save failed: ' + String(err)
      }
    }

    async function loadLayout() {
      try {
        const resp = await apiGet(`${API}/layout`)
        if (resp.layout) {
          // Merge with defaults for any missing keys
          layout.value = deepMerge(JSON.parse(JSON.stringify(DEFAULT_LAYOUT)), resp.layout)
          statusMsg.value = 'Layout loaded'
        }
      } catch (err) {
        statusMsg.value = 'Load failed: ' + String(err)
      }
    }

    async function resetLayout(target) {
      try {
        const resp = await apiPost(`${API}/layout/reset`, { target })
        if (resp.ok) {
          const getResp = await apiGet(`${API}/layout`)
          if (getResp.layout) layout.value = deepMerge(JSON.parse(JSON.stringify(DEFAULT_LAYOUT)), getResp.layout)
          statusMsg.value = `Layout reset: ${target}`
        }
      } catch (err) {
        statusMsg.value = 'Reset failed: ' + String(err)
      }
    }

    function deepMerge(target, source) {
      for (const key in source) {
        if (source[key] && typeof source[key] === 'object' && !Array.isArray(source[key])) {
          if (!target[key]) target[key] = {}
          deepMerge(target[key], source[key])
        } else if (source[key] !== undefined) {
          target[key] = source[key]
        }
      }
      return target
    }

    // ── Render ──
    async function startTestRender() {
      renderRunning.value = true
      renderStatus.value = 'Starting test render...'
      renderProgress.value = 0
      renderLog.value = []
      try {
        const resp = await apiPost(`${API}/render/test`)
        const jobId = resp.job_id
        pollTimer.value = setInterval(() => pollRender(jobId), 1000)
      } catch (err) {
        renderRunning.value = false
        renderStatus.value = 'Failed: ' + String(err)
      }
    }

    async function startFullRender() {
      renderRunning.value = true
      renderStatus.value = 'Starting full render...'
      renderProgress.value = 0
      renderLog.value = []
      try {
        const resp = await apiPost(`${API}/render/full`)
        const jobId = resp.job_id
        pollTimer.value = setInterval(() => pollRender(jobId), 1000)
      } catch (err) {
        renderRunning.value = false
        renderStatus.value = 'Failed: ' + String(err)
      }
    }

    async function pollRender(jobId) {
      try {
        const job = await apiGet(`${API}/jobs/${jobId}`)
        renderProgress.value = job.progress || 0
        renderLog.value = job.log || []
        if (job.status === 'done') {
          renderRunning.value = false
          renderStatus.value = '✅ Render complete!'
          renderProgress.value = 1
          clearInterval(pollTimer.value)
          pollTimer.value = null
        } else if (job.status === 'failed') {
          renderRunning.value = false
          renderStatus.value = '❌ Render failed'
          clearInterval(pollTimer.value)
          pollTimer.value = null
        } else {
          renderStatus.value = `Rendering... ${Math.round(renderProgress.value * 100)}%`
        }
      } catch (err) {
        // Silently retry
      }
    }

    // ── Bookmarks / chapters ──
    async function refreshChapters() {
      statusMsg.value = 'Refreshing chapters...'
      try {
        const resp = await apiPost(`${API}/book-project/refresh-chapters`)
        if (resp.ok && resp.chapters) {
          chapters.value = resp.chapters
          statusMsg.value = `Chapters updated: ${chapters.value.length}`
        } else {
          statusMsg.value = 'No chapters found'
        }
      } catch (err) {
        statusMsg.value = 'Error: ' + String(err)
      }
    }

    function openAdvanced() {
      window.open('/advanced.html', '_blank')
    }

    // ── Init ──
    async function init() {
      loadMsg.value = 'Connecting to API...'
      try {
        const health = await apiGet(`${API}/health`)
        apiOk.value = health.ok
      } catch {
        apiOk.value = false
        loadMsg.value = 'API server not available. Start the backend.'
        loading.value = false
        return
      }

      loadMsg.value = 'Discovering project data...'
      try {
        const p = await apiGet(`${API}/book-project`)
        project.value = p
      } catch (err) {
        project.value = {}
      }

      loadMsg.value = 'Loading chapters...'
      try {
        const chResp = await apiGet(`${API}/chapters`)
        if (chResp.exists && chResp.chapters.length) {
          chapters.value = chResp.chapters
        }
      } catch { /* ignore */ }

      loadMsg.value = 'Loading layout...'
      try {
        const layoutResp = await apiGet(`${API}/layout`)
        if (layoutResp.layout) {
          layout.value = deepMerge(JSON.parse(JSON.stringify(DEFAULT_LAYOUT)), layoutResp.layout)
        }
      } catch { /* ignore */ }

      loadMsg.value = 'Loading waveform...'
      try {
        const wf = await apiGet(`${API}/waveform?samples=2000`)
        if (wf.samples) waveformSamples.value = wf.samples
      } catch { /* ignore */ }

      statusMsg.value = project.value.ready ? 'Ready for render' : 'Project incomplete'

      loading.value = false

      nextTick(() => {
        updateSceneSize()
        const el = audioEl.value
        if (el) el.load()
      })
    }

    onMounted(init)

    return {
      loading, loadMsg, apiOk, project,
      chapters, layout, waveformSamples,
      showAllChapters, showLayoutDialog, showLog,
      audioUrl, coverUrl,
      audioOk, coverOk, bgOk, rppOk, projectReady, missing,
      projectName, chapterCount, audioName, audioSize, coverName, bgName,
      currentTime, duration, playing, statusMsg,
      audioEl, sceneEl, waveformEl,
      currentChapterIdx, currentChapterTitle, progressPct,
      selectedObj, draggingObj,
      renderRunning, renderProgress, renderStatus, renderLog,
      sceneWidth, sceneHeight,

      bgStyle, coverStyle, titleStyle, bookTitleStyle, authorStyle,
      waveformStyle, progressBarStyle,

      togglePlay, seek, seekClick, onTime, onMeta, onEnded,
      playChapter, formatTime,
      onObjMouseDown, onSceneMouseDown,
      saveLayout, loadLayout, resetLayout,
      startTestRender, startFullRender,
      refreshChapters, openAdvanced,
    }
  }
}
</script>

<style>
/* ── BookForge Studio — Noir Cyberpunk Console ── */

:root {
  --bf-bg: #0a0a14;
  --bf-panel: #10101e;
  --bf-card-bg: #16162a;
  --bf-border: #262640;
  --bf-text: #ddd8f0;
  --bf-dim: #7a74a0;
  --bf-accent: #7b68ee;
  --bf-green: #00e5a0;
  --bf-red: #ff456a;
  --bf-glow-green: 0 0 20px rgba(0,229,160,0.25);
  --bf-glow-accent: 0 0 20px rgba(123,104,238,0.25);
  --bf-font: 'Segoe UI', system-ui, -apple-system, sans-serif;
  --bf-radius: 12px;
  --bf-radius-sm: 8px;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

html, body {
  height: 100%;
  overflow: hidden;
  background: var(--bf-bg);
  color: var(--bf-text);
  font-family: var(--bf-font);
  font-size: 14px;
}

.bf-app {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--bf-bg);
}

/* ── Loading ── */
.bf-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 12px;
  background: radial-gradient(ellipse at 50% 30%, rgba(123,104,238,0.08), transparent 60%);
}
.bf-spinner {
  width: 40px; height: 40px;
  border: 3px solid var(--bf-border);
  border-top: 3px solid var(--bf-green);
  border-radius: 50%;
  animation: bf-spin 0.8s linear infinite;
}
@keyframes bf-spin { to { transform: rotate(360deg); } }
.bf-loading-text {
  font-size: 24px; font-weight: 800;
  background: linear-gradient(135deg, var(--bf-green), var(--bf-accent));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
}
.bf-loading-sub { font-size: 14px; color: var(--bf-dim); letter-spacing: 1px; }
.bf-loading-status { font-size: 13px; color: var(--bf-dim); margin-top: 8px; }

/* ── Top bar ── */
.bf-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 44px;
  padding: 0 20px;
  background: linear-gradient(90deg, #0a0a14, #12122a, #0a0a14);
  border-bottom: 1px solid var(--bf-border);
  flex-shrink: 0;
}
.bf-brand {
  display: flex;
  align-items: center;
  gap: 10px;
}
.bf-logo-icon {
  font-size: 20px;
  background: linear-gradient(135deg, var(--bf-green), var(--bf-accent));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
}
.bf-title {
  font-size: 16px; font-weight: 800;
  background: linear-gradient(135deg, var(--bf-green), var(--bf-accent));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
}
.bf-subtitle {
  font-size: 11px; color: var(--bf-dim); letter-spacing: 0.5px;
  border-left: 1px solid var(--bf-border); padding-left: 10px;
}
.bf-topbar-right {
  display: flex; align-items: center; gap: 12px;
}
.bf-api-dot {
  width: 8px; height: 8px; border-radius: 50%;
}
.bf-api-dot.bf-ok { background: var(--bf-green); box-shadow: 0 0 10px var(--bf-green); }
.bf-api-dot.bf-bad { background: var(--bf-red); box-shadow: 0 0 10px var(--bf-red); }
.bf-version { font-size: 11px; color: var(--bf-dim); font-family: 'Consolas', monospace; }

/* ── Body layout ── */
.bf-body {
  flex: 1;
  display: flex;
  gap: 0;
  overflow: hidden;
}

/* ── Scene area (left, large) ── */
.bf-scene-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 12px 16px 8px;
  gap: 8px;
  overflow: hidden;
  min-width: 0;
}

.bf-scene {
  position: relative;
  flex: 1;
  min-height: 300px;
  border-radius: var(--bf-radius);
  overflow: hidden;
  background: radial-gradient(ellipse at 50% 40%, rgba(123,104,238,0.10), transparent 60%), #0a0a14;
  border: 1px solid var(--bf-border);
  cursor: default;
}

.bf-layer {
  position: absolute;
  user-select: none;
  transition: box-shadow 0.15s;
}
.bf-layer.bf-selected {
  outline: 2px dashed var(--bf-accent);
  outline-offset: 2px;
}
.bf-layer.bf-dragging {
  cursor: grabbing !important;
  box-shadow: 0 0 30px rgba(123,104,238,0.3);
}

.bf-layer-bg {
  inset: 0;
  width: 100% !important;
  height: 100% !important;
}
.bf-layer-bg.bf-selected { outline: none; }

.bf-cover-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.bf-scene-time {
  position: absolute;
  bottom: 8px; right: 10px;
  font-size: 12px; color: rgba(255,255,255,0.6);
  font-family: 'Consolas', monospace;
  text-shadow: 0 0 10px rgba(0,0,0,0.8);
}

/* Waveform bars */
.bf-wave-bars {
  display: flex;
  align-items: center;
  height: 100%;
  width: 100%;
  overflow: hidden;
}
.bf-wave-bar {
  flex-shrink: 0;
  border-radius: 2px;
  transition: background 0.1s;
}

/* Progress bar in scene */
.bf-progress-track {
  width: 100%;
  height: 100%;
  background: var(--bf-border);
  border-radius: inherit;
  overflow: hidden;
}
.bf-progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--bf-accent), var(--bf-green));
  border-radius: inherit;
  transition: width 0.1s;
}

/* ── Player bar ── */
.bf-player-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--bf-panel);
  border-radius: var(--bf-radius-sm);
  border: 1px solid var(--bf-border);
  flex-shrink: 0;
}
.bf-btn-icon {
  width: 32px; height: 32px;
  border-radius: 50%;
  border: 1px solid var(--bf-border);
  background: var(--bf-card-bg);
  color: var(--bf-text);
  font-size: 13px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.12s;
}
.bf-btn-icon:hover { background: var(--bf-panel); border-color: var(--bf-dim); }
.bf-btn-play { width: 40px; height: 40px; font-size: 18px; }

.bf-progress-click {
  flex: 1;
  cursor: pointer;
  min-width: 60px;
}
.bf-progress-bar {
  height: 4px;
  background: var(--bf-border);
  border-radius: 99px;
}
.bf-progress-fill-slim {
  height: 100%;
  background: linear-gradient(90deg, var(--bf-accent), var(--bf-green));
  border-radius: 99px;
  transition: width 0.1s;
}
.bf-time {
  font-family: 'Consolas', monospace;
  font-size: 12px;
  color: var(--bf-dim);
  min-width: 36px;
}

/* ── Timeline chips ── */
.bf-timeline {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  flex-shrink: 0;
  overflow-x: auto;
  padding: 6px 0;
}
.bf-timeline-label {
  font-size: 11px;
  color: var(--bf-dim);
  white-space: nowrap;
  padding-top: 4px;
}
.bf-timeline-chips {
  display: flex;
  gap: 4px;
  overflow-x: auto;
  padding-bottom: 2px;
}
.bf-chip {
  white-space: nowrap;
  padding: 4px 12px;
  border-radius: 20px;
  border: 1px solid var(--bf-border);
  background: transparent;
  color: var(--bf-text);
  font-family: var(--bf-font);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.1s;
  flex-shrink: 0;
}
.bf-chip:hover { background: var(--bf-card-bg); border-color: var(--bf-dim); }
.bf-chip-active {
  background: rgba(123,104,238,0.2);
  border-color: var(--bf-accent);
  color: var(--bf-accent);
  box-shadow: 0 0 12px rgba(123,104,238,0.15);
}
.bf-chip-more { color: var(--bf-dim); font-size: 11px; }

/* ── Right panel ── */
.bf-panel {
  width: 340px;
  min-width: 300px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px 14px;
  background: var(--bf-panel);
  border-left: 1px solid var(--bf-border);
  overflow-y: auto;
  flex-shrink: 0;
}

/* Status cards grid */
.bf-status-cards {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.bf-card {
  display: flex;
  gap: 8px;
  padding: 10px 12px;
  border-radius: var(--bf-radius-sm);
  background: var(--bf-card-bg);
  border: 1px solid var(--bf-border);
  transition: all 0.15s;
}
.bf-card-ok { border-left: 3px solid var(--bf-green); }
.bf-card-missing { border-left: 3px solid var(--bf-red); opacity: 0.6; }
.bf-card-warn { border-left: 3px solid #ffa500; }
.bf-card-icon { font-size: 18px; }
.bf-card-body { flex: 1; min-width: 0; }
.bf-card-label { font-size: 10px; text-transform: uppercase; letter-spacing: 1px; color: var(--bf-dim); }
.bf-card-value { font-size: 12px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bf-card-sub { font-size: 10px; color: var(--bf-dim); }

/* Status banner */
.bf-status-banner {
  padding: 8px 14px;
  border-radius: var(--bf-radius-sm);
  font-size: 13px;
  font-weight: 600;
  text-align: center;
}
.bf-ready { background: rgba(0,229,160,0.08); color: var(--bf-green); border: 1px solid rgba(0,229,160,0.2); }
.bf-not-ready { background: rgba(255,69,106,0.08); color: var(--bf-red); border: 1px solid rgba(255,69,106,0.2); }

/* Action buttons */
.bf-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.bf-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px 18px;
  border-radius: var(--bf-radius-sm);
  border: 1px solid var(--bf-border);
  background: var(--bf-card-bg);
  color: var(--bf-text);
  font-family: var(--bf-font);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.12s;
}
.bf-btn:hover { background: var(--bf-panel); border-color: var(--bf-dim); }
.bf-btn:disabled { opacity: 0.4; cursor: default; }
.bf-btn-sm { padding: 6px 12px; font-size: 12px; }
.bf-btn-primary {
  padding: 14px 20px;
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 0.5px;
}
.bf-btn-test {
  background: linear-gradient(135deg, rgba(0,229,160,0.15), rgba(123,104,238,0.10));
  border-color: rgba(0,229,160,0.3);
}
.bf-btn-test:hover:not(:disabled) { border-color: var(--bf-green); box-shadow: var(--bf-glow-green); }
.bf-btn-full {
  background: linear-gradient(135deg, rgba(123,104,238,0.15), rgba(0,229,160,0.08));
  border-color: rgba(123,104,238,0.3);
}
.bf-btn-full:hover:not(:disabled) { border-color: var(--bf-accent); box-shadow: var(--bf-glow-accent); }
.bf-btn-label { flex: 1; }
.bf-btn-icon-small { font-size: 16px; }

/* Render status */
.bf-render-status {
  padding: 10px 12px;
  background: var(--bf-card-bg);
  border-radius: var(--bf-radius-sm);
  border: 1px solid var(--bf-border);
}
.bf-render-bar {
  height: 4px;
  background: var(--bf-border);
  border-radius: 99px;
  margin-bottom: 6px;
  overflow: hidden;
}
.bf-render-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--bf-accent), var(--bf-green));
  border-radius: 99px;
  transition: width 0.3s;
}
.bf-render-text { font-size: 12px; color: var(--bf-dim); margin-bottom: 6px; }
.bf-render-log {
  max-height: 200px;
  overflow-y: auto;
  background: #050510;
  border-radius: 6px;
  padding: 8px;
  margin-top: 6px;
  font-family: 'Consolas', monospace;
  font-size: 10px;
  line-height: 1.4;
  color: var(--bf-dim);
}
.bf-log-line { border-bottom: 1px solid rgba(255,255,255,0.03); padding: 1px 0; }

/* Secondary actions */
.bf-secondary-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

/* Layout dialog */
.bf-layout-dialog {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px;
  background: var(--bf-card-bg);
  border-radius: var(--bf-radius-sm);
  border: 1px solid var(--bf-border);
}
.bf-layout-title { font-size: 12px; font-weight: 600; color: var(--bf-dim); margin-bottom: 4px; }

/* ── Status bar ── */
.bf-statusbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 26px;
  padding: 0 16px;
  font-size: 11px;
  color: var(--bf-dim);
  background: var(--bf-panel);
  border-top: 1px solid var(--bf-border);
  flex-shrink: 0;
}

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--bf-border); border-radius: 99px; }
::-webkit-scrollbar-thumb:hover { background: var(--bf-dim); }
</style>