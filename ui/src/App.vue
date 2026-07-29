<template>
  <div class="studio" :class="[`theme-${project.theme}`, `workspace-${activeWorkspace}`, { 'is-loading': loading }]">
    <header class="topbar">
      <div class="brand" aria-label="Book Wunderwaffe Studio">
        <span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i></span>
        <span class="brand-copy">
          <strong>BOOK WUNDERWAFFE STUDIO</strong>
          <small>BOOK · VOICE · VIDEO · v{{ backend.version || '3.0.0' }}</small>
        </span>
      </div>

      <div class="ecosystem-nav">
        <div class="workspace-tabs" role="tablist" aria-label="Рабочий режим">
          <button type="button" role="tab" :aria-selected="activeWorkspace === 'book'"
                  :class="{ active: activeWorkspace === 'book' }" @click="setWorkspace('book')">Книга</button>
          <button type="button" role="tab" :aria-selected="activeWorkspace === 'video'"
                  :class="{ active: activeWorkspace === 'video' }" @click="setWorkspace('video')"
                  @dragover.prevent @drop.prevent="dropBookAudioOnVideoTab">
            {{ videoPreparing ? 'Собираю видео…' : 'Видео' }}
          </button>
        </div>
        <label class="global-project-picker">
          <span>Проект</span>
          <select :value="activeProjectUuid || ''" :disabled="switchingProject" @change="switchProject($event.target.value)">
            <option value="" disabled>{{ projectCatalog.length ? 'Выберите проект' : 'Проекты не найдены' }}</option>
            <option v-for="item in projectCatalog" :key="item.uuid" :value="item.uuid">
              {{ item.title }} · {{ projectKindLabel(item.project_kind) }}
            </option>
          </select>
        </label>
        <button class="ecosystem-new" type="button" @click="createEcosystemProject">＋ Новый проект</button>
        <button class="ecosystem-manage" type="button" title="Управление проектами" @click="openProjectManager">•••</button>
      </div>

      <nav v-if="activeWorkspace === 'video'" class="project-actions" aria-label="Действия с видеопроектом">
        <button class="action-button" type="button" @click="newProject" title="Новый проект">
          <span aria-hidden="true">＋</span><b>Новый</b>
        </button>
        <button class="action-button" type="button" @click="projectInput?.click()" title="Открыть проект">
          <span aria-hidden="true">⌞</span><b>Открыть</b>
        </button>
        <button class="action-button" type="button" :disabled="saving" @click="saveProject()" title="Сохранить проект (Ctrl+S)">
          <span aria-hidden="true">◇</span><b>{{ saving ? 'Сохраняю' : 'Сохранить' }}</b>
        </button>
        <button class="action-button" type="button" @click="assetInput?.click()" title="Добавить аудио, видео или изображение">
          <span aria-hidden="true">↑</span><b>Импорт</b>
        </button>
        <button class="export-button" type="button" :disabled="!canOpenExport" @click="openExport">
          <span aria-hidden="true">↗</span><b>Экспорт</b>
        </button>
      </nav>
      <nav v-else class="project-actions book-actions" aria-label="Действия с книгой">
        <button class="book-icon-action" type="button" title="Новая книга"
                aria-label="Новая книга" @click="createBookProject">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M4 5.5c2.8-.7 5.4-.2 8 1.5v12c-2.6-1.7-5.2-2.2-8-1.5zM20 5.5c-2.8-.7-5.4-.2-8 1.5M17 9v6M14 12h6" />
          </svg>
        </button>
        <button class="book-icon-action" :class="{ saving: bookSaveState === 'saving' }"
                type="button" :disabled="bookSaveState === 'saving'"
                :title="bookSaveState === 'saving' ? 'Сохраняю…' : 'Сохранить'"
                :aria-label="bookSaveState === 'saving' ? 'Сохраняю' : 'Сохранить'"
                @click="saveCurrentChapter()">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M5 3.5h11l3 3V20.5H5zM8 3.5v6h8v-6M8 20.5v-7h8v7" />
          </svg>
        </button>
        <button class="book-icon-action" type="button" :disabled="!activeProjectUuid"
                title="Резервная копия" aria-label="Резервная копия"
                @click="backupActiveProject">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M4 7.5h16v13H4zM3 3.5h18v4H3zM9 11.5h6M12 11.5v5M9.5 14l2.5 2.5 2.5-2.5" />
          </svg>
        </button>
        <button class="book-export-button" type="button" :disabled="!activeProjectRecord?.book"
                @click="openBookExport">
          <span aria-hidden="true">⇩</span><b>Экспорт книги</b>
        </button>
        <button class="export-button" type="button" :disabled="!activeProjectRecord?.book" @click="openBookInVideo">
          <span aria-hidden="true">→</span><b>В видеокнигу</b>
        </button>
      </nav>

      <div class="topbar-status">
        <span class="status-light" :class="backend.online ? 'online' : 'offline'"></span>
        <span class="status-copy">
          <b>{{ backend.online ? 'Движок в сети' : 'Автономный режим' }}</b>
          <small>{{ activeWorkspace === 'book' ? bookSaveLabel : (dirty ? 'Есть изменения' : 'Проект сохранён') }}</small>
        </span>
      </div>

      <input ref="assetInput" class="visually-hidden" type="file" multiple
             accept="audio/*,video/*,image/png,image/jpeg,image/webp,image/gif" @change="onAssetInput" />
      <input ref="musicInput" class="visually-hidden" type="file"
             accept="audio/mpeg,audio/wav,audio/mp4,audio/aac,audio/flac,audio/ogg,audio/opus"
             @change="onMusicInput" />
      <input ref="projectInput" class="visually-hidden" type="file" accept="application/json,.json" @change="onProjectInput" />
      <input ref="bookChapterImageInput" class="visually-hidden" type="file"
             accept="image/png,image/jpeg,image/webp,image/bmp,image/gif"
             @change="onBookChapterImageInput" />
    </header>

    <main v-if="activeWorkspace === 'video'" class="workspace">
      <aside class="materials-panel panel-shell">
        <div class="panel-heading">
          <div>
            <span class="eyebrow">Библиотека</span>
            <h2>Материалы</h2>
          </div>
          <span class="count-badge">{{ project.materials.length }}</span>
        </div>

        <button class="drop-zone" type="button" @click="assetInput?.click()"
                @dragover.prevent @drop.prevent="onDrop">
          <span class="drop-icon" aria-hidden="true">＋</span>
          <span><b>Добавить файлы</b><small>или перетащить сюда</small></span>
        </button>

        <div v-if="project.materials.length" class="material-list">
          <button v-for="asset in project.materials" :key="asset.id" type="button"
                  class="material-row"
                  :class="{ active: selection.type === 'asset' && selection.id === asset.id }"
                  @click="select('asset', asset.id)">
            <span class="material-kind" :class="asset.type">{{ materialCode(asset.type) }}</span>
            <span class="material-copy">
              <b>{{ asset.name }}</b>
              <small>{{ materialRole(asset) || materialLabel(asset.type) }}</small>
              <span v-if="asset.status === 'uploading'" class="upload-track">
                <i :style="{ width: `${Math.round((asset.progress || 0) * 100)}%` }"></i>
              </span>
            </span>
            <span class="material-state" :class="asset.status" :title="assetStatus(asset)"></span>
          </button>
        </div>

        <div v-else class="empty-library">
          <span class="empty-wave" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span>
          <p>Начните с аудиокниги.<br />Обложку и фон можно добавить позже.</p>
        </div>

        <div class="library-summary">
          <span><i class="mini-dot audio"></i>{{ audioAsset ? 'Аудио готово' : 'Нет аудио' }}</span>
          <span><i class="mini-dot cover"></i>{{ coverAsset ? 'Обложка готова' : 'Нет обложки' }}</span>
        </div>
      </aside>

      <section class="stage-column">
        <div class="stage-toolbar">
          <div class="stage-context">
            <span class="eyebrow">Предпросмотр · 16:9</span>
            <strong>{{ project.title || 'Новая аудиокнига' }}</strong>
          </div>
          <div class="chapter-context" v-if="currentChapter">
            <p><b>{{ currentChapter.title }}</b></p>
          </div>
          <div class="stage-quick-actions">
            <span class="video-sync-count" :class="{ ready: videoReadyChapterCount > 0 }">
              Озвучено {{ videoReadyChapterCount }}/{{ videoBookChapterCount }}
            </span>
            <label class="caption-quick-toggle" :class="{ active: project.captions?.enabled }">
              <input v-model="project.captions.enabled" type="checkbox" />
              <span aria-hidden="true">Аа</span>
              <b>Текст на экране</b>
            </label>
          </div>
        </div>

        <div ref="sceneEl" class="scene-frame" :class="{ 'glitch-enabled': project.glitch }"
             @pointerdown.self="select('project')">
          <div class="scene-backdrop" :style="backgroundStyle"></div>
          <video v-if="videoSource" ref="videoEl" class="scene-video" :src="videoSource" playsinline
                 crossorigin="anonymous" preload="metadata" :muted="masterKind === 'audio'"
                 :loop="masterKind === 'audio'"
                 @loadedmetadata="onMediaMetadata('video')" @timeupdate="onMediaTime('video')"
                 @play="onMediaPlay('video')" @pause="onMediaPause('video')"
                 @ended="onMediaEnded('video')" @error="onMediaError('video')"></video>
          <div class="scene-grade"></div>
          <div class="scene-grid" aria-hidden="true"></div>
          <div v-if="project.glitch" class="glitch-scan" aria-hidden="true"></div>

          <button v-if="layerVisible('cover')" type="button" class="composition-layer cover-layer"
                  :class="{ selected: selection.type === 'layer' && selection.id === 'cover' }"
                  :style="layerStyle('cover')" @pointerdown.stop="onLayerPointerDown('cover', $event)">
            <img v-if="coverSource" :src="coverSource" alt="Обложка книги" />
            <span v-else class="cover-placeholder"><i>BW</i><b>ОБЛОЖКА</b><small>добавьте изображение</small></span>
          </button>

          <button v-if="layerVisible('title')" ref="titleLayerEl" type="button" class="composition-layer title-layer"
                  :class="{ selected: selection.type === 'layer' && selection.id === 'title' }"
                  :style="layerStyle('title')" @pointerdown.stop="onLayerPointerDown('title', $event)">
            <span ref="titleStackEl" class="chapter-stack" lang="ru">
              <span v-if="previousChapter" class="chapter-neighbor previous" aria-hidden="true">
                <b>{{ previousChapter.title }}</b>
              </span>
              <strong>{{ currentChapter?.title || 'Добавьте первую главу' }}</strong>
              <span v-if="nextChapter" class="chapter-neighbor next" aria-hidden="true">
                <b>{{ nextChapter.title }}</b>
              </span>
            </span>
          </button>

          <button v-if="project.captions?.enabled && layerVisible('caption') && currentReadingCaption"
                  type="button" class="composition-layer reading-caption"
                  :class="{ selected: selection.type === 'layer' && selection.id === 'caption' }"
                  :style="layerStyle('caption')" aria-live="off"
                  title="Перетащите текст в нужное место"
                  @pointerdown.stop="onLayerPointerDown('caption', $event)">
            {{ currentReadingCaption }}
          </button>

          <div v-if="videoPreparing" class="video-prepare-overlay">
            <i></i><b>Собираю озвученные главы</b><span>Создаю мастер-аудио и таймлайн…</span>
          </div>
          <div v-else-if="!audioAsset && activeProjectRecord?.book" class="video-empty-audio">
            <b>В книге пока нет готовой озвучки</b>
            <span>Озвучьте хотя бы одну главу — она автоматически появится здесь.</span>
            <button type="button" @click="setWorkspace('book')">Перейти к озвучке</button>
          </div>

          <a class="telegram-qr" :href="TELEGRAM_URL" target="_blank" rel="noopener noreferrer"
             title="Telegram · Temple of Lizard" draggable="false" @pointerdown.stop @click.stop>
            <span class="telegram-qr-code">
              <QrcodeVue :value="TELEGRAM_URL" :size="256" level="H" render-as="svg"
                          foreground="#17131d" background="#f4efe7" />
            </span>
            <span class="telegram-qr-copy"><b>TELEGRAM</b><small>@temple_of_lizard</small></span>
          </a>

          <button v-if="layerVisible('visualizer')" type="button" class="composition-layer visualizer-layer"
                  :class="{ selected: selection.type === 'layer' && selection.id === 'visualizer' }"
                  :style="layerStyle('visualizer')" @pointerdown.stop="onLayerPointerDown('visualizer', $event)">
            <canvas ref="visualizerCanvas" aria-label="Визуализация аудио"></canvas>
          </button>

          <div class="scene-corner scene-corner-bottom">
            <span>{{ formatTime(currentTime) }}</span>
            <div><i :style="{ width: `${progressPercent}%` }"></i></div>
            <span>{{ formatTime(duration) }}</span>
          </div>
        </div>

        <div class="transport" :class="{ disabled: !masterKind }">
          <button type="button" class="transport-button seek-button" :disabled="!masterKind" @click="seekBy(-15)" title="Назад на 15 секунд">−15</button>
          <button type="button" class="transport-button play-button" :disabled="!masterKind" @click="togglePlay" :title="playing ? 'Пауза' : 'Воспроизвести'">
            <span v-if="playing" class="pause-icon" aria-hidden="true"><i></i><i></i></span>
            <span v-else class="play-icon" aria-hidden="true"></span>
          </button>
          <button type="button" class="transport-button stop-button" :disabled="!masterKind" @click="stopPlayback" title="Остановить"><span aria-hidden="true"></span></button>
          <button type="button" class="transport-button seek-button" :disabled="!masterKind" @click="seekBy(15)" title="Вперёд на 15 секунд">+15</button>
          <span class="transport-time current">{{ formatTime(currentTime, true) }}</span>
          <input class="transport-scrubber" type="range" min="0" :max="Math.max(duration, 0.01)" step="0.01"
                 :value="currentTime" :disabled="!masterKind" aria-label="Позиция воспроизведения" @input="seekTo(Number($event.target.value))" />
          <span class="transport-time">{{ formatTime(duration, true) }}</span>
          <label class="volume-control" title="Громкость">
            <span aria-hidden="true">◖</span>
            <input type="range" min="0" max="1" step="0.01" v-model.number="volume" @input="applyVolume" />
          </label>
          <audio :key="audioSource || 'audio-empty'" ref="audioEl" :src="audioSource" crossorigin="anonymous" preload="metadata"
                 @loadedmetadata="onMediaMetadata('audio')" @timeupdate="onMediaTime('audio')"
                 @play="onMediaPlay('audio')" @pause="onMediaPause('audio')"
                 @ended="onMediaEnded('audio')" @error="onMediaError('audio')"></audio>
          <audio ref="musicEl" :src="musicSource" crossorigin="anonymous" preload="metadata"
                 :loop="project.music.loop" @loadedmetadata="onMusicMetadata"
                 @play="musicPreviewPlaying = true" @pause="musicPreviewPlaying = false"
                 @error="onMusicError"></audio>
        </div>
      </section>

      <aside class="properties-panel panel-shell">
        <div class="panel-heading properties-heading">
          <div>
            <span class="eyebrow">Инспектор</span>
            <h2>{{ inspectorTitle }}</h2>
          </div>
          <button v-if="selection.type !== 'project'" type="button" class="back-button" @click="select('project')" title="К проекту">↩</button>
        </div>

        <div class="inspector-scroll">
          <template v-if="selection.type === 'project'">
            <label class="field-label">Название книги
              <input v-model.trim="project.title" type="text" placeholder="Название" />
            </label>
            <label class="field-label">Автор
              <input v-model.trim="project.author" type="text" placeholder="Имя автора" />
            </label>
            <label class="field-label">Характер оформления
              <select v-model="project.theme">
                <option value="amber">Тёплый графит</option>
                <option value="violet">Ночной фиолетовый</option>
                <option value="mono">Монохром</option>
              </select>
            </label>

            <div class="inspector-section">
              <span class="section-title">Сцена</span>
              <label class="switch-row">
                <span><b>Glitch-фон</b><small>Тонкие цифровые смещения</small></span>
                <input v-model="project.glitch" type="checkbox" /><i></i>
              </label>
              <label class="switch-row">
                <span><b>Визуализатор</b><small>Реагирует на воспроизведение</small></span>
                <input v-model="project.layers.visualizer.visible" type="checkbox" /><i></i>
              </label>
              <label class="switch-row">
                <span><b>Текст озвучки</b><small>Показывать читаемый фрагмент на экране и в MP4</small></span>
                <input v-model="project.captions.enabled" type="checkbox" /><i></i>
              </label>
            </div>

            <button type="button" class="music-summary-card" :class="{ ready: musicAsset }" @click="select('music')">
              <span aria-hidden="true">♫</span>
              <span>
                <b>{{ musicAsset ? 'Музыка проекта' : 'Добавить музыку' }}</b>
                <small>{{ musicAsset ? `${musicAsset.name} · громкость ${Math.round(project.music.volume * 100)}%` : 'Громкость и эквалайзер' }}</small>
              </span>
              <i>Настроить →</i>
            </button>

            <div class="project-readiness">
              <span class="section-title">Готовность</span>
              <div><i :class="{ done: !!audioAsset }"></i><span>Аудио</span><b>{{ audioAsset ? 'готово' : 'нужно' }}</b></div>
              <div><i :class="{ done: !!coverAsset }"></i><span>Обложка</span><b>{{ coverAsset ? 'готово' : 'нужно' }}</b></div>
              <div><i :class="{ done: project.chapters.length > 0 }"></i><span>Главы</span><b>{{ project.chapters.length || 'нужно' }}</b></div>
            </div>
          </template>

          <template v-else-if="selection.type === 'music'">
            <div class="music-mixer music-mixer-dedicated">
              <div class="mixer-heading">
                <span class="section-title">Музыкальная дорожка</span>
                <button type="button" @click="musicInput?.click()">＋ Добавить файл</button>
              </div>
              <label class="field-label">Файл музыки
                <select v-model="project.musicAssetId" @change="onMusicSelectionChanged">
                  <option :value="null">Без музыки</option>
                  <option v-for="asset in musicCandidates" :key="asset.id" :value="asset.id">{{ asset.name }}</option>
                </select>
              </label>
              <template v-if="musicAsset">
                <div class="music-volume-card">
                  <div>
                    <span>Громкость музыки</span>
                    <output>{{ Math.round(project.music.volume * 100) }}%</output>
                  </div>
                  <input v-model.number="project.music.volume" type="range" min="0" max="1" step="0.01"
                         aria-label="Громкость музыки" @input="onMusicControlInput(false)" />
                  <div class="music-volume-presets">
                    <button type="button" @click="setMusicVolume(0.08)">Тихо · 8%</button>
                    <button type="button" @click="setMusicVolume(0.16)">Фон · 16%</button>
                    <button type="button" @click="setMusicVolume(0.3)">Громче · 30%</button>
                  </div>
                  <button type="button" class="music-preview-button" @click="toggleMusicPreview">
                    {{ musicPreviewPlaying ? '■ Остановить пробу' : '▶ Проверить музыку' }}
                  </button>
                </div>
                <label class="switch-row">
                  <span><b>Музыка включена</b><small>Смешивать с озвучкой в MP4</small></span>
                  <input v-model="project.music.enabled" type="checkbox" @change="applyMusicMix" /><i></i>
                </label>
                <label class="switch-row">
                  <span><b>Повторять по кругу</b><small>На всю длину книги</small></span>
                  <input v-model="project.music.loop" type="checkbox" /><i></i>
                </label>
                <div class="simple-eq">
                  <span class="section-title">Эквалайзер</span>
                  <div class="music-eq-status" :class="{ active: musicEqState.active, error: musicEqState.error }">
                    <i></i><span>{{ musicEqState.message }}</span>
                  </div>
                  <label v-for="band in MUSIC_EQ_BANDS" :key="band.key">
                    <span><b>{{ band.label }}</b><output>{{ formatDb(project.music[band.key]) }}</output></span>
                    <input v-model.number="project.music[band.key]" type="range" min="-12" max="12" step="1"
                           @input="onMusicControlInput(true)" />
                  </label>
                  <small class="music-export-note">В экспортируемом MP4 эквалайзер применяется движком FFmpeg независимо от предпросмотра.</small>
                </div>
                <button type="button" class="jump-button" @click="resetMusicMix">Сбросить громкость и EQ</button>
              </template>
              <div v-else class="music-empty-state">
                <span aria-hidden="true">♫</span>
                <b>Музыка ещё не добавлена</b>
                <p>Выберите MP3, WAV, M4A, FLAC, OGG или OPUS. Файл появится на отдельной зелёной дорожке.</p>
                <button type="button" @click="musicInput?.click()">Выбрать музыку</button>
              </div>
            </div>
          </template>

          <template v-else-if="selectedAsset">
            <div class="asset-preview" :class="selectedAsset.type">
              <img v-if="selectedAsset.type === 'image'" :src="assetUrl(selectedAsset)" alt="" />
              <span v-else>{{ materialCode(selectedAsset.type) }}</span>
            </div>
            <div class="asset-meta">
              <strong>{{ selectedAsset.name }}</strong>
              <span>{{ materialLabel(selectedAsset.type) }}<i></i>{{ formatBytes(selectedAsset.size) }}</span>
            </div>
            <div class="role-actions" v-if="selectedAsset.type === 'image'">
              <button type="button" :class="{ active: project.coverAssetId === selectedAsset.id }" @click="assignAsset('cover', selectedAsset.id)">Как обложку</button>
              <button type="button" :class="{ active: project.backgroundAssetId === selectedAsset.id }" @click="assignAsset('background', selectedAsset.id)">Как фон</button>
            </div>
            <div class="role-actions" v-else-if="selectedAsset.type === 'audio'">
              <button type="button" :class="{ active: project.audioAssetId === selectedAsset.id }" @click="assignAsset('audio', selectedAsset.id)">Основная озвучка</button>
              <button type="button" :class="{ active: project.musicAssetId === selectedAsset.id }" @click="assignAsset('music', selectedAsset.id)">Музыка</button>
            </div>
            <button v-if="project.musicAssetId === selectedAsset.id" type="button" class="open-music-mixer" @click="select('music')">
              ♫ Настроить громкость и эквалайзер
            </button>
            <div class="role-actions" v-else-if="selectedAsset.type === 'video'">
              <button type="button" class="wide" :class="{ active: project.videoAssetId === selectedAsset.id }" @click="assignAsset('video', selectedAsset.id)">Видео сцены</button>
            </div>
            <p v-if="selectedAsset.status === 'uploading'" class="sync-note">Синхронизация с движком: {{ Math.round((selectedAsset.progress || 0) * 100) }}%</p>
            <p v-else-if="selectedAsset.status === 'local'" class="sync-note warning">Файл доступен для предпросмотра, но экспорт потребует запущенный backend.</p>
            <button type="button" class="danger-button" @click="removeAsset(selectedAsset.id)">Убрать из проекта</button>
          </template>

          <template v-else-if="selectedChapter">
            <label class="field-label">Название главы
              <input v-model.trim="selectedChapter.title" type="text" />
            </label>
            <label class="field-label">Начало
              <input :value="formatTimecode(selectedChapter.start_seconds)" type="text" placeholder="00:00:00"
                     @change="updateChapterStart(selectedChapter, $event.target.value)" />
            </label>
            <div class="readonly-row"><span>Конец</span><b>{{ formatTimecode(chapterEnd(selectedChapter.id)) }}</b></div>
            <div class="readonly-row"><span>Длительность</span><b>{{ formatTime(chapterEnd(selectedChapter.id) - selectedChapter.start_seconds, true) }}</b></div>
            <label class="field-label">Изображение главы
              <select v-model="selectedChapter.imageAssetId">
                <option :value="null">Общий фон проекта</option>
                <option v-for="image in imageAssets" :key="image.id" :value="image.id">{{ image.name }}</option>
              </select>
            </label>
            <button type="button" class="jump-button" @click="seekTo(selectedChapter.start_seconds)">Перейти к главе</button>
            <button type="button" class="danger-button" @click="removeChapter(selectedChapter.id)">Удалить главу</button>
          </template>

          <template v-else-if="selectedScene">
            <label class="field-label">Название сцены
              <input v-model.trim="selectedScene.name" type="text" />
            </label>
            <div class="field-grid">
              <label class="field-label">Начало
                <input :value="formatTimecode(selectedScene.start)" type="text" @change="updateSceneTime('start', $event.target.value)" />
              </label>
              <label class="field-label">Конец
                <input :value="formatTimecode(selectedScene.end)" type="text" @change="updateSceneTime('end', $event.target.value)" />
              </label>
            </div>
            <label class="field-label">Фон сцены
              <select v-model="selectedScene.backgroundAssetId">
                <option :value="null">Фон проекта</option>
                <option v-for="image in imageAssets" :key="image.id" :value="image.id">{{ image.name }}</option>
              </select>
            </label>
            <button type="button" class="jump-button" @click="seekTo(selectedScene.start)">Перейти к сцене</button>
            <button type="button" class="danger-button" :disabled="project.scenes.length <= 1" @click="removeScene(selectedScene.id)">Удалить сцену</button>
          </template>

          <template v-else-if="selectedLayer">
            <label class="switch-row solo-switch">
              <span><b>Слой видим</b><small>{{ layerLabel(selection.id) }}</small></span>
              <input v-model="selectedLayer.visible" type="checkbox" /><i></i>
            </label>
            <div class="field-grid geometry-grid">
              <label class="field-label">X, %<input v-model.number="selectedLayer.x" type="number" min="0" max="100" step="0.5" /></label>
              <label class="field-label">Y, %<input v-model.number="selectedLayer.y" type="number" min="0" max="100" step="0.5" /></label>
              <label class="field-label">Ширина, %<input v-model.number="selectedLayer.w" type="number" min="5" max="100" step="0.5" /></label>
              <label class="field-label">Высота, %<input v-model.number="selectedLayer.h" type="number" min="5" max="100" step="0.5" /></label>
            </div>
            <template v-if="selection.id === 'title'">
              <label class="field-label">Размер текста
                <input v-model.number="selectedLayer.fontSize" type="range" min="24" max="72" step="1" />
              </label>
              <label class="field-label color-field">Цвет заголовка
                <input v-model="selectedLayer.color" type="color" />
                <span>{{ selectedLayer.color }}</span>
              </label>
            </template>
            <template v-if="selection.id === 'caption'">
              <p class="layer-drag-hint">Текст можно перетаскивать мышью прямо по кадру.</p>
              <label class="field-label">Размер текста
                <input v-model.number="selectedLayer.fontSize" type="range" min="16" max="48" step="1" />
              </label>
              <label class="field-label">Начертание
                <select v-model.number="selectedLayer.fontWeight">
                  <option :value="300">Тонкое</option>
                  <option :value="400">Обычное</option>
                  <option :value="500">Среднее</option>
                </select>
              </label>
              <label class="field-label">Плотность подложки
                <input v-model.number="selectedLayer.backgroundOpacity" type="range" min="0" max="0.9" step="0.05" />
              </label>
            </template>
            <button type="button" class="jump-button" @click="resetLayer(selection.id)">Вернуть положение</button>
          </template>
        </div>
      </aside>
    </main>

    <main v-else class="book-workspace" :class="`inspector-${bookInspectorState}`">
      <aside v-if="activeProjectRecord?.book" class="book-chapters panel-shell">
        <div class="panel-heading">
          <div><span class="eyebrow">Структура</span><h2>Главы</h2></div>
          <span class="count-badge">{{ filteredBookChapters.length }}</span>
        </div>
        <label class="book-search">
          <span>⌕</span>
          <input v-model.trim="bookSearch" type="search" placeholder="Поиск по книге" />
        </label>
        <div class="chapter-book-list">
          <button v-for="chapter in filteredBookChapters" :key="chapter.id" type="button"
                  :class="{ active: currentBookChapter?.id === chapter.id }"
                  @click="selectBookChapter(chapter.id)">
            <span>{{ chapter.position + 1 }}</span>
            <b>{{ chapter.title }}</b>
            <small>{{ chapter.content.length.toLocaleString('ru-RU') }} зн.</small>
            <i class="chapter-audio-state"
               :class="chapterAudioState(chapter)"
               :title="chapterAudioStateLabel(chapter)"></i>
          </button>
        </div>
        <div class="chapter-list-actions">
          <button type="button" @click="createBookChapter">＋ Глава</button>
          <button type="button" :disabled="!currentBookChapter" @click="moveBookChapter(-1)">↑</button>
          <button type="button" :disabled="!currentBookChapter" @click="moveBookChapter(1)">↓</button>
          <button type="button" :disabled="!currentBookChapter" title="Дублировать главу" @click="duplicateBookChapter">⧉</button>
          <button class="danger" type="button" :disabled="!currentBookChapter" @click="archiveBookChapter">Удалить</button>
        </div>
      </aside>

      <section v-if="activeProjectRecord?.book" class="book-editor-column">
        <header class="book-editor-header">
          <div>
            <span class="eyebrow">{{ activeProjectRecord.book.author || activeProjectRecord.author || 'Без автора' }}</span>
            <h1>{{ activeProjectRecord.book.title }}</h1>
          </div>
          <div class="book-editor-head-actions">
            <span class="book-save-indicator" :class="bookSaveState"><i></i>{{ bookSaveLabel }}</span>
            <button v-if="bookInspectorState === 'hidden'" type="button" @click="setBookInspectorState('open')">Настройки</button>
          </div>
        </header>
        <template v-if="currentBookChapter">
          <input v-model="bookChapterTitle" class="book-chapter-title" type="text"
                 aria-label="Название главы" @input="markBookDirty" />
          <textarea ref="bookTextEditor" v-model="bookChapterContent" class="book-text-editor"
                    spellcheck="true" aria-label="Текст главы"
                    placeholder="Начните писать…" @input="markBookDirty"></textarea>
          <div v-if="bookPlayerAsset" class="book-audio-player"
               :draggable="!bookPlayerAsset.temporary"
               @dragstart="startBookAudioDrag(bookPlayerAsset, $event)">
            <div class="book-player-copy">
              <small>{{ bookPlayerAsset.temporary ? 'Проба голоса' : 'Озвучка главы' }}</small>
              <b>{{ bookPlayerTitle }}</b>
              <span>{{ formatTime(bookPlayerDuration, true) }} · {{ voiceShortLabel(bookPlayerAsset.voice) }}</span>
            </div>
            <audio ref="bookAudioEl" :src="bookPlayerUrl" controls preload="metadata"
                   @loadedmetadata="onBookAudioMetadata" @timeupdate="onBookAudioTime"
                   @play="bookPlayerPlaying = true" @pause="bookPlayerPlaying = false"
                   @ended="bookPlayerPlaying = false"></audio>
            <button type="button" :disabled="!previousChapterAudio" title="Предыдущая версия" @click="selectAdjacentChapterAudio(-1)">‹</button>
            <button type="button" :disabled="!nextChapterAudio" title="Следующая версия" @click="selectAdjacentChapterAudio(1)">›</button>
            <button v-if="!bookPlayerAsset.temporary" class="book-player-video" type="button"
                    title="Передать эту озвучку в видео"
                    @click="sendBookAudioToVideo(bookPlayerAsset)">→ В видео</button>
          </div>
          <footer class="book-editor-footer">
            <span>{{ bookWordCount.toLocaleString('ru-RU') }} слов</span>
            <span>{{ bookChapterContent.length.toLocaleString('ru-RU') }} символов</span>
            <span v-if="currentChapterAudio" :class="{ stale: currentChapterAudio.is_stale }">
              {{ currentChapterAudio.is_stale ? 'Озвучка устарела' : 'Озвучка актуальна' }}
            </span>
          </footer>
        </template>
        <div v-else class="book-empty-chapter">
          <span>✦</span><h2>У книги пока нет глав</h2>
          <p>Создайте первую главу и сразу начинайте писать.</p>
          <button type="button" @click="createBookChapter">Создать главу</button>
        </div>
      </section>

      <aside v-if="activeProjectRecord?.book && bookInspectorState !== 'hidden'"
             class="book-inspector panel-shell" :class="{ collapsed: bookInspectorState === 'collapsed' }">
        <button v-if="bookInspectorState === 'collapsed'" class="book-inspector-rail" type="button"
                @click="setBookInspectorState('open')"><span>Настройки</span></button>
        <template v-else>
          <div class="panel-heading">
            <div><span class="eyebrow">Книга</span><h2>Инспектор</h2></div>
            <div class="inspector-toggle-actions">
              <button type="button" title="Свернуть" @click="setBookInspectorState('collapsed')">›</button>
              <button type="button" title="Скрыть" @click="setBookInspectorState('hidden')">×</button>
            </div>
          </div>
          <div class="book-inspector-scroll">
            <details>
              <summary>Книга</summary>
              <label class="field-label">Название
                <input v-model="bookMetadata.title" type="text" @change="saveBookMetadata" />
              </label>
              <label class="field-label">Автор
                <input v-model="bookMetadata.author" type="text" @change="saveBookMetadata" />
              </label>
              <label class="field-label">Описание
                <textarea v-model="bookMetadata.description" rows="4" @change="saveBookMetadata"></textarea>
              </label>
            </details>

            <details open>
              <summary>Изображение главы</summary>
              <div class="book-chapter-image-panel">
                <div class="book-chapter-image-preview"
                     :style="currentBookChapterImageUrl ? { backgroundImage: `url('${currentBookChapterImageUrl}')` } : {}">
                  <span v-if="!currentBookChapterImageUrl">У главы пока нет отдельной картинки</span>
                </div>
                <p>В видеокниге изображение этой главы заменит общий фон на время её озвучки.</p>
                <div>
                  <button class="book-primary" type="button" :disabled="!currentBookChapter"
                          @click="bookChapterImageInput?.click()">
                    {{ currentBookChapterImage ? 'Заменить картинку' : 'Выбрать картинку' }}
                  </button>
                  <button v-if="currentBookChapterImage" class="book-secondary" type="button"
                          @click="removeBookChapterImage">Убрать</button>
                </div>
              </div>
            </details>

            <details open>
              <summary>Озвучка</summary>
              <div class="book-tts-panel">
                <p class="tts-runtime-state" :class="{ unavailable: !ttsRuntime.available }">
                  <i></i>{{ ttsRuntime.message || 'Проверяю компонент озвучки…' }}
                </p>
                <div class="voice-filters">
                  <input v-model.trim="voiceSearch" type="search" placeholder="Поиск голоса" />
                  <select v-model="voiceLanguage">
                    <option value="">Все языки</option>
                    <option v-for="language in voiceLanguages" :key="language" :value="language">{{ language.toUpperCase() }}</option>
                  </select>
                </div>
                <label class="field-label">Голос
                  <select v-model="bookTts.voice" @change="saveBookTtsSettings">
                    <option v-for="voice in filteredTtsVoices" :key="voice.id" :value="voice.id">
                      {{ voiceLabel(voice) }}
                    </option>
                  </select>
                </label>
                <div class="field-grid">
                  <label class="field-label">Скорость
                    <select v-model="bookTts.rate" @change="saveBookTtsSettings">
                      <option v-for="preset in RATE_PRESETS" :key="preset.value" :value="preset.value">{{ preset.label }} · {{ preset.value }}</option>
                    </select>
                  </label>
                  <label class="field-label">Высота тона
                    <select v-model="bookTts.pitch" @change="saveBookTtsSettings">
                      <option v-for="preset in PITCH_PRESETS" :key="preset.value" :value="preset.value">{{ preset.label }} · {{ preset.value }}</option>
                    </select>
                  </label>
                </div>
                <label class="field-label">Громкость синтеза
                  <select v-model="bookTts.volume" @change="saveBookTtsSettings">
                    <option v-for="preset in VOLUME_PRESETS" :key="preset.value" :value="preset.value">{{ preset.label }} · {{ preset.value }}</option>
                  </select>
                </label>
                <div class="book-tts-actions">
                  <button class="book-secondary" type="button" :disabled="previewLoading || !ttsRuntime.available" @click="previewBookVoice">
                    {{ previewLoading ? 'Создаю пробу…' : 'Проба голоса' }}
                  </button>
                  <button class="book-primary" type="button" :disabled="!currentBookChapter || activeTtsJobRunning || !ttsRuntime.available" @click="narrateCurrentChapter">
                    {{ activeTtsJobRunning ? 'Озвучивание идёт…' : 'Озвучить главу' }}
                  </button>
                  <button class="book-secondary" type="button" :disabled="activeTtsJobRunning || !ttsRuntime.available" @click="narrateWholeBook">
                    Озвучить всю книгу
                  </button>
                </div>
                <div v-if="ttsProgressState.active" class="tts-progress-card">
                  <div class="tts-progress-heading">
                    <span><i></i><b>Озвучивание</b></span>
                    <strong>{{ ttsProgressState.percent }}%</strong>
                  </div>
                  <div class="tts-progress-track">
                    <i :style="{ width: `${ttsProgressState.percent}%` }"></i>
                  </div>
                  <p>{{ ttsProgressState.detail }}</p>
                  <small>Прошло {{ formatTime(ttsProgressState.elapsed, true) }}</small>
                </div>
                <p v-else-if="latestTtsJob" class="book-job-state" :class="latestTtsJob.status">
                  {{ ttsJobLabel(latestTtsJob) }}
                  <button v-if="latestTtsJob.status === 'failed'" type="button" @click="narrateCurrentChapter">Повторить</button>
                  <button v-if="latestTtsJob.status === 'failed'" type="button" @click="openTtsLog">Технический лог</button>
                </p>
                <div v-if="visibleTtsJobs.length > 1" class="tts-batch-list">
                  <span v-for="job in visibleTtsJobs.slice(0, 12)" :key="job.uuid" :class="job.status">
                    <b>{{ chapterTitleForJob(job) }}</b><i>{{ ttsJobShortLabel(job.status) }}</i>
                  </span>
                </div>
              </div>
            </details>

            <details open>
              <summary>Аудио · {{ currentChapterAudios.length }}</summary>
              <div class="book-audio-list">
                <p v-if="!currentChapterAudios.length" class="book-audio-empty">
                  У текущей главы пока нет озвучки. Выберите голос и создайте первую версию.
                </p>
                <article v-for="asset in currentChapterAudios" :key="asset.id" draggable="true"
                         @dragstart="startBookAudioDrag(asset, $event)"
                         :class="{ active: asset.is_active, stale: asset.is_stale, selected: selectedBookAudioId === asset.id }">
                  <button class="audio-version-main" type="button" @click="selectBookAudio(asset, true)">
                    <span><b>{{ asset.title || `Версия ${asset.version_number}` }}</b><i v-if="asset.is_active">активная</i></span>
                    <small>{{ formatProjectDate(asset.created_at) }} · {{ voiceShortLabel(asset.voice) }}</small>
                    <small>{{ asset.rate }} · {{ pitchPresetLabel(asset.pitch) }} · {{ formatTime(asset.duration || 0, true) }}</small>
                    <em v-if="asset.is_stale">Озвучка устарела</em>
                  </button>
                  <div class="audio-version-actions">
                    <button type="button" title="Воспроизвести" @click="selectBookAudio(asset, true)">▶</button>
                    <button type="button" :disabled="asset.is_active" title="Сделать активной" @click="activateBookAudio(asset)">✓</button>
                    <button type="button" title="Переименовать" @click="renameBookAudio(asset)">✎</button>
                    <button type="button" title="Открыть папку" @click="openBookAudioFolder(asset)">⌞</button>
                    <button type="button" title="Передать в видео" @click="sendBookAudioToVideo(asset)">→</button>
                    <button class="danger" type="button" title="Удалить версию" @click="deleteBookAudio(asset)">×</button>
                  </div>
                </article>
              </div>
            </details>

            <details>
              <summary>Экспорт</summary>
              <div class="book-inspector-export">
                <button class="book-primary" type="button" @click="openBookExport">⇩ Скачать книгу</button>
                <button class="book-secondary" type="button" @click="openBookInVideo">Передать в видеоредактор</button>
              </div>
            </details>
            <details>
              <summary>Техническое</summary>
              <button class="book-secondary" type="button" @click="openTtsLog">Открыть журнал TTS</button>
              <p class="technical-note">Интерпретатор: {{ backend.python || 'не определён' }}</p>
            </details>
          </div>
        </template>
      </aside>

      <section v-else class="book-missing">
        <span class="loading-mark"><i></i><i></i><i></i></span>
        <h1>{{ activeProjectRecord ? 'У этого видеопроекта нет текстовой книги' : 'Выберите проект' }}</h1>
        <p v-if="activeProjectRecord">Текстовую часть можно добавить, не затрагивая существующий таймлайн и медиа.</p>
        <button v-if="activeProjectRecord" type="button" @click="createBookPart">Создать текстовую часть</button>
        <button v-else type="button" @click="createBookProject">Новая книга</button>
      </section>
    </main>

    <section v-if="activeWorkspace === 'video'" class="timeline-panel">
      <div class="timeline-toolbar">
        <div class="timeline-title">
          <span class="eyebrow">Монтаж</span>
          <strong>Таймлайн</strong>
          <span>{{ formatTime(duration, true) }}</span>
        </div>
        <div class="timeline-actions">
          <button type="button" class="music-mixer-shortcut"
                  :class="{ active: selection.type === 'music', empty: !musicAsset }"
                  @click="select('music')">
            <span>♫</span>{{ musicAsset ? `Музыка · ${Math.round(project.music.volume * 100)}%` : 'Добавить музыку' }}
          </button>
          <button type="button" @click="addChapterAtCursor"><span>＋</span> Глава</button>
          <button type="button" @click="addSceneAtCursor"><span>＋</span> Сцена</button>
          <label class="zoom-control" title="Масштаб таймлайна"><span>−</span><input v-model.number="timelineZoom" type="range" min="1" max="6" step="0.25" /><span>＋</span></label>
        </div>
      </div>

      <div ref="timelineScroll" class="timeline-scroll">
        <div class="timeline-labels">
          <div class="ruler-spacer"></div>
          <div><span class="track-icon chapter"></span>Главы</div>
          <div><span class="track-icon scene"></span>Сцены</div>
          <div><span class="track-icon visual"></span>Видео / фон</div>
          <div><span class="track-icon audio"></span>Аудио</div>
          <button type="button" class="timeline-track-button" @click="select('music')">
            <span class="track-icon music"></span>
            <span>Музыка<small>{{ musicAsset ? `${Math.round(project.music.volume * 100)}%` : 'добавить' }}</small></span>
          </button>
        </div>
        <div class="timeline-content" :style="{ width: `${timelineZoom * 100}%` }">
          <div class="timeline-ruler">
            <span v-for="mark in rulerMarks" :key="mark.p" :style="{ left: `${mark.p}%` }"><i></i>{{ mark.label }}</span>
          </div>

          <div class="timeline-lane chapter-lane" @pointerdown.self="seekFromTimeline">
            <button v-for="chapter in timelineChapters" :key="chapter.id" type="button" class="chapter-clip"
                    :class="{ active: currentChapter?.id === chapter.id, selected: selection.type === 'chapter' && selection.id === chapter.id }"
                    :style="clipStyle(chapter.start_seconds, chapter.end_seconds, 0.35)"
                    @click.stop="selectChapter(chapter)">
              <b>{{ chapter.title }}</b>
            </button>
          </div>

          <div class="timeline-lane scene-lane" @pointerdown.self="seekFromTimeline">
            <button v-for="scene in project.scenes" :key="scene.id" type="button" class="scene-clip"
                    :class="{ active: currentScene?.id === scene.id, selected: selection.type === 'scene' && selection.id === scene.id }"
                    :style="clipStyle(scene.start, scene.end, 0.8)" @click.stop="selectScene(scene)">
              <i></i><b>{{ scene.name }}</b>
            </button>
          </div>

          <div class="timeline-lane visual-lane" @pointerdown.self="seekFromTimeline">
            <button v-if="videoAsset || backgroundAsset" type="button" class="visual-clip"
                    :style="clipStyle(0, duration, 100)" @click.stop="select('asset', (videoAsset || backgroundAsset).id)">
              <span class="clip-thumb" :style="backgroundThumbnailStyle"></span>
              <b>{{ videoAsset?.name || backgroundAsset?.name }}</b><small>{{ videoAsset ? 'Видео сцены' : 'Фон проекта' }}</small>
            </button>
          </div>

          <div class="timeline-lane audio-lane" @pointerdown.self="seekFromTimeline">
            <button v-if="audioAsset" type="button" class="audio-clip master-audio-clip"
                    :style="clipStyle(0, duration, 100)" @click.stop="select('asset', audioAsset.id)">
              <span class="timeline-waveform" aria-hidden="true">
                <i v-for="(bar, index) in timelineBars" :key="index" :style="{ height: `${bar * 100}%` }"
                   :class="{ played: index / timelineBars.length <= progressPercent / 100 }"></i>
              </span>
              <b>{{ audioAsset.name }}</b>
            </button>
            <button v-for="chapter in videoAudioChapters" :key="`audio-${chapter.id}`"
                    type="button" class="chapter-audio-clip"
                    :class="{ active: currentChapter?.id === chapter.id }"
                    :style="clipStyle(chapter.start_seconds, chapter.end_seconds, 0.35)"
                    @click.stop="selectVideoChapterAudio(chapter)">
              <i></i><b>{{ chapter.title }}</b>
            </button>
          </div>

          <div class="timeline-lane music-lane" @pointerdown.self="seekFromTimeline">
            <button v-if="musicAsset" type="button" class="music-clip"
                    :class="{ muted: !project.music.enabled }"
                    :style="clipStyle(0, duration, 100)"
                    @click.stop="select('music')">
              <span aria-hidden="true">♫</span>
              <b>{{ musicAsset.name }}</b>
              <small>{{ project.music.enabled ? `${Math.round(project.music.volume * 100)}% · EQ ${musicEqSummary}` : 'выключена' }}</small>
            </button>
          </div>

          <div class="timeline-playhead" :style="{ left: `${progressPercent}%` }"><i></i><span></span></div>
        </div>
      </div>
    </section>

    <div v-if="notice.text" class="notice" :class="notice.kind" role="status">
      <i></i><span>{{ notice.text }}</span><button type="button" @click="notice.text = ''">×</button>
    </div>

    <div v-if="showExport" class="modal-backdrop" @mousedown.self="closeExport">
      <section class="export-modal" role="dialog" aria-modal="true" aria-labelledby="export-title">
        <header>
          <div><span class="eyebrow">Финальный файл</span><h2 id="export-title">Экспорт видеокниги</h2></div>
          <button type="button" @click="closeExport" aria-label="Закрыть">×</button>
        </header>

        <template v-if="!renderJob">
          <div class="export-summary">
            <div><span>Формат</span><b>MP4 · 1920×1080 · H.264</b></div>
            <label class="export-preset-row">
              <span>Качество YouTube</span>
              <span class="export-preset-control">
                <select v-model="project.renderPreset" aria-label="Профиль битрейта для YouTube">
                  <option v-for="preset in renderPresetOptions" :key="preset.id" :value="preset.id">
                    {{ preset.label }} · {{ preset.videoLabel }}
                  </option>
                </select>
                <small>Видео {{ activeRenderPreset.videoLabel }} · AAC {{ activeRenderPreset.audioLabel }}</small>
              </span>
            </label>
            <div><span>Длительность</span><b>{{ formatTime(duration, true) }}</b></div>
            <div><span>Оценка полного файла</span><b>≈ {{ estimatedFullRenderSize }}</b></div>
            <div><span>Главы</span><b>{{ project.chapters.length }}</b></div>
            <div><span>Музыка</span><b>{{ musicAsset && project.music.enabled ? `${musicAsset.name} · ${Math.round(project.music.volume * 100)}%` : 'нет' }}</b></div>
          </div>
          <label class="switch-row export-test-switch">
            <span><b>Тестовый фрагмент</b><small>Первые 60 секунд — быстрее проверить оформление</small></span>
            <input v-model="exportTest" type="checkbox" /><i></i>
          </label>
          <p v-if="duration > YOUTUBE_MAX_DURATION_SECONDS" class="export-warning youtube-limit-warning">
            YouTube не примет один файл длиннее 12 часов. Полный локальный MP4 будет создан, но перед загрузкой его потребуется разделить.
          </p>
          <p v-if="exportIssue" class="export-issue">{{ exportIssue }}</p>
          <p v-for="warning in exportReadiness?.warnings || []" :key="warning" class="export-warning">{{ warning }}</p>
          <button type="button" class="modal-primary" :disabled="!!exportIssue || startingExport" @click="startExport">
            {{ startingExport ? 'Подготавливаю…' : exportTest ? 'Собрать тест 60 секунд' : 'Начать полный экспорт' }}
          </button>
        </template>

        <template v-else>
          <div class="render-progress-orb" :class="renderJob.status">
            <span>{{ Math.round((renderJob.progress || 0) * 100) }}<small>%</small></span>
          </div>
          <h3>{{ renderStateTitle }}</h3>
          <p class="render-state-copy">{{ renderStateCopy }}</p>
          <div class="render-progress"><i :style="{ width: `${Math.round((renderJob.progress || 0) * 100)}%` }"></i></div>
          <a v-if="renderJob.status === 'done' && renderJob.download_url" class="modal-primary download-link" :href="renderJob.download_url">Скачать MP4</a>
          <button v-if="renderJob.status === 'done'" type="button" class="modal-secondary" @click="resetExport">Новый экспорт</button>
          <button v-if="renderJob.status === 'failed'" type="button" class="modal-primary" @click="renderJob = null">Вернуться к настройкам</button>
          <pre v-if="renderJob.status === 'failed' && renderJob.log?.length" class="render-error">{{ renderJob.log.slice(-4).join('\n') }}</pre>
        </template>
      </section>
    </div>

    <div v-if="showBookExport" class="modal-backdrop" @mousedown.self="showBookExport = false">
      <section class="book-export-modal" role="dialog" aria-modal="true" aria-labelledby="book-export-title">
        <header>
          <div>
            <span class="eyebrow">Текст и материалы</span>
            <h2 id="book-export-title">Экспорт книги</h2>
            <p>{{ activeProjectRecord?.book?.title }} · {{ activeProjectRecord?.chapters?.length || 0 }} глав</p>
          </div>
          <button type="button" @click="showBookExport = false" aria-label="Закрыть">×</button>
        </header>

        <div class="book-export-choices">
          <button type="button" :disabled="bookExportBusy" @click="downloadBookExport('complete')">
            <span class="book-export-choice-icon">▤</span>
            <span><b>Вся книга</b><small>Один аккуратно собранный TXT-файл</small></span>
            <i>TXT</i>
          </button>
          <button type="button" :disabled="bookExportBusy || !currentBookChapter" @click="downloadBookExport('chapter')">
            <span class="book-export-choice-icon">¶</span>
            <span><b>Текущая глава</b><small>{{ currentBookChapter?.title || 'Глава не выбрана' }}</small></span>
            <i>TXT</i>
          </button>
          <button class="featured" type="button" :disabled="bookExportBusy" @click="downloadBookExport('chapters')">
            <span class="book-export-choice-icon">▦</span>
            <span><b>Книга по главам</b><small>Каждая глава — отдельная папка и TXT</small></span>
            <i>ZIP</i>
          </button>
        </div>

        <label class="switch-row book-export-media-switch">
          <span>
            <b>Добавить материалы глав</b>
            <small>Активная озвучка и изображение попадут в поглавный ZIP</small>
          </span>
          <input v-model="bookExportIncludeMedia" type="checkbox" /><i></i>
        </label>
        <footer>
          <span>Файлы сохраняются также в папке <b>exports</b> текущего проекта.</span>
          <i v-if="bookExportBusy">Собираю экспорт…</i>
        </footer>
      </section>
    </div>

    <div v-if="showProjectManager" class="modal-backdrop" @mousedown.self="showProjectManager = false">
      <section class="project-manager-modal" role="dialog" aria-modal="true" aria-labelledby="project-manager-title">
        <header>
          <div><span class="eyebrow">Локальная библиотека</span><h2 id="project-manager-title">Проекты Book Wunderwaffe</h2></div>
          <button type="button" @click="showProjectManager = false" aria-label="Закрыть">×</button>
        </header>
        <label class="project-manager-search">
          <span>⌕</span><input v-model.trim="projectManagerSearch" type="search" placeholder="Название или автор" />
        </label>
        <div class="project-manager-list">
          <article v-for="item in managedProjects" :key="item.uuid" :class="{ archived: !!item.archived_at }">
            <button class="project-manager-open" type="button" @click="openManagedProject(item.uuid)">
              <span>{{ projectKindLabel(item.project_kind) }}</span>
              <b>{{ item.title }}</b>
              <small>{{ item.author || 'Без автора' }} · {{ item.chapter_count }} глав · {{ formatProjectDate(item.updated_at) }}</small>
            </button>
            <div>
              <button type="button" title="Переименовать" @click="renameManagedProject(item)">✎</button>
              <button type="button" title="Дублировать" @click="duplicateManagedProject(item)">⧉</button>
              <button type="button" title="Резервная копия" @click="backupManagedProject(item)">◫</button>
              <button type="button" :title="item.archived_at ? 'Вернуть из архива' : 'Архивировать'"
                      @click="toggleManagedArchive(item)">{{ item.archived_at ? '↥' : '⌄' }}</button>
            </div>
          </article>
        </div>
        <footer>
          <span>Физическое удаление отключено: проекты безопасно архивируются.</span>
          <button type="button" @click="createEcosystemProject">＋ Новый проект</button>
        </footer>
      </section>
    </div>

    <div v-if="loading" class="loading-screen">
      <span class="loading-mark"><i></i><i></i><i></i></span>
      <strong>BOOK WUNDERWAFFE STUDIO</strong>
      <small>{{ loadingMessage }}</small>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import QrcodeVue from 'qrcode.vue'

const API = import.meta.env.VITE_API_URL || '/api'
const TELEGRAM_URL = 'https://t.me/temple_of_lizard'
const AUDIO_EXT = new Set(['mp3', 'wav', 'm4a', 'aac', 'flac', 'ogg', 'opus'])
const VIDEO_EXT = new Set(['mp4', 'mov', 'm4v', 'webm', 'mkv', 'avi'])
const IMAGE_EXT = new Set(['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp'])
const YOUTUBE_MAX_DURATION_SECONDS = 12 * 60 * 60
const RENDER_PRESETS = Object.freeze({
  compact: {
    id: 'compact', label: 'Компактный', videoKbps: 1200, audioKbps: 192,
    videoLabel: '1,2 Мбит/с', audioLabel: '192 кбит/с',
  },
  balanced: {
    id: 'balanced', label: 'Оптимальный', videoKbps: 1800, audioKbps: 192,
    videoLabel: '1,8 Мбит/с', audioLabel: '192 кбит/с',
  },
  youtube_1080p: {
    id: 'youtube_1080p', label: 'YouTube 1080p', videoKbps: 7500, audioKbps: 384,
    videoLabel: 'до 8 Мбит/с', audioLabel: '384 кбит/с',
  },
})
const renderPresetOptions = Object.values(RENDER_PRESETS)
const RATE_PRESETS = Object.freeze([
  { label: 'Медленно', value: '-25%' },
  { label: 'Немного медленнее', value: '-10%' },
  { label: 'Обычно', value: '+0%' },
  { label: 'Немного быстрее', value: '+15%' },
  { label: 'Быстро', value: '+30%' },
])
const PITCH_PRESETS = Object.freeze([
  { label: 'Очень низкий', value: '-40Hz' },
  { label: 'Низкий', value: '-25Hz' },
  { label: 'Немного ниже', value: '-10Hz' },
  { label: 'Нормальный', value: '+0Hz' },
  { label: 'Немного выше', value: '+10Hz' },
  { label: 'Высокий', value: '+25Hz' },
  { label: 'Очень высокий', value: '+40Hz' },
])
const VOLUME_PRESETS = Object.freeze([
  { label: 'Тише', value: '-20%' },
  { label: 'Обычно', value: '+0%' },
  { label: 'Громче', value: '+20%' },
])
const MUSIC_EQ_BANDS = Object.freeze([
  { key: 'bass', label: 'НЧ' },
  { key: 'mid', label: 'СЧ' },
  { key: 'treble', label: 'ВЧ' },
])
const DEFAULT_MUSIC_MIX = Object.freeze({
  enabled: true,
  loop: true,
  volume: 0.16,
  bass: 0,
  mid: 0,
  treble: 0,
})

const DEFAULT_LAYERS = {
  cover: { visible: true, x: 7, y: 17, w: 27, h: 66 },
  title: { visible: true, x: 39, y: 23, w: 54, h: 31, fontSize: 48, color: '#f4f0e8' },
  visualizer: { visible: true, x: 38, y: 59, w: 56, h: 23 },
  caption: { visible: true, x: 14, y: 69, w: 72, h: 18, fontSize: 28, fontWeight: 400, backgroundOpacity: 0.68 },
}

function uid(prefix = 'id') {
  const value = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `${prefix}-${value}`
}

function clone(value) {
  return JSON.parse(JSON.stringify(value))
}

function freshProject() {
  return {
    schemaVersion: 1,
    title: 'Новая аудиокнига',
    author: '',
    theme: 'amber',
    glitch: true,
    renderPreset: 'balanced',
    audioAssetId: null,
    musicAssetId: null,
    videoAssetId: null,
    coverAssetId: null,
    backgroundAssetId: null,
    captions: { enabled: false, wordsPerCard: 14 },
    music: clone(DEFAULT_MUSIC_MIX),
    materials: [],
    chapters: [],
    scenes: [{ id: uid('scene'), name: 'Основная сцена', start: 0, end: 60, backgroundAssetId: null }],
    layers: clone(DEFAULT_LAYERS),
  }
}

const project = reactive(freshProject())
const backend = reactive({ online: false, checking: true, version: '', python: '' })
const selection = reactive({ type: 'project', id: null })
const notice = reactive({ text: '', kind: 'info' })
const activeWorkspace = ref('book')
const projectCatalog = ref([])
const managerProjectCatalog = ref([])
const activeProjectUuid = ref('')
const activeProjectRecord = ref(null)
const switchingProject = ref(false)
const activeVideoEditionId = ref(null)
const showProjectManager = ref(false)
const projectManagerSearch = ref('')
const bookSearch = ref('')
const currentBookChapterId = ref(null)
const bookChapterTitle = ref('')
const bookChapterContent = ref('')
const bookSaveState = ref('saved')
const bookInspectorState = ref(localStorage.getItem('bookender.bookInspector') || 'open')
const bookMetadata = reactive({ title: '', author: '', description: '' })
const bookTts = reactive({
  voice: 'ru-RU-SvetlanaNeural',
  rate: '+0%',
  pitch: '+0Hz',
  volume: '+0%',
  provider: 'edge-tts',
})
const ttsJobs = ref([])
const narrationJobIds = ref([])
const ttsNow = ref(Date.now())
const ttsSessionStartedAt = Date.now()
const ttsRuntime = reactive({ available: false, message: '', provider: 'edge-tts', version: '' })
const ttsVoices = ref([])
const voiceSearch = ref('')
const voiceLanguage = ref('ru')
const previewLoading = ref(false)
const previewAudio = ref(null)
const selectedBookAudioId = ref(null)
const bookPlayerTime = ref(0)
const bookPlayerDuration = ref(0)
const bookPlayerPlaying = ref(false)
const bookPlayerVolume = ref(0.86)
let bookAutosaveTimer = null
let ttsPollTimer = null
let bookPlayerLoadToken = 0
let bookPlayerShouldAutoplay = false

const loading = ref(true)
const loadingMessage = ref('Подключаю медиадвижок…')
const dirty = ref(false)
const saving = ref(false)
const videoPreparing = ref(false)
const hydrating = ref(true)
const assetInput = ref(null)
const musicInput = ref(null)
const projectInput = ref(null)
const bookChapterImageInput = ref(null)
const bookTextEditor = ref(null)
const bookAudioEl = ref(null)
const audioEl = ref(null)
const musicEl = ref(null)
const videoEl = ref(null)
const sceneEl = ref(null)
const visualizerCanvas = ref(null)
const timelineScroll = ref(null)
const titleLayerEl = ref(null)
const titleStackEl = ref(null)

const currentTime = ref(0)
const audioDuration = ref(0)
const videoDuration = ref(0)
const playing = ref(false)
const volume = ref(0.86)
const musicPreviewPlaying = ref(false)
const musicEqState = reactive({
  active: false,
  error: false,
  message: 'Запустите пробу музыки — EQ включится в реальном времени',
})
const waveformSamples = ref([])
const timelineZoom = ref(1)

const showExport = ref(false)
const showBookExport = ref(false)
const bookExportBusy = ref(false)
const bookExportIncludeMedia = ref(true)
const exportTest = ref(true)
const exportReadiness = ref(null)
const startingExport = ref(false)
const renderJob = ref(null)
let renderPoll = null
let noticeTimer = null
let playbackFrame = null
let visualFrame = null
let titleFitFrame = null
let titleResizeObserver = null
let titleMeasureCanvas = null
let visualAudioContext = null
let visualAnalyser = null
let visualStreamSource = null
let visualizerStream = null
let visualizerMaster = null
let visualizerFrequencyData = null
let visualizerConnectPending = null
let visualizerLastConnectAttempt = 0
let visualizerGeneration = 0
let musicAudioContext = null
let musicMediaSource = null
let musicLowFilter = null
let musicMidFilter = null
let musicHighFilter = null
let musicGain = null
const visualizerLevels = new Float32Array(72)
const visualizerPeaks = new Float32Array(72)
const objectUrls = new Set()

const assetById = (id) => project.materials.find((item) => item.id === id) || null
const audioAsset = computed(() => assetById(project.audioAssetId))
const musicAsset = computed(() => assetById(project.musicAssetId))
const videoAsset = computed(() => assetById(project.videoAssetId))
const coverAsset = computed(() => assetById(project.coverAssetId))
const backgroundAsset = computed(() => assetById(project.backgroundAssetId))
const imageAssets = computed(() => project.materials.filter((item) => item.type === 'image'))
const musicCandidates = computed(() => project.materials.filter((item) => (
  item.type === 'audio'
  && item.id !== project.audioAssetId
  && !['chapter-audio', 'book-master'].includes(item.role)
)))
const videoAudioChapters = computed(() => (
  project.chapters.filter((chapter) => chapter.audioAssetId && assetById(chapter.audioAssetId))
))
const videoReadyChapterCount = computed(() => videoAudioChapters.value.length)
const videoBookChapterCount = computed(() => activeProjectRecord.value?.chapters?.length || project.chapters.length)
const currentBookChapter = computed(() => (
  activeProjectRecord.value?.chapters?.find((item) => item.id === currentBookChapterId.value) || null
))
const filteredBookChapters = computed(() => {
  const chapters = activeProjectRecord.value?.chapters || []
  const query = bookSearch.value.toLocaleLowerCase('ru-RU')
  if (!query) return chapters
  return chapters.filter((item) => (
    item.title.toLocaleLowerCase('ru-RU').includes(query)
    || item.content.toLocaleLowerCase('ru-RU').includes(query)
  ))
})
const managedProjects = computed(() => {
  const query = projectManagerSearch.value.toLocaleLowerCase('ru-RU')
  if (!query) return managerProjectCatalog.value
  return managerProjectCatalog.value.filter((item) => (
    item.title.toLocaleLowerCase('ru-RU').includes(query)
    || String(item.author || '').toLocaleLowerCase('ru-RU').includes(query)
  ))
})
const bookWordCount = computed(() => (
  (bookChapterContent.value.trim().match(/[\p{L}\p{N}]+(?:[-’'][\p{L}\p{N}]+)*/gu) || []).length
))
const bookSaveLabel = computed(() => ({
  modified: 'Есть изменения',
  saving: 'Сохраняется…',
  saved: 'Сохранено',
  error: 'Ошибка сохранения',
}[bookSaveState.value] || 'Сохранено'))
const currentChapterAudios = computed(() => (
  (activeProjectRecord.value?.audio_assets || [])
    .filter((asset) => asset.chapter_id === currentBookChapterId.value)
    .sort((a, b) => Number(b.version_number || b.id) - Number(a.version_number || a.id))
))
const currentChapterAudio = computed(() => (
  currentChapterAudios.value.find((asset) => asset.is_active)
  || currentChapterAudios.value[0]
  || null
))
const currentBookChapterImages = computed(() => (
  (activeProjectRecord.value?.visual_assets || [])
    .filter((asset) => (
      asset.chapter_id === currentBookChapterId.value
      && asset.asset_type === 'chapter-image'
    ))
    .sort((a, b) => Number(b.id) - Number(a.id))
))
const currentBookChapterImage = computed(() => currentBookChapterImages.value[0] || null)
const currentBookChapterImageUrl = computed(() => (
  currentBookChapterImage.value?.file_path
    ? mediaUrl(currentBookChapterImage.value.file_path)
    : ''
))
const selectedBookAudio = computed(() => (
  currentChapterAudios.value.find((asset) => asset.id === selectedBookAudioId.value)
  || currentChapterAudio.value
  || null
))
const bookPlayerAsset = computed(() => previewAudio.value || selectedBookAudio.value)
const bookPlayerUrl = computed(() => {
  const asset = bookPlayerAsset.value
  if (!asset?.file_path || asset.file_path.startsWith('external:')) return ''
  return `${API}/project-media/${asset.file_path.split('/').map(encodeURIComponent).join('/')}`
})
const bookPlayerTitle = computed(() => {
  if (previewAudio.value) return `Проба · ${voiceShortLabel(previewAudio.value.voice)}`
  return selectedBookAudio.value?.title || `Версия ${selectedBookAudio.value?.version_number || ''}`
})
const selectedAudioIndex = computed(() => (
  currentChapterAudios.value.findIndex((asset) => asset.id === selectedBookAudio.value?.id)
))
const previousChapterAudio = computed(() => currentChapterAudios.value[selectedAudioIndex.value + 1] || null)
const nextChapterAudio = computed(() => currentChapterAudios.value[selectedAudioIndex.value - 1] || null)
const voiceLanguages = computed(() => (
  [...new Set(ttsVoices.value.map((voice) => voice.language).filter(Boolean))].sort((a, b) => (
    a === 'ru' ? -1 : b === 'ru' ? 1 : a.localeCompare(b)
  ))
))
const filteredTtsVoices = computed(() => {
  const query = voiceSearch.value.toLocaleLowerCase('ru-RU')
  return ttsVoices.value.filter((voice) => (
    (!voiceLanguage.value || voice.language === voiceLanguage.value)
    && (!query || `${voice.name} ${voice.friendly_name} ${voice.id} ${voice.locale}`.toLocaleLowerCase('ru-RU').includes(query))
  ))
})
const visibleTtsJobs = computed(() => ttsJobs.value.filter((job) => (
  ['queued', 'running'].includes(job.status)
  || new Date(job.created_at).getTime() >= ttsSessionStartedAt
)))
const latestTtsJob = computed(() => visibleTtsJobs.value[0] || null)
const activeTtsJobRunning = computed(() => ttsJobs.value.some((job) => ['queued', 'running'].includes(job.status)))
const narrationJobs = computed(() => {
  const selected = new Set(narrationJobIds.value)
  if (selected.size) return ttsJobs.value.filter((job) => selected.has(job.uuid))
  return ttsJobs.value.filter((job) => ['queued', 'running'].includes(job.status))
})
const ttsProgressState = computed(() => {
  const jobs = narrationJobs.value
  const active = jobs.some((job) => ['queued', 'running'].includes(job.status))
  if (!active || !jobs.length) {
    return { active: false, percent: 0, detail: '', elapsed: 0 }
  }
  const progress = jobs.reduce((total, job) => {
    if (['done', 'failed', 'cancelled', 'skipped'].includes(job.status)) return total + 1
    return total + Math.max(0, Math.min(1, Number(job.progress) || 0))
  }, 0) / jobs.length
  const running = jobs.find((job) => job.status === 'running')
    || jobs.find((job) => job.status === 'queued')
  const finished = jobs.filter((job) => (
    ['done', 'failed', 'cancelled', 'skipped'].includes(job.status)
  )).length
  const totalChunks = Math.max(1, Number(running?.progress_total) || 1)
  const completedChunks = Math.max(0, Number(running?.progress_done) || 0)
  const currentChunk = Math.min(totalChunks, completedChunks + 1)
  let detail = ''
  if (jobs.length > 1) {
    detail = `Готово глав: ${finished} из ${jobs.length}`
    if (running) detail += ` · сейчас «${chapterTitleForJob(running)}»`
  } else if (totalChunks > 1) {
    detail = `Фрагмент ${currentChunk} из ${totalChunks} · ${chapterTitleForJob(running)}`
  } else {
    detail = `Получаю аудио · ${chapterTitleForJob(running)}`
  }
  const timestamps = jobs
    .map((job) => new Date(job.started_at || job.created_at).getTime())
    .filter(Number.isFinite)
  const startedAt = timestamps.length ? Math.min(...timestamps) : ttsNow.value
  return {
    active: true,
    percent: Math.max(1, Math.min(99, Math.round(progress * 100))),
    detail,
    elapsed: Math.max(0, (ttsNow.value - startedAt) / 1000),
  }
})
const audioSource = computed(() => assetUrl(audioAsset.value))
const musicSource = computed(() => assetUrl(musicAsset.value))
const videoSource = computed(() => assetUrl(videoAsset.value))
const coverSource = computed(() => assetUrl(coverAsset.value))

const masterKind = computed(() => audioSource.value ? 'audio' : videoSource.value ? 'video' : null)
const chapterMax = computed(() => project.chapters.reduce((max, item) => Math.max(max, Number(item.end_seconds) || Number(item.start_seconds) || 0), 0))
const sceneMax = computed(() => project.scenes.reduce((max, item) => Math.max(max, Number(item.end) || 0), 0))
const duration = computed(() => {
  const media = masterKind.value === 'audio' ? audioDuration.value : videoDuration.value
  if (Number.isFinite(media) && media > 0) return media
  return Math.max(chapterMax.value, sceneMax.value, 0)
})
const activeRenderPreset = computed(() => RENDER_PRESETS[project.renderPreset] || RENDER_PRESETS.balanced)
const estimatedFullRenderSize = computed(() => {
  const seconds = Number(exportReadiness.value?.audioProbe?.duration) || duration.value
  const bitrate = activeRenderPreset.value.videoKbps + activeRenderPreset.value.audioKbps
  return formatBytes(Math.max(0, seconds) * bitrate * 1000 / 8)
})
const estimatedPeakRenderBytes = computed(() => {
  const seconds = Number(exportReadiness.value?.audioProbe?.duration) || duration.value
  const videoBytes = Math.max(0, seconds) * activeRenderPreset.value.videoKbps * 1000 / 8
  const audioBytes = Math.max(0, seconds) * activeRenderPreset.value.audioKbps * 1000 / 8
  return Math.ceil((videoBytes * 3 + audioBytes + 128 * 1024 ** 2) * 1.08)
})
const progressPercent = computed(() => duration.value ? Math.min(100, Math.max(0, currentTime.value / duration.value * 100)) : 0)
const musicEqSummary = computed(() => {
  const values = MUSIC_EQ_BANDS.map((band) => Number(project.music?.[band.key]) || 0)
  return values.every((value) => value === 0) ? 'ровно' : values.map((value) => `${value > 0 ? '+' : ''}${value}`).join('/')
})

const timelineChapters = computed(() => {
  const sorted = [...project.chapters].sort((a, b) => a.start_seconds - b.start_seconds)
  return sorted.map((chapter, index) => {
    const nextStart = sorted[index + 1]?.start_seconds
    const end = (nextStart ?? Number(chapter.end_seconds)) || duration.value || chapter.start_seconds + 60
    return {
      ...chapter,
      index,
      end_seconds: Math.max(chapter.start_seconds + 0.1, end),
    }
  })
})

const currentChapterIndex = computed(() => {
  const chapters = timelineChapters.value
  if (!chapters.length) return -1
  const time = Number.isFinite(Number(currentTime.value)) ? Math.max(0, Number(currentTime.value)) : 0
  let low = 0
  let high = chapters.length - 1
  let result = 0
  while (low <= high) {
    const middle = Math.floor((low + high) / 2)
    if (chapters[middle].start_seconds <= time) {
      result = middle
      low = middle + 1
    } else {
      high = middle - 1
    }
  }
  return result
})
const currentChapter = computed(() => currentChapterIndex.value >= 0 ? timelineChapters.value[currentChapterIndex.value] : null)
const previousChapter = computed(() => currentChapterIndex.value > 0 ? timelineChapters.value[currentChapterIndex.value - 1] : null)
const nextChapter = computed(() => currentChapterIndex.value >= 0 ? timelineChapters.value[currentChapterIndex.value + 1] || null : null)

const currentScene = computed(() => {
  const sorted = [...project.scenes].sort((a, b) => a.start - b.start)
  return [...sorted].reverse().find((scene) => currentTime.value >= scene.start && currentTime.value < scene.end)
    || null
})

const currentChapterImageAsset = computed(() => assetById(currentChapter.value?.imageAssetId))
const sceneBackgroundAsset = computed(() => (
  currentChapterImageAsset.value
  || assetById(currentScene.value?.backgroundAssetId)
  || backgroundAsset.value
))
const backgroundSource = computed(() => assetUrl(sceneBackgroundAsset.value))
const backgroundStyle = computed(() => backgroundSource.value
  ? { backgroundImage: `url("${backgroundSource.value.replaceAll('"', '%22')}")` }
  : {})
const backgroundThumbnailStyle = computed(() => backgroundSource.value
  ? { backgroundImage: `url("${backgroundSource.value.replaceAll('"', '%22')}")` }
  : {})
const currentReadingCaption = computed(() => {
  if (!project.captions?.enabled || !currentChapter.value?.text) return ''
  const start = Number(currentChapter.value.start_seconds) || 0
  const end = Math.max(start + 0.1, Number(currentChapter.value.end_seconds) || start + 0.1)
  const fraction = Math.max(0, Math.min(0.999999, (currentTime.value - start) / (end - start)))
  const chunks = readingCaptionChunks(
    currentChapter.value.text,
    Number(project.captions.wordsPerCard) || 14,
  )
  return chunks[Math.min(chunks.length - 1, Math.floor(fraction * chunks.length))] || ''
})

const selectedAsset = computed(() => selection.type === 'asset' ? assetById(selection.id) : null)
const selectedChapter = computed(() => selection.type === 'chapter' ? project.chapters.find((item) => item.id === selection.id) || null : null)
const selectedScene = computed(() => selection.type === 'scene' ? project.scenes.find((item) => item.id === selection.id) || null : null)
const selectedLayer = computed(() => selection.type === 'layer' ? project.layers[selection.id] || null : null)
const inspectorTitle = computed(() => ({
  project: 'Проект', music: 'Музыка', asset: 'Материал', chapter: 'Глава', scene: 'Сцена', layer: layerLabel(selection.id),
})[selection.type] || 'Свойства')

const timelineBars = computed(() => {
  const source = waveformSamples.value.length ? waveformSamples.value : Array.from({ length: 720 }, (_, i) => 0.2 + Math.abs(Math.sin(i * 0.37) * Math.cos(i * 0.11)) * 0.65)
  const count = 180
  const step = Math.max(1, Math.floor(source.length / count))
  return Array.from({ length: count }, (_, index) => {
    const slice = source.slice(index * step, (index + 1) * step)
    return Math.max(0.08, Math.min(1, slice.reduce((sum, value) => sum + Math.abs(Number(value) || 0), 0) / Math.max(1, slice.length)))
  })
})

const rulerMarks = computed(() => Array.from({ length: 11 }, (_, index) => ({
  p: index * 10,
  label: formatTime(duration.value * index / 10),
})))

const hasUploadingAssets = computed(() => project.materials.some((item) => item.status === 'uploading'))
const canOpenExport = computed(() => backend.online && !!audioAsset.value && !!coverAsset.value && project.chapters.length > 0 && !hasUploadingAssets.value)
const exportIssue = computed(() => {
  if (!backend.online) return 'Медиадвижок недоступен. Запустите проект через run.bat.'
  if (!audioAsset.value) return 'Добавьте основную аудиокнигу.'
  if (!coverAsset.value) return 'Назначьте изображение обложкой.'
  if (!project.chapters.length) return 'Добавьте хотя бы одну главу.'
  if (hasUploadingAssets.value) return 'Дождитесь завершения синхронизации файлов.'
  if (exportReadiness.value && exportReadiness.value.ready === false) {
    const labels = {
      audio: 'Backend не видит выбранное аудио.',
      cover: 'Backend не видит выбранную обложку.',
      chapters: 'Главы не сохранены.',
      'audio-decodable': 'Выбранный аудиофайл повреждён или не читается FFmpeg. Назначьте другую копию из материалов.',
      'chapters-duration-mismatch': 'Главы не покрывают всю аудиокнигу. Продлите последнюю главу или обновите разметку из RPP.',
      'chapters-outside-audio': 'Разметка глав выходит за пределы аудиофайла.',
      'chapters-start-after-audio': 'Первая глава должна начинаться с 00:00:00.',
      'chapters-have-gaps': 'Между главами есть непокрытый интервал.',
      ffmpeg: 'FFmpeg не найден.',
      ffprobe: 'FFprobe не найден.',
    }
    return exportReadiness.value.missing?.map((item) => labels[item] || item).join(' · ') || 'Проект пока не готов к экспорту.'
  }
  const freeBytes = Number(exportReadiness.value?.renderEstimate?.full?.freeBytes)
  if (!exportTest.value && freeBytes > 0 && estimatedPeakRenderBytes.value > freeBytes) {
    return `Недостаточно места для надёжной сборки: нужно около ${formatBytes(estimatedPeakRenderBytes.value)}, доступно ${formatBytes(freeBytes)}. Выберите более компактный профиль или освободите диск.`
  }
  return ''
})

const renderStateTitle = computed(() => {
  if (renderJob.value?.status === 'done') return 'Видеокнига готова'
  if (renderJob.value?.status === 'failed') return 'Экспорт остановлен'
  return 'Собираю видеокнигу'
})
const renderStateCopy = computed(() => {
  if (renderJob.value?.status === 'done') return 'Файл собран и готов к скачиванию.'
  if (renderJob.value?.status === 'failed') return 'Движок вернул ошибку. Последние строки лога показаны ниже.'
  return exportTest.value ? 'Рендерится тестовый фрагмент длиной 60 секунд.' : 'Полный экспорт может занять продолжительное время.'
})

function materialType(fileName = '', mime = '') {
  const extension = fileName.split('.').pop()?.toLowerCase() || ''
  if (mime.startsWith('audio/') || AUDIO_EXT.has(extension)) return 'audio'
  if (mime.startsWith('video/') || VIDEO_EXT.has(extension)) return 'video'
  if (mime.startsWith('image/') || IMAGE_EXT.has(extension)) return 'image'
  return null
}

function materialCode(type) {
  return ({ audio: 'AUD', video: 'VID', image: 'IMG' })[type] || 'FILE'
}

function materialLabel(type) {
  return ({ audio: 'Аудио', video: 'Видео', image: 'Изображение' })[type] || 'Файл'
}

function materialRole(asset) {
  const roles = []
  if (project.audioAssetId === asset.id) roles.push('Основное аудио')
  if (project.musicAssetId === asset.id) roles.push('Музыка')
  if (project.videoAssetId === asset.id) roles.push('Видео сцены')
  if (project.coverAssetId === asset.id) roles.push('Обложка')
  if (project.backgroundAssetId === asset.id) roles.push('Фон')
  if (asset.role === 'chapter-audio') roles.push('Озвучка главы')
  if (asset.role === 'chapter-image') roles.push('Изображение главы')
  if (asset.role === 'book-master') roles.push('Мастер-аудио')
  if (asset.role === 'default-cover') roles.push('Обложка по умолчанию')
  return roles.join(' · ')
}

function assetStatus(asset) {
  if (asset.status === 'uploading') return `Синхронизация ${Math.round((asset.progress || 0) * 100)}%`
  if (asset.status === 'error') return 'Ошибка синхронизации'
  if (asset.status === 'local') return 'Только в этой сессии'
  return 'Готово'
}

function formatBytes(bytes) {
  const size = Number(bytes) || 0
  if (!size) return 'размер неизвестен'
  if (size >= 1024 ** 3) return `${(size / 1024 ** 3).toFixed(1)} ГБ`
  if (size >= 1024 ** 2) return `${(size / 1024 ** 2).toFixed(1)} МБ`
  return `${Math.max(1, Math.round(size / 1024))} КБ`
}

function formatDb(value) {
  const amount = Number(value) || 0
  return `${amount > 0 ? '+' : ''}${amount} дБ`
}

function mediaUrl(path) {
  if (!path) return ''
  const normalized = String(path).replaceAll('\\', '/').replace(/^\/+/, '')
  if (normalized === 'assets/bookender-studio-icon.png') {
    return '/bookender-studio-icon.png'
  }
  if (normalized.startsWith('projects/')) {
    return `${API}/project-media/${normalized.split('/').map(encodeURIComponent).join('/')}`
  }
  return `${API}/media/${normalized.split('/').map(encodeURIComponent).join('/')}`
}

function assetUrl(asset) {
  if (!asset) return ''
  return asset.src || mediaUrl(asset.serverPath)
}

function readingCaptionChunks(text, wordsPerCard = 14) {
  const words = String(text || '').trim().split(/\s+/).filter(Boolean)
  const size = Math.max(6, Math.min(28, Number(wordsPerCard) || 14))
  const chunks = []
  for (let index = 0; index < words.length; index += size) {
    chunks.push(words.slice(index, index + size).join(' '))
  }
  return chunks
}

function normalizeChapter(item, index) {
  const start = Number(item.start_seconds ?? parseTimecode(item.start ?? 0)) || 0
  const end = Number(item.end_seconds ?? parseTimecode(item.end ?? 0)) || 0
  return {
    ...item,
    id: item.id || uid('chapter'),
    title: String(item.title || `Глава ${index + 1}`),
    start_seconds: Math.max(0, start),
    end_seconds: Math.max(start, end),
  }
}

function normalizeProject(value) {
  const base = freshProject()
  const source = value && typeof value === 'object' ? value : {}
  const normalized = {
    ...base,
    ...source,
    captions: { ...base.captions, ...(source.captions || {}) },
    music: { ...base.music, ...(source.music || {}) },
    renderPreset: RENDER_PRESETS[source.renderPreset] ? source.renderPreset : base.renderPreset,
    materials: Array.isArray(source.materials) ? source.materials.map((asset) => ({
      ...asset,
      id: asset.id || uid('asset'),
      status: asset.serverPath ? 'ready' : 'missing',
      progress: asset.serverPath ? 1 : 0,
      src: asset.serverPath ? mediaUrl(asset.serverPath) : '',
    })) : [],
    chapters: Array.isArray(source.chapters) ? source.chapters.map(normalizeChapter) : [],
    scenes: Array.isArray(source.scenes) && source.scenes.length ? source.scenes.map((scene) => ({
      id: scene.id || uid('scene'),
      name: scene.name || 'Сцена',
      start: Math.max(0, Number(scene.start) || 0),
      end: Math.max(Number(scene.start) || 0, Number(scene.end) || 60),
      backgroundAssetId: scene.backgroundAssetId || null,
    })) : base.scenes,
    layers: {
      cover: { ...DEFAULT_LAYERS.cover, ...(source.layers?.cover || {}) },
      title: { ...DEFAULT_LAYERS.title, ...(source.layers?.title || {}) },
      visualizer: { ...DEFAULT_LAYERS.visualizer, ...(source.layers?.visualizer || {}) },
      caption: { ...DEFAULT_LAYERS.caption, ...(source.layers?.caption || {}) },
    },
  }
  return normalized
}

function replaceProject(value) {
  hydrating.value = true
  releaseObjectUrls()
  const normalized = normalizeProject(value)
  for (const key of Object.keys(project)) delete project[key]
  Object.assign(project, normalized)
  selection.type = 'project'
  selection.id = null
  currentTime.value = 0
  nextTick(() => {
    audioEl.value?.load()
    musicEl.value?.load()
    videoEl.value?.load()
    hydrating.value = false
  })
}

function serializeProject() {
  return {
    ...clone(project),
    duration_seconds: duration.value,
    updatedAt: new Date().toISOString(),
    materials: project.materials.map(({ file, src, progress, ...asset }) => ({ ...asset, status: asset.serverPath ? 'ready' : 'missing' })),
    chapters: timelineChapters.value.map(({ index, ...chapter }) => chapter),
  }
}

function select(type, id = null) {
  selection.type = type
  selection.id = id
}

function setNotice(text, kind = 'info', timeout = 4200) {
  notice.text = text
  notice.kind = kind
  clearTimeout(noticeTimer)
  if (timeout) noticeTimer = setTimeout(() => { notice.text = '' }, timeout)
}

async function apiRequest(path, options = {}) {
  const response = await fetch(`${API}${path}`, options)
  const text = await response.text()
  let data = null
  try { data = text ? JSON.parse(text) : {} } catch { data = { detail: text } }
  if (!response.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : data.detail?.message
    throw new Error(detail || data.message || `HTTP ${response.status}`)
  }
  return data
}

function projectKindLabel(kind) {
  return ({ book: 'книга', video: 'видео', hybrid: 'книга + видео' }[kind] || kind)
}

async function loadProjectCatalog(includeArchived = false) {
  const response = await apiRequest(`/projects?include_archived=${includeArchived ? 'true' : 'false'}`)
  projectCatalog.value = response.projects || []
  return response.active_project_uuid || projectCatalog.value[0]?.uuid || ''
}

async function loadManagerCatalog() {
  const response = await apiRequest('/projects?include_archived=true')
  managerProjectCatalog.value = response.projects || []
}

async function openProjectManager() {
  try {
    await loadManagerCatalog()
    showProjectManager.value = true
  } catch (error) {
    setNotice(`Не удалось открыть библиотеку: ${error.message}`, 'error')
  }
}

async function openManagedProject(projectUuid) {
  showProjectManager.value = false
  await switchProject(projectUuid)
}

async function renameManagedProject(item) {
  const title = window.prompt('Новое название проекта', item.title)
  if (!title || title === item.title) return
  try {
    await apiRequest(`/projects/${encodeURIComponent(item.uuid)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    })
    await Promise.all([loadProjectCatalog(), loadManagerCatalog()])
    if (item.uuid === activeProjectUuid.value) {
      activeProjectRecord.value = await apiRequest(`/projects/${encodeURIComponent(item.uuid)}`)
      hydrateBookState(activeProjectRecord.value)
    }
  } catch (error) {
    setNotice(`Не удалось переименовать проект: ${error.message}`, 'error')
  }
}

async function duplicateManagedProject(item) {
  try {
    const duplicate = await apiRequest(`/projects/${encodeURIComponent(item.uuid)}/duplicate`, { method: 'POST' })
    await Promise.all([loadProjectCatalog(), loadManagerCatalog()])
    showProjectManager.value = false
    await switchProject(duplicate.uuid)
  } catch (error) {
    setNotice(`Не удалось дублировать проект: ${error.message}`, 'error')
  }
}

async function backupManagedProject(item) {
  try {
    const result = await apiRequest(`/projects/${encodeURIComponent(item.uuid)}/backup`, { method: 'POST' })
    setNotice(`Резервная копия создана: ${result.path}`, 'success', 7000)
  } catch (error) {
    setNotice(`Не удалось создать резервную копию: ${error.message}`, 'error')
  }
}

async function toggleManagedArchive(item) {
  const archived = !item.archived_at
  if (archived && !window.confirm(`Архивировать проект «${item.title}»?`)) return
  try {
    await apiRequest(`/projects/${encodeURIComponent(item.uuid)}/archive`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ archived }),
    })
    await Promise.all([loadProjectCatalog(), loadManagerCatalog()])
  } catch (error) {
    setNotice(`Не удалось изменить архив: ${error.message}`, 'error')
  }
}

function formatProjectDate(value) {
  if (!value) return 'дата неизвестна'
  return new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value))
}

function normalizedVoiceId(value) {
  const voice = String(value || '')
  const folded = voice.toLocaleLowerCase('ru-RU')
  if (folded.includes('дмит') || folded === 'dmitry') return 'ru-RU-DmitryNeural'
  if (folded.includes('свет') || folded === 'svetlana') return 'ru-RU-SvetlanaNeural'
  return voice || 'ru-RU-SvetlanaNeural'
}

function normalizePreset(value, presets, fallback) {
  return presets.some((preset) => preset.value === value) ? value : fallback
}

function setBookInspectorState(state) {
  bookInspectorState.value = ['open', 'collapsed', 'hidden'].includes(state) ? state : 'open'
  localStorage.setItem('bookender.bookInspector', bookInspectorState.value)
}

function voiceLabel(voice) {
  const name = voice.name || voice.id
  const gender = ({ Female: 'жен.', Male: 'муж.' }[voice.gender] || voice.gender || '')
  return `${name} · ${voice.locale}${gender ? ` · ${gender}` : ''}`
}

function voiceShortLabel(voiceId) {
  const voice = ttsVoices.value.find((item) => item.id === voiceId)
  return voice?.name || voiceId || 'голос не указан'
}

function pitchPresetLabel(value) {
  return PITCH_PRESETS.find((preset) => preset.value === value)?.label || value || 'Нормальный'
}

async function loadTtsRuntime({ refresh = false } = {}) {
  try {
    const status = await apiRequest('/tts/status')
    Object.assign(ttsRuntime, status)
    if (!status.available) return
    const result = await apiRequest(`/tts/voices${refresh ? '?refresh=true' : ''}`)
    ttsVoices.value = result.voices || []
    if (!ttsVoices.value.some((voice) => voice.id === bookTts.voice)) {
      const fallback = ttsVoices.value.find((voice) => voice.id === 'ru-RU-SvetlanaNeural')
        || ttsVoices.value[0]
      if (fallback) bookTts.voice = fallback.id
    }
  } catch (error) {
    ttsRuntime.available = false
    ttsRuntime.message = error.message || 'Модуль озвучки не запущен. Проверьте установку компонентов TTS.'
  }
}

function hydrateBookState(record) {
  const book = record?.book
  bookMetadata.title = book?.title || record?.title || ''
  bookMetadata.author = book?.author || record?.author || ''
  bookMetadata.description = book?.description || record?.description || ''
  Object.assign(bookTts, {
    voice: normalizedVoiceId(record?.tts_settings?.voice),
    rate: normalizePreset(record?.tts_settings?.rate, RATE_PRESETS, '+0%'),
    pitch: normalizePreset(record?.tts_settings?.pitch, PITCH_PRESETS, '+0Hz'),
    volume: normalizePreset(record?.tts_settings?.volume, VOLUME_PRESETS, '+0%'),
    provider: record?.tts_settings?.provider || 'edge-tts',
  })
  const selectedVoice = ttsVoices.value.find((voice) => voice.id === bookTts.voice)
  if (selectedVoice?.language) voiceLanguage.value = selectedVoice.language
  const chapters = record?.chapters || []
  const preferred = chapters.find((item) => item.id === currentBookChapterId.value) || chapters[0] || null
  currentBookChapterId.value = preferred?.id || null
  bookChapterTitle.value = preferred?.title || ''
  bookChapterContent.value = preferred?.content || ''
  bookSaveState.value = 'saved'
  previewAudio.value = null
  const chapterAssets = (record?.audio_assets || []).filter((asset) => asset.chapter_id === preferred?.id)
  selectedBookAudioId.value = (
    chapterAssets.find((asset) => asset.is_active)?.id
    || chapterAssets[0]?.id
    || null
  )
  stopBookPlayer()
}

function addBookAudioToVideo(record) {
  const grouped = new Map()
  for (const audio of record?.audio_assets || []) {
    const key = audio.chapter_id ?? `book-${audio.id}`
    const current = grouped.get(key)
    const rank = [
      Number(Boolean(audio.is_active)),
      Number(audio.version_number || 0),
      Number(audio.id || 0),
    ]
    const currentRank = [
      Number(Boolean(current?.is_active)),
      Number(current?.version_number || 0),
      Number(current?.id || 0),
    ]
    if (!current || rank.some((value, index) => (
      value > currentRank[index] && rank.slice(0, index).every((part, partIndex) => part === currentRank[partIndex])
    ))) {
      grouped.set(key, audio)
    }
  }
  const livePaths = new Set(
    [...grouped.values()]
      .map((audio) => audio.file_path)
      .filter((path) => path && !path.startsWith('external:')),
  )
  const retainedMaterials = project.materials.filter((item) => (
    item.role !== 'chapter-audio' || livePaths.has(item.serverPath)
  ))
  project.materials.splice(0, project.materials.length, ...retainedMaterials)
  const materialByChapter = new Map()
  for (const audio of grouped.values()) {
    if (!audio.file_path || audio.file_path.startsWith('external:')) continue
    const serverPath = audio.file_path
    const chapter = record.chapters?.find((item) => item.id === audio.chapter_id)
    let material = project.materials.find((item) => item.serverPath === serverPath)
    if (!material) {
      material = {
        id: `chapter-audio-${audio.id}`,
        type: 'audio',
        name: `${chapter?.title || 'Озвучка'}.mp3`,
        size: Number(audio.file_size || 0),
        serverPath,
        src: mediaUrl(serverPath),
        status: 'ready',
        progress: 1,
      }
      project.materials.push(material)
    }
    material.chapterId = audio.chapter_id
    material.sourceTextHash = audio.source_text_hash
    material.role = 'chapter-audio'
    materialByChapter.set(audio.chapter_id, material)
  }
  return materialByChapter
}

function addBookVisualsToVideo(record) {
  const latestByChapter = new Map()
  for (const visual of record?.visual_assets || []) {
    if (visual.asset_type !== 'chapter-image' || !visual.chapter_id || !visual.file_path) continue
    const current = latestByChapter.get(visual.chapter_id)
    if (!current || Number(visual.id) > Number(current.id)) {
      latestByChapter.set(visual.chapter_id, visual)
    }
  }
  const livePaths = new Set([...latestByChapter.values()].map((visual) => visual.file_path))
  const retainedMaterials = project.materials.filter((item) => (
    item.role !== 'chapter-image' || livePaths.has(item.serverPath)
  ))
  project.materials.splice(0, project.materials.length, ...retainedMaterials)
  const materialByChapter = new Map()
  for (const [chapterId, visual] of latestByChapter) {
    let metadata = {}
    try { metadata = JSON.parse(visual.metadata_json || '{}') } catch { /* optional metadata */ }
    let material = project.materials.find((item) => item.serverPath === visual.file_path)
    if (!material) {
      material = {
        id: `chapter-image-${visual.id}`,
        type: 'image',
        name: visual.title || `Глава ${chapterId}`,
        size: Number(metadata.size || 0),
        serverPath: visual.file_path,
        src: mediaUrl(visual.file_path),
        status: 'ready',
        progress: 1,
        chapterId,
        role: 'chapter-image',
      }
      project.materials.push(material)
    }
    materialByChapter.set(chapterId, material)
  }
  return materialByChapter
}

function ensureDefaultVideoCover() {
  let material = project.materials.find((item) => item.role === 'default-cover')
  if (!material) {
    material = {
      id: 'book-wunderwaffe-default-cover',
      type: 'image',
      name: 'Book Wunderwaffe · обложка по умолчанию',
      size: 0,
      serverPath: 'assets/bookender-studio-icon.png',
      src: '/bookender-studio-icon.png',
      status: 'ready',
      progress: 1,
      role: 'default-cover',
    }
    project.materials.push(material)
  }
  project.coverAssetId = material.id
  return material
}

function syncBookChaptersToVideo(record, master = null) {
  const audioMaterials = addBookAudioToVideo(record)
  const images = addBookVisualsToVideo(record)
  const selectedCover = assetById(project.coverAssetId)
  if (images.size && (!selectedCover || selectedCover.role === 'default-cover')) {
    project.coverAssetId = images.values().next().value.id
  } else if (!selectedCover) {
    ensureDefaultVideoCover()
  }
  const timings = new Map((master?.chapters || []).map((item) => [item.chapter_id, item]))
  const existing = new Map(project.chapters.map((item) => [item.chapterId, item]))
  const sourceChapters = master?.chapters?.length
    ? (record?.chapters || []).filter((chapter) => timings.has(chapter.id))
    : (record?.chapters || [])
  let cursor = 0
  project.chapters = sourceChapters.map((chapter, index) => {
    const timing = timings.get(chapter.id)
    const previous = existing.get(chapter.id) || {}
    const start = timing ? Number(timing.start_seconds) : Math.max(cursor, Number(previous.start_seconds) || index)
    const end = timing ? Number(timing.end_seconds) : Math.max(start + 1, Number(previous.end_seconds) || start + 1)
    cursor = end
    return {
      ...previous,
      id: previous.id || `book-chapter-${chapter.id}`,
      chapterId: chapter.id,
      title: chapter.title,
      text: chapter.content,
      start_seconds: start,
      end_seconds: end,
      imageAssetId: images.get(chapter.id)?.id || null,
      audioAssetId: audioMaterials.get(chapter.id)?.id || null,
    }
  })
  if (master?.file_path) {
    const retainedMaterials = project.materials.filter((item) => (
      item.role !== 'book-master' || item.serverPath === master.file_path
    ))
    project.materials.splice(0, project.materials.length, ...retainedMaterials)
    let material = project.materials.find((item) => item.serverPath === master.file_path)
    if (!material) {
      material = {
        id: `book-master-${master.source_asset_ids.join('-')}`,
        type: 'audio',
        name: `${record?.book?.title || record?.title || 'Книга'} · мастер.mp3`,
        size: Number(master.file_size || 0),
        serverPath: master.file_path,
        src: mediaUrl(master.file_path),
        status: 'ready',
        progress: 1,
        role: 'book-master',
      }
      project.materials.push(material)
    }
    project.audioAssetId = material.id
    const total = Number(master.duration) || cursor
    project.scenes = project.scenes
      .filter((scene) => Number(scene.start) < total)
      .map((scene) => ({
        ...scene,
        start: Math.max(0, Number(scene.start) || 0),
        end: Math.min(total, Math.max((Number(scene.start) || 0) + 0.1, Number(scene.end) || total)),
      }))
    if (!project.scenes.length) {
      project.scenes = [{ id: uid('scene'), name: 'Основная сцена', start: 0, end: total, backgroundAssetId: null }]
    } else if (project.scenes.length === 1) {
      project.scenes[0].start = 0
      project.scenes[0].end = total
    }
  }
}

async function prepareBookVideoProject(record) {
  let master = null
  if ((record?.audio_assets || []).length) {
    master = await apiRequest(
      `/projects/${encodeURIComponent(activeProjectUuid.value)}/video-audio/master`,
      { method: 'POST' },
    )
  }
  syncBookChaptersToVideo(record, master)
  dirty.value = true
  return master
}

async function publishVideoCompatibility(projectUuid, editionId, payload) {
  if (!backend.online || !projectUuid || !editionId) return
  await apiRequest(
    `/editor-project?project_uuid=${encodeURIComponent(projectUuid)}&edition_id=${encodeURIComponent(editionId)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
}

async function flushActiveWorkspace() {
  clearTimeout(bookAutosaveTimer)
  if (bookSaveState.value === 'modified' || bookSaveState.value === 'error') {
    const saved = await saveCurrentChapter({ silent: true })
    if (!saved) return false
  }
  if (dirty.value && activeVideoEditionId.value) {
    const saved = await saveProject({ silent: true })
    if (!saved) return false
  }
  return true
}

async function switchProject(projectUuid, { initial = false } = {}) {
  if (!projectUuid || switchingProject.value) return
  if (!initial && projectUuid === activeProjectUuid.value) return
  switchingProject.value = true
  try {
    if (!initial && !(await flushActiveWorkspace())) {
      setNotice('Переключение отменено: текущие изменения не сохранены', 'error')
      return
    }
    pauseAll()
    const record = await apiRequest(`/projects/${encodeURIComponent(projectUuid)}/open`, { method: 'POST' })
    activeProjectUuid.value = projectUuid
    activeProjectRecord.value = record
    hydrateBookState(record)
    ttsJobs.value = []
    narrationJobIds.value = []
    if (record.book) {
      try {
        const jobs = await apiRequest(`/projects/${encodeURIComponent(projectUuid)}/tts-jobs`)
        ttsJobs.value = jobs.jobs || []
        narrationJobIds.value = ttsJobs.value
          .filter((job) => ['queued', 'running'].includes(job.status))
          .map((job) => job.uuid)
        ttsNow.value = Date.now()
      } catch { /* TTS history is optional */ }
    }
    const edition = record.video_editions?.[0] || null
    activeVideoEditionId.value = edition?.id || null
    if (edition) {
      replaceProject(edition.settings)
      syncBookChaptersToVideo(record)
      await publishVideoCompatibility(projectUuid, edition.id, serializeProject())
    } else {
      const emptyVideo = freshProject()
      emptyVideo.title = record.title
      emptyVideo.author = record.author
      emptyVideo.chapters = (record.chapters || []).map((chapter) => ({
        id: `book-chapter-${chapter.id}`,
        chapterId: chapter.id,
        title: chapter.title,
        start_seconds: 0,
        end_seconds: 0,
      }))
      replaceProject(emptyVideo)
    }
    if (initial) activeWorkspace.value = record.book ? 'book' : 'video'
    dirty.value = false
    await loadProjectCatalog()
    setNotice(`Открыт проект «${record.title}»`, 'success', 2200)
  } catch (error) {
    setNotice(`Не удалось открыть проект: ${error.message}`, 'error', 7000)
  } finally {
    switchingProject.value = false
  }
}

async function setWorkspace(workspace) {
  if (workspace === activeWorkspace.value) return
  if (workspace === 'video' && activeProjectRecord.value?.book) {
    await openBookInVideo()
    return
  }
  if (!(await flushActiveWorkspace())) return
  activeWorkspace.value = workspace
}

async function createEcosystemProject() {
  if (activeWorkspace.value === 'video') {
    const title = window.prompt('Название нового видеопроекта', 'Новая видеокнига')
    if (!title) return
    await createProjectRequest({ title, project_kind: 'video' })
  } else {
    await createBookProject()
  }
}

async function createBookProject() {
  const title = window.prompt('Название новой книги', 'Новая книга')
  if (!title) return
  const author = window.prompt('Автор', '') ?? ''
  await createProjectRequest({
    title,
    author,
    project_kind: 'book',
    create_first_chapter: true,
    voice: bookTts.voice,
  })
}

async function createProjectRequest(payload) {
  if (!(await flushActiveWorkspace())) return
  try {
    const created = await apiRequest('/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    await loadProjectCatalog()
    await switchProject(created.uuid, { initial: true })
  } catch (error) {
    setNotice(`Не удалось создать проект: ${error.message}`, 'error')
  }
}

async function createBookPart() {
  if (!activeProjectUuid.value) return
  try {
    const record = await apiRequest(`/projects/${encodeURIComponent(activeProjectUuid.value)}/book`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: activeProjectRecord.value?.title, language: 'ru' }),
    })
    activeProjectRecord.value = record
    hydrateBookState(record)
    await createBookChapter()
  } catch (error) {
    setNotice(`Не удалось создать книгу: ${error.message}`, 'error')
  }
}

async function selectBookChapter(chapterId) {
  if (chapterId === currentBookChapterId.value) return
  clearTimeout(bookAutosaveTimer)
  if (!(await saveCurrentChapter({ silent: true }))) return
  const chapter = activeProjectRecord.value?.chapters?.find((item) => item.id === chapterId)
  if (!chapter) return
  currentBookChapterId.value = chapterId
  bookChapterTitle.value = chapter.title
  bookChapterContent.value = chapter.content
  bookSaveState.value = 'saved'
  previewAudio.value = null
  const assets = (activeProjectRecord.value?.audio_assets || []).filter((asset) => asset.chapter_id === chapterId)
  selectedBookAudioId.value = assets.find((asset) => asset.is_active)?.id || assets[0]?.id || null
  stopBookPlayer()
}

function markBookDirty() {
  bookSaveState.value = 'modified'
  clearTimeout(bookAutosaveTimer)
  bookAutosaveTimer = setTimeout(() => { void saveCurrentChapter({ silent: true }) }, 900)
}

async function saveCurrentChapter({ silent = false } = {}) {
  const chapter = currentBookChapter.value
  if (!chapter || bookSaveState.value === 'saved') return true
  if (bookSaveState.value === 'saving') return false
  bookSaveState.value = 'saving'
  try {
    const saved = await apiRequest(
      `/projects/${encodeURIComponent(activeProjectUuid.value)}/chapters/${chapter.id}`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: bookChapterTitle.value, content: bookChapterContent.value }),
      },
    )
    const index = activeProjectRecord.value.chapters.findIndex((item) => item.id === saved.id)
    if (index >= 0) activeProjectRecord.value.chapters[index] = saved
    for (const asset of activeProjectRecord.value.audio_assets || []) {
      if (asset.chapter_id === saved.id) {
        asset.is_stale = Boolean(asset.source_text_hash && asset.source_text_hash !== saved.content_hash)
      }
    }
    bookSaveState.value = 'saved'
    if (!silent) setNotice('Глава сохранена', 'success', 1800)
    return true
  } catch (error) {
    bookSaveState.value = 'error'
    if (!silent) setNotice(`Не удалось сохранить главу: ${error.message}`, 'error')
    return false
  }
}

async function createBookChapter() {
  if (!activeProjectUuid.value) return
  if (!(await saveCurrentChapter({ silent: true }))) return
  try {
    const chapter = await apiRequest(`/projects/${encodeURIComponent(activeProjectUuid.value)}/chapters`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: '', content: '' }),
    })
    activeProjectRecord.value.chapters.push(chapter)
    await selectBookChapter(chapter.id)
  } catch (error) {
    setNotice(`Не удалось создать главу: ${error.message}`, 'error')
  }
}

async function duplicateBookChapter() {
  const chapter = currentBookChapter.value
  if (!chapter || !(await saveCurrentChapter({ silent: true }))) return
  try {
    const duplicate = await apiRequest(`/projects/${encodeURIComponent(activeProjectUuid.value)}/chapters`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: `${bookChapterTitle.value || chapter.title} — копия`,
        content: bookChapterContent.value,
      }),
    })
    activeProjectRecord.value.chapters.push(duplicate)
    await selectBookChapter(duplicate.id)
  } catch (error) {
    setNotice(`Не удалось дублировать главу: ${error.message}`, 'error')
  }
}

async function moveBookChapter(direction) {
  const chapters = activeProjectRecord.value?.chapters || []
  const index = chapters.findIndex((item) => item.id === currentBookChapterId.value)
  const nextIndex = index + direction
  if (index < 0 || nextIndex < 0 || nextIndex >= chapters.length) return
  const reordered = [...chapters]
  const [item] = reordered.splice(index, 1)
  reordered.splice(nextIndex, 0, item)
  try {
    await apiRequest(`/projects/${encodeURIComponent(activeProjectUuid.value)}/chapters/reorder`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chapter_ids: reordered.map((chapter) => chapter.id) }),
    })
    reordered.forEach((chapter, position) => { chapter.position = position })
    activeProjectRecord.value.chapters = reordered
  } catch (error) {
    setNotice(`Не удалось изменить порядок: ${error.message}`, 'error')
  }
}

async function archiveBookChapter() {
  const chapter = currentBookChapter.value
  if (!chapter || !window.confirm(`Удалить главу «${chapter.title}»? Она будет архивирована.`)) return
  try {
    await apiRequest(`/projects/${encodeURIComponent(activeProjectUuid.value)}/chapters/${chapter.id}`, { method: 'DELETE' })
    activeProjectRecord.value.chapters = activeProjectRecord.value.chapters.filter((item) => item.id !== chapter.id)
    currentBookChapterId.value = null
    hydrateBookState(activeProjectRecord.value)
  } catch (error) {
    setNotice(`Не удалось удалить главу: ${error.message}`, 'error')
  }
}

async function saveBookMetadata() {
  try {
    const record = await apiRequest(`/projects/${encodeURIComponent(activeProjectUuid.value)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(bookMetadata),
    })
    activeProjectRecord.value = record
    hydrateBookState(record)
    await loadProjectCatalog()
  } catch (error) {
    setNotice(`Не удалось сохранить метаданные: ${error.message}`, 'error')
  }
}

async function saveBookTtsSettings() {
  try {
    const settings = await apiRequest(`/projects/${encodeURIComponent(activeProjectUuid.value)}/tts-settings`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(bookTts),
    })
    activeProjectRecord.value.tts_settings = settings
    return true
  } catch (error) {
    setNotice(`Не удалось сохранить настройки TTS: ${error.message}`, 'error')
    return false
  }
}

async function narrateCurrentChapter() {
  if (!currentBookChapter.value || !(await saveCurrentChapter({ silent: true }))) return
  if (!(await saveBookTtsSettings())) return
  try {
    const job = await apiRequest(
      `/projects/${encodeURIComponent(activeProjectUuid.value)}/chapters/${currentBookChapter.value.id}/tts`,
      { method: 'POST' },
    )
    ttsJobs.value.unshift(job)
    narrationJobIds.value = [job.uuid]
    ttsNow.value = Date.now()
    pollTtsJob(job.uuid)
  } catch (error) {
    setNotice(`Не удалось запустить озвучивание: ${error.message}`, 'error')
  }
}

async function narrateWholeBook() {
  if (!(await saveCurrentChapter({ silent: true }))) return
  if (!(await saveBookTtsSettings())) return
  if (!window.confirm('Поставить все непустые главы в последовательную очередь озвучивания?')) return
  try {
    const result = await apiRequest(`/projects/${encodeURIComponent(activeProjectUuid.value)}/tts`, { method: 'POST' })
    ttsJobs.value = [...(result.jobs || []), ...ttsJobs.value]
    narrationJobIds.value = (result.jobs || []).map((job) => job.uuid)
    ttsNow.value = Date.now()
    if (result.jobs?.length) pollTtsBook()
    setNotice(`В очередь добавлено глав: ${result.queued}`, 'success')
  } catch (error) {
    setNotice(`Не удалось озвучить книгу: ${error.message}`, 'error')
  }
}

function pollTtsBook() {
  clearInterval(ttsPollTimer)
  ttsPollTimer = setInterval(async () => {
    try {
      ttsNow.value = Date.now()
      const result = await apiRequest(`/projects/${encodeURIComponent(activeProjectUuid.value)}/tts-jobs`)
      ttsJobs.value = result.jobs || []
      if (!ttsJobs.value.some((job) => ['queued', 'running'].includes(job.status))) {
        clearInterval(ttsPollTimer)
        const record = await apiRequest(`/projects/${encodeURIComponent(activeProjectUuid.value)}`)
        activeProjectRecord.value = record
        hydrateBookState(record)
        if (activeVideoEditionId.value) {
          try { await rebuildBookVideo(record) } catch { /* video can be rebuilt on next open */ }
        }
        const failed = visibleTtsJobs.value.filter((job) => job.status === 'failed').length
        setNotice(
          failed ? `Очередь завершена, ошибок: ${failed}. Готовые файлы сохранены.` : 'Озвучивание книги завершено',
          failed ? 'warning' : 'success',
          7000,
        )
      }
    } catch {
      clearInterval(ttsPollTimer)
    }
  }, 1500)
}

function pollTtsJob(jobUuid) {
  clearInterval(ttsPollTimer)
  ttsPollTimer = setInterval(async () => {
    try {
      ttsNow.value = Date.now()
      const job = await apiRequest(`/tts-jobs/${encodeURIComponent(jobUuid)}`)
      const index = ttsJobs.value.findIndex((item) => item.uuid === jobUuid)
      if (index >= 0) ttsJobs.value[index] = job
      if (!['queued', 'running'].includes(job.status)) {
        clearInterval(ttsPollTimer)
        const record = await apiRequest(`/projects/${encodeURIComponent(activeProjectUuid.value)}`)
        activeProjectRecord.value = record
        hydrateBookState(record)
        if (job.status === 'done') {
          if (activeVideoEditionId.value) {
            try { await rebuildBookVideo(record) } catch { /* video can be rebuilt on next open */ }
          }
          const ready = record.audio_assets?.find((asset) => asset.file_path === job.output_path)
          if (ready) selectBookAudio(ready, true)
          setNotice('Озвучка главы готова', 'success')
        } else {
          setNotice(job.user_error || 'Модуль озвучки не запущен. Проверьте установку компонентов TTS.', 'error', 8000)
        }
      }
    } catch {
      clearInterval(ttsPollTimer)
    }
  }, 1200)
}

function ttsJobLabel(job) {
  return ({
    queued: 'Задача поставлена в очередь',
    running: 'Озвучивание выполняется в фоне',
    done: 'Озвучка готова',
    failed: job.user_error || 'Модуль озвучки не запущен. Проверьте установку компонентов TTS.',
  }[job.status] || job.status)
}

function ttsJobShortLabel(status) {
  return ({
    queued: 'ожидает',
    running: 'генерируется',
    done: 'готово',
    failed: 'ошибка',
    cancelled: 'отменено',
    skipped: 'пропущено',
  }[status] || status)
}

function chapterTitleForJob(job) {
  return activeProjectRecord.value?.chapters?.find((chapter) => chapter.id === job.chapter_id)?.title || 'Глава'
}

async function previewBookVoice() {
  if (!activeProjectUuid.value || previewLoading.value) return
  if (!(await saveBookTtsSettings())) return
  const editor = bookTextEditor.value
  const selected = editor && editor.selectionStart !== editor.selectionEnd
    ? bookChapterContent.value.slice(editor.selectionStart, editor.selectionEnd)
    : ''
  previewLoading.value = true
  try {
    const preview = await apiRequest(`/projects/${encodeURIComponent(activeProjectUuid.value)}/tts-preview`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...bookTts, text: selected }),
    })
    bookPlayerShouldAutoplay = true
    previewAudio.value = preview
    selectedBookAudioId.value = null
  } catch (error) {
    setNotice(error.message || 'Не удалось создать пробу голоса.', 'error', 7000)
  } finally {
    previewLoading.value = false
  }
}

function selectBookAudio(asset, autoplay = false) {
  const previousUrl = bookPlayerUrl.value
  bookPlayerShouldAutoplay = autoplay
  previewAudio.value = null
  selectedBookAudioId.value = asset.id
  bookPlayerTime.value = 0
  bookPlayerDuration.value = Number(asset.duration || 0)
  if (bookPlayerUrl.value === previousUrl) {
    bookPlayerShouldAutoplay = false
    void reloadBookPlayer(autoplay)
  }
}

function selectAdjacentChapterAudio(direction) {
  const asset = direction < 0 ? previousChapterAudio.value : nextChapterAudio.value
  if (asset) selectBookAudio(asset, true)
}

function toggleBookPlayer() {
  const player = bookAudioEl.value
  if (!player) return
  if (player.paused) player.play().catch(() => setNotice('Не удалось воспроизвести аудиофайл.', 'error'))
  else player.pause()
}

function stopBookPlayer() {
  bookPlayerLoadToken += 1
  const player = bookAudioEl.value
  if (player) {
    player.pause()
    player.currentTime = 0
  }
  bookPlayerPlaying.value = false
  bookPlayerTime.value = 0
}

async function reloadBookPlayer(autoplay = false) {
  const token = ++bookPlayerLoadToken
  await nextTick()
  const player = bookAudioEl.value
  if (!player || !bookPlayerUrl.value || token !== bookPlayerLoadToken) return
  player.pause()
  player.currentTime = 0
  bookPlayerPlaying.value = false
  bookPlayerTime.value = 0
  bookPlayerDuration.value = Number(bookPlayerAsset.value?.duration || 0)
  applyBookPlayerVolume()
  if (!autoplay) return
  const ready = await waitForBookPlayerReady(player)
  if (token !== bookPlayerLoadToken) return
  if (!ready) {
    setNotice('Аудиофайл создан, но плеер не смог его загрузить. Нажмите ▶ или создайте пробу ещё раз.', 'error', 7000)
    return
  }
  try {
    await player.play()
  } catch (error) {
    if (token !== bookPlayerLoadToken) return
    setNotice('Аудиофайл создан, но браузер не разрешил автозапуск. Нажмите ▶ в плеере.', 'error', 7000)
  }
}

function waitForBookPlayerReady(player) {
  if (player.readyState >= 3) return Promise.resolve(true)
  return new Promise((resolve) => {
    let timeoutId = null
    const finish = (ready) => {
      player.removeEventListener('canplay', onReady)
      player.removeEventListener('error', onError)
      if (timeoutId !== null) window.clearTimeout(timeoutId)
      resolve(ready)
    }
    const onReady = () => finish(true)
    const onError = () => finish(false)
    player.addEventListener('canplay', onReady, { once: true })
    player.addEventListener('error', onError, { once: true })
    timeoutId = window.setTimeout(() => finish(player.readyState >= 2), 8000)
  })
}

function seekBookPlayer(value) {
  if (!bookAudioEl.value) return
  bookAudioEl.value.currentTime = Math.max(0, Math.min(value, bookPlayerDuration.value || value))
}

function applyBookPlayerVolume() {
  if (bookAudioEl.value) bookAudioEl.value.volume = bookPlayerVolume.value
}

function onBookAudioMetadata() {
  const player = bookAudioEl.value
  bookPlayerDuration.value = Number.isFinite(player?.duration) ? player.duration : Number(bookPlayerAsset.value?.duration || 0)
  applyBookPlayerVolume()
}

function onBookAudioTime() {
  bookPlayerTime.value = bookAudioEl.value?.currentTime || 0
}

async function refreshActiveProjectRecord() {
  const record = await apiRequest(`/projects/${encodeURIComponent(activeProjectUuid.value)}`)
  const chapterId = currentBookChapterId.value
  activeProjectRecord.value = record
  currentBookChapterId.value = chapterId
  return record
}

async function activateBookAudio(asset) {
  try {
    await apiRequest(`/projects/${encodeURIComponent(activeProjectUuid.value)}/audio/${asset.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_active: true }),
    })
    await refreshActiveProjectRecord()
    selectedBookAudioId.value = asset.id
  } catch (error) {
    setNotice(`Не удалось выбрать версию: ${error.message}`, 'error')
  }
}

async function renameBookAudio(asset) {
  const title = window.prompt('Название версии озвучки', asset.title || `Версия ${asset.version_number}`)
  if (!title) return
  try {
    await apiRequest(`/projects/${encodeURIComponent(activeProjectUuid.value)}/audio/${asset.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    })
    await refreshActiveProjectRecord()
  } catch (error) {
    setNotice(`Не удалось переименовать аудио: ${error.message}`, 'error')
  }
}

async function openBookAudioFolder(asset) {
  try {
    await apiRequest(`/projects/${encodeURIComponent(activeProjectUuid.value)}/audio/${asset.id}/open-folder`, { method: 'POST' })
  } catch (error) {
    setNotice(`Не удалось открыть папку: ${error.message}`, 'error')
  }
}

async function deleteBookAudio(asset) {
  if (!window.confirm(`Удалить аудиоверсию «${asset.title || asset.file_path}»? Это действие удалит файл с диска.`)) return
  try {
    await apiRequest(`/projects/${encodeURIComponent(activeProjectUuid.value)}/audio/${asset.id}`, { method: 'DELETE' })
    if (selectedBookAudioId.value === asset.id) selectedBookAudioId.value = null
    await refreshActiveProjectRecord()
  } catch (error) {
    setNotice(`Не удалось удалить аудио: ${error.message}`, 'error')
  }
}

async function sendBookAudioToVideo(asset) {
  if (!asset.is_active) await activateBookAudio(asset)
  await openBookInVideo()
  if (activeWorkspace.value === 'video') {
    await saveProject({ silent: true })
    setNotice('Озвучка собрана в мастер-аудио и добавлена на видеотаймлайн', 'success', 6500)
  }
}

function startBookAudioDrag(asset, event) {
  if (!asset?.id || asset.temporary || !event?.dataTransfer) return
  event.dataTransfer.effectAllowed = 'copy'
  event.dataTransfer.setData('application/x-bookender-audio-id', String(asset.id))
  event.dataTransfer.setData('text/plain', asset.title || asset.file_path || 'Озвучка главы')
}

async function dropBookAudioOnVideoTab(event) {
  const assetId = Number(event.dataTransfer?.getData('application/x-bookender-audio-id'))
  const asset = (activeProjectRecord.value?.audio_assets || []).find((item) => item.id === assetId)
  if (!asset) return
  await sendBookAudioToVideo(asset)
}

async function openTtsLog() {
  try {
    await apiRequest('/tts/open-log', { method: 'POST' })
  } catch (error) {
    setNotice(error.message || 'Не удалось открыть технический лог.', 'error')
  }
}

function chapterAudioState(chapter) {
  const assets = (activeProjectRecord.value?.audio_assets || []).filter((asset) => asset.chapter_id === chapter.id)
  if (!assets.length) return 'none'
  return assets.some((asset) => !asset.is_stale) ? 'ready' : 'stale'
}

function chapterAudioStateLabel(chapter) {
  return ({ none: 'Нет озвучки', ready: 'Озвучка готова', stale: 'Озвучка устарела' }[chapterAudioState(chapter)])
}

function chapterTitleForAudio(asset) {
  return activeProjectRecord.value?.chapters?.find((item) => item.id === asset.chapter_id)?.title || 'Аудиокнига'
}

async function createVideoEditionForActiveBook({ prepare = true } = {}) {
  if (!activeProjectUuid.value) return
  try {
    const edition = await apiRequest(`/projects/${encodeURIComponent(activeProjectUuid.value)}/video-editions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: activeProjectRecord.value?.title || null }),
    })
    activeVideoEditionId.value = edition.id
    replaceProject(edition.settings)
    if (prepare) {
      await prepareBookVideoProject(activeProjectRecord.value)
      await publishVideoCompatibility(activeProjectUuid.value, edition.id, serializeProject())
      dirty.value = false
    }
    const refreshed = await apiRequest(`/projects/${encodeURIComponent(activeProjectUuid.value)}`)
    activeProjectRecord.value = refreshed
    await loadProjectCatalog()
    return edition
  } catch (error) {
    setNotice(`Не удалось создать видеоверсию: ${error.message}`, 'error')
    return null
  }
}

async function rebuildBookVideo(record, { announce = false } = {}) {
  let master = null
  let warning = ''
  try {
    master = await prepareBookVideoProject(record)
    if (master?.missing_chapter_ids?.length) {
      warning = `Без озвучки пока глав: ${master.missing_chapter_ids.length}.`
    }
  } catch (error) {
    syncBookChaptersToVideo(record)
    warning = error.message
  }
  if (activeVideoEditionId.value) {
    await publishVideoCompatibility(
      activeProjectUuid.value,
      activeVideoEditionId.value,
      serializeProject(),
    )
    dirty.value = false
  }
  await nextTick()
  audioEl.value?.load()
  await refreshWaveform()
  if (announce) {
    if (master) {
      setNotice(
        warning
          ? `Озвученные главы разложены на таймлайне. ${warning}`
          : `Видео готово: на таймлайне глав ${master.chapters.length}.`,
        warning ? 'warning' : 'success',
        7000,
      )
    } else {
      setNotice(
        `Видео открыто без мастер-аудио: ${warning || 'нет готовых озвучек'}`,
        'warning',
        7000,
      )
    }
  }
  return master
}

async function openBookInVideo() {
  if (videoPreparing.value) return
  if (!(await saveCurrentChapter({ silent: true }))) return
  videoPreparing.value = true
  activeWorkspace.value = 'video'
  pauseAll()
  try {
    if (!activeVideoEditionId.value) {
      await createVideoEditionForActiveBook({ prepare: false })
      if (!activeVideoEditionId.value) return
    }
    await rebuildBookVideo(activeProjectRecord.value, { announce: true })
  } catch (error) {
    setNotice(`Не удалось подготовить видео: ${error.message}`, 'error', 8000)
  } finally {
    videoPreparing.value = false
  }
}

async function backupActiveProject() {
  if (!activeProjectUuid.value) return
  try {
    const result = await apiRequest(`/projects/${encodeURIComponent(activeProjectUuid.value)}/backup`, { method: 'POST' })
    setNotice(`Резервная копия создана: ${result.path}`, 'success', 7000)
  } catch (error) {
    setNotice(`Не удалось создать резервную копию: ${error.message}`, 'error')
  }
}

async function loadInitialProject() {
  loading.value = true
  hydrating.value = true
  try {
    const health = await apiRequest('/health')
    backend.online = !!health.ok
    backend.version = health.version || ''
    backend.python = health.python || ''
    Object.assign(ttsRuntime, health.tts || {})
  } catch {
    backend.online = false
  } finally {
    backend.checking = false
  }

  let restored = false
  if (backend.online) {
    void loadTtsRuntime()
    loadingMessage.value = 'Загружаю библиотеку проектов…'
    try {
      const activeUuid = await loadProjectCatalog()
      if (activeUuid) {
        await switchProject(activeUuid, { initial: true })
        restored = true
      }
    } catch (error) {
      // Compatibility fallback for an installation that has not run the
      // ecosystem migration yet.
      try {
        const saved = await apiRequest('/editor-project')
        if (saved.exists && saved.project) {
          replaceProject(saved.project)
          activeWorkspace.value = 'video'
          restored = true
        }
      } catch { /* recovery JSON is optional */ }
      setNotice(`Библиотека проектов недоступна: ${error.message}`, 'warning')
    }
    if (activeWorkspace.value === 'video') void refreshWaveform()
  } else {
    const local = localStorage.getItem('book-wunderwaffe-project')
    if (local) {
      try { replaceProject(JSON.parse(local)); restored = true } catch { /* ignore invalid local cache */ }
    }
  }

  ensureSceneBounds()
  dirty.value = false
  hydrating.value = false
  loading.value = false
  if (!backend.online) setNotice('Backend не найден: предпросмотр работает, экспорт временно недоступен.', 'warning', 6500)
  else if (restored) setNotice('Проект восстановлен', 'success', 2400)

  await nextTick()
  audioEl.value?.load()
  videoEl.value?.load()
}

function hydrateDiscoveredMaterials(data) {
  const discovered = Array.isArray(data.materials)
    ? data.materials
    : [...(data.audios || []), ...(data.images || []), ...(data.videos || [])]
  for (const item of discovered) {
    const serverPath = String(item.serverPath || item.path || '')
    if (!serverPath || project.materials.some((asset) => asset.serverPath === serverPath)) continue
    const type = item.kind || materialType(item.name || serverPath, '')
    if (!type) continue
    project.materials.push({
      id: uid(`server-${type}`),
      type,
      name: item.name || serverPath.replaceAll('\\', '/').split('/').pop(),
      size: item.size || 0,
      serverPath,
      src: mediaUrl(serverPath),
      status: 'ready',
      progress: 1,
    })
  }

  const entries = [
    ['audio', data.audio, 'audio', 'audioAssetId'],
    ['video', data.video, 'video', 'videoAssetId'],
    ['cover', data.cover, 'image', 'coverAssetId'],
    ['background', data.background, 'image', 'backgroundAssetId'],
  ]
  for (const [role, info, type, key] of entries) {
    if (!info?.exists || project[key]) continue
    const serverPath = String(info.path || '')
    let asset = project.materials.find((item) => item.serverPath === serverPath)
    if (!asset) {
      asset = {
        id: uid(`server-${role}`),
        type,
        name: serverPath.replaceAll('\\', '/').split('/').pop() || role,
        size: info.size || 0,
        serverPath,
        src: mediaUrl(serverPath),
        status: 'ready',
        progress: 1,
      }
      project.materials.push(asset)
    }
    project[key] = asset.id
  }
}

async function refreshWaveform() {
  if (!backend.online || !audioAsset.value) return
  try {
    const result = await apiRequest('/waveform?samples=10000')
    if (Array.isArray(result.samples)) waveformSamples.value = result.samples
  } catch { /* visualizer has a deterministic idle fallback */ }
}

function newProject() {
  if (dirty.value && !window.confirm('Создать новый проект? Несохранённые изменения будут потеряны.')) return
  pauseAll()
  replaceProject(freshProject())
  waveformSamples.value = []
  dirty.value = true
  setNotice('Создан новый проект', 'success')
}

async function saveProject({ silent = false } = {}) {
  if (saving.value) return false
  saving.value = true
  const payload = serializeProject()
  localStorage.setItem('book-wunderwaffe-project', JSON.stringify(payload))
  try {
    if (backend.online) {
      if (activeProjectUuid.value && !activeVideoEditionId.value) {
        const edition = await apiRequest(`/projects/${encodeURIComponent(activeProjectUuid.value)}/video-editions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: project.title || null }),
        })
        activeVideoEditionId.value = edition.id
      }
      const query = activeProjectUuid.value
        ? `?project_uuid=${encodeURIComponent(activeProjectUuid.value)}&edition_id=${encodeURIComponent(activeVideoEditionId.value)}`
        : ''
      const saved = await apiRequest(`/editor-project${query}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (saved.edition_id) activeVideoEditionId.value = saved.edition_id
    }
    dirty.value = false
    if (!silent) setNotice(backend.online ? 'Проект сохранён' : 'Проект сохранён в браузере', 'success')
    return true
  } catch (error) {
    setNotice(`Не удалось сохранить: ${error.message}`, 'error', 7000)
    return false
  } finally {
    saving.value = false
  }
}

function onProjectInput(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    try {
      replaceProject(JSON.parse(String(reader.result)))
      dirty.value = true
      ensureSceneBounds()
      setNotice('Проект открыт. Локальные файлы без копии на backend нужно добавить повторно.', 'success', 6200)
    } catch (error) {
      setNotice(`Файл проекта повреждён: ${error.message}`, 'error')
    }
  }
  reader.readAsText(file, 'utf-8')
}

function onAssetInput(event) {
  importFiles(event.target.files)
  event.target.value = ''
}

function onMusicInput(event) {
  importFiles(event.target.files, { asMusic: true })
  event.target.value = ''
}

async function onBookChapterImageInput(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  const chapterId = currentBookChapterId.value
  if (!file || !chapterId || !activeProjectUuid.value) return
  try {
    await apiRequest(
      `/projects/${encodeURIComponent(activeProjectUuid.value)}/chapters/${chapterId}/image?filename=${encodeURIComponent(file.name)}`,
      {
        method: 'PUT',
        headers: { 'Content-Type': file.type || 'application/octet-stream' },
        body: file,
      },
    )
    const record = await refreshActiveProjectRecord()
    if (activeVideoEditionId.value) {
      syncBookChaptersToVideo(record)
      await publishVideoCompatibility(
        activeProjectUuid.value,
        activeVideoEditionId.value,
        serializeProject(),
      )
    }
    setNotice('Изображение главы сохранено и будет использовано в видеокниге', 'success', 6000)
  } catch (error) {
    setNotice(`Не удалось сохранить изображение главы: ${error.message}`, 'error', 7000)
  }
}

async function removeBookChapterImage() {
  const chapterId = currentBookChapterId.value
  if (!chapterId || !activeProjectUuid.value) return
  try {
    await apiRequest(
      `/projects/${encodeURIComponent(activeProjectUuid.value)}/chapters/${chapterId}/image`,
      { method: 'DELETE' },
    )
    const record = await refreshActiveProjectRecord()
    if (activeVideoEditionId.value) {
      syncBookChaptersToVideo(record)
      await publishVideoCompatibility(
        activeProjectUuid.value,
        activeVideoEditionId.value,
        serializeProject(),
      )
    }
    setNotice('Изображение главы убрано', 'success')
  } catch (error) {
    setNotice(`Не удалось убрать изображение: ${error.message}`, 'error')
  }
}

function onDrop(event) {
  importFiles(event.dataTransfer?.files)
}

function importFiles(fileList, { asMusic = false } = {}) {
  const files = [...(fileList || [])]
  if (!files.length) return
  let accepted = 0
  for (const file of files) {
    const type = materialType(file.name, file.type)
    if (asMusic && type !== 'audio') {
      setNotice(`Для музыкальной дорожки нужен аудиофайл: «${file.name}»`, 'error', 6000)
      continue
    }
    if (!type) {
      setNotice(`Формат «${file.name}» не поддерживается`, 'error', 6000)
      continue
    }
    const src = URL.createObjectURL(file)
    objectUrls.add(src)
    const asset = {
      id: uid('asset'), type, name: file.name, size: file.size, mime: file.type,
      file, src, serverPath: '', status: backend.online ? 'uploading' : 'local', progress: 0,
      role: asMusic ? 'music' : undefined,
    }
    project.materials.push(asset)
    if (asMusic) {
      project.musicAssetId = asset.id
      project.music.enabled = true
    } else {
      assignImportedAsset(asset)
    }
    accepted += 1
    if (backend.online) uploadAsset(asset)
  }
  if (accepted) {
    dirty.value = true
    setNotice(`Добавлено файлов: ${accepted}`, 'success')
    nextTick(() => {
      audioEl.value?.load()
      musicEl.value?.load()
      videoEl.value?.load()
      applyMusicMix()
    })
  }
}

function assignImportedAsset(asset) {
  if (asset.type === 'audio' && !project.audioAssetId) project.audioAssetId = asset.id
  if (asset.type === 'video' && !project.videoAssetId) project.videoAssetId = asset.id
  if (asset.type === 'image') {
    const lower = asset.name.toLowerCase()
    if ((!project.coverAssetId || /cover|облож/.test(lower)) && !/background|backdrop|\bbg\b|фон/.test(lower)) project.coverAssetId = asset.id
    else if (!project.backgroundAssetId) project.backgroundAssetId = asset.id
  }
}

function uploadAsset(asset) {
  const xhr = new XMLHttpRequest()
  const query = new URLSearchParams({ filename: asset.name, kind: asset.type })
  xhr.open('PUT', `${API}/media/import?${query}`)
  xhr.setRequestHeader('Content-Type', asset.mime || 'application/octet-stream')
  xhr.upload.onprogress = (event) => {
    if (event.lengthComputable) asset.progress = event.loaded / event.total
  }
  xhr.onerror = () => {
    asset.status = 'error'
    setNotice(`Не удалось синхронизировать «${asset.name}»`, 'error', 6500)
  }
  xhr.onload = async () => {
    let result = {}
    try { result = JSON.parse(xhr.responseText || '{}') } catch { /* handled below */ }
    if (xhr.status < 200 || xhr.status >= 300) {
      asset.status = 'error'
      setNotice(result.detail || `Ошибка загрузки «${asset.name}»`, 'error', 6500)
      return
    }
    asset.serverPath = result.serverPath || result.path || ''
    asset.status = 'ready'
    asset.progress = 1
    dirty.value = true
    if (asset.type === 'audio' && project.audioAssetId === asset.id) await refreshWaveform()
    if (asset.type === 'audio' && project.musicAssetId === asset.id) {
      nextTick(() => {
        musicEl.value?.load()
        applyMusicMix()
      })
    }
  }
  xhr.send(asset.file)
}

function assignAsset(role, id) {
  if (role === 'music' && project.audioAssetId === id) project.audioAssetId = null
  if (role === 'audio' && project.musicAssetId === id) project.musicAssetId = null
  project[`${role}AssetId`] = id
  if (role === 'music') {
    const asset = assetById(id)
    if (asset) asset.role = 'music'
    project.music.enabled = true
    select('music')
  }
  dirty.value = true
  nextTick(() => {
    if (role === 'audio') { audioEl.value?.load(); refreshWaveform() }
    if (role === 'music') {
      musicEl.value?.load()
      applyMusicMix()
    }
    if (role === 'video') videoEl.value?.load()
  })
}

function removeAsset(id) {
  const asset = assetById(id)
  if (!asset) return
  if (project.audioAssetId === id || project.musicAssetId === id || project.videoAssetId === id) pauseAll()
  for (const key of ['audioAssetId', 'musicAssetId', 'videoAssetId', 'coverAssetId', 'backgroundAssetId']) {
    if (project[key] === id) project[key] = null
  }
  for (const scene of project.scenes) if (scene.backgroundAssetId === id) scene.backgroundAssetId = null
  if (asset.src?.startsWith('blob:')) {
    URL.revokeObjectURL(asset.src)
    objectUrls.delete(asset.src)
  }
  project.materials.splice(project.materials.findIndex((item) => item.id === id), 1)
  select('project')
  dirty.value = true
  setNotice('Материал убран из проекта. Исходный файл не удалён.', 'info')
}

function layerVisible(id) {
  return project.layers[id]?.visible !== false
}

function measuredTextWidth(context, text, letterSpacing) {
  const value = String(text || '')
  return context.measureText(value).width + Math.max(0, value.length - 1) * letterSpacing
}

function measuredLineCount(context, text, maxWidth, letterSpacing) {
  let lines = 0
  for (const paragraph of String(text || '').split(/\r?\n/)) {
    const words = paragraph.trim().split(/\s+/).filter(Boolean)
    if (!words.length) {
      lines += 1
      continue
    }
    let line = ''
    for (const word of words) {
      const candidate = line ? `${line} ${word}` : word
      if (measuredTextWidth(context, candidate, letterSpacing) <= maxWidth) {
        line = candidate
        continue
      }
      if (line) {
        lines += 1
        line = ''
      }
      if (measuredTextWidth(context, word, letterSpacing) <= maxWidth) {
        line = word
        continue
      }
      let fragment = ''
      for (const character of word) {
        if (fragment && measuredTextWidth(context, `${fragment}${character}`, letterSpacing) > maxWidth) {
          lines += 1
          fragment = character
        } else {
          fragment += character
        }
      }
      line = fragment
    }
    if (line) lines += 1
  }
  return Math.max(1, lines)
}

function fitChapterTitles() {
  const stack = titleStackEl.value
  if (!stack || stack.clientWidth < 2 || stack.clientHeight < 2) return

  const configured = Number(project.layers.title?.fontSize)
  const maximum = Math.max(16, Math.min(96, Number.isFinite(configured) ? configured : 48))
  const title = currentChapter.value?.title || 'Добавьте первую главу'
  const titleElement = stack.querySelector(':scope > strong')
  const titleStyle = titleElement ? getComputedStyle(titleElement) : null
  titleMeasureCanvas ||= document.createElement('canvas')
  const context = titleMeasureCanvas.getContext('2d')
  if (!context) return

  let low = 24
  let high = Math.round(maximum * 2)
  let best = low

  while (low <= high) {
    const middle = Math.floor((low + high) / 2)
    const candidate = middle / 2
    const weight = titleStyle?.fontWeight || '640'
    const family = titleStyle?.fontFamily || 'Inter, sans-serif'
    context.font = `${weight} ${candidate}px ${family}`
    const letterSpacing = candidate * -.035
    const titleLines = measuredLineCount(context, title, stack.clientWidth, letterSpacing)
    const neighborCount = Number(!!previousChapter.value) + Number(!!nextChapter.value)
    const neighborHeight = Math.max(8, candidate * .3) * 1.15
    const gap = Math.max(4, candidate * .18)
    const contentHeight = titleLines * candidate * 1.04
      + neighborCount * neighborHeight
      + Math.max(0, neighborCount) * gap
    const fits = contentHeight <= stack.clientHeight + 1
    if (fits) {
      best = middle
      low = middle + 1
    } else {
      high = middle - 1
    }
  }

  stack.style.setProperty('font-size', `${best / 2}px`, 'important')
}

function scheduleTitleFit() {
  if (titleFitFrame !== null) cancelAnimationFrame(titleFitFrame)
  titleFitFrame = requestAnimationFrame(() => {
    titleFitFrame = null
    fitChapterTitles()
  })
}

function layerStyle(id) {
  const layer = project.layers[id]
  if (!layer) return {}
  const style = { left: `${layer.x}%`, top: `${layer.y}%`, width: `${layer.w}%`, height: `${layer.h}%` }
  if (id === 'title') {
    style['--title-size'] = `${layer.fontSize || 48}px`
    style['--title-color'] = layer.color || '#f4f0e8'
  }
  if (id === 'caption') {
    style['--caption-size'] = `${layer.fontSize || 28}px`
    style['--caption-weight'] = String(layer.fontWeight || 400)
    style['--caption-background'] = `rgba(7, 5, 10, ${Number.isFinite(Number(layer.backgroundOpacity)) ? Number(layer.backgroundOpacity) : 0.68})`
  }
  return style
}

function layerLabel(id) {
  return ({ cover: 'Обложка', title: 'Заголовок', visualizer: 'Визуализатор', caption: 'Текст озвучки' })[id] || 'Слой'
}

function onLayerPointerDown(id, event) {
  select('layer', id)
  const layer = project.layers[id]
  const rect = sceneEl.value?.getBoundingClientRect()
  if (!layer || !rect) return
  const start = { clientX: event.clientX, clientY: event.clientY, x: layer.x, y: layer.y }
  const move = (moveEvent) => {
    const dx = (moveEvent.clientX - start.clientX) / rect.width * 100
    const dy = (moveEvent.clientY - start.clientY) / rect.height * 100
    layer.x = Math.max(0, Math.min(100 - layer.w, start.x + dx))
    layer.y = Math.max(0, Math.min(100 - layer.h, start.y + dy))
    dirty.value = true
  }
  const up = () => {
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', up)
  }
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', up)
}

function resetLayer(id) {
  if (!DEFAULT_LAYERS[id]) return
  Object.assign(project.layers[id], clone(DEFAULT_LAYERS[id]))
  dirty.value = true
}

function parseTimecode(value) {
  if (typeof value === 'number') return Math.max(0, value)
  const text = String(value || '').trim().replace(',', '.')
  if (!text.includes(':')) return Math.max(0, Number(text) || 0)
  const parts = text.split(':').map(Number)
  if (parts.some((part) => !Number.isFinite(part))) return 0
  return parts.reduce((total, part) => total * 60 + part, 0)
}

function formatTime(value, forceHours = false) {
  const seconds = Number.isFinite(Number(value)) ? Math.max(0, Number(value)) : 0
  const whole = Math.floor(seconds)
  const hours = Math.floor(whole / 3600)
  const minutes = Math.floor((whole % 3600) / 60)
  const secs = whole % 60
  if (hours || forceHours) return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`
  return `${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`
}

function formatTimecode(value) {
  return formatTime(value, true)
}

function chapterEnd(id) {
  return timelineChapters.value.find((item) => item.id === id)?.end_seconds || 0
}

function updateChapterStart(chapter, value) {
  chapter.start_seconds = Math.max(0, Math.min(parseTimecode(value), Math.max(0, duration.value - 0.1)))
  project.chapters.sort((a, b) => a.start_seconds - b.start_seconds)
  dirty.value = true
}

function addChapterAtCursor() {
  const start = project.chapters.length ? Math.round(currentTime.value * 10) / 10 : 0
  const chapter = normalizeChapter({ title: `Глава ${project.chapters.length + 1}`, start_seconds: start }, project.chapters.length)
  project.chapters.push(chapter)
  project.chapters.sort((a, b) => a.start_seconds - b.start_seconds)
  select('chapter', chapter.id)
  dirty.value = true
  setNotice(`Глава добавлена в ${formatTimecode(start)}`, 'success')
}

function removeChapter(id) {
  const index = project.chapters.findIndex((item) => item.id === id)
  if (index < 0) return
  project.chapters.splice(index, 1)
  select('project')
  dirty.value = true
}

function selectChapter(chapter) {
  seekTo(chapter.start_seconds)
  select('chapter', chapter.id)
}

function selectVideoChapterAudio(chapter) {
  seekTo(chapter.start_seconds)
  if (chapter.audioAssetId) select('asset', chapter.audioAssetId)
}

function ensureSceneBounds() {
  if (!project.scenes.length) project.scenes.push({ id: uid('scene'), name: 'Основная сцена', start: 0, end: Math.max(duration.value, 60), backgroundAssetId: null })
  if (project.scenes.length === 1 && project.scenes[0].start === 0 && project.scenes[0].end <= 60) {
    project.scenes[0].end = Math.max(duration.value, 60)
  }
}

function addSceneAtCursor() {
  const start = Math.round(currentTime.value * 10) / 10
  const nextChapter = timelineChapters.value.find((item) => item.start_seconds > start)
  const end = Math.min(duration.value || start + 60, Math.max(start + 1, nextChapter?.start_seconds || start + 60))
  const scene = { id: uid('scene'), name: `Сцена ${project.scenes.length + 1}`, start, end, backgroundAssetId: null }
  project.scenes.push(scene)
  project.scenes.sort((a, b) => a.start - b.start)
  select('scene', scene.id)
  dirty.value = true
  setNotice(`Сцена добавлена в ${formatTimecode(start)}`, 'success')
}

function selectScene(scene) {
  seekTo(scene.start)
  select('scene', scene.id)
}

function updateSceneTime(key, value) {
  if (!selectedScene.value) return
  const parsed = Math.max(0, parseTimecode(value))
  if (key === 'start') selectedScene.value.start = Math.min(parsed, selectedScene.value.end - 0.1)
  else selectedScene.value.end = Math.max(parsed, selectedScene.value.start + 0.1)
  project.scenes.sort((a, b) => a.start - b.start)
  dirty.value = true
}

function removeScene(id) {
  if (project.scenes.length <= 1) return
  const index = project.scenes.findIndex((item) => item.id === id)
  if (index >= 0) project.scenes.splice(index, 1)
  select('project')
  dirty.value = true
}

function masterElement() {
  return masterKind.value === 'audio' ? audioEl.value : masterKind.value === 'video' ? videoEl.value : null
}

function secondaryElement() {
  return masterKind.value === 'audio' && videoSource.value ? videoEl.value : null
}

function musicTimeAt(absoluteTime) {
  const music = musicEl.value
  const musicDuration = Number(music?.duration)
  if (!Number.isFinite(musicDuration) || musicDuration <= 0) return Math.max(0, absoluteTime)
  if (project.music.loop) return Math.max(0, absoluteTime) % musicDuration
  return Math.min(Math.max(0, absoluteTime), Math.max(0, musicDuration - 0.02))
}

async function ensureMusicGraph() {
  const element = musicEl.value
  const AudioContextClass = globalThis.AudioContext || globalThis.webkitAudioContext
  if (!element || !AudioContextClass) {
    musicEqState.active = false
    musicEqState.error = true
    musicEqState.message = 'EQ предпросмотра недоступен; в MP4 он всё равно будет применён'
    return false
  }
  try {
    if (!musicAudioContext || musicAudioContext.state === 'closed') {
      musicAudioContext = new AudioContextClass()
    }
    if (!musicMediaSource) {
      musicMediaSource = musicAudioContext.createMediaElementSource(element)
      musicLowFilter = musicAudioContext.createBiquadFilter()
      musicLowFilter.type = 'lowshelf'
      musicLowFilter.frequency.value = 120
      musicMidFilter = musicAudioContext.createBiquadFilter()
      musicMidFilter.type = 'peaking'
      musicMidFilter.frequency.value = 1100
      musicMidFilter.Q.value = 0.85
      musicHighFilter = musicAudioContext.createBiquadFilter()
      musicHighFilter.type = 'highshelf'
      musicHighFilter.frequency.value = 7000
      musicGain = musicAudioContext.createGain()
      musicMediaSource
        .connect(musicLowFilter)
        .connect(musicMidFilter)
        .connect(musicHighFilter)
        .connect(musicGain)
        .connect(musicAudioContext.destination)
    }
    if (musicAudioContext.state === 'suspended') await musicAudioContext.resume()
    musicEqState.active = musicAudioContext.state === 'running'
    musicEqState.error = !musicEqState.active
    musicEqState.message = musicEqState.active
      ? 'EQ активен — изменения слышны сразу'
      : 'Аудиодвижок приостановлен; нажмите «Проверить музыку»'
    return true
  } catch (error) {
    musicEqState.active = false
    musicEqState.error = true
    musicEqState.message = `EQ предпросмотра не запустился: ${error?.message || 'ошибка аудиодвижка'}`
    return false
  }
}

function applyMusicMix() {
  const element = musicEl.value
  const enabled = !!project.music.enabled && !!musicSource.value
  const level = enabled ? Math.max(0, Math.min(1, Number(project.music.volume) || 0)) : 0
  const now = musicAudioContext?.currentTime || 0

  function setAudioValue(parameter, value) {
    if (!parameter) return
    parameter.cancelScheduledValues(now)
    parameter.setValueAtTime(value, now)
  }

  setAudioValue(musicLowFilter?.gain, Math.max(-12, Math.min(12, Number(project.music.bass) || 0)))
  setAudioValue(musicMidFilter?.gain, Math.max(-12, Math.min(12, Number(project.music.mid) || 0)))
  setAudioValue(musicHighFilter?.gain, Math.max(-12, Math.min(12, Number(project.music.treble) || 0)))
  setAudioValue(musicGain?.gain, 1)
  if (element) {
    // Native media volume is reliable in Qt WebEngine even when Web Audio is
    // unavailable. Keep EQ in the graph, but never route volume through it.
    element.volume = level
    element.loop = !!project.music.loop
    if (!enabled) element.pause()
  }
}

async function onMusicControlInput(activateEq = false) {
  applyMusicMix()
  if (activateEq || musicPreviewPlaying.value || playing.value) {
    await ensureMusicGraph()
    applyMusicMix()
  }
}

async function startMusicPreview(absoluteTime) {
  const element = musicEl.value
  if (!element || !musicSource.value || !project.music.enabled) return
  const target = musicTimeAt(absoluteTime)
  if (Math.abs((element.currentTime || 0) - target) > 0.08) {
    try { element.currentTime = target } catch { /* metadata not ready */ }
  }
  await ensureMusicGraph()
  applyMusicMix()
  await element.play()
}

async function toggleMusicPreview() {
  const element = musicEl.value
  if (!element || !musicSource.value) {
    setNotice('Сначала выберите музыкальный файл', 'warning')
    return
  }
  if (!element.paused) {
    element.pause()
    return
  }
  audioEl.value?.pause()
  videoEl.value?.pause()
  playing.value = false
  cancelAnimationFrame(playbackFrame)
  try {
    project.music.enabled = true
    await ensureMusicGraph()
    applyMusicMix()
    const target = musicTimeAt(currentTime.value)
    if (Math.abs((element.currentTime || 0) - target) > 0.08) element.currentTime = target
    await element.play()
  } catch (error) {
    musicEqState.active = false
    musicEqState.error = true
    musicEqState.message = `Не удалось запустить пробу: ${error.message}`
  }
}

function onMusicMetadata() {
  const element = musicEl.value
  if (element) {
    try { element.currentTime = musicTimeAt(currentTime.value) } catch { /* metadata not ready */ }
  }
  applyMusicMix()
}

function onMusicError() {
  musicEqState.active = false
  musicEqState.error = true
  musicEqState.message = 'Музыкальный файл не удалось открыть'
  if (musicSource.value) setNotice('Музыкальный файл недоступен или не поддерживается браузером.', 'error', 6500)
}

function onMusicSelectionChanged() {
  pauseAll()
  nextTick(() => {
    musicEl.value?.load()
    applyMusicMix()
  })
}

function resetMusicMix() {
  Object.assign(project.music, clone(DEFAULT_MUSIC_MIX))
  applyMusicMix()
}

function setMusicVolume(level) {
  project.music.volume = Math.max(0, Math.min(1, Number(level) || 0))
  void onMusicControlInput(false)
}

function releaseLiveVisualizer() {
  try { visualStreamSource?.disconnect() } catch { /* already disconnected */ }
  try { visualAnalyser?.disconnect() } catch { /* analyser has no outputs */ }
  for (const track of visualizerStream?.getTracks?.() || []) {
    try { track.stop() } catch { /* already stopped */ }
  }
  visualStreamSource = null
  visualAnalyser = null
  visualizerStream = null
  visualizerMaster = null
  visualizerFrequencyData = null
}

function disconnectLiveVisualizer({ clearPending = true } = {}) {
  visualizerGeneration += 1
  releaseLiveVisualizer()
  if (clearPending) visualizerConnectPending = null
}

async function connectLiveVisualizer() {
  const master = masterElement()
  if (!master || !playing.value) return false
  if (visualizerConnectPending) return visualizerConnectPending

  visualizerLastConnectAttempt = performance.now()
  const capture = master.captureStream || master.mozCaptureStream
  const AudioContextClass = globalThis.AudioContext || globalThis.webkitAudioContext
  if (typeof capture !== 'function' || !AudioContextClass) return false

  const generation = visualizerGeneration
  const request = (async () => {
    let stream = null
    let source = null
    let analyser = null
    try {
      const liveTracks = visualizerStream?.getAudioTracks?.()
        ?.some((track) => track.readyState === 'live')
      if (visualAnalyser && visualizerMaster === master && liveTracks) {
        if (visualAudioContext?.state === 'suspended') await visualAudioContext.resume()
        return generation === visualizerGeneration
          && masterElement() === master
          && playing.value
          && visualAudioContext?.state === 'running'
      }

      stream = capture.call(master)
      if (!stream?.getAudioTracks?.().length) return false
      if (!visualAudioContext || visualAudioContext.state === 'closed') {
        visualAudioContext = new AudioContextClass()
      }
      if (visualAudioContext.state === 'suspended') await visualAudioContext.resume()
      if (generation !== visualizerGeneration || masterElement() !== master || !playing.value) return false

      analyser = visualAudioContext.createAnalyser()
      analyser.fftSize = 2048
      analyser.smoothingTimeConstant = 0.62
      analyser.minDecibels = -84
      analyser.maxDecibels = -10
      source = visualAudioContext.createMediaStreamSource(stream)
      source.connect(analyser)

      releaseLiveVisualizer()
      visualStreamSource = source
      visualAnalyser = analyser
      visualizerStream = stream
      visualizerMaster = master
      visualizerFrequencyData = new Uint8Array(analyser.frequencyBinCount)
      stream = null
      source = null
      analyser = null
      return true
    } catch {
      return false
    } finally {
      try { source?.disconnect() } catch { /* connection was never published */ }
      try { analyser?.disconnect() } catch { /* analyser was never published */ }
      for (const track of stream?.getTracks?.() || []) {
        try { track.stop() } catch { /* temporary capture already stopped */ }
      }
    }
  })()
  visualizerConnectPending = request
  try {
    return await request
  } finally {
    if (visualizerConnectPending === request) visualizerConnectPending = null
  }
}

function secondaryTimeAt(absoluteTime) {
  const secondary = secondaryElement()
  const secondaryDuration = Number(secondary?.duration)
  if (Number.isFinite(secondaryDuration) && secondaryDuration > 0) return absoluteTime % secondaryDuration
  return absoluteTime
}

async function togglePlay() {
  const master = masterElement()
  if (!master) return setNotice('Сначала добавьте аудио или видео', 'warning')
  if (!master.paused) {
    pauseAll()
    return
  }

  // Keep the audible master on the browser's native media path. Capturing the
  // element in a suspended Web Audio graph can leave Firefox playing silence.
  const level = Math.min(1, Math.max(0, Number(volume.value) || 0))
  master.volume = level
  if (master === audioEl.value) {
    master.defaultMuted = false
    master.muted = false
  }

  const secondary = secondaryElement()
  if (secondary) {
    secondary.muted = true
    const target = secondaryTimeAt(master.currentTime)
    if (Math.abs(secondary.currentTime - target) > 0.08) secondary.currentTime = target
  }
  try {
    await startMusicPreview(master.currentTime)
  } catch (error) {
    setNotice(`Музыка не запустилась, озвучка продолжит играть: ${error.message}`, 'warning', 6000)
  }
  try {
    await master.play()
    void connectLiveVisualizer()
    if (secondary) secondary.play().catch(() => {})
  } catch (error) {
    musicEl.value?.pause()
    setNotice(`Не удалось воспроизвести файл: ${error.message}`, 'error', 6500)
  }
}

function pauseAll() {
  audioEl.value?.pause()
  videoEl.value?.pause()
  musicEl.value?.pause()
  playing.value = false
  cancelAnimationFrame(playbackFrame)
}

function stopPlayback() {
  pauseAll()
  seekTo(0)
}

function seekBy(offset) {
  seekTo(currentTime.value + offset)
}

function seekTo(value) {
  const next = Math.max(0, Math.min(Number(value) || 0, duration.value || Number(value) || 0))
  currentTime.value = next
  for (const element of [audioEl.value, videoEl.value, musicEl.value]) {
    if (element && Number.isFinite(element.duration) && Math.abs(element.currentTime - next) > 0.02) {
      const target = element === musicEl.value
        ? musicTimeAt(next)
        : element === secondaryElement()
          ? secondaryTimeAt(next)
          : Math.min(next, element.duration)
      try { element.currentTime = target } catch { /* metadata not ready */ }
    }
  }
}

function onMediaMetadata(kind) {
  const element = kind === 'audio' ? audioEl.value : videoEl.value
  const mediaDuration = Number(element?.duration)
  if (Number.isFinite(mediaDuration) && mediaDuration > 0) {
    if (kind === 'audio') audioDuration.value = mediaDuration
    else videoDuration.value = mediaDuration
    ensureSceneBounds()
  }
  applyVolume()
}

function onMediaTime(kind) {
  if (kind !== masterKind.value) return
  const master = masterElement()
  if (!master) return
  currentTime.value = master.currentTime || 0
  const secondary = secondaryElement()
  const secondaryTarget = secondaryTimeAt(master.currentTime)
  if (secondary && Math.abs(secondary.currentTime - secondaryTarget) > 0.22) secondary.currentTime = secondaryTarget
  const music = musicEl.value
  const musicTarget = musicTimeAt(master.currentTime)
  if (music && project.music.enabled && Math.abs(music.currentTime - musicTarget) > 0.28) music.currentTime = musicTarget
}

function onMediaPlay(kind) {
  if (kind !== masterKind.value) return
  playing.value = true
  void connectLiveVisualizer()
  tickPlayback()
}

function onMediaPause(kind) {
  if (kind !== masterKind.value) return
  playing.value = false
  cancelAnimationFrame(playbackFrame)
  visualAudioContext?.suspend().catch(() => {})
  secondaryElement()?.pause()
  musicEl.value?.pause()
}

function onMediaEnded(kind) {
  if (kind !== masterKind.value) return
  pauseAll()
  disconnectLiveVisualizer()
}

function onMediaError(kind) {
  const source = kind === 'audio' ? audioSource.value : videoSource.value
  if (source) setNotice(`${kind === 'audio' ? 'Аудио' : 'Видео'} не поддерживается браузером или файл недоступен.`, 'error', 7000)
}

function tickPlayback() {
  if (!playing.value) return
  const master = masterElement()
  if (master) currentTime.value = master.currentTime || currentTime.value
  playbackFrame = requestAnimationFrame(tickPlayback)
}

function applyVolume() {
  const master = masterElement()
  const level = Math.min(1, Math.max(0, Number(volume.value) || 0))
  if (master) {
    master.volume = level
    if (master === audioEl.value) {
      master.defaultMuted = false
      master.muted = false
    }
  }
  if (videoEl.value && masterKind.value === 'audio') videoEl.value.muted = true
}

function clipStyle(start, end, minWidth = 0.4) {
  const total = Math.max(duration.value, 1)
  const left = Math.max(0, Math.min(100, Number(start) / total * 100))
  const width = Math.max(minWidth, Math.min(100 - left, (Math.max(Number(end), Number(start)) - Number(start)) / total * 100))
  return { left: `${left}%`, width: `${width}%` }
}

function seekFromTimeline(event) {
  const rect = event.currentTarget.getBoundingClientRect()
  seekTo((event.clientX - rect.left) / rect.width * duration.value)
}

function visualizerValues(now) {
  const count = visualizerLevels.length
  const live = playing.value
    && visualAnalyser
    && visualizerFrequencyData
    && visualizerMaster === masterElement()
    && visualizerStream?.getAudioTracks?.().some((track) => track.readyState === 'live')
    && visualAudioContext?.state === 'running'

  if (playing.value && !live && !visualizerConnectPending && now - visualizerLastConnectAttempt > 1200) {
    void connectLiveVisualizer()
  }

  let targets = null
  if (live) {
    visualAnalyser.getByteFrequencyData(visualizerFrequencyData)
    const binHz = visualAudioContext.sampleRate / visualAnalyser.fftSize
    const minFrequency = 70
    const maxFrequency = Math.min(12000, visualAudioContext.sampleRate / 2)
    const spread = maxFrequency / minFrequency
    targets = Array.from({ length: count }, (_, index) => {
      const low = minFrequency * spread ** (index / count)
      const high = minFrequency * spread ** ((index + 1) / count)
      const first = Math.max(1, Math.floor(low / binHz))
      const last = Math.max(first + 1, Math.min(visualizerFrequencyData.length, Math.ceil(high / binHz)))
      let peak = 0
      let sum = 0
      for (let bin = first; bin < last; bin += 1) {
        const value = visualizerFrequencyData[bin]
        peak = Math.max(peak, value)
        sum += value
      }
      const raw = (peak * 0.72 + sum / Math.max(1, last - first) * 0.28) / 255
      const normalized = Math.max(0, (raw - 0.035) / 0.965)
      return Math.min(1, normalized ** 0.58 * 1.18)
    })
  } else {
    const source = waveformSamples.value
    const cursor = source.length && duration.value
      ? Math.floor(currentTime.value / duration.value * Math.max(0, source.length - 1))
      : 0
    targets = Array.from({ length: count }, (_, index) => {
      const sample = source.length
        ? Math.abs(Number(source[Math.max(0, Math.min(source.length - 1, cursor + (index % 11) - 5))]) || 0)
        : 0.26
      const shimmer = 0.22 + Math.abs(
        Math.sin(now * 0.0052 + index * 0.71)
        * Math.cos(now * 0.0017 - index * 0.19),
      ) * 0.86
      const energy = Math.min(1, sample ** 0.52 * 1.3)
      return playing.value ? Math.min(1, energy * shimmer) : Math.max(0.035, energy * 0.3)
    })
  }

  for (let index = 0; index < count; index += 1) {
    const current = visualizerLevels[index]
    const target = targets[index]
    const response = target > current ? 0.62 : 0.13
    visualizerLevels[index] = current + (target - current) * response
    visualizerPeaks[index] = Math.max(visualizerLevels[index], visualizerPeaks[index] * (playing.value ? 0.965 : 0.92))
  }
  return visualizerLevels
}

function addRoundedBar(context, x, y, width, height, radius) {
  if (typeof context.roundRect === 'function') context.roundRect(x, y, width, height, radius)
  else context.rect(x, y, width, height)
}

function drawVisualizer() {
  const canvas = visualizerCanvas.value
  if (canvas) {
    const rect = canvas.getBoundingClientRect()
    const ratio = Math.min(2, globalThis.devicePixelRatio || 1)
    const width = Math.max(1, Math.floor(rect.width * ratio))
    const height = Math.max(1, Math.floor(rect.height * ratio))
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width
      canvas.height = height
    }
    const context = canvas.getContext('2d')
    const now = performance.now()
    const values = visualizerValues(now)
    context.clearRect(0, 0, width, height)

    context.strokeStyle = 'rgba(255,255,255,.055)'
    context.lineWidth = Math.max(1, ratio * 0.55)
    for (let row = 1; row < 5; row += 1) {
      context.beginPath()
      context.moveTo(0, height * row / 5)
      context.lineTo(width, height * row / 5)
      context.stroke()
    }

    const travel = Math.sin(now * 0.00035) * width * 0.28
    const gradient = context.createLinearGradient(-width * 0.35 + travel, 0, width * 1.35 + travel, 0)
    gradient.addColorStop(0, '#ffad27')
    gradient.addColorStop(0.28, '#d74fe8')
    gradient.addColorStop(0.55, '#55ddcf')
    gradient.addColorStop(0.78, '#b750da')
    gradient.addColorStop(1, '#ffad27')

    const baseline = height * 0.78
    const slot = width / values.length
    const barWidth = Math.max(1.2 * ratio, slot * 0.58)
    const maximumBarHeight = height * 0.68

    context.save()
    context.fillStyle = gradient
    context.shadowColor = 'rgba(201, 73, 226, .62)'
    context.shadowBlur = 11 * ratio
    context.beginPath()
    values.forEach((value, index) => {
      const barHeight = Math.max(1.5 * ratio, value ** 0.86 * maximumBarHeight)
      const x = index * slot + (slot - barWidth) / 2
      addRoundedBar(context, x, baseline - barHeight, barWidth, barHeight, barWidth / 2)
    })
    context.fill()
    context.restore()

    context.save()
    context.globalAlpha = 0.16
    context.fillStyle = gradient
    context.beginPath()
    values.forEach((value, index) => {
      const reflection = Math.max(1, value ** 0.86 * height * 0.12)
      const x = index * slot + (slot - barWidth) / 2
      addRoundedBar(context, x, baseline + 3 * ratio, barWidth, reflection, barWidth / 2)
    })
    context.fill()
    context.restore()

    context.save()
    context.strokeStyle = gradient
    context.globalAlpha = 0.82
    context.lineWidth = Math.max(1, ratio * 0.85)
    visualizerPeaks.forEach((peak, index) => {
      const x = index * slot + slot * 0.23
      const y = baseline - peak ** 0.86 * maximumBarHeight - 2.5 * ratio
      context.beginPath()
      context.moveTo(x, y)
      context.lineTo(x + barWidth, y)
      context.stroke()
    })
    context.restore()

    context.save()
    context.globalAlpha = 0.34
    context.strokeStyle = gradient
    context.lineWidth = Math.max(1, ratio * 0.6)
    context.beginPath()
    context.moveTo(0, baseline + ratio)
    context.lineTo(width, baseline + ratio)
    context.stroke()
    context.restore()
  }
  visualFrame = requestAnimationFrame(drawVisualizer)
}

async function openExport() {
  exportReadiness.value = null
  showExport.value = true
  if (backend.online) {
    try {
      const running = await apiRequest('/render/status')
      if (running.active && running.latest) {
        renderJob.value = running.latest
        clearInterval(renderPoll)
        renderPoll = setInterval(() => pollRender(running.latest.id), 1200)
        return
      }
      if (dirty.value) {
        setNotice('Сохраняю актуальную разметку перед проверкой экспорта…', 'info', 0)
        const saved = await saveProject({ silent: true })
        if (!saved) return
      }
      exportReadiness.value = await apiRequest('/export/readiness')
      if (exportReadiness.value.missing?.includes('chapters-duration-mismatch') && !exportReadiness.value.editorProject?.exists) {
        setNotice('Обновляю главы из исходного RPP…', 'info', 0)
        const refreshed = await apiRequest('/book-project/refresh-chapters', { method: 'POST' })
        if (refreshed.ok && refreshed.chapters?.length) {
          project.chapters = refreshed.chapters.map(normalizeChapter)
          ensureSceneBounds()
          dirty.value = true
          exportReadiness.value = await apiRequest('/export/readiness')
          setNotice(`Разметка обновлена: ${project.chapters.length} глав`, 'success')
        }
      }
    } catch { /* client checks remain visible */ }
  }
}

function openBookExport() {
  if (!activeProjectRecord.value?.book) return
  showBookExport.value = true
}

function responseDownloadName(response, fallback) {
  const disposition = response.headers.get('content-disposition') || ''
  const encoded = disposition.match(/filename\*=utf-8''([^;]+)/i)?.[1]
  if (encoded) {
    try { return decodeURIComponent(encoded) } catch { /* use plain fallback */ }
  }
  return disposition.match(/filename="?([^";]+)"?/i)?.[1] || fallback
}

async function downloadBookExport(mode) {
  if (!activeProjectUuid.value || bookExportBusy.value) return
  if (!(await saveCurrentChapter({ silent: true }))) {
    setNotice('Сначала нужно сохранить текущую главу', 'error')
    return
  }
  bookExportBusy.value = true
  try {
    const params = new URLSearchParams({
      mode,
      include_media: String(bookExportIncludeMedia.value),
    })
    if (mode === 'chapter' && currentBookChapterId.value) {
      params.set('chapter_id', String(currentBookChapterId.value))
    }
    const response = await fetch(
      `${API}/projects/${encodeURIComponent(activeProjectUuid.value)}/book-export?${params}`,
    )
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}))
      throw new Error(
        typeof payload.detail === 'string'
          ? payload.detail
          : 'Сервер не смог собрать файл книги',
      )
    }
    const extension = mode === 'chapters' ? 'zip' : 'txt'
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = responseDownloadName(response, `Книга.${extension}`)
    document.body.appendChild(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1500)
    setNotice(
      mode === 'chapters'
        ? 'Поглавный архив книги готов'
        : 'Текст книги экспортирован',
      'success',
      5500,
    )
  } catch (error) {
    setNotice(`Не удалось экспортировать книгу: ${error.message}`, 'error', 7500)
  } finally {
    bookExportBusy.value = false
  }
}

async function resetExport() {
  renderJob.value = null
  await openExport()
}

function closeExport() {
  if (renderJob.value?.status === 'running') return
  showExport.value = false
}

async function startExport() {
  if (exportIssue.value) return
  startingExport.value = true
  try {
    const saved = await saveProject({ silent: true })
    if (!saved) return
    exportReadiness.value = await apiRequest('/export/readiness')
    if (!exportReadiness.value.ready || exportIssue.value) return
    const response = await apiRequest(exportTest.value ? '/render/test' : '/render/full', { method: 'POST' })
    renderJob.value = { id: response.job_id, status: 'running', progress: 0, log: [], download_url: response.download_url || '' }
    pollRender(response.job_id)
    renderPoll = setInterval(() => pollRender(response.job_id), 1200)
  } catch (error) {
    setNotice(`Экспорт не запущен: ${error.message}`, 'error', 7500)
  } finally {
    startingExport.value = false
  }
}

async function pollRender(jobId) {
  try {
    const job = await apiRequest(`/jobs/${encodeURIComponent(jobId)}`)
    renderJob.value = job
    if (job.status === 'done' || job.status === 'failed') {
      clearInterval(renderPoll)
      renderPoll = null
      if (job.status === 'done') setNotice('Экспорт завершён', 'success', 7000)
    }
  } catch { /* keep polling transient backend errors */ }
}

function releaseObjectUrls() {
  for (const url of objectUrls) URL.revokeObjectURL(url)
  objectUrls.clear()
}

function handleKeydown(event) {
  const target = event.target
  const editing = target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
    event.preventDefault()
    if (activeWorkspace.value === 'book') saveCurrentChapter()
    else saveProject()
  } else if (activeWorkspace.value === 'video' && event.code === 'Space' && !editing && !showExport.value) {
    event.preventDefault()
    togglePlay()
  }
}

watch(() => audioSource.value, () => {
  pauseAll()
  disconnectLiveVisualizer()
  visualizerLevels.fill(0)
  visualizerPeaks.fill(0)
  audioDuration.value = 0
  nextTick(() => audioEl.value?.load())
})

watch(() => videoSource.value, () => {
  pauseAll()
  disconnectLiveVisualizer()
  visualizerLevels.fill(0)
  visualizerPeaks.fill(0)
  videoDuration.value = 0
  nextTick(() => videoEl.value?.load())
})

watch(() => musicSource.value, () => {
  musicEl.value?.pause()
  nextTick(() => {
    musicEl.value?.load()
    applyMusicMix()
  })
})

watch(() => bookPlayerUrl.value, () => {
  const autoplay = bookPlayerShouldAutoplay
  bookPlayerShouldAutoplay = false
  void reloadBookPlayer(autoplay)
}, { flush: 'sync' })

watch([
  () => previousChapter.value?.id,
  () => previousChapter.value?.title,
  () => currentChapter.value?.id,
  () => currentChapter.value?.title,
  () => nextChapter.value?.id,
  () => nextChapter.value?.title,
  () => project.layers.title?.w,
  () => project.layers.title?.h,
  () => project.layers.title?.fontSize,
  () => project.layers.title?.visible,
], () => nextTick(scheduleTitleFit), { flush: 'post' })

watch(titleLayerEl, (element, previous) => {
  if (previous) titleResizeObserver?.unobserve(previous)
  if (element) {
    titleResizeObserver?.observe(element)
    nextTick(scheduleTitleFit)
  }
}, { flush: 'post' })

watch(project, () => {
  if (!hydrating.value) dirty.value = true
}, { deep: true })

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
  window.addEventListener('beforeunload', handleBeforeUnload)
  if (typeof ResizeObserver !== 'undefined') {
    titleResizeObserver = new ResizeObserver(scheduleTitleFit)
    if (titleLayerEl.value) titleResizeObserver.observe(titleLayerEl.value)
  }
  document.fonts?.ready?.then(scheduleTitleFit).catch(() => {})
  scheduleTitleFit()
  drawVisualizer()
  loadInitialProject()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeydown)
  window.removeEventListener('beforeunload', handleBeforeUnload)
  stopBookPlayer()
  pauseAll()
  cancelAnimationFrame(visualFrame)
  clearInterval(renderPoll)
  clearTimeout(noticeTimer)
  clearTimeout(bookAutosaveTimer)
  clearInterval(ttsPollTimer)
  titleResizeObserver?.disconnect()
  if (titleFitFrame !== null) cancelAnimationFrame(titleFitFrame)
  disconnectLiveVisualizer()
  visualAudioContext?.close().catch(() => {})
  musicAudioContext?.close().catch(() => {})
  releaseObjectUrls()
})

function handleBeforeUnload(event) {
  if (!dirty.value && !['modified', 'saving', 'error'].includes(bookSaveState.value)) return
  event.preventDefault()
  event.returnValue = ''
}
</script>
