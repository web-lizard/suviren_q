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
