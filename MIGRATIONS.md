# SQLite migrations

Файлы миграций находятся в `bookender/migrations`:

1. `001_initial.sql` — проекты, книги, главы, assets, video editions,
   timeline, settings, imports и app state.
2. `002_jobs_and_backups.sql` — фоновые TTS jobs и история backups.

Запуск:

```powershell
python -m bookender.cli migrate
```

`BookenderDatabase` применяет версии по порядку внутри транзакций и записывает
их в `schema_migrations`. Повторный запуск идемпотентен. База не удаляется и
не пересоздаётся. При ошибке текущая DDL-миграция откатывается; это покрыто
автоматическим тестом.

Проверка:

```powershell
python -m bookender.cli verify
python -m unittest discover -s tests -v
```
