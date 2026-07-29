@echo off
setlocal EnableExtensions
cd /d "%~dp0" || exit /b 1

set "APP_PYTHON=%~dp0.venv\Scripts\python.exe"
set "APP_PYTHONW=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%APP_PYTHON%" set "APP_PYTHON=python.exe"
if not exist "%APP_PYTHONW%" set "APP_PYTHONW=pythonw.exe"

"%APP_PYTHON%" -c "from PySide6.QtWebEngineWidgets import QWebEngineView; import PIL, qrcode, fastapi, uvicorn, edge_tts" >nul 2>&1
if errorlevel 1 (
    echo Installing or updating Bookender Studio runtime...
    "%APP_PYTHON%" -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
    if errorlevel 1 (
        echo [ERROR] Desktop dependencies could not be installed.
        pause
        exit /b 1
    )
)

start "" "%APP_PYTHONW%" "%~dp0book_wunderwaffe_desktop.py" %*
if errorlevel 1 (
    echo [ERROR] Desktop studio could not be started.
    echo Install dependencies with: python -m pip install -r requirements.txt
    pause
    exit /b 1
)
exit /b 0
