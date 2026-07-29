"""Maintenance commands for the local Bookender project database."""

from __future__ import annotations

import argparse
import json

from .bootstrap import initialize_ecosystem
from .legacy_importer import LegacyBookImporter
from .paths import BACKUPS_DIR, DATABASE_PATH, LEGACY_EDITOR
from .repository import ProjectRepository


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m bookender.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init", help="Apply migrations and import local legacy data")
    subparsers.add_parser("migrate", help="Apply database migrations only")
    subparsers.add_parser("inventory", help="Discover legacy books without importing")
    subparsers.add_parser("verify", help="Run SQLite integrity checks")
    args = parser.parse_args()
    repository = ProjectRepository()
    if args.command == "init":
        result = initialize_ecosystem(repository)
    elif args.command == "migrate":
        result = {"migrations": repository.initialize(), "database": str(DATABASE_PATH)}
    elif args.command == "inventory":
        destination = BACKUPS_DIR / "legacy_books_inventory.json"
        repository.initialize()
        inventory = LegacyBookImporter(repository, LEGACY_EDITOR).write_inventory(
            destination
        )
        result = {**inventory.inventory(), "destination": str(destination)}
    else:
        repository.initialize()
        result = {
            "database": str(DATABASE_PATH),
            "integrity_check": repository.database.integrity_check(),
            "projects": len(repository.list_projects(include_archived=True)),
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
