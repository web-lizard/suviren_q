import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')

function between(start, end) {
  const startIndex = source.indexOf(start)
  const endIndex = source.indexOf(end, startIndex + start.length)
  assert.notEqual(startIndex, -1, `Missing start marker: ${start}`)
  assert.notEqual(endIndex, -1, `Missing end marker: ${end}`)
  return source.slice(startIndex, endIndex)
}

test('voice preview has one playback owner and never reloads after play', () => {
  const preview = between('async function previewBookVoice()', 'function selectBookAudio')
  const reloader = between('async function reloadBookPlayer', 'function seekBookPlayer')
  const sourceWatcher = between(
    'watch(() => bookPlayerUrl.value',
    'watch([\n  () => previousChapter.value?.id',
  )

  assert.doesNotMatch(preview, /\.load\(/)
  assert.doesNotMatch(reloader, /\.load\(/)
  assert.doesNotMatch(sourceWatcher, /\.load\(/)
  assert.match(reloader, /await waitForBookPlayerReady\(player\)/)
  assert.match(reloader, /await player\.play\(\)/)
  assert.match(sourceWatcher, /flush:\s*'sync'/)
})
