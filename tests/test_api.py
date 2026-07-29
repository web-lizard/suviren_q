from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import suviren_q_server as server
from bookender.database import BookenderDatabase
from bookender.repository import ProjectRepository
from bookender.tts import TtsService


ROOT = Path(__file__).resolve().parents[1]


class ProjectApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.user_data = Path(self.temp.name) / "user_data"
        self.user_patch = patch("bookender.repository.USER_DATA", self.user_data)
        self.user_patch.start()
        repository = ProjectRepository(
            BookenderDatabase(
                self.user_data / "bookender.db",
                ROOT / "bookender" / "migrations",
            )
        )
        repository.initialize()
        self.old_repository = server.PROJECT_REPOSITORY
        self.old_tts = server.TTS_SERVICE
        self.old_editor_path = server.EDITOR_PROJECT_PATH
        self.old_chapters_path = server.CHAPTERS_PATH
        server.PROJECT_REPOSITORY = repository
        server.TTS_SERVICE = TtsService(repository)
        server.EDITOR_PROJECT_PATH = self.user_data / "compat" / "editor-project.json"
        server.CHAPTERS_PATH = self.user_data / "compat" / "chapters.json"

    def tearDown(self) -> None:
        server.PROJECT_REPOSITORY = self.old_repository
        server.TTS_SERVICE = self.old_tts
        server.EDITOR_PROJECT_PATH = self.old_editor_path
        server.CHAPTERS_PATH = self.old_chapters_path
        self.user_patch.stop()
        self.temp.cleanup()

    def test_create_edit_switch_and_video_roundtrip(self) -> None:
        project = server.create_bookender_project(
            server.ProjectCreateRequest(
                title="API книга",
                project_kind="book",
                create_first_chapter=True,
            )
        )
        chapter = project["chapters"][0]
        saved = server.update_project_chapter(
            project["uuid"],
            chapter["id"],
            server.ChapterUpdateRequest(
                title="Новая глава", content="Персистентный текст"
            ),
        )
        self.assertEqual(saved["content"], "Персистентный текст")
        edition_data = server.create_project_video_edition(
            project["uuid"], server.VideoEditionCreateRequest(title="Видео API")
        )
        payload = edition_data["settings"]
        payload["scenes"] = [
            {"id": "api-scene", "name": "Сцена", "start": 1, "end": 5}
        ]
        saved_video = server.save_editor_project(
            payload,
            project_uuid=project["uuid"],
            edition_id=edition_data["id"],
        )
        self.assertEqual(saved_video["storage"], "sqlite")
        restored = server.open_bookender_project(project["uuid"])
        self.assertEqual(restored["chapters"][0]["content"], "Персистентный текст")
        self.assertEqual(
            restored["video_editions"][0]["settings"]["scenes"][0]["id"],
            "api-scene",
        )
        listing = server.list_bookender_projects(
            search="", kind=None, include_archived=False
        )
        self.assertEqual(listing["active_project_uuid"], project["uuid"])

    def test_render_command_includes_selected_music(self) -> None:
        server.EDITOR_PROJECT_PATH.parent.mkdir(parents=True, exist_ok=True)
        server.EDITOR_PROJECT_PATH.write_text("{}", encoding="utf-8")
        inputs = {
            "audio": Path("voice.mp3"),
            "music": Path("music.flac"),
            "cover": Path("cover.png"),
            "background": None,
            "chapters": server.CHAPTERS_PATH,
        }
        with (
            patch.object(server, "BUILD_DIR", self.user_data / "render"),
            patch.object(server, "get_export_inputs", return_value=inputs),
            patch.object(server, "load_editor_project", return_value={"theme": "violet"}),
        ):
            command = server.build_render_cmd(test_mode=True)
        self.assertIn("--music", command)
        self.assertEqual(command[command.index("--music") + 1], "music.flac")


if __name__ == "__main__":
    unittest.main()
