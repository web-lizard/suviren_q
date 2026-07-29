# Book editor integration

Вкладка «Книга» встроена в тот же Vue/FastAPI desktop runtime, что и
видеоредактор. Отдельный PHP-сервер не требуется.

Функции:

- глобальный project picker и создание книги;
- список, создание, переименование, архивирование и reorder глав;
- полноэкранный текстовый редактор, поиск, слова/символы;
- debounce autosave со статусами changed/saving/saved/error;
- защита сохранения при смене главы, проекта и закрытии;
- metadata и TTS settings;
- фоновая озвучка главы через Edge TTS;
- source text hash и индикатор устаревшей озвучки;
- audio assets доступны при создании video edition.

API находится под `/api/projects`. Frontend не пишет SQLite и не дублирует
правила порядка/хэшей: это делает `ProjectRepository`.

«Озвучить главу» создаёт `tts_jobs` и сразу возвращает управление. Фоновый
worker сохраняет MP3 в project folder и создаёт `audio_assets`. Полный текст
главы не попадает в structured log.
