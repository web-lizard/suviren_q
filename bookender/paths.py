"""Filesystem locations used by the project ecosystem."""

from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
USER_DATA = Path(os.environ.get("BOOKENDER_USER_DATA", ROOT / "user_data")).resolve()
DATABASE_PATH = Path(
    os.environ.get("BOOKENDER_DATABASE", USER_DATA / "bookender.db")
).resolve()
PROJECTS_DIR = USER_DATA / "projects"
LOGS_DIR = USER_DATA / "logs"
BACKUPS_DIR = USER_DATA / "backups"
MIGRATIONS_DIR = Path(__file__).with_name("migrations")
LEGACY_EDITOR = (
    ROOT
    / "editor_legacy"
    / "be2-p256w34-lizard-souverain-20260519_205739"
)


def ensure_user_directories() -> None:
    for path in (USER_DATA, PROJECTS_DIR, LOGS_DIR, BACKUPS_DIR):
        path.mkdir(parents=True, exist_ok=True)
