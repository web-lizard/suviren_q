# Existing video project audit

## Исходное состояние

Основной документ: `_suviren_q_build/editor-project.json`.
Связанные данные находятся в `_suviren_q_build`, `data`,
`bookforge.project.json`, локальном RPP и `_suviren_q_local`.

Зафиксированы:

- 8 media-материалов;
- 37 маркеров глав;
- 1 сцена;
- выбранные audio/cover/background IDs;
- theme, glitch, render preset и geometry слоёв;
- waveform, layout, panels, preview, RPP report и render outputs.

Крупное исходное audio (несколько файлов, общий объём около 5,8 ГБ) не
дублировалось в pre-work snapshot: оно зафиксировано SHA-256-манифестом.
Project state скопирован полностью.

Резервная копия:
`backups/legacy-video-project-20260729-153312`.

## Миграция

Проект зарегистрирован как самостоятельный video project:

- название: «Зина. Книга»;
- UUID: `7499709e-b905-53f7-9470-143018f689c8`;
- video edition ID: `1`;
- source SHA-256:
  `69cd5e69a9e2505644f74018b07e2a4ec34fa242cdc51a9aaff4c1199be01b6f`.

SQLite хранит edition settings и нормализованные timeline items. Media
зарегистрированы как внешние legacy paths, чтобы не копировать
многогигабайтные мастера. При открытии состояние загружается из SQLite; перед
рендером активная версия атомарно экспортируется в старый compatibility JSON.

Проверено: 8 материалов, 37 глав и 1 сцена открываются из SQLite. Исходный
compatibility-файл после тестов имеет тот же SHA-256, что и pre-work backup.
