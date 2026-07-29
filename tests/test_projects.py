from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bookender.database import BookenderDatabase
from bookender.repository import ProjectRepository


ROOT = Path(__file__).resolve().parents[1]


class ProjectRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.user_data = Path(self.temp.name) / "user_data"
        self.database = BookenderDatabase(
            self.user_data / "bookender.db", ROOT / "bookender" / "migrations"
        )
        self.user_patch = patch("bookender.repository.USER_DATA", self.user_data)
        self.backup_patch = patch(
            "bookender.repository.BACKUPS_DIR", self.user_data / "backups"
        )
        self.user_patch.start()
        self.backup_patch.start()
        self.repository = ProjectRepository(self.database)
        self.repository.initialize()

    def tearDown(self) -> None:
        self.backup_patch.stop()
        self.user_patch.stop()
        self.temp.cleanup()

    def test_projects_keep_books_settings_and_timelines_isolated(self) -> None:
        project_a = self.repository.create_project(
            title="Книга A", create_first_chapter=True, voice="ru-RU-SvetlanaNeural"
        )
        project_b = self.repository.create_project(
            title="Книга B", create_first_chapter=True, voice="ru-RU-DmitryNeural"
        )
        chapter_a = project_a["chapters"][0]
        chapter_b = project_b["chapters"][0]
        self.repository.update_chapter(
            project_a["uuid"], chapter_a["id"], content="Текст только A"
        )
        self.repository.update_chapter(
            project_b["uuid"], chapter_b["id"], content="Texte français — seulement B"
        )
        edition_a = self.repository.create_video_edition(project_a["uuid"])
        edition_b = self.repository.create_video_edition(project_b["uuid"])
        payload_a = edition_a["settings"]
        payload_a["scenes"] = [{"id": "a", "name": "A", "start": 0, "end": 10}]
        self.repository.save_video_edition(
            project_a["uuid"], payload_a, edition_id=edition_a["id"]
        )
        payload_b = edition_b["settings"]
        payload_b["scenes"] = [{"id": "b", "name": "B", "start": 20, "end": 30}]
        self.repository.save_video_edition(
            project_b["uuid"], payload_b, edition_id=edition_b["id"]
        )

        restored_a = self.repository.open_project(project_a["uuid"])
        restored_b = self.repository.open_project(project_b["uuid"])
        self.assertEqual(restored_a["chapters"][0]["content"], "Текст только A")
        self.assertIn("français", restored_b["chapters"][0]["content"])
        self.assertEqual(
            restored_a["video_editions"][0]["settings"]["scenes"][0]["id"], "a"
        )
        self.assertEqual(
            restored_b["video_editions"][0]["settings"]["scenes"][0]["id"], "b"
        )
        self.assertEqual(
            self.repository.active_project_uuid(), project_b["uuid"]
        )

    def test_reorder_archive_duplicate_and_backup(self) -> None:
        project = self.repository.create_project(title="Порядок")
        chapters = [
            self.repository.create_chapter(project["uuid"], title=f"Глава {index}")
            for index in range(3)
        ]
        order = [chapters[2]["id"], chapters[0]["id"], chapters[1]["id"]]
        self.repository.reorder_chapters(project["uuid"], order)
        self.repository.archive_chapter(project["uuid"], chapters[0]["id"])
        restored = self.repository.get_project(project["uuid"], include_details=True)
        self.assertEqual(
            [item["id"] for item in restored["chapters"]],
            [chapters[2]["id"], chapters[1]["id"]],
        )
        duplicate = self.repository.duplicate_project(project["uuid"])
        self.assertEqual(len(duplicate["chapters"]), 2)
        backup = self.repository.backup_project(project["uuid"])
        self.assertTrue((backup / "project.json").is_file())
        self.assertTrue((backup / "manifest.json").is_file())


if __name__ == "__main__":
    unittest.main()
