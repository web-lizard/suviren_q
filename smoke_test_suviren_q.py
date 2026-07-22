#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
PY = VENV_PY if VENV_PY.exists() else Path(sys.executable)

BUILD_DIR = ROOT / "_suviren_q_build"
CHAPTERS_JSON = BUILD_DIR / "chapters.detected.json"


class TestFail(Exception):
    pass


def line(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def ok(text: str) -> None:
    print(f"[OK] {text}")


def warn(text: str) -> None:
    print(f"[WARN] {text}")


def fail(text: str) -> None:
    print(f"[FAIL] {text}")


def normalize_cmd(cmd: list[str | Path]) -> list[str | Path]:
    if os.name == "nt" and cmd:
        first = str(cmd[0])
        found = None

        if Path(first).exists():
            found = first
        else:
            found = shutil.which(first)

        if found:
            found_path = Path(found)

            if found_path.suffix == "":
                cmd_candidate = Path(str(found_path) + ".cmd")
                bat_candidate = Path(str(found_path) + ".bat")
                if cmd_candidate.exists():
                    found_path = cmd_candidate
                elif bat_candidate.exists():
                    found_path = bat_candidate

            suffix = found_path.suffix.lower()
            if suffix in (".cmd", ".bat"):
                comspec = os.environ.get("ComSpec", "C:\\Windows\\System32\\cmd.exe")
                return [Path(comspec), "/c", found_path, *cmd[1:]]

            return [found_path, *cmd[1:]]

    return cmd


def run(cmd: list[str | Path], cwd: Path = ROOT, timeout: int = 60) -> subprocess.CompletedProcess:
    cmd = normalize_cmd(cmd)
    printable = " ".join(f'"{x}"' if " " in str(x) else str(x) for x in cmd)
    print(f"[run] {printable}")

    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}

    proc = subprocess.run(
        [str(x) for x in cmd],
        cwd=str(cwd),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        env=env,
    )

    out = proc.stdout.strip()
    if out:
        # Replace non-ASCII chars for Windows console (charmap/cp866 issues)
        safe = out.encode("ascii", "replace").decode("ascii")
        print(safe)

    if proc.returncode != 0:
        raise TestFail(f"Command failed with code {proc.returncode}: {printable}")

    return proc


def assert_exists(path: Path, label: str | None = None) -> None:
    if not path.exists():
        raise TestFail(f"Missing {label or path}: {path}")
    ok(f"Exists: {label or path.name}")


def test_required_files() -> None:
    line("1. Required files")

    required = [
        ROOT / "suviren_q.py",
        ROOT / "suviren_q_server.py",
        ROOT / "book_wunderwaffe_desktop.py",
        ROOT / "install_suviren_q.py",
        ROOT / "install_suviren_q_ui.py",
        ROOT / "requirements.txt",
        ROOT / "ui" / "package.json",
        ROOT / "ui" / "index.html",
        ROOT / "ui" / "vite.config.js",
        ROOT / "ui" / "src" / "main.js",
        ROOT / "ui" / "src" / "App.vue",
        ROOT / "ui" / "src" / "style.css",
    ]

    for path in required:
        assert_exists(path, path.relative_to(ROOT).as_posix())


def test_python_compile() -> None:
    line("2. Python syntax")

    files = [
        ROOT / "suviren_q.py",
        ROOT / "suviren_q_server.py",
        ROOT / "book_wunderwaffe_desktop.py",
        ROOT / "install_suviren_q.py",
        ROOT / "install_suviren_q_ui.py",
    ]

    run([PY, "-m", "py_compile", *files])
    ok("Python files compile")


def test_cli_help() -> None:
    line("3. CLI help")

    run([PY, ROOT / "suviren_q.py", "--help"])
    run([PY, ROOT / "suviren_q.py", "inspect-rpp", "--help"])
    run([PY, ROOT / "suviren_q.py", "preview", "--help"])
    run([PY, ROOT / "suviren_q.py", "render", "--help"])
    ok("CLI help commands work")


def find_rpp() -> Path | None:
    # The data/ project is the renderer source of truth. A legacy root-level
    # RPP is intentionally kept for reference but has fewer chapters.
    rpps = (
        sorted((ROOT / "data").glob("*.rpp"))
        + sorted((ROOT / "data").glob("*.RPP"))
        + sorted(ROOT.glob("*.rpp"))
        + sorted(ROOT.glob("*.RPP"))
    )
    if not rpps:
        return None

    preferred = [p for p in rpps if "зина" in p.name.lower()]
    return preferred[0] if preferred else rpps[0]


def find_audio() -> Path | None:
    candidates = [
        path for path in (ROOT / "data").glob("*")
        if path.suffix.lower() in {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg"}
        and path.stat().st_size < 2 * 1024 ** 3
        and ".tmp_probe" not in path.name
    ]
    preferred = [path for path in candidates if "render" in path.name.lower()]
    return max(preferred or candidates, key=lambda path: path.stat().st_size, default=None)


def test_rpp_inspection_optional() -> None:
    line("4. RPP inspection")

    rpp = find_rpp()
    if not rpp:
        warn("No .rpp file found. Skipping RPP inspection test.")
        return

    ok(f"Using RPP: {rpp.name}")

    command = [
        PY,
        ROOT / "suviren_q.py",
        "inspect-rpp",
        "--rpp",
        rpp,
        "--rpp-track",
        "КНИГА ОЗВУЧКА",
        "--chapter-pattern",
        "Глава",
        "--add-intro",
    ]
    audio = find_audio()
    if audio:
        command.extend(["--audio", audio])
    run(command, timeout=120)

    assert_exists(CHAPTERS_JSON, "_suviren_q_build/chapters.detected.json")

    data = json.loads(CHAPTERS_JSON.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise TestFail("chapters.detected.json must be a list")

    if len(data) < 30:
        raise TestFail(f"Expected at least 30 chapters, got {len(data)}")

    titles = [str(x.get("title", "")) for x in data]
    if not any("Глава" in t for t in titles):
        raise TestFail("No chapter titles containing 'Глава' found")

    ok(f"Detected chapters: {len(data)}")
    ok(f"First: {titles[0]}")
    ok(f"Last: {titles[-1]}")


def test_preview_optional() -> None:
    line("5. Preview render")

    cover_candidates = [
        ROOT / "cover.png",
        ROOT / "cover.jpg",
        ROOT / "cover.jpeg",
    ]
    cover = next((p for p in cover_candidates if p.exists()), None)

    if not cover:
        warn("No cover.png/cover.jpg found. Skipping preview test.")
        return

    if not CHAPTERS_JSON.exists():
        warn("No chapters.detected.json found. Skipping preview test.")
        return

    run([
        PY,
        ROOT / "suviren_q.py",
        "preview",
        "--cover",
        cover,
        "--chapters",
        CHAPTERS_JSON,
    ], timeout=120)

    panels_dir = BUILD_DIR / "panels"
    assert_exists(panels_dir, "_suviren_q_build/panels")

    panels = sorted(panels_dir.glob("*.png"))
    if not panels:
        raise TestFail("No preview panels generated")

    ok(f"Generated preview panels: {len(panels)}")


def test_ui_build_optional() -> None:
    line("6. Vue UI build")

    npm = shutil.which("npm")
    if not npm:
        warn("npm not found. Skipping UI build.")
        return

    if not (ROOT / "ui" / "node_modules").exists():
        warn("ui/node_modules not found. Running npm install first.")
        run(["npm", "install"], cwd=ROOT / "ui", timeout=240)

    run(["npm", "run", "build"], cwd=ROOT / "ui", timeout=240)
    assert_exists(ROOT / "ui" / "dist", "ui/dist")
    ok("Vue build works")


def main() -> int:
    print("BOOK WUNDERWAFFE Studio smoke test")
    print(f"Root: {ROOT}")
    print(f"Python: {PY}")

    tests = [
        test_required_files,
        test_python_compile,
        test_cli_help,
        test_rpp_inspection_optional,
        test_preview_optional,
        test_ui_build_optional,
    ]

    try:
        for test in tests:
            test()
    except Exception as exc:
        fail(str(exc))
        return 1

    line("RESULT")
    ok("All smoke tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
