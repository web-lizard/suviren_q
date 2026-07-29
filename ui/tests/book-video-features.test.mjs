import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')

test('book audio can be played, dragged, and assembled for video', () => {
  assert.match(source, /<audio[^>]+controls/)
  assert.match(source, /application\/x-bookender-audio-id/)
  assert.match(source, /dropBookAudioOnVideoTab/)
  assert.match(source, /\/video-audio\/master/)
})

test('chapter images and optional reading captions reach the video workspace', () => {
  assert.match(source, /\/chapters\/\$\{chapterId\}\/image/)
  assert.match(source, /imageAssetId/)
  assert.match(source, /project\.captions\.enabled/)
  assert.match(source, /currentReadingCaption/)
})

test('reading captions are a movable layer with adjustable typography', () => {
  assert.match(source, /onLayerPointerDown\('caption'/)
  assert.match(source, /caption:\s*\{[^}]+fontWeight:\s*400/)
  assert.match(source, /selectedLayer\.fontWeight/)
  assert.match(source, /--caption-weight/)
  assert.match(source, /source\.layers\?\.caption/)
})

test('video projects support a separate music bed with volume and three-band EQ', () => {
  assert.match(source, /musicAssetId/)
  assert.match(source, /MUSIC_EQ_BANDS/)
  assert.match(source, /project\.music\.volume/)
  assert.match(source, /project\.music\[band\.key\]/)
  assert.match(source, /class="timeline-lane music-lane"/)
  assert.match(source, /ensureMusicGraph/)
  assert.match(source, /createBiquadFilter/)
})

test('music volume is directly reachable from the timeline and has quick presets', () => {
  assert.match(source, /class="music-mixer-shortcut"/)
  assert.match(source, /class="timeline-track-button"/)
  assert.match(source, /selection\.type === 'music'/)
  assert.match(source, /setMusicVolume\(0\.08\)/)
  assert.match(source, /setMusicVolume\(0\.16\)/)
  assert.match(source, /setMusicVolume\(0\.3\)/)
  assert.match(source, /Громкость музыки/)
})

test('music preview applies native volume and reports whether live EQ is active', () => {
  assert.match(source, /element\.volume = level/)
  assert.match(source, /setAudioValue\(musicGain\?\.gain, 1\)/)
  assert.match(source, /parameter\.cancelScheduledValues\(now\)/)
  assert.match(source, /async function onMusicControlInput/)
  assert.match(source, /async function toggleMusicPreview/)
  assert.match(source, /musicEqState\.active/)
  assert.match(source, /EQ активен/)
})

test('opening video rebuilds narrated chapters and exposes chapter audio clips', () => {
  assert.match(source, /workspace === 'video' && activeProjectRecord\.value\?\.book/)
  assert.match(source, /await openBookInVideo\(\)/)
  assert.match(source, /await rebuildBookVideo\(activeProjectRecord\.value/)
  assert.match(source, /audioAssetId: audioMaterials\.get\(chapter\.id\)/)
  assert.match(source, /v-for="chapter in videoAudioChapters"/)
  assert.match(source, /filter\(\(chapter\) => timings\.has\(chapter\.id\)\)/)
  assert.match(source, /ensureDefaultVideoCover/)
  assert.match(source, />Текст на экране</)
})

test('book export is visible and supports whole, current, and chapter bundle modes', () => {
  assert.match(source, />Экспорт книги</)
  assert.match(source, /downloadBookExport\('complete'\)/)
  assert.match(source, /downloadBookExport\('chapter'\)/)
  assert.match(source, /downloadBookExport\('chapters'\)/)
  assert.match(source, /bookExportIncludeMedia/)
})

test('book toolbar is compact and narration exposes real progress', () => {
  assert.match(source, /class="book-icon-action"/)
  assert.match(source, /aria-label="Новая книга"/)
  assert.match(source, /aria-label="Резервная копия"/)
  assert.match(source, /ttsProgressState\.percent/)
  assert.match(source, /progress_total/)
  assert.match(source, /Прошло/)
})

test('timeline playhead supports pointer scrubbing and keyboard seeking', () => {
  assert.match(source, /ref="timelineContent"/)
  assert.match(source, /@pointerdown\.stop="startTimelineScrub"/)
  assert.match(source, /window\.addEventListener\('pointermove', timelinePointerMove\)/)
  assert.match(source, /window\.addEventListener\('pointerup', timelinePointerUp\)/)
  assert.match(source, /function onTimelinePlayheadKeydown/)
  assert.match(source, /event\.key === 'ArrowLeft'/)
  assert.match(source, /event\.key === 'ArrowRight'/)
})

test('text navigator maps words to the timeline and plays selected excerpts', () => {
  assert.match(source, /Текст книги/)
  assert.match(source, /id="text-navigator-title"/)
  assert.match(source, /function chapterTimelineWords/)
  assert.match(source, /event\.shiftKey/)
  assert.match(source, /seekTo\(word\.start\)/)
  assert.match(source, /scrollTimelineToTime\(word\.start\)/)
  assert.match(source, /async function playSelectedExcerpt/)
  assert.match(source, /function stopAtExcerptEnd/)
  assert.match(source, /class="timeline-excerpt-range"/)
  assert.match(source, /Привязка слов расчётная/)
})
