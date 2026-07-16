@echo off
chcp 65001 >nul
title suviren-q Launcher

echo =======================================
echo    suviren-q — редактор видеокниг
echo =======================================
cd /d "%~dp0"

:: Мочим всё что заняло 8787
echo [x] Чищу порты...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8787 ^| findstr LISTENING') do (
    if not "%%a"=="" taskkill /f /pid %%a 2>nul
)
timeout /t 1 /nobreak >nul

:: Ставим зависимости npm если ещё нет
echo [1/3] Проверка npm...
if not exist "ui\node_modules" (
    echo    npm install...
    cd ui
    call npm install
    cd ..
)

:: Запускаем API сервер
echo [2/3] Запуск API сервера (порт 8787)...
start "suviren-q API" /MIN cmd /c "python suviren_q_server.py"

:: Ждём пока API встанет
echo    Ожидание API...
:wait_api
timeout /t 2 /nobreak >nul
python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/health')" 2>nul
if errorlevel 1 goto wait_api
echo    API готов!

:: Запускаем UI
echo [3/3] Запуск редактора...
start "suviren-q UI" /MIN cmd /c "cd /d %~dp0ui && npx vite --host 127.0.0.1"

timeout /t 4 /nobreak >nul

:: Находим какой порт занял Vite
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :51[0-9][0-9] ^| findstr LISTENING') do (
    for /f "tokens=4" %%b in ('netstat -ano ^| findstr %%a ^| findstr LISTENING') do (
        set "port=%%b"
    )
)

:: Если не нашли, пробуем стандартный
if "%port%"=="" set "port=127.0.0.1:5173"

echo.
echo =======================================
echo    Всё запущено! Открываю браузер...
echo    http://%port%/
echo =======================================
start http://%port%/

echo.
echo [Для выхода закрой это окно]
echo.
pause