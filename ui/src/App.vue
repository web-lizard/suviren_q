<template>
  <div class="studio" :class="[`theme-${project.theme}`, { 'is-loading': loading }]">
    <header class="topbar">
      <div class="brand" aria-label="BOOK WUNDERWAFFE Studio">
        <span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i></span>
        <span class="brand-copy">
          <strong>BOOK WUNDERWAFFE STUDIO</strong>
          <small>AUDIOBOOK SUITE · v{{ backend.version || '1.1.0' }}</small>
        </span>
      </div>

      <nav class="project-actions" aria-label="Действия с проектом">
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

      <div class="topbar-status">
        <span class="status-light" :class="backend.online ? 'online' : 'offline'"></span>
        <span class="status-copy">
          <b>{{ backend.online ? 'Движок в сети' : 'Автономный режим' }}</b>
          <small>{{ dirty ? 'Есть изменения' : 'Проект сохранён' }}</small>
        </span>
      </div>

      <input ref="assetInput" class="visually-hidden" type="file" multiple
             accept="audio/*,video/*,image/png,image/jpeg,image/webp,image/gif" @change="onAssetInput" />
      <input ref="projectInput" class="visually-hidden" type="file" accept="application/json,.json" @change="onProjectInput" />
    </header>

    <main class="workspace">
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
            </div>

            <div class="project-readiness">
              <span class="section-title">Готовность</span>
              <div><i :class="{ done: !!audioAsset }"></i><span>Аудио</span><b>{{ audioAsset ? 'готово' : 'нужно' }}</b></div>
              <div><i :class="{ done: !!coverAsset }"></i><span>Обложка</span><b>{{ coverAsset ? 'готово' : 'нужно' }}</b></div>
              <div><i :class="{ done: project.chapters.length > 0 }"></i><span>Главы</span><b>{{ project.chapters.length || 'нужно' }}</b></div>
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
              <button type="button" class="wide" :class="{ active: project.audioAssetId === selectedAsset.id }" @click="assignAsset('audio', selectedAsset.id)">Основная аудиокнига</button>
            </div>
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
            <button type="button" class="jump-button" @click="resetLayer(selection.id)">Вернуть положение</button>
          </template>
        </div>
      </aside>
    </main>

    <section class="timeline-panel">
      <div class="timeline-toolbar">
        <div class="timeline-title">
          <span class="eyebrow">Монтаж</span>
          <strong>Таймлайн</strong>
          <span>{{ formatTime(duration, true) }}</span>
        </div>
        <div class="timeline-actions">
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
            <button v-if="audioAsset" type="button" class="audio-clip" :style="clipStyle(0, duration, 100)" @click.stop="select('asset', audioAsset.id)">
              <span class="timeline-waveform" aria-hidden="true">
                <i v-for="(bar, index) in timelineBars" :key="index" :style="{ height: `${bar * 100}%` }"
                   :class="{ played: index / timelineBars.length <= progressPercent / 100 }"></i>
              </span>
              <b>{{ audioAsset.name }}</b>
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

const DEFAULT_LAYERS = {
  cover: { visible: true, x: 7, y: 17, w: 27, h: 66 },
  title: { visible: true, x: 39, y: 23, w: 54, h: 31, fontSize: 48, color: '#f4f0e8' },
  visualizer: { visible: true, x: 38, y: 59, w: 56, h: 23 },
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
    videoAssetId: null,
    coverAssetId: null,
    backgroundAssetId: null,
    materials: [],
    chapters: [],
    scenes: [{ id: uid('scene'), name: 'Основная сцена', start: 0, end: 60, backgroundAssetId: null }],
    layers: clone(DEFAULT_LAYERS),
  }
}

const project = reactive(freshProject())
const backend = reactive({ online: false, checking: true, version: '' })
const selection = reactive({ type: 'project', id: null })
const notice = reactive({ text: '', kind: 'info' })

const loading = ref(true)
const loadingMessage = ref('Подключаю медиадвижок…')
const dirty = ref(false)
const saving = ref(false)
const hydrating = ref(true)
const assetInput = ref(null)
const projectInput = ref(null)
const audioEl = ref(null)
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
const waveformSamples = ref([])
const timelineZoom = ref(1)

const showExport = ref(false)
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
const visualizerLevels = new Float32Array(72)
const visualizerPeaks = new Float32Array(72)
const objectUrls = new Set()

const assetById = (id) => project.materials.find((item) => item.id === id) || null
const audioAsset = computed(() => assetById(project.audioAssetId))
const videoAsset = computed(() => assetById(project.videoAssetId))
const coverAsset = computed(() => assetById(project.coverAssetId))
const backgroundAsset = computed(() => assetById(project.backgroundAssetId))
const imageAssets = computed(() => project.materials.filter((item) => item.type === 'image'))
const audioSource = computed(() => assetUrl(audioAsset.value))
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

const sceneBackgroundAsset = computed(() => assetById(currentScene.value?.backgroundAssetId) || backgroundAsset.value)
const backgroundSource = computed(() => assetUrl(sceneBackgroundAsset.value))
const backgroundStyle = computed(() => backgroundSource.value
  ? { backgroundImage: `url("${backgroundSource.value.replaceAll('"', '%22')}")` }
  : {})
const backgroundThumbnailStyle = computed(() => backgroundSource.value
  ? { backgroundImage: `url("${backgroundSource.value.replaceAll('"', '%22')}")` }
  : {})

const selectedAsset = computed(() => selection.type === 'asset' ? assetById(selection.id) : null)
const selectedChapter = computed(() => selection.type === 'chapter' ? project.chapters.find((item) => item.id === selection.id) || null : null)
const selectedScene = computed(() => selection.type === 'scene' ? project.scenes.find((item) => item.id === selection.id) || null : null)
const selectedLayer = computed(() => selection.type === 'layer' ? project.layers[selection.id] || null : null)
const inspectorTitle = computed(() => ({
  project: 'Проект', asset: 'Материал', chapter: 'Глава', scene: 'Сцена', layer: layerLabel(selection.id),
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
  if (project.videoAssetId === asset.id) roles.push('Видео сцены')
  if (project.coverAssetId === asset.id) roles.push('Обложка')
  if (project.backgroundAssetId === asset.id) roles.push('Фон')
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

function mediaUrl(path) {
  if (!path) return ''
  const normalized = String(path).replaceAll('\\', '/').replace(/^\/+/, '')
  return `${API}/media/${normalized.split('/').map(encodeURIComponent).join('/')}`
}

function assetUrl(asset) {
  if (!asset) return ''
  return asset.src || mediaUrl(asset.serverPath)
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

async function loadInitialProject() {
  loading.value = true
  hydrating.value = true
  try {
    const health = await apiRequest('/health')
    backend.online = !!health.ok
    backend.version = health.version || ''
  } catch {
    backend.online = false
  } finally {
    backend.checking = false
  }

  let restored = false
  if (backend.online) {
    loadingMessage.value = 'Восстанавливаю проект…'
    try {
      const saved = await apiRequest('/editor-project')
      if (saved.exists && saved.project) {
        replaceProject(saved.project)
        restored = true
      }
    } catch { /* endpoint may be absent on an older backend */ }

    try {
      const discovered = await apiRequest('/book-project')
      hydrateDiscoveredMaterials(discovered)
      if (!project.title || project.title === 'Новая аудиокнига') project.title = discovered.projectName || project.title
    } catch (error) {
      setNotice(`Не удалось прочитать материалы: ${error.message}`, 'warning')
    }

    if (!project.chapters.length) {
      try {
        const chapterData = await apiRequest('/chapters')
        if (chapterData.chapters?.length) project.chapters = chapterData.chapters.map(normalizeChapter)
      } catch { /* chapters are optional at startup */ }
    }

    loadingMessage.value = 'Строю форму звука…'
    // A very large audiobook must not hold the whole editor behind a waveform job.
    // The cached/decoded shape arrives in the background and updates both canvases.
    void refreshWaveform()
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
      await apiRequest('/editor-project', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
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

function onDrop(event) {
  importFiles(event.dataTransfer?.files)
}

function importFiles(fileList) {
  const files = [...(fileList || [])]
  if (!files.length) return
  let accepted = 0
  for (const file of files) {
    const type = materialType(file.name, file.type)
    if (!type) {
      setNotice(`Формат «${file.name}» не поддерживается`, 'error', 6000)
      continue
    }
    const src = URL.createObjectURL(file)
    objectUrls.add(src)
    const asset = {
      id: uid('asset'), type, name: file.name, size: file.size, mime: file.type,
      file, src, serverPath: '', status: backend.online ? 'uploading' : 'local', progress: 0,
    }
    project.materials.push(asset)
    assignImportedAsset(asset)
    accepted += 1
    if (backend.online) uploadAsset(asset)
  }
  if (accepted) {
    dirty.value = true
    setNotice(`Добавлено файлов: ${accepted}`, 'success')
    nextTick(() => {
      audioEl.value?.load()
      videoEl.value?.load()
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
  }
  xhr.send(asset.file)
}

function assignAsset(role, id) {
  project[`${role}AssetId`] = id
  dirty.value = true
  nextTick(() => {
    if (role === 'audio') { audioEl.value?.load(); refreshWaveform() }
    if (role === 'video') videoEl.value?.load()
  })
}

function removeAsset(id) {
  const asset = assetById(id)
  if (!asset) return
  if (project.audioAssetId === id || project.videoAssetId === id) pauseAll()
  for (const key of ['audioAssetId', 'videoAssetId', 'coverAssetId', 'backgroundAssetId']) {
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
  return style
}

function layerLabel(id) {
  return ({ cover: 'Обложка', title: 'Заголовок', visualizer: 'Визуализатор' })[id] || 'Слой'
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
    await master.play()
    void connectLiveVisualizer()
    if (secondary) secondary.play().catch(() => {})
  } catch (error) {
    setNotice(`Не удалось воспроизвести файл: ${error.message}`, 'error', 6500)
  }
}

function pauseAll() {
  audioEl.value?.pause()
  videoEl.value?.pause()
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
  for (const element of [audioEl.value, videoEl.value]) {
    if (element && Number.isFinite(element.duration) && Math.abs(element.currentTime - next) > 0.02) {
      const target = element === secondaryElement() ? secondaryTimeAt(next) : Math.min(next, element.duration)
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
    saveProject()
  } else if (event.code === 'Space' && !editing && !showExport.value) {
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
  pauseAll()
  cancelAnimationFrame(visualFrame)
  clearInterval(renderPoll)
  clearTimeout(noticeTimer)
  titleResizeObserver?.disconnect()
  if (titleFitFrame !== null) cancelAnimationFrame(titleFitFrame)
  disconnectLiveVisualizer()
  visualAudioContext?.close().catch(() => {})
  releaseObjectUrls()
})
</script>
