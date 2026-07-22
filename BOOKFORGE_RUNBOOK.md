# BookForge Engine — Runbook v1

> [!WARNING]
> Архив раннего CLI-прототипа. Для BOOK WUNDERWAFFE Studio 1.1.0 используйте актуальные инструкции в [README.md](README.md); архитектурные и render-команды ниже сохранены только для истории.

## 1. Что это

**BookForge Engine** — CLI-first компоновщик аудиокниг для YouTube.  
Собирает аудио + обложку + фон + главы в видео с waveform, прогресс-баром и текстом глав.

Формат: статика + аудио (image + audio → video). Без перекодирования аудио.

---

## 2. Структура проекта

```
d:\PYTHON\suviren_q\
├── data/                     # Исходные медиафайлы
│   ├── zinaida.mp3           #  Аудиокнига (mp3/wav/m4a)
│   ├── zina-cover.png        #  Обложка (квадратная, png/jpg)
│   ├── background.png        #  Фон 16:9 (опционально)
│   └── *.rpp                 #  REAPER-проект с разметкой глав
├── _suviren_q_build/         #  Результаты сборки
│   ├── layout.json           #  Конфиг сцены (x/y/w/h объектов)
│   ├── waveform.json         #  Данные waveform
│   ├── preview.png           #  Одиночный кадр превью
│   ├── preview_contact.png   #  Контакт-лист 2×2
│   ├── test_60sec.mp4        #  Тестовый рендер (60 с)
│   └── zina_book_youtube_full.mp4  #  Полный рендер (≈15.5ч)
├── bookforge.py              #  Главный CLI-инструмент
├── suviren_q.py              #  Общие функции
├── BOOKFORGE_RUNBOOK.md      #  Этот файл
└── bookforge.project.json    #  Конфиг проекта
```

---

## 3. Базовый порядок команд

### Первичная настройка

```bash
python bookforge.py doctor              #  Проверка окружения
python bookforge.py scan                #  Поиск файлов в data/
python bookforge.py chapters            #  Извлечение глав из RPP
python bookforge.py preset zina-noir    #  Создание визуального шаблона
python bookforge.py waveform            #  Генерация waveform
python bookforge.py preview --contact   #  Превью + контакт-лист
```

### Отчёт и проверка

```bash
python bookforge.py check-preview       #  QA проверка превью
python bookforge.py report              #  Полный отчёт (JSON + MD)
python bookforge.py status              #  Статус проекта
```

### Рендер

```bash
python bookforge.py render-test --overwrite          #  Тест (60 с)
python bookforge.py render-full                      #  Полный рендер (≈15.5 ч)
```

---

## 4. Что делать, если комп лагает

| Проблема                    | Решение |
|-----------------------------|---------|
| render-full грузит CPU 100% | `Ctrl+C`, затем `python bookforge.py clean-temp` |
| Закончилось место на диске  | `python bookforge.py clean-temp`, удалить `_suviren_q_build/segments/`, `_suviren_q_build/panels_render/` |
| ffmpeg завис                | Открыть PowerShell: `Get-Process ffmpeg \| Stop-Process -Force` |
| lock file висит             | `python bookforge.py clean-temp` |

Не запускайте render-full из браузера (через suviren_q_server).  
На машине должно быть >5 GB свободного места для полного рендера.

---

## 5. Как менять внешний вид

Все визуальные параметры в `_suviren_q_build/layout.json`:

- **Позиции**: `x`, `y`, `w`, `h` каждого объекта
- **Размер шрифта**: `font_size` у текстовых объектов
- **Цвета**: `theme.accent`, `theme.text`, `theme.waveform_played`
- **Фон**: `background_dim`, `background_overlay`

После изменения layout:

```bash
python bookforge.py preview --contact   #  Проверить результат
```

---

## 6. Часто используемые флаги

```bash
# Превью конкретной главы
python bookforge.py preview --chapter 5

# Превью и открыть в просмотрщике
python bookforge.py preview --open

# Контакт-лист
python bookforge.py preview --contact --open

# Тестовый рендер с настройками
python bookforge.py render-test --overwrite --seconds 120 --quality youtube_high --open-output-folder

# Полный рендер с перезаписью
python bookforge.py render-full --force
```

---

## 7. Что пока НЕ ДЕЛАТЬ

❌ Не запускать `render-full`, пока `test_60sec.mp4` не проверен визуально  
❌ Не коммитить большие mp3/wav/mp4 в git  
❌ Не трогать legacy Vue UI (`ui/`) — он не нужен для CLI-пайплайна  

---

## 8. Аварийное завершение

Если всё пошло не так:

```bash
python bookforge.py clean-temp           #  Снять lock, удалить временные
rmdir /s _suviren_q_build\panels_render  #  Удалить панели вручную
rmdir /s _suviren_q_build\segments       #  Удалить сегменты вручную
```

---

## 9. Термины

| Термин          | Значение |
|-----------------|----------|
| RPP             | Файл-проект REAPER (DAW) — содержит разметку глав |
| Preset          | Шаблон визуального оформления (zina-noir) |
| Waveform        | График амплитуды аудио |
| Contact sheet   | 4 кадра в одном (начало, четверть, половина, конец) |
| Render lock     | Флаг, блокирующий запуск второго рендера |
| CRF             | Rate control в x264 (18 = высокое качество, 23 = стандарт) |

---

*BookForge Engine v1 — Monsieur Souveraineté / 2026*
