#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
install_suviren_q.py

Bootstrap installer for BOOK WUNDERWAFFE Studio 1.1.0.

This script prepares a local Windows-friendly Python environment:
- checks Python version
- creates .venv
- writes requirements.txt
- installs the Python desktop/API/render runtime
- checks ffmpeg and ffprobe
- creates local helper scripts
- runs a smoke test for suviren_q.py

It does not upload or modify media files.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable


APP_NAME = "book-wunderwaffe-studio"
APP_FULL_NAME = "BOOK WUNDERWAFFE Studio 1.1.0"

ROOT = Path(__file__).resolve().parent
MAIN_SCRIPT = ROOT / "suviren_q.py"
VENV_DIR = ROOT / ".venv"
REQ_FILE = ROOT / "requirements.txt"
GITIGNORE_FILE = ROOT / ".gitignore"
BUILD_DIR = ROOT / "_suviren_q_build"
LOCAL_DIR = ROOT / "_suviren_q_local"


REQUIREMENTS = [
    "Pillow>=10.0.0",
    "qrcode[pil]>=8.2",
    "fastapi>=0.115.0",
    "uvicorn>=0.30.0",
    "PySide6>=6.8,<7",
]


GITIGNORE_RULES = [
    "",
    "# BOOK WUNDERWAFFE Studio local/build files",
    "_suviren_q_build/",
    "_suviren_q_local/",
    "",
    "# Python",
    "__pycache__/",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    ".venv/",
    "venv/",
    "env/",
    "",
    "# Media and heavy files",
    "*.mp3",
    "*.wav",
    "*.m4a",
    "*.flac",
    "*.aac",
    "*.ogg",
    "*.mp4",
    "*.mov",
    "*.avi",
    "*.mkv",
    "",
    "# REAPER projects usually contain local paths and private project data",
    "*.rpp",
    "*.RPP",
]


def is_windows() -> bool:
    return os.name == "nt"


def venv_python() -> Path:
    if is_windows():
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def quote_cmd(cmd: Iterable[str | os.PathLike[str]]) -> str:
    result = []
    for part in cmd:
        s = str(part)
        if " " in s or "\t" in s or any(ch in s for ch in ['"', "'", "(", ")"]):
            result.append(f'"{s}"')
        else:
            result.append(s)
    return " ".join(result)


def run(
    cmd: list[str | os.PathLike[str]],
    *,
    check: bool = True,
    cwd: Path = ROOT,
) -> subprocess.CompletedProcess:
    print()
    print(f"[run] {quote_cmd(cmd)}")
    return subprocess.run(
        [str(x) for x in cmd],
        cwd=str(cwd),
        check=check,
    )


def run_capture(
    cmd: list[str | os.PathLike[str]],
    *,
    check: bool = False,
    cwd: Path = ROOT,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(x) for x in cmd],
        cwd=str(cwd),
        check=check,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def print_header(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def print_ok(text: str) -> None:
    print(f"[OK] {text}")


def print_warn(text: str) -> None:
    print(f"[WARN] {text}")


def print_fail(text: str) -> None:
    print(f"[FAIL] {text}")


def check_python_version() -> None:
    print_header("1. Python check")

    version = sys.version_info
    print(f"Python: {sys.version.split()[0]}")
    print(f"Executable: {sys.executable}")
    print(f"Platform: {platform.platform()}")

    if version < (3, 10):
        raise SystemExit("Python 3.10+ is required.")

    print_ok("Python version is suitable.")


def check_project_files() -> None:
    print_header("2. Project file check")

    if not MAIN_SCRIPT.exists():
        raise SystemExit(
            f"Main script not found: {MAIN_SCRIPT}\n"
            f"Put install_suviren_q.py next to suviren_q.py."
        )

    print_ok(f"Found {MAIN_SCRIPT.name}")


def write_requirements() -> None:
    print_header("3. requirements.txt")

    text = "\n".join(REQUIREMENTS) + "\n"
    if REQ_FILE.exists():
        current = REQ_FILE.read_text(encoding="utf-8", errors="replace")
        missing = [line for line in REQUIREMENTS if line not in current]
        if missing:
            with REQ_FILE.open("a", encoding="utf-8", newline="\n") as f:
                if not current.endswith("\n"):
                    f.write("\n")
                for line in missing:
                    f.write(line + "\n")
            print_ok(f"Updated {REQ_FILE.name}")
        else:
            print_ok(f"{REQ_FILE.name} already contains required packages.")
    else:
        REQ_FILE.write_text(text, encoding="utf-8", newline="\n")
        print_ok(f"Created {REQ_FILE.name}")


def ensure_gitignore() -> None:
    print_header("4. .gitignore")

    if GITIGNORE_FILE.exists():
        current = GITIGNORE_FILE.read_text(encoding="utf-8", errors="replace")
    else:
        current = ""

    lines_to_add = []
    existing_lines = set(line.strip() for line in current.splitlines())

    for rule in GITIGNORE_RULES:
        if rule == "":
            lines_to_add.append(rule)
        elif rule.strip() not in existing_lines:
            lines_to_add.append(rule)

    if not GITIGNORE_FILE.exists():
        GITIGNORE_FILE.write_text("\n".join(GITIGNORE_RULES).strip() + "\n", encoding="utf-8", newline="\n")
        print_ok("Created .gitignore")
        return

    meaningful = [x for x in lines_to_add if x.strip()]
    if meaningful:
        with GITIGNORE_FILE.open("a", encoding="utf-8", newline="\n") as f:
            if current and not current.endswith("\n"):
                f.write("\n")
            f.write("\n".join(lines_to_add).strip() + "\n")
        print_ok("Updated .gitignore")
    else:
        print_ok(".gitignore already looks good.")


def create_dirs() -> None:
    print_header("5. Local directories")

    for path in [
        BUILD_DIR,
        BUILD_DIR / "panels",
        BUILD_DIR / "segments",
        LOCAL_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)
        print_ok(f"Directory ready: {path.relative_to(ROOT)}")


def create_venv(force: bool = False) -> Path:
    print_header("6. Virtual environment")

    py = venv_python()

    if VENV_DIR.exists() and force:
        print_warn("Removing existing .venv because --force-venv was used.")
        shutil.rmtree(VENV_DIR)

    if not VENV_DIR.exists():
        print(f"Creating virtual environment: {VENV_DIR}")
        import venv

        builder = venv.EnvBuilder(with_pip=True)
        builder.create(str(VENV_DIR))
        print_ok(".venv created.")
    else:
        print_ok(".venv already exists.")

    if not py.exists():
        raise SystemExit(f"Venv Python not found: {py}")

    print_ok(f"Venv Python: {py}")
    return py


def install_python_deps(py: Path, skip_pip: bool = False) -> None:
    print_header("7. Python dependencies")

    if skip_pip:
        print_warn("Skipping pip install because --skip-pip was used.")
        return

    run([py, "-m", "pip", "install", "--upgrade", "pip"])
    run([py, "-m", "pip", "install", "-r", REQ_FILE])

    print_ok("Python dependencies installed.")


def command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def first_line_of_command(command: str) -> str | None:
    proc = run_capture([command, "-version"])
    if proc.returncode != 0:
        return None
    first = proc.stdout.splitlines()[0] if proc.stdout.splitlines() else ""
    return first.strip() or None


def check_ffmpeg(install_winget: bool = False) -> None:
    print_header("8. ffmpeg / ffprobe check")

    missing = []

    for tool in ["ffmpeg", "ffprobe"]:
        if command_exists(tool):
            version = first_line_of_command(tool)
            if version:
                print_ok(f"{tool}: {version}")
            else:
                print_ok(f"{tool}: found")
        else:
            missing.append(tool)
            print_warn(f"{tool}: not found in PATH")

    if not missing:
        return

    if install_winget and is_windows():
        if not command_exists("winget"):
            print_warn("winget is not available. Install ffmpeg manually.")
            return

        print()
        print("Trying to install ffmpeg with winget...")
        print("This may open Windows prompts.")
        run(["winget", "install", "--id", "Gyan.FFmpeg", "-e", "--source", "winget"], check=False)
        print_warn("Restart terminal after winget installation, then run installer again.")
        return

    print()
    print_warn("ffmpeg/ffprobe are required for final render.")
    print("Install ffmpeg and make sure both commands are available in PATH.")
    print()
    print("After installing, check:")
    print("  ffmpeg -version")
    print("  ffprobe -version")


def write_helper_scripts(py: Path) -> None:
    print_header("9. Helper scripts")

    if not is_windows():
        print_warn("Helper .bat scripts are Windows-only. Skipping.")
        return

    py_rel = r"%~dp0..\.venv\Scripts\python.exe"
    main_rel = r"%~dp0..\suviren_q.py"

    helpers = {
        "sq_help.bat": f"""@echo off
chcp 65001 >nul
"{py_rel}" "{main_rel}" --help
pause
""",
        "sq_inspect_zina_add_intro.bat": f"""@echo off
chcp 65001 >nul
"{py_rel}" "{main_rel}" inspect-rpp --rpp "%~dp0..\\зина книга вступление.rpp" --rpp-track "КНИГА ОЗВУЧКА" --chapter-pattern "Глава" --add-intro
pause
""",
        "sq_inspect_zina_first_chapter.bat": f"""@echo off
chcp 65001 >nul
"{py_rel}" "{main_rel}" inspect-rpp --rpp "%~dp0..\\зина книга вступление.rpp" --rpp-track "КНИГА ОЗВУЧКА" --chapter-pattern "Глава" --origin first-chapter
pause
""",
        "sq_preview.bat": f"""@echo off
chcp 65001 >nul
"{py_rel}" "{main_rel}" preview --cover "%~dp0..\\cover.png" --chapters "%~dp0..\\_suviren_q_build\\chapters.detected.json"
pause
""",
        "sq_render.bat": f"""@echo off
chcp 65001 >nul
"{py_rel}" "{main_rel}" render --audio "%~dp0..\\book.mp3" --cover "%~dp0..\\cover.png" --chapters "%~dp0..\\_suviren_q_build\\chapters.detected.json" --out "%~dp0..\\intimny_protokol_video.mp4"
pause
""",
    }

    LOCAL_DIR.mkdir(parents=True, exist_ok=True)

    for name, content in helpers.items():
        path = LOCAL_DIR / name
        path.write_text(content, encoding="utf-8", newline="\r\n")
        print_ok(f"Created helper: {path.relative_to(ROOT)}")


def smoke_test(py: Path) -> None:
    print_header("10. Smoke test")

    proc = run_capture([py, MAIN_SCRIPT, "--help"])
    if proc.returncode != 0:
        print_fail("suviren_q.py --help failed.")
        print(proc.stdout)
        print(proc.stderr)
        raise SystemExit(1)

    print_ok("suviren_q.py --help works.")
    first_lines = proc.stdout.splitlines()[:12]
    if first_lines:
        print()
        print("\n".join(first_lines))


def print_next_steps(py: Path) -> None:
    print_header("NEXT STEPS")

    if is_windows():
        py_cmd = r".\.venv\Scripts\python.exe"
    else:
        py_cmd = "./.venv/bin/python"

    print("1. Inspect REAPER project with intro:")
    print()
    print(
        f'{py_cmd} suviren_q.py inspect-rpp '
        f'--rpp "зина книга вступление.rpp" '
        f'--rpp-track "КНИГА ОЗВУЧКА" '
        f'--chapter-pattern "Глава" '
        f'--add-intro'
    )

    print()
    print("2. If final audio starts from first chapter instead of project start:")
    print()
    print(
        f'{py_cmd} suviren_q.py inspect-rpp '
        f'--rpp "зина книга вступление.rpp" '
        f'--rpp-track "КНИГА ОЗВУЧКА" '
        f'--chapter-pattern "Глава" '
        f'--origin first-chapter'
    )

    print()
    print("3. Preview panels:")
    print()
    print(
        f'{py_cmd} suviren_q.py preview '
        f'--cover "cover.png" '
        f'--chapters "_suviren_q_build/chapters.detected.json"'
    )

    print()
    print("4. Render final video:")
    print()
    print(
        f'{py_cmd} suviren_q.py render '
        f'--audio "book.mp3" '
        f'--cover "cover.png" '
        f'--chapters "_suviren_q_build/chapters.detected.json" '
        f'--out "intimny_protokol_video.mp4"'
    )

    print()
    print("Local helper .bat files are in:")
    print(f"  {LOCAL_DIR}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="install_suviren_q.py",
        description="Bootstrap installer for BOOK WUNDERWAFFE Studio.",
    )

    parser.add_argument(
        "--force-venv",
        action="store_true",
        help="Delete existing .venv and create it again.",
    )
    parser.add_argument(
        "--skip-pip",
        action="store_true",
        help="Do not install Python dependencies.",
    )
    parser.add_argument(
        "--install-ffmpeg-winget",
        action="store_true",
        help="Try to install ffmpeg with winget on Windows if missing.",
    )
    parser.add_argument(
        "--no-helpers",
        action="store_true",
        help="Do not create local helper .bat files.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    print_header(APP_FULL_NAME)
    print(f"Project root: {ROOT}")

    check_python_version()
    check_project_files()
    write_requirements()
    ensure_gitignore()
    create_dirs()

    py = create_venv(force=args.force_venv)
    install_python_deps(py, skip_pip=args.skip_pip)

    check_ffmpeg(install_winget=args.install_ffmpeg_winget)

    if not args.no_helpers:
        write_helper_scripts(py)

    smoke_test(py)
    print_next_steps(py)

    print()
    print_ok("Installer finished.")


if __name__ == "__main__":
    main()
