# BookForge Engine v1 — Implementation Plan

## Phase 0 (Done)
[x] Smoke test passes (suviren_q.py + suviren_q_server.py compile)
[x] Project stable

## Phase 1 — bookforge.py CLI engine

### 1. Создать bookforge.py с командами:
- doctor — проверка окружения
- scan — сканирование data, автоопределение файлов
- chapters — извлечение глав из RPP
- preset — создание layout.json
- waveform — генерация waveform.json
- preview — рендер PNG preview
- status — статус проекта
- clean-temp — очистка временных файлов
- render-test — тестовый рендер 60с
- render-full — полный рендер

### 2. Переиспользовать из suviren_q.py:
- Chapter dataclass
- parse_rpp / extract_chapters_from_rpp
- normalize_chapters / save_chapters
- seconds_to_timecode / parse_time_value
- build_dir / ensure_dir

### 3. Создать модули/функции:
- data_scanner.py (auto-discovery файлов)
- project_config.py (bookforge.project.json)
- layout_builder.py (zina-noir preset)
- waveform_gen.py (ffmpeg-based waveform)
- preview_renderer.py (layout-driven PNG render)
- video_renderer.py (ffmpeg chapter-by-chapter render)
- font_utils.py (шрифты)
- style_presets.py (цветовые схемы)

### 4. Визуальный дизайн zina-noir:
- Фон на весь экран с затемнением
- Обложка слева с тенью
- Название книги и глава справа
- Waveform под текстом
- Progress bar внизу
- Brand внизу
- Нуарные цвета: бирюзовый акцент, фиолетовый, тёмный фон

### Файлы:
- bookforge.py — главный entrypoint
- _suviren_q_build/ — билд директория
- bookforge.project.json — конфиг
- _suviren_q_build/layout.json — визуальный layout
- _suviren_q_build/chapters.detected.json — главы
- _suviren_q_build/youtube_chapters.txt — YouTube
- _suviren_q_build/waveform.json — waveform данные
- _suviren_q_build/preview.png — preview
- _suviren_q_build/preview_contact.png — contact sheet
- _suviren_q_build/test_60sec.mp4 — тестовый render
- _suviren_q_build/zina_book_youtube_full.mp4 — полный render