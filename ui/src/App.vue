
<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'

const apiOk = ref(false)
const apiInfo = ref(null)
const activeJob = ref(null)
const jobLog = ref([])
const jobStatus = ref('idle')
const chapters = ref([])
const buildFiles = ref([])
const lastError = ref('')
const selectedIndex = ref(0)
const logOpen = ref(true)

const manualPath = '_suviren_q_build/chapters.manual.json'

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

const draft = reactive({
  title: '',
  start: '',
  end: ''
})

const statusLabel = computed(() => {
  if (jobStatus.value === 'running') return 'Running'
  if (jobStatus.value === 'done') return 'Done'
  if (jobStatus.value === 'failed') return 'Failed'
  return 'Idle'
})

const selectedChapter = computed(() => chapters.value[selectedIndex.value] || null)

const totalStart = computed(() => {
  if (!chapters.value.length) return 0
  return getStartSeconds(chapters.value[0])
})

const totalEnd = computed(() => {
  if (!chapters.value.length) return 0
  return Math.max(...chapters.value.map(ch => getEndSeconds(ch)))
})

const totalDuration = computed(() => Math.max(1, totalEnd.value - totalStart.value))

const selectedDuration = computed(() => {
  const ch = selectedChapter.value
  if (!ch) return 0
  return Math.max(0, getEndSeconds(ch) - getStartSeconds(ch))
})

const timelineSegments = computed(() => {
  return chapters.value.map((ch, index) => {
    const duration = Math.max(1, getEndSeconds(ch) - getStartSeconds(ch))
    const width = Math.max(1.2, duration / totalDuration.value * 100)
    return { chapter: ch, index, duration, width }
  })
})

const visibleToc = computed(() => {
  if (!chapters.value.length) return []
  const center = selectedIndex.value
  const start = Math.max(0, center - 4)
  const end = Math.min(chapters.value.length, start + 9)
  return chapters.value.slice(start, end).map((chapter, localIndex) => ({
    chapter,
    index: start + localIndex
  }))
})

function parseTimeToSeconds(value) {
  if (value === undefined || value === null || value === '') return 0
  if (typeof value === 'number') return value

  const text = String(value).trim().replace(',', '.')
  if (!text) return 0

  const parts = text.split(':').map(x => x.trim())
  if (parts.length === 3) {
    return Number(parts[0]) * 3600 + Number(parts[1]) * 60 + Number(parts[2])
  }
  if (parts.length === 2) {
    return Number(parts[0]) * 60 + Number(parts[1])
  }

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

function syncDraft() {
  const ch = selectedChapter.value
  if (!ch) {
    draft.title = ''
    draft.start = ''
    draft.end = ''
    return
  }

  draft.title = ch.title || ''
  draft.start = formatClock(getStartSeconds(ch), true)
  draft.end = formatClock(getEndSeconds(ch), true)
}

function selectChapter(index) {
  selectedIndex.value = Math.max(0, Math.min(index, chapters.value.length - 1))
  syncDraft()
}

function applyDraft() {
  const ch = selectedChapter.value
  if (!ch) return

  const start = parseTimeToSeconds(draft.start)
  const end = parseTimeToSeconds(draft.end)

  ch.title = draft.title
  ch.start = formatClock(start, true)
  ch.end = formatClock(end, true)
  ch.start_seconds = start
  ch.end_seconds = end
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
    if (selectedIndex.value >= chapters.value.length) selectedIndex.value = 0
    syncDraft()
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

async function saveManualChapters() {
  try {
    applyDraft()
    const data = await apiPost('/api/save-chapters', {
      path: manualPath,
      chapters: chapters.value
    })
    form.chapters = manualPath
    lastError.value = ''
    jobLog.value = [
      '[suviren-q] manual chapters saved',
      `[path] ${data.path}`,
      `[count] ${data.count}`
    ]
    jobStatus.value = 'done'
    await loadBuildFiles()
  } catch (err) {
    jobStatus.value = 'failed'
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
  applyDraft()
  startJob('/api/preview', {
    cover: form.cover,
    chapters: form.chapters,
    background: form.background || null,
    font: form.font || null
  })
}

function runRender() {
  applyDraft()
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

watch(selectedIndex, syncDraft)

onMounted(async () => {
  await checkApi()
  await loadChapters()
  await loadBuildFiles()
})
</script>

<template>
  <main class="editor-shell" :data-theme="form.theme">
    <header class="topbar">
      <div class="brand">
        <div class="brand-mark">Q</div>
        <div>
          <div class="kicker">suviren-q</div>
          <h1>La Queue Souveraine</h1>
        </div>
      </div>

      <div class="top-actions">
        <div class="status-pill" :class="{ ok: apiOk, bad: !apiOk }">
          <span></span>
          API {{ apiOk ? 'online' : 'offline' }}
        </div>

        <button @click="runInspect">Extract chapters</button>
        <button @click="runPreview">Preview PNG</button>
        <button class="primary" @click="runRender">Render MP4</button>
      </div>
    </header>

    <section class="workspace">
      <aside class="left-panel panel">
        <div class="panel-title">
          <h2>Project</h2>
          <small>sources</small>
        </div>

        <label>
          <span>REAPER .rpp</span>
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

        <div class="field-grid">
          <label>
            <span>Origin</span>
            <select v-model="form.origin">
              <option value="project">project</option>
              <option value="first-chapter">first-chapter</option>
            </select>
          </label>

          <label>
            <span>Offset</span>
            <input v-model="form.offset" type="number" step="0.001" />
          </label>
        </div>

        <label class="checkbox">
          <input v-model="form.add_intro" type="checkbox" />
          <span>Add intro before first chapter</span>
        </label>

        <div class="panel-separator"></div>

        <label>
          <span>Audio</span>
          <input v-model="form.audio" />
        </label>

        <label>
          <span>Cover</span>
          <input v-model="form.cover" />
        </label>

        <label>
          <span>Background</span>
          <input v-model="form.background" placeholder="optional" />
        </label>

        <label>
          <span>Chapters JSON</span>
          <input v-model="form.chapters" />
        </label>

        <label>
          <span>Output MP4</span>
          <input v-model="form.out" />
        </label>

        <label>
          <span>Theme</span>
          <select v-model="form.theme">
            <option value="cyber-zina">cyber-zina</option>
            <option value="imperial-dark">imperial-dark</option>
            <option value="clean-audiobook">clean-audiobook</option>
          </select>
        </label>

        <label>
          <span>Waveform MP4</span>
          <select v-model="form.waveform">
            <option value="ffmpeg">ffmpeg live wave</option>
            <option value="static">static panel only</option>
          </select>
        </label>
      </aside>

      <section class="center-stage">
        <div class="viewer-toolbar">
          <div>
            <div class="kicker">Program monitor</div>
            <strong>{{ selectedChapter ? shortTitle(selectedChapter.title) : 'No chapter' }}</strong>
          </div>

          <div class="viewer-meta">
            <span>{{ chapters.length }} blocks</span>
            <span>{{ formatClock(totalDuration) }}</span>
            <span>{{ statusLabel }}</span>
          </div>
        </div>

        <div class="viewer">
          <div class="video-frame">
            <div class="bg-orb one"></div>
            <div class="bg-orb two"></div>

            <div class="book-cover">
              <div class="cover-inner">
                <div class="cover-label">Intimate Protocol</div>
                <div class="cover-main">ZINA</div>
                <div class="cover-foot">audiobook</div>
              </div>
            </div>

            <div class="now-playing">
              <div class="kicker">Now playing</div>
              <h2>{{ selectedChapter ? shortTitle(selectedChapter.title) : 'Select a chapter on timeline' }}</h2>

              <div class="time-row">
                <span>{{ selectedChapter ? formatClock(getStartSeconds(selectedChapter)) : '00:00:00' }}</span>
                <span>{{ formatClock(selectedDuration) }}</span>
                <span>{{ selectedChapter ? formatClock(getEndSeconds(selectedChapter)) : '00:00:00' }}</span>
              </div>

              <div class="waveform">
                <i v-for="n in 72" :key="n" :style="{ '--i': n }"></i>
              </div>

              <div class="toc-preview">
                <div
                  v-for="item in visibleToc"
                  :key="item.index"
                  class="toc-row"
                  :class="{ active: item.index === selectedIndex }"
                >
                  <b>{{ String(item.index + 1).padStart(2, '0') }}</b>
                  <span>{{ shortTitle(item.chapter.title) }}</span>
                  <em>{{ formatClock(getStartSeconds(item.chapter)) }}</em>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="timeline-panel panel">
          <div class="timeline-head">
            <div>
              <div class="kicker">Timeline</div>
              <strong>Voice track</strong>
            </div>

            <div class="timeline-buttons">
              <button @click="loadChapters">Reload</button>
              <button @click="saveManualChapters">Save manual JSON</button>
            </div>
          </div>

          <div class="time-ruler">
            <span>00:00:00</span>
            <span>{{ formatClock(totalDuration / 4) }}</span>
            <span>{{ formatClock(totalDuration / 2) }}</span>
            <span>{{ formatClock(totalDuration * 0.75) }}</span>
            <span>{{ formatClock(totalDuration) }}</span>
          </div>

          <div class="timeline-scroll">
            <div class="track-row chapters-track">
              <button
                v-for="seg in timelineSegments"
                :key="seg.index"
                class="clip"
                :class="{ active: seg.index === selectedIndex }"
                :style="{ width: seg.width + '%' }"
                @click="selectChapter(seg.index)"
                :title="shortTitle(seg.chapter.title)"
              >
                <span>{{ seg.index + 1 }}</span>
              </button>
            </div>

            <div class="track-row voice-track">
              <div
                v-for="seg in timelineSegments"
                :key="'v' + seg.index"
                class="voice-block"
                :style="{ width: seg.width + '%' }"
              ></div>
            </div>
          </div>
        </div>
      </section>

      <aside class="right-panel panel">
        <div class="panel-title">
          <h2>Inspector</h2>
          <small>chapter {{ selectedIndex + 1 }}</small>
        </div>

        <div v-if="!selectedChapter" class="empty">
          Extract chapters from RPP first.
        </div>

        <template v-else>
          <label>
            <span>Title</span>
            <textarea v-model="draft.title" @change="applyDraft"></textarea>
          </label>

          <div class="field-grid">
            <label>
              <span>Start</span>
              <input v-model="draft.start" @change="applyDraft" />
            </label>

            <label>
              <span>End</span>
              <input v-model="draft.end" @change="applyDraft" />
            </label>
          </div>

          <div class="metric-grid">
            <div>
              <span>Duration</span>
              <b>{{ formatClock(selectedDuration, true) }}</b>
            </div>
            <div>
              <span>Index</span>
              <b>{{ selectedIndex + 1 }} / {{ chapters.length }}</b>
            </div>
          </div>

          <div class="inspector-actions">
            <button @click="selectChapter(selectedIndex - 1)">Prev</button>
            <button @click="selectChapter(selectedIndex + 1)">Next</button>
          </div>

          <button class="wide primary" @click="saveManualChapters">
            Save manual chapters
          </button>

          <div class="panel-separator"></div>

          <div class="file-box">
            <div class="kicker">Build files</div>
            <div v-if="!buildFiles.length" class="empty small">No files yet.</div>
            <div v-for="file in buildFiles.slice(0, 9)" :key="file.path" class="file-row">
              <span>{{ file.path }}</span>
              <em>{{ Math.round(file.size / 1024) }} KB</em>
            </div>
          </div>
        </template>
      </aside>
    </section>

    <section class="log-panel panel" :class="{ collapsed: !logOpen }">
      <button class="log-toggle" @click="logOpen = !logOpen">
        Log: {{ statusLabel }}
      </button>

      <div v-if="logOpen">
        <div v-if="lastError" class="error">{{ lastError }}</div>
        <pre>{{ jobLog.length ? jobLog.join('\n') : 'Ready. Extract chapters or render.' }}</pre>
      </div>
    </section>
  </main>
</template>
