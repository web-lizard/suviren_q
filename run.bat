@echo off
setlocal
chcp 65001 >nul
title BOOK WUNDERWAFFE
cd /d "%~dp0"

set "APP_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%APP_PYTHON%" set "APP_PYTHON=python"

echo.
echo   BOOK WUNDERWAFFE
echo   Локальная студия аудиокниг
echo.

if not exist "ui\node_modules" (
    echo [1/3] Устанавливаю зависимости интерфейса...
    pushd ui
    call npm.cmd install
    if errorlevel 1 goto :fail
    popd
) else (
    echo [1/3] Интерфейс готов
)

echo [2/3] Запускаю медиадвижок на порту 8787...
start "BOOK WUNDERWAFFE API" /MIN "%APP_PYTHON%" "%~dp0suviren_q_server.py"

set /a API_TRIES=0
:wait_api
set /a API_TRIES+=1
"%APP_PYTHON%" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/health', timeout=1)" >nul 2>nul
if not errorlevel 1 goto :api_ready
if %API_TRIES% GEQ 30 goto :api_failed
timeout /t 1 /nobreak >nul
goto :wait_api

:api_ready
echo [3/3] Запускаю студию на порту 5178...
start "BOOK WUNDERWAFFE UI" /MIN /D "%~dp0ui" cmd /c npm.cmd run dev
timeout /t 3 /nobreak >nul
start "" "http://127.0.0.1:5178"
echo.
echo   Студия открыта: http://127.0.0.1:5178
echo   Это окно можно закрыть — серверы продолжат работать.
echo.
exit /b 0

:api_failed
echo.
echo [ОШИБКА] Backend не ответил за 30 секунд.
echo Проверьте сообщения в окне BOOK WUNDERWAFFE API.
goto :fail

:fail
echo.
pause
exit /b 1
