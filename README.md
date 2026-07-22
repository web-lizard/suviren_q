# BOOK WUNDERWAFFE Studio

<p align="center">
  <img src="assets/book-wunderwaffe-icon.png" width="180" alt="BOOK WUNDERWAFFE Studio icon" />
</p>

> **Local-first Audiobook Production Suite** — превращает мастер-аудио и разметку глав в аккуратный, готовый к публикации видеорелиз.

![Version](https://img.shields.io/badge/version-1.1.0-ffb731?style=flat-square)
![Platform](https://img.shields.io/badge/platform-Windows-4b8bbe?style=flat-square)
![Vue](https://img.shields.io/badge/Vue-3-42b883?style=flat-square)
![FastAPI](https://img.shields.io/badge/FastAPI-local-009688?style=flat-square)
![FFmpeg](https://img.shields.io/badge/FFmpeg-GPU%20%2F%20CPU-5cb85c?style=flat-square)

BOOK WUNDERWAFFE Studio — локальная production-система для сборки аудиокниг в готовые видео. Она импортирует мастер-аудио, обложку, фон и главы из REAPER/RPP, показывает итоговую композицию в визуальном редакторе, синхронизирует waveform и прогресс, автоматически подбирает типографику и собирает стабильный MP4 через FFmpeg.

Без облака, подписки и ручной сборки десятков или сотен глав.

## Что умеет

- нативное desktop-окно на PySide6 с единым Vue-интерфейсом;
- импорт MP3/WAV/M4A/FLAC и изображений; видео поддерживается в синхронном предпросмотре, а MP4-экспорт пока использует статический фон;
- автообнаружение REAPER `.rpp` в `data/`, извлечение и ручное редактирование глав;
- перемещение и масштабирование обложки, заголовка и визуализатора;
- предыдущая и следующая главы с пониженной непрозрачностью;
- автоматический перенос и подбор размера длинных названий;
- живой аудиореактивный waveform в предпросмотре и финальном видео;
- движущаяся полоса общего прогресса с таймкодом;
- мягкий blur, RGB-glitch и цветовые темы;
- сканируемый QR-код Telegram с высокой коррекцией ошибок;
- тестовый 60-секундный и полный экспорт;
- AMD AMF, NVIDIA NVENC, Intel QSV и автоматический CPU-fallback;
- единое кодирование мастер-аудио без разрывов AAC между главами;
- локальная работа: материалы проекта не отправляются в сторонние сервисы.

## Быстрый запуск на Windows

Нужны Python 3.10+, Node.js `^20.19.0` или `>=22.12.0`, npm и FFmpeg в `PATH`.

```powershell
git clone https://github.com/web-lizard/suviren_q.git
cd suviren_q

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

cd ui
npm install
npm run build
cd ..

.\run.bat
```

`run.bat` открывает самостоятельное GUI-окно. Внешний браузер и постоянно работающий Vite dev-server для обычной работы не нужны. Если production-сборка интерфейса устарела, desktop-оболочка пересоберёт её автоматически.

Создать фирменный ярлык на рабочем столе:

```powershell
powershell -ExecutionPolicy Bypass -File .\create_desktop_shortcut.ps1
```

FFmpeg можно поставить через Winget:

```powershell
winget install Gyan.FFmpeg
```

## Рабочий процесс

1. Импортируйте мастер-аудио, обложку и фон.
2. Поместите RPP в `data/` и обновите главы либо создайте их вручную в редакторе.
3. Настройте композицию непосредственно на сцене.
4. Проверьте звук, заголовки, waveform и таймлайн.
5. Запустите тестовый 60-секундный экспорт.
6. После проверки соберите полный MP4.

Тестовый экспорт сохраняет контекст полного проекта: соседние главы и общий прогресс не превращаются в искусственные `1 / 1`.

## Архитектура

```text
Desktop shell (PySide6 / Qt WebEngine)
                │
                ▼
Vue 3 editor ── loopback HTTP ── FastAPI media engine
                                        │
                                        ▼
                       Pillow composition + FFmpeg filters
                                        │
                                        ▼
                         H.264 / AAC upload-ready MP4
```

Vue остаётся единственным интерфейсом: desktop-оболочка встраивает его в нативное окно. Экспортный движок читает сохранённую геометрию слоёв и воспроизводит её в итоговом видео.

## Надёжность рендера

- статические слои готовятся отдельно для каждой главы;
- waveform строится из реального аудио во время кодирования;
- прогресс рассчитывается по времени всей книги, а не по номеру главы;
- аппаратный кодировщик при сбое автоматически заменяется на `libx264`;
- одновременно работают не более двух тяжёлых segment workers;
- сегменты склеиваются как video-only, после чего мастер-аудио кодируется один раз;
- перед стартом проверяется пиковое свободное место, а после успешной проверки MP4 тяжёлые временные сегменты удаляются;
- единый bitrate-профиль применяется одинаково к NVENC, AMF, QSV и `libx264`, включая CPU fallback;
- доступны три профиля для YouTube: `compact` (1,2 Мбит/с), `balanced` (1,8 Мбит/с) и `youtube_1080p` (до 8 Мбит/с);
- финальное AAC-аудио кодируется с частотой 48 кГц и битрейтом выбранного профиля;
- итоговый контейнер получает `faststart` и совместимый `yuv420p`.

## CLI

```powershell
.\.venv\Scripts\python.exe suviren_q.py --version
.\.venv\Scripts\python.exe suviren_q.py preview --help
.\.venv\Scripts\python.exe suviren_q.py render --help
```

Пример короткого контрольного рендера:

```powershell
.\.venv\Scripts\python.exe suviren_q.py render `
  --audio data\book.mp3 `
  --cover data\cover.png `
  --background data\background.png `
  --chapters _suviren_q_build\chapters.detected.json `
  --editor-project _suviren_q_build\editor-project.json `
  --waveform ffmpeg `
  --bitrate-preset balanced `
  --max-duration 60 `
  --out _suviren_q_build\test.mp4
```

## Структура проекта

```text
book_wunderwaffe_desktop.py  native desktop shell
ui/                          Vue editor
suviren_q_server.py          local API and render jobs
suviren_q.py                 composition and FFmpeg renderer
data/                        local media; ignored by Git
_suviren_q_build/            project state and exports
run.bat                      desktop launcher
```

## Диагностика

```powershell
.\.venv\Scripts\python.exe smoke_test_suviren_q.py
.\.venv\Scripts\python.exe book_wunderwaffe_desktop.py --smoke-test
.\.venv\Scripts\python.exe book_wunderwaffe_desktop.py --window-smoke-test
ffmpeg -version
ffprobe -version
```

Если GPU-кодировщик недоступен, это не должно останавливать экспорт: движок повторит сегмент через CPU. Логи и готовые файлы доступны в экспортном окне и `_suviren_q_build/`.

## English overview

BOOK WUNDERWAFFE Studio is a local-first audiobook production suite that turns mastered audio and REAPER chapter markers into polished, upload-ready videos—with synchronized waveform visuals, adaptive typography, branded QR overlays, a native desktop shell, and reliable accelerated FFmpeg export.

## Канал проекта

[Temple of Lizard в Telegram](https://t.me/temple_of_lizard)

## Лицензия

Лицензия проекта пока не выбрана. До появления файла `LICENSE` права на исходный код явно не предоставляются.
