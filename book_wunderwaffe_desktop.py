#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Native desktop shell for the Vue/FastAPI audiobook studio.

The editor remains a single Vue implementation.  This module serves the
production build and the existing API from one loopback-only ASGI server,
then embeds that URL in a Qt WebEngine window.  No external browser or Vite
development server is needed at runtime.
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
UI_ROOT = ROOT / "ui"
UI_DIST = UI_ROOT / "dist"
UI_INDEX = UI_DIST / "index.html"
HOST = "127.0.0.1"


def hidden_process_options() -> dict[str, int]:
    """Keep npm's helper console hidden when launched through pythonw.exe."""
    if os.name == "nt":
        return {"creationflags": int(getattr(subprocess, "CREATE_NO_WINDOW", 0))}
    return {}


def ensure_runtime_streams() -> None:
    """Give libraries valid streams when Windows starts us through pythonw.exe."""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


class DesktopStartupError(RuntimeError):
    """Raised when the local desktop runtime cannot be prepared."""


def _latest_source_mtime() -> float:
    candidates = [
        UI_ROOT / "package.json",
        UI_ROOT / "package-lock.json",
        UI_ROOT / "index.html",
        UI_ROOT / "vite.config.js",
    ]
    source_dir = UI_ROOT / "src"
    if source_dir.is_dir():
        candidates.extend(path for path in source_dir.rglob("*") if path.is_file())
    return max((path.stat().st_mtime for path in candidates if path.is_file()), default=0.0)


def ui_build_is_current() -> bool:
    """Return whether the production bundle exists and is newer than its source."""
    if not UI_INDEX.is_file():
        return False
    assets_dir = UI_DIST / "assets"
    if not assets_dir.is_dir() or not any(path.is_file() for path in assets_dir.iterdir()):
        return False
    return UI_INDEX.stat().st_mtime >= _latest_source_mtime()


def _npm_command() -> str:
    executable = shutil.which("npm.cmd") or shutil.which("npm")
    if not executable:
        raise DesktopStartupError(
            "Node.js/npm не найден. Установите Node.js, затем выполните "
            "`npm install` и `npm run build` в папке ui."
        )
    return executable


def ensure_ui_build(*, force: bool = False) -> None:
    """Create a production Vue bundle when it is missing or stale."""
    if not force and ui_build_is_current():
        return
    if not (UI_ROOT / "package.json").is_file():
        raise DesktopStartupError(f"Vue-проект не найден: {UI_ROOT}")

    npm = _npm_command()
    if not (UI_ROOT / "node_modules").is_dir():
        install = subprocess.run(
            [npm, "install"],
            cwd=UI_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            **hidden_process_options(),
        )
        if install.returncode:
            details = (install.stderr or install.stdout).strip()
            raise DesktopStartupError(f"Не удалось установить зависимости Vue.\n\n{details}")

    build = subprocess.run(
        [npm, "run", "build"],
        cwd=UI_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        **hidden_process_options(),
    )
    if build.returncode or not UI_INDEX.is_file():
        details = (build.stderr or build.stdout).strip()
        raise DesktopStartupError(f"Не удалось собрать интерфейс Vue.\n\n{details}")


def _reserve_port() -> int:
    """Ask Windows for a currently unused loopback port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((HOST, 0))
        return int(probe.getsockname()[1])


def create_desktop_asgi_app() -> tuple[Any, str, str]:
    """Append the production UI mount after all existing API routes."""
    from fastapi.staticfiles import StaticFiles
    import suviren_q_server as server_module

    ensure_ui_build()
    app = server_module.app
    if not any(getattr(route, "name", "") == "desktop-ui" for route in app.routes):
        # The mount is deliberately last: declared /api routes keep precedence.
        app.mount("/", StaticFiles(directory=str(UI_DIST), html=True), name="desktop-ui")
    return app, server_module.APP_NAME, server_module.APP_VERSION


class LocalServer:
    """Small lifecycle wrapper around an in-process uvicorn server."""

    def __init__(self, app: Any, port: int | None = None) -> None:
        import uvicorn

        self.port = port or _reserve_port()
        config = uvicorn.Config(
            app,
            host=HOST,
            port=self.port,
            log_level="warning",
            access_log=False,
            server_header=False,
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(
            target=self.server.run,
            name="book-wunderwaffe-local-server",
            daemon=True,
        )

    @property
    def url(self) -> str:
        return f"http://{HOST}:{self.port}"

    def start(self, timeout: float = 20.0) -> None:
        self.thread.start()
        deadline = time.monotonic() + timeout
        health_url = f"{self.url}/api/health"
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            if not self.thread.is_alive():
                raise DesktopStartupError("Локальный сервер завершился во время запуска.")
            try:
                with urllib.request.urlopen(health_url, timeout=1.0) as response:
                    if response.status == 200:
                        return
            except (OSError, urllib.error.URLError) as exc:
                last_error = exc
            time.sleep(0.1)
        raise DesktopStartupError(f"Локальный сервер не запустился: {last_error}")

    def stop(self, timeout: float = 5.0) -> None:
        self.server.should_exit = True
        if self.thread.is_alive() and threading.current_thread() is not self.thread:
            self.thread.join(timeout=timeout)


def _show_fatal_message(message: str) -> None:
    """Show a native error when Qt is available, otherwise write to stderr."""
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication(sys.argv[:1])
        QMessageBox.critical(None, "Ошибка запуска", message)
        app.processEvents()
    except Exception:
        print(message, file=sys.stderr)


def run_desktop(*, window_smoke_test: bool = False) -> int:
    try:
        from PySide6.QtCore import QLockFile, QStandardPaths, QTimer, QUrl, Qt
        from PySide6.QtGui import QAction, QDesktopServices, QIcon, QKeySequence
        from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox
    except ImportError as exc:
        _show_fatal_message(
            "Не найден Qt WebEngine. Установите зависимости командой:\n\n"
            "python -m pip install -r requirements.txt\n\n"
            f"Техническая информация: {exc}"
        )
        return 2

    import suviren_q_server as backend_module

    app_name = backend_module.APP_NAME
    app_version = backend_module.APP_VERSION

    QApplication.setOrganizationName("Temple of Lizard")
    QApplication.setApplicationName(app_name)
    QApplication.setApplicationDisplayName(app_name)
    QApplication.setApplicationVersion(app_version)
    qt_app = QApplication.instance() or QApplication(sys.argv)
    qt_app.setQuitOnLastWindowClosed(True)

    data_dir = Path(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation))
    data_dir.mkdir(parents=True, exist_ok=True)
    instance_lock = QLockFile(str(data_dir / "book-wunderwaffe-studio.lock"))
    if not instance_lock.tryLock(0):
        QMessageBox.information(
            None,
            app_name,
            "BOOK WUNDERWAFFE Studio уже запущена.\n\n"
            "Используйте открытое окно, чтобы проект и рендер не конфликтовали.",
        )
        return 0

    try:
        asgi_app, app_name, app_version = create_desktop_asgi_app()
    except Exception as exc:
        instance_lock.unlock()
        _show_fatal_message(str(exc))
        return 2

    server = LocalServer(asgi_app)
    try:
        server.start()
    except Exception as exc:
        instance_lock.unlock()
        _show_fatal_message(str(exc))
        return 2

    class StudioPage(QWebEnginePage):
        def acceptNavigationRequest(self, url: QUrl, navigation_type: Any, is_main_frame: bool) -> bool:
            if is_main_frame and url.isValid() and url.host() not in {HOST, "localhost"}:
                QDesktopServices.openUrl(url)
                return False
            return super().acceptNavigationRequest(url, navigation_type, is_main_frame)

    class StudioWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.smoke_succeeded: bool | None = None
            self.setWindowTitle(f"{app_name} · {app_version}")
            self.resize(1600, 960)
            self.setMinimumSize(1120, 720)
            if (ROOT / "cover.png").is_file():
                self.setWindowIcon(QIcon(str(ROOT / "cover.png")))

            self.view = QWebEngineView(self)
            profile = QWebEngineProfile.defaultProfile()
            profile.setPersistentStoragePath(str(data_dir / "web-profile"))
            profile.setCachePath(str(data_dir / "web-cache"))

            page = StudioPage(profile, self.view)
            self.view.setPage(page)
            settings = self.view.settings()
            settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
            settings.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
            settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
            self.setCentralWidget(self.view)

            if window_smoke_test:
                self.view.loadFinished.connect(self._smoke_load_finished)

            profile.downloadRequested.connect(self._download_requested)
            if hasattr(page, "newWindowRequested"):
                page.newWindowRequested.connect(
                    lambda request: QDesktopServices.openUrl(request.requestedUrl())
                )
            page.fullScreenRequested.connect(self._full_screen_requested)

            reload_action = QAction(self)
            reload_action.setShortcut(QKeySequence.Refresh)
            reload_action.triggered.connect(self.view.reload)
            self.addAction(reload_action)

            full_screen_action = QAction(self)
            full_screen_action.setShortcut(QKeySequence(Qt.Key.Key_F11))
            full_screen_action.triggered.connect(self._toggle_full_screen)
            self.addAction(full_screen_action)

            self.view.load(QUrl(server.url))

        def _smoke_load_finished(self, loaded: bool) -> None:
            if not loaded:
                self.smoke_succeeded = False
                QTimer.singleShot(100, self.close)
                return

            def verify_vue(mounted: Any) -> None:
                self.smoke_succeeded = bool(mounted)
                QTimer.singleShot(100, self.close)

            QTimer.singleShot(
                750,
                lambda: self.view.page().runJavaScript(
                    "Boolean(document.querySelector('.studio'))", verify_vue
                ),
            )

        def _download_requested(self, download: Any) -> None:
            suggested = download.downloadFileName() or "export.mp4"
            path, _ = QFileDialog.getSaveFileName(self, "Сохранить экспорт", suggested)
            if not path:
                download.cancel()
                return
            destination = Path(path)
            download.setDownloadDirectory(str(destination.parent))
            download.setDownloadFileName(destination.name)
            download.accept()

        def _toggle_full_screen(self) -> None:
            self.showNormal() if self.isFullScreen() else self.showFullScreen()

        def _full_screen_requested(self, request: Any) -> None:
            request.accept()
            self.showFullScreen() if request.toggleOn() else self.showNormal()

        def closeEvent(self, event: Any) -> None:
            with backend_module.JOBS_LOCK:
                active_render = any(
                    job.get("status") == "running"
                    and job.get("kind") in {"render-test", "render-full"}
                    for job in backend_module.JOBS.values()
                )
            if active_render:
                QMessageBox.warning(
                    self,
                    "Рендер выполняется",
                    "Сейчас идёт сборка видео. Окно останется открытым, чтобы "
                    "renderer и FFmpeg корректно завершили работу.\n\n"
                    "Дождитесь статуса «готово», затем закройте программу.",
                )
                event.ignore()
                return
            self.view.stop()
            server.stop()
            super().closeEvent(event)

    window = StudioWindow()
    qt_app.aboutToQuit.connect(server.stop)
    window.showMaximized()
    if window_smoke_test:
        QTimer.singleShot(
            20_000,
            lambda: (
                setattr(window, "smoke_succeeded", False),
                window.close(),
            ),
        )
    exit_code = qt_app.exec()
    server.stop()
    instance_lock.unlock()
    if window_smoke_test and not window.smoke_succeeded:
        return 3
    return int(exit_code)


def smoke_test() -> int:
    """Exercise the integrated HTTP lifecycle without opening a GUI."""
    app, app_name, app_version = create_desktop_asgi_app()
    server = LocalServer(app)
    try:
        server.start()
        with urllib.request.urlopen(server.url, timeout=3) as response:
            html = response.read().decode("utf-8", errors="replace")
        with urllib.request.urlopen(f"{server.url}/api/health", timeout=3) as response:
            health = response.read().decode("utf-8", errors="replace")
        if "<div id=\"app\"></div>" not in html or '"ok":true' not in health:
            raise DesktopStartupError("Smoke test получил некорректный ответ UI/API.")
        print(f"[OK] {app_name} {app_version}: UI + API at {server.url}")
        return 0
    finally:
        server.stop()


def main() -> int:
    ensure_runtime_streams()
    parser = argparse.ArgumentParser(description="Native desktop shell for the audiobook studio")
    parser.add_argument("--smoke-test", action="store_true", help="test UI/API server without a window")
    parser.add_argument(
        "--window-smoke-test",
        action="store_true",
        help="open Qt WebEngine, verify Vue mounted, then close automatically",
    )
    parser.add_argument("--rebuild-ui", action="store_true", help="force a fresh Vue production build")
    args = parser.parse_args()
    if args.rebuild_ui:
        ensure_ui_build(force=True)
    return smoke_test() if args.smoke_test else run_desktop(window_smoke_test=args.window_smoke_test)


if __name__ == "__main__":
    raise SystemExit(main())
