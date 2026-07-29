# Bookender Studio runbook

## Запуск

```powershell
python -m pip install -r requirements.txt
cd ui
npm.cmd install
npm.cmd run build
cd ..
python book_wunderwaffe_desktop.py
```

Или используйте существующий `run.bat`.

## Инициализация и импорт

```powershell
python -m bookender.cli init
```

Команда применяет миграции, инвентаризирует все legacy JSON, импортирует
каждую логическую книгу и регистрирует старый видеопроект. Она идемпотентна.
Проверка без импорта: `python -m bookender.cli inventory`.

## Рабочие данные

- база: `user_data/bookender.db`;
- проекты: `user_data/projects/<uuid>`;
- structured logs: `user_data/logs/bookender.log`;
- локальные backups: `user_data/backups`;
- pre-work/legacy backups: `backups/`.

В интерфейсе выбранный проект виден сверху. «Книга» редактирует текст и TTS,
«Видео» — media, сцену, timeline и render. Если части нет, вкладка предлагает
создать её. Перед project switch текущая работа сохраняется.

## Резервное копирование и восстановление

Кнопка «Резервная копия» создаёт каталог с project export, media и
SHA-256-манифестом. Для восстановления не заменяйте базу вручную: сначала
сделайте копию текущего `user_data`, затем импортируйте `project.json` через
maintenance workflow. До появления отдельной команды restore резервный
каталог остаётся полностью переносимым и читаемым.

## Git

`user_data`, `data`, `backups`, `editor_legacy`, media, local databases,
logs, render outputs, `.env` и tokens игнорируются. Коммитятся только код,
SQL, тесты, templates и обезличенная документация. Push не выполняется
автоматически.
