# Аудит локальной копии legacy-редактора

Оригинал: `editor_legacy/be2-p256w34-lizard-souverain-20260519_205739`.
Каталог исследовался только на чтение и не используется как новая точка
истины.

## Структура

Приложение — PHP/JavaScript редактор с entry point `api.php` и историческими
версиями PHP-файлов. Данные дублируются в `data`, `public/data`, `storage`,
`data/books/<slug>`, `storage/books/<slug>` и многочисленных backup-папках.
Активная книга указывается несколькими `current_book.txt`.

TTS реализован Python-скриптами в `tts/`, локальными `_pydeps`, JSON status,
batch-конфигурациями и каталогами `audio/`. Есть ZIP-экспорты и промежуточные
chunks.

## Найденные логические книги

| Книга | Канонический источник | Глав | Символов | Голос |
|---|---|---:|---:|---|
| Lizardia | `data/books/lizardia/book.json` | 35 | 1 009 589 | `ru-RU-DmitryNeural` |
| Интимный протокол | `data/books/intimny-protokol/book.json` | 37 | 831 171 | `ru-RU-SvetlanaNeural` |
| Протокол 256 W34 | `data/_backup_imports/lizardia.before_import_20260519_213623.json` | 3 | 90 844 | legacy default |

Третья книга не присутствует в основном index и найдена только в старом
backup-формате. Поэтому импорт только `current_book.txt` потерял бы данные.
Текущая активная книга — `intimny-protokol`; старые release-backups также
содержат состояние, где активна `lizardia`.

## Настройки и audio

В book JSON сохранены `active`, `saved_at`, `tts_voice`, а у части источников
editorial metadata. В `audio/books`, `_book_tts_build`, `_book_exports`,
`tts/status` и rerender backups найдены готовые файлы, chunks и статусы.
Актуальные audio-файлы `audio/books/lizardia` перенесены с сохранением
вложенной структуры; неполные/нулевые файлы и старые chunks оставлены в
резервной копии и отмечаются как legacy-материалы.

## Повреждения и server-only зависимости

Инвентаризация фиксирует повреждённые JSON, но не прекращает импорт остальных
книг. В concat-файлах и скриптах найдены абсолютные
`/home/.../public_html/...` пути, зависимости от Linux/PHP permissions и
серверной структуры. Старые URL и PHP endpoints не нужны новой desktop-версии.

Повторно используются UX главы/текста, TTS voice metadata и форматы книг.
PHP, абсолютные пути, независимое JSON-хранилище и server deployment не
переносятся в постоянную архитектуру.
