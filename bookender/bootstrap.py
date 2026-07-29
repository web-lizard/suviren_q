"""Idempotent startup for schema, legacy books and the existing video project."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .legacy_importer import LegacyBookImporter
from .paths import BACKUPS_DIR, LEGACY_EDITOR
from .repository import ProjectRepository
from .video_migration import LegacyVideoMigrator


def initialize_ecosystem(
    repository: ProjectRepository | None = None,
    *,
    import_legacy: bool = True,
    copy_legacy_audio: bool = True,
) -> dict[str, Any]:
    repository = repository or ProjectRepository()
    migrations = repository.initialize()
    result: dict[str, Any] = {"migrations": migrations}
    if import_legacy and LEGACY_EDITOR.exists():
        importer = LegacyBookImporter(repository)
        inventory_path = BACKUPS_DIR / "legacy_books_inventory.json"
        importer.write_inventory(inventory_path)
        result["legacy_books"] = importer.import_all(copy_audio=copy_legacy_audio)
        result["legacy_inventory"] = str(inventory_path)
    result["legacy_video"] = LegacyVideoMigrator(repository).migrate()
    result["integrity_check"] = repository.database.integrity_check()
    return result
