@echo off
setlocal EnableExtensions
title BOOK WUNDERWAFFE Launcher
cd /d "%~dp0" || goto :fail

set "APP_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%APP_PYTHON%" set "APP_PYTHON=python.exe"

echo.
echo   BOOK WUNDERWAFFE
echo   Starting audiobook studio...
echo.

if not exist "ui\package.json" (
    echo [ERROR] UI project not found: %~dp0ui
    goto :fail
)

if not exist "ui\node_modules" (
    echo [1/3] Installing UI dependencies...
    pushd "ui"
    call npm.cmd install
    if errorlevel 1 (
        popd
        goto :fail
    )
    popd
) else (
    echo [1/3] UI dependencies are ready.
)

echo [2/3] Checking media engine on http://127.0.0.1:8787 ...
"%APP_PYTHON%" -c "import json,urllib.request; data=json.load(urllib.request.urlopen('http://127.0.0.1:8787/api/health', timeout=1)); assert data.get('app') == 'BOOK WUNDERWAFFE'" >nul 2>&1
if not errorlevel 1 goto :api_ready

echo       Starting media engine...
start "BOOK WUNDERWAFFE API" /min "%APP_PYTHON%" "%~dp0suviren_q_server.py"

set /a API_TRIES=0
:wait_api
set /a API_TRIES+=1
"%APP_PYTHON%" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/health', timeout=1)" >nul 2>&1
if not errorlevel 1 goto :api_ready
if %API_TRIES% GEQ 30 goto :api_failed
"%APP_PYTHON%" -c "import time; time.sleep(1)" >nul 2>&1
goto :wait_api

:api_ready
echo [3/3] Checking studio on http://127.0.0.1:5178 ...
"%APP_PYTHON%" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5178', timeout=1)" >nul 2>&1
if not errorlevel 1 goto :ui_ready

echo       Starting studio...
start "BOOK WUNDERWAFFE UI" /min /d "%~dp0ui" cmd.exe /d /c "npm.cmd run dev"

set /a UI_TRIES=0
:wait_ui
set /a UI_TRIES+=1
"%APP_PYTHON%" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5178', timeout=1)" >nul 2>&1
if not errorlevel 1 goto :ui_ready
if %UI_TRIES% GEQ 30 goto :ui_failed
"%APP_PYTHON%" -c "import time; time.sleep(1)" >nul 2>&1
goto :wait_ui

:ui_ready
start "" "http://127.0.0.1:5178"
echo.
echo   Studio is ready: http://127.0.0.1:5178
exit /b 0

:api_failed
echo [ERROR] Media engine did not answer on port 8787.
goto :fail

:ui_failed
echo [ERROR] Studio did not answer on port 5178.
goto :fail

:fail
echo.
echo BOOK WUNDERWAFFE could not start. Review the API/UI windows above.
pause
exit /b 1
