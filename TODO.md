# BookForge Studio — Todo List

## Phase 0 — Stabilize ✓
- [x] Починить IndentationError в suviren_q.py (была на ~line 914)
- [x] Smoke test green
- [x] Убрать App.vue.bak из проекта

## Phase 1 — Data project API
- [x] Endpoint /api/book-project уже реализован в suviren_q_server.py
- [x] Data auto-discovery из data/
- [ ] Запустить сервер и проверить работу
- [ ] Убедиться что UI видит данные при boot

## Phase 2 — Clean Render Console
- [x] BookForge Studio интерфейс уже в App.vue
- [ ] Проверить что UI корректно показывает статусы
- [ ] Проверить Test Render / Full Render кнопки

## Phase 3 — Mouse layout composer
- [x] Drag/resize объектов на сцене (уже реализовано)
- [x] Save/load layout
- [x] Reset default composition

## Phase 4 — Waveform
- [x] Генерация waveform из mp3 (backend endpoint /api/waveform)
- [x] Отображение waveform на сцене
- [ ] Проверить синхронизацию с playback

## Phase 5 — Render by layout
- [x] Render использует layout.json
- [x] Test render 60 sec
- [x] Full render

## Проверка
- [ ] Запустить приложение (backend + frontend)
- [ ] Проверить что всё работает в браузере