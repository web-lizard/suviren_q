from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bookender.database import BookenderDatabase
from bookender.legacy_importer import LegacyBookImporter
from bookender.repository import ProjectRepository


ROOT = Path(__file__).resolve().parents[1]


def write_book(
    root: Path,
    slug: str,
    title: str,
    chapters: list[tuple[str, str, str]],
    *,
    saved_at: str,
    voice: str = "ru-RU-SvetlanaNeural",
) -> Path:
    path = root / "data" / "books" / slug / "book.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "title": title,
                "saved_at": saved_at,
                "tts_voice": voice,
                "chapters": [
                    {"id": identifier, "title": chapter_title, "text": text}
                    for identifier, chapter_title, text in chapters
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


class LegacyImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.legacy = self.root / "legacy"
        self.user_data = self.root / "user_data"
        self.database = BookenderDatabase(
            self.user_data / "bookender.db", ROOT / "bookender" / "migrations"
        )
        self.user_patch = patch("bookender.repository.USER_DATA", self.user_data)
        self.import_user_patch = patch(
            "bookender.legacy_importer.USER_DATA", self.user_data
        )
        self.user_patch.start()
        self.import_user_patch.start()
        self.repository = ProjectRepository(self.database)
        self.repository.initialize()

    def tearDown(self) -> None:
        self.import_user_patch.stop()
        self.user_patch.stop()
        self.temp.cleanup()

    def test_discovers_multiple_inactive_books_and_preserves_unicode_order(self) -> None:
        write_book(
            self.legacy,
            "russian",
            "Русская книга",
            [
                ("intro", "Введение", ""),
                ("one", "Глава ёлка", "Большой текст " * 5000),
            ],
            saved_at="2026-01-02T00:00:00+00:00",
        )
        write_book(
            self.legacy,
            "french",
            "Livre français",
            [
                ("a", "Épilogue", "Ça va — déjà vu"),
                ("b", "Fin", "œuvre"),
            ],
            saved_at="2026-01-03T00:00:00+00:00",
            voice="fr-FR-DeniseNeural",
        )
        (self.legacy / "data" / "current_book.txt").write_text(
            "russian", encoding="utf-8"
        )
        broken = self.legacy / "data" / "backups" / "book_broken.json"
        broken.parent.mkdir(parents=True)
        broken.write_text("{broken", encoding="utf-8")

        importer = LegacyBookImporter(self.repository, self.legacy)
        discovery = importer.discover()
        self.assertEqual(len(discovery.books), 2)
        self.assertTrue(discovery.damaged_files)
        report = importer.import_all(copy_audio=False)
        self.assertEqual(report["imported"], 2)
        self.assertEqual(report["integrity_check"], "ok")
        projects = self.repository.list_projects()
        self.assertEqual(len(projects), 2)
        french = next(item for item in projects if item["title"] == "Livre français")
        restored = self.repository.get_project(french["uuid"], include_details=True)
        self.assertEqual(
            [item["title"] for item in restored["chapters"]],
            ["Épilogue", "Fin"],
        )
        self.assertEqual(restored["chapters"][0]["content"], "Ça va — déjà vu")
        second = importer.import_all(copy_audio=False)
        self.assertEqual(second["imported"], 0)
        self.assertEqual(second["skipped"], 2)

    def test_changed_source_never_overwrites_local_edits(self) -> None:
        source = write_book(
            self.legacy,
            "safe",
            "Безопасная книга",
            [("one", "Глава", "Исходный текст")],
            saved_at="2026-01-01T00:00:00+00:00",
        )
        importer = LegacyBookImporter(self.repository, self.legacy)
        first = importer.import_all(copy_audio=False)
        project_id = first["books"][0]["project_id"]
        with self.database.connect() as connection:
            project_uuid = connection.execute(
                "SELECT uuid FROM projects WHERE id=?", (project_id,)
            ).fetchone()[0]
        project = self.repository.get_project(project_uuid, include_details=True)
        self.repository.update_chapter(
            project_uuid, project["chapters"][0]["id"], content="Локальная правка"
        )
        value = json.loads(source.read_text(encoding="utf-8"))
        value["chapters"][0]["text"] = "Новая серверная версия"
        source.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        second = importer.import_all(copy_audio=False)
        self.assertEqual(second["conflicts"], 1)
        restored = self.repository.get_project(project_uuid, include_details=True)
        self.assertEqual(restored["chapters"][0]["content"], "Локальная правка")


if __name__ == "__main__":
    unittest.main()
