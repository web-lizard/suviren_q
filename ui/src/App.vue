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
