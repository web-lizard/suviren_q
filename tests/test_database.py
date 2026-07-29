from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from bookender.database import BookenderDatabase, MigrationError


ROOT = Path(__file__).resolve().parents[1]


class MigrationTests(unittest.TestCase):
    def test_migrations_are_sequential_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = BookenderDatabase(
                Path(temp) / "bookender.db", ROOT / "bookender" / "migrations"
            )
            self.assertEqual(database.migrate(), [1, 2, 3])
            self.assertEqual(database.migrate(), [])
            self.assertEqual(database.integrity_check(), "ok")
            with database.connect() as connection:
                versions = [
                    row[0]
                    for row in connection.execute(
                        "SELECT version FROM schema_migrations ORDER BY version"
                    )
                ]
                self.assertEqual(versions, [1, 2, 3])

    def test_failed_migration_rolls_back_its_ddl(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            migrations = root / "migrations"
            migrations.mkdir()
            (migrations / "001_ok.sql").write_text(
                "CREATE TABLE stable(id INTEGER PRIMARY KEY);", encoding="utf-8"
            )
            (migrations / "002_broken.sql").write_text(
                "CREATE TABLE must_rollback(id INTEGER); BROKEN SQL;",
                encoding="utf-8",
            )
            database = BookenderDatabase(root / "bookender.db", migrations)
            with self.assertRaises(MigrationError):
                database.migrate()
            with closing(sqlite3.connect(database.path)) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                self.assertIn("stable", tables)
                self.assertNotIn("must_rollback", tables)
                versions = [
                    row[0]
                    for row in connection.execute(
                        "SELECT version FROM schema_migrations"
                    )
                ]
                self.assertEqual(versions, [1])


if __name__ == "__main__":
    unittest.main()
