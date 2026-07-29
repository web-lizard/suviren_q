# Bookender project architecture

`projects` — корневая сущность. Проект бывает `book`, `video` или `hybrid`.
Книга связана с одним project и упорядоченными chapters. Один project может
иметь несколько `video_editions`; каждый edition имеет свой timeline.

Основные таблицы:

- `projects`, `books`, `chapters`;
- `tts_settings`, `tts_jobs`, `audio_assets`;
- `visual_assets`, `video_editions`, `timeline_items`;
- `project_settings`, `legacy_imports`, `backup_history`, `app_state`;
- `schema_migrations`.

Полные тексты находятся только в `chapters.content`. Бинарники находятся в
`user_data/projects/<uuid>/{audio,images,video,exports}`. База хранит
относительные пути. `settings_json` используется только для гибких настроек
сцены/редактора, не как замена книге или timeline.

Project switch сначала сохраняет текущую главу или видеоверсию, затем вызывает
`open`, очищает frontend-state и загружает ресурсы только нового UUID.
Физическое удаление не используется: проекты и главы архивируются.

Legacy JSON разрешён для read-only импорта, backup/export и renderer
compatibility. Каноническое состояние после импорта — SQLite.
