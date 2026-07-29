from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import suviren_q_server as server
from bookender.database import BookenderDatabase
from bookender.repository import ProjectRepository


ROOT = Path(__file__).resolve().parents[1]


class BookExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.user_data = Path(self.temp.name) / "user_data"
        self.patches = [
            patch("bookender.repository.USER_DATA", self.user_data),
            patch("suviren_q_server.USER_DATA", self.user_data),
        ]
        for item in self.patches:
            item.start()
        self.repository = ProjectRepository(
            BookenderDatabase(
                self.user_data / "bookender.db",
                ROOT / "bookender" / "migrations",
            )
        )
        self.repository.initialize()
        self.old_repository = server.PROJECT_REPOSITORY
        server.PROJECT_REPOSITORY = self.repository
        self.project = self.repository.create_project(
            title="Книга: тест",
            author="Автор",
            description="Описание",
            create_first_chapter=True,
        )
        first = self.project["chapters"][0]
        self.repository.update_chapter(
            self.project["uuid"],
            first["id"],
            title="Первая / глава",
            content="Первый текст.",
        )
        self.second = self.repository.create_chapter(
            self.project["uuid"],
            title="Вторая глава",
            content="Второй текст.",
        )

    def tearDown(self) -> None:
        server.PROJECT_REPOSITORY = self.old_repository
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_complete_book_export_is_utf8_text_in_book_order(self) -> None:
        output, media_type = server.create_book_export(
            self.project["uuid"], mode="complete"
        )
        text = output.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("\ufeff"))
        self.assertLess(text.index("Первый текст."), text.index("Второй текст."))
        self.assertEqual(media_type, "text/plain; charset=utf-8")

    def test_chapter_bundle_contains_text_and_selected_media(self) -> None:
        restored = self.repository.get_project(
            self.project["uuid"], include_details=True
        )
        project_folder = restored["project_folder"]
        project_root = self.user_data / project_folder
        audio_path = project_root / "audio" / "first.mp3"
        audio_path.write_bytes(b"ID3-test-audio")
        image_path = project_root / "images" / "first.png"
        image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
        first = restored["chapters"][0]
        with self.repository.database.transaction() as connection:
            project_id = connection.execute(
                "SELECT id FROM projects WHERE uuid=?", (self.project["uuid"],)
            ).fetchone()["id"]
            connection.execute(
                """
                INSERT INTO audio_assets(
                    project_id, chapter_id, file_path, duration,
                    generation_status, voice, source_text_hash,
                    created_at, updated_at, title, version_number,
                    is_active, file_size
                ) VALUES (?, ?, ?, 1, 'ready', 'test', '', ?, ?, 'Голос', 1, 1, ?)
                """,
                (
                    project_id,
                    first["id"],
                    f"{project_folder}/audio/first.mp3",
                    "2026-07-29T00:00:00+00:00",
                    "2026-07-29T00:00:00+00:00",
                    audio_path.stat().st_size,
                ),
            )
        self.repository.add_chapter_visual_asset(
            self.project["uuid"],
            first["id"],
            file_path=f"{project_folder}/images/first.png",
            title="Иллюстрация",
        )
        output, media_type = server.create_book_export(
            self.project["uuid"], mode="chapters", include_media=True
        )
        with zipfile.ZipFile(output) as archive:
            names = archive.namelist()
            chapter_files = [name for name in names if name.endswith(".txt")]
            self.assertIn("manifest.json", names)
            self.assertEqual(len(chapter_files), 3)
            self.assertTrue(any("001 - Первая _ глава" in name for name in names))
            self.assertTrue(any("002 - Вторая глава" in name for name in names))
            self.assertTrue(any(name.endswith("/Озвучка.mp3") for name in names))
            self.assertTrue(any(name.endswith("/Изображение.png") for name in names))
        self.assertEqual(media_type, "application/zip")


if __name__ == "__main__":
    unittest.main()
