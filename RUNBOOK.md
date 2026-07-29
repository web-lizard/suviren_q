# Bookender Studio runbook

## Запуск

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd ui
npm.cmd install
npm.cmd run build
cd ..
python book_wunderwaffe_desktop.py
```

Или используйте существующий `run.bat`. Он всегда выбирает Python из
`.venv` и проверяет импорт `edge_tts`; если компонент отсутствует, официальный
`requirements.txt` устанавливается именно в это окружение.

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

## Озвучка

- «Проба голоса» озвучивает выделение до 500 символов или нейтральную фразу.
- Пробы находятся в `user_data/projects/<uuid>/temp` и не попадают в список
  версий главы.
- Озвучка главы создаёт новый MP3 в `audio`, не перезаписывая старые версии.
- После изменения текста прежние файлы остаются доступными, но помечаются
  как устаревшие.
- Активную версию можно воспроизвести встроенным плеером и передать в
  видеоредактор.

Edge TTS работает через интернет. При явном запуске озвучки выбранный текст
или текст главы отправляется TTS-провайдеру. Остальные данные проекта
остаются локальными.

Проверка runtime:

```powershell
.\.venv\Scripts\python.exe -c "import edge_tts; print(edge_tts.__version__)"
.\.venv\Scripts\python.exe -m bookender.cli verify
```

Если интерфейс сообщает, что модуль недоступен:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Технические причины находятся в `user_data/logs/bookender.log`; основной UI
не показывает Python traceback.

## Иконка Windows

Окно использует `assets/bookender-studio.ico`, содержащий размеры от 16 до
256 px. Пересоздать или обновить ярлык:

```powershell
powershell -ExecutionPolicy Bypass -File .\create_desktop_shortcut.ps1
```

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
