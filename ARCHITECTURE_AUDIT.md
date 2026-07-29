# Architecture audit

## Фактический стек

- Desktop: Python 3.11, PySide6, Qt WebEngine.
- Backend: FastAPI/uvicorn на loopback-интерфейсе.
- Frontend: Vue 3 Composition API, Vite 7, один production bundle.
- Media/render: FFmpeg/FFprobe, Pillow, собственные Python CLI
  `suviren_q.py` и `bookforge.py`.
- Дополнительно: REAPER RPP parser, waveform decoder, Edge TTS.

Точка запуска desktop — `book_wunderwaffe_desktop.py`; `run.bat` запускает
оболочку. Backend entry point — `suviren_q_server.py`. Frontend entry point —
`ui/src/main.js`, главный экран — `ui/src/App.vue`.

## Состояние до миграции

Видеоинтерфейс был полноценным, но однопроектным. Каноническое состояние
лежало в `_suviren_q_build/editor-project.json`; главы, layout, waveform и
рендер-артефакты — рядом. Исходные media/RPP лежали в `data/`, а
`bookforge.project.json` содержал локальные и абсолютные пути.

FastAPI уже предоставлял импорт media, waveform, главы, layout, тестовый и
полный render. Vue уже имел материалы, сцену 16:9, слои, timeline, главы,
waveform, preview и экспорт. Сохранение выполнялось атомарной записью JSON.

## Обнаруженный технический долг

- один глобальный timeline и один `editor-project.json`;
- frontend одновременно хранил бизнес-состояние и UI-состояние;
- отсутствие project_id, базы, миграций и модели книги;
- абсолютные пути и mojibake в части старого project config;
- build/output и приватная обложка были в Git;
- waveform/render endpoints используют активный compatibility-файл;
- нет фоновой предметной очереди TTS и контроля актуальности текста.

## Реализованная архитектура

`bookender/` — отдельный доменный слой. SQLite
`user_data/bookender.db` является источником истины. Проекты, книги, главы,
TTS, audio/visual assets, video editions и timeline нормализованы. Гибкий JSON
сохранён только в `settings_json` видеоверсии и второстепенных настройках.

FastAPI предоставляет project-aware API. Vue показывает глобальный проект и
две раздельные рабочие вкладки. Старый renderer не переписан: активная
видеоверсия экспортируется в recovery/compatibility JSON, после чего
проверенный FFmpeg pipeline работает как раньше.

## Основные изменяемые зоны

- `.gitignore`, `requirements.txt`;
- `bookender/**`, `tests/**`;
- `suviren_q_server.py`, `book_wunderwaffe_desktop.py`;
- `ui/src/App.vue`, `ui/src/style.css`, metadata npm;
- документы аудита, миграции и runbook.

Риски миграции снижены резервными копиями, транзакциями SQLite,
идемпотентностью импорта, source/destination hashes и отсутствием физических
удалений проектов.
