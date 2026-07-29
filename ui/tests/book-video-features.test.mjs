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
