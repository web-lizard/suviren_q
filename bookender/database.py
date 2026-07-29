"""SQLite connection and transactional schema migrations."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .logging import log_event
from .paths import DATABASE_PATH, MIGRATIONS_DIR, ensure_user_directories


class MigrationError(RuntimeError):
    pass


class ClosingConnection(sqlite3.Connection):
    """sqlite3's context manager commits but does not close on exit."""

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        try:
            return bool(super().__exit__(exc_type, exc, traceback))
        finally:
            self.close()


class BookenderDatabase:
    def __init__(
        self,
        path: Path | str = DATABASE_PATH,
        migrations_dir: Path | str = MIGRATIONS_DIR,
    ) -> None:
        self.path = Path(path)
        self.migrations_dir = Path(migrations_dir)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.path, timeout=30, factory=ClosingConnection
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def migrate(self) -> list[int]:
        ensure_user_directories()
        files = sorted(self.migrations_dir.glob("[0-9][0-9][0-9]_*.sql"))
        applied_now: list[int] = []
        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            applied = {
                int(row["version"])
                for row in connection.execute(
                    "SELECT version FROM schema_migrations"
                ).fetchall()
            }
            for file in files:
                version = int(file.name.split("_", 1)[0])
                if version in applied:
                    continue
                sql = file.read_text(encoding="utf-8")
                try:
                    # executescript commits a transaction that was started
                    # separately. Put BEGIN inside the script so every DDL
                    # statement and the migration marker share one rollback.
                    connection.executescript(f"BEGIN IMMEDIATE;\n{sql}\n")
                    connection.execute(
                        "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
                        (version, file.name),
                    )
                    connection.commit()
                except sqlite3.Error as exc:
                    connection.rollback()
                    log_event(
                        "migration_failed",
                        version=version,
                        migration=file.name,
                        error=str(exc),
                    )
                    raise MigrationError(
                        f"Migration {file.name} failed: {exc}"
                    ) from exc
                applied_now.append(version)
                log_event(
                    "migration_applied", version=version, migration=file.name
                )
        return applied_now

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def integrity_check(self) -> str:
        with self.connect() as connection:
            return str(connection.execute("PRAGMA integrity_check").fetchone()[0])
