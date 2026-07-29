from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from bookender.database import BookenderDatabase
from bookender.repository import ProjectRepository
from bookender.tts import TtsService


ROOT = Path(__file__).resolve().parents[1]


class TtsServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.user_data = Path(self.temp.name) / "user_data"
        self.patches = [
            patch("bookender.repository.USER_DATA", self.user_data),
            patch("bookender.tts.USER_DATA", self.user_data),
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
        self.project = self.repository.create_project(
            title="TTS тест",
            create_first_chapter=True,
            voice="ru-RU-SvetlanaNeural",
        )
        self.chapter = self.repository.update_chapter(
            self.project["uuid"],
            self.project["chapters"][0]["id"],
            content="Нейтральный текст для теста озвучивания.",
        )
        self.service = TtsService(self.repository)

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    @staticmethod
    def fake_synthesize(
        text: str,
        output: Path,
        settings: dict[str, str],
        progress_callback=None,
    ) -> None:
        if progress_callback:
            progress_callback(1, 1, 1.0)
        output.write_bytes(b"ID3" + text.encode("utf-8"))

    def wait_for_job(self, job_uuid: str) -> dict:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = self.service.get_job(job_uuid)
            if job["status"] not in {"queued", "running"}:
                return job
            time.sleep(0.02)
        self.fail("TTS job did not finish")

    def test_preview_is_temporary_and_not_registered_as_chapter_audio(self) -> None:
        with (
            patch.object(self.service, "require_available"),
            patch.object(self.service, "_synthesize", self.fake_synthesize),
            patch.object(self.service, "_audio_duration", return_value=1.25),
        ):
            preview = self.service.preview(
                self.project["uuid"],
                "Проба",
                {
                    "voice": "ru-RU-DmitryNeural",
                    "rate": "+15%",
                    "pitch": "-10Hz",
                    "volume": "+0%",
                    "provider": "edge-tts",
                },
            )
        self.assertTrue(preview["temporary"])
        self.assertTrue((self.user_data / preview["file_path"]).is_file())
        restored = self.repository.get_project(
            self.project["uuid"], include_details=True
        )
        self.assertEqual(restored["audio_assets"], [])

    def test_long_text_is_split_on_readable_boundaries(self) -> None:
        text = ("Первое предложение. Второе предложение! " * 180).strip()
        chunks = self.service._split_text_chunks(text, limit=240)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(0 < len(chunk) <= 240 for chunk in chunks))
        self.assertEqual(" ".join(chunks).split(), text.split())

    def test_synthesis_reports_monotonic_chunk_progress(self) -> None:
        text = ("Нейтральное длинное предложение для индикатора. " * 130).strip()
        updates: list[tuple[int, int, float]] = []

        def fake_chunk(
            chunk: str,
            output: Path,
            settings: dict[str, str],
            progress_callback=None,
        ) -> None:
            if progress_callback:
                progress_callback(0.35)
                progress_callback(1.0)
            output.write_bytes(b"ID3" + chunk.encode("utf-8"))

        def fake_concat(parts: list[Path], output: Path, **_: object) -> None:
            output.write_bytes(b"".join(path.read_bytes() for path in parts))

        output = self.user_data / "progress.mp3"
        with (
            patch.object(TtsService, "_synthesize_chunk", side_effect=fake_chunk),
            patch.object(TtsService, "_concat_mp3_files", side_effect=fake_concat),
            patch("bookender.tts.shutil.which", return_value="ffmpeg"),
        ):
            self.service._synthesize(
                text,
                output,
                {
                    "voice": "ru-RU-DmitryNeural",
                    "rate": "+0%",
                    "pitch": "+0Hz",
                    "volume": "+0%",
                    "provider": "edge-tts",
                },
                progress_callback=lambda done, total, fraction: updates.append(
                    (done, total, fraction)
                ),
            )
        fractions = [item[2] for item in updates]
        self.assertGreater(len(updates), 4)
        self.assertEqual(fractions, sorted(fractions))
        self.assertEqual(updates[-1][0], updates[-1][1])
        self.assertEqual(updates[-1][2], 1.0)
        self.assertTrue(output.is_file())

    def test_chapter_versions_remain_isolated_and_become_stale(self) -> None:
        with (
            patch.object(self.service, "require_available"),
            patch.object(self.service, "_synthesize", self.fake_synthesize),
            patch.object(self.service, "_audio_duration", return_value=2.5),
        ):
            first = self.wait_for_job(
                self.service.queue_chapter(
                    self.project["uuid"], self.chapter["id"]
                )["uuid"]
            )
            second = self.wait_for_job(
                self.service.queue_chapter(
                    self.project["uuid"], self.chapter["id"]
                )["uuid"]
            )
        self.assertEqual(first["status"], "done")
        self.assertEqual(second["status"], "done")
        restored = self.repository.get_project(
            self.project["uuid"], include_details=True
        )
        assets = [
            item
            for item in restored["audio_assets"]
            if item["chapter_id"] == self.chapter["id"]
        ]
        self.assertEqual([item["version_number"] for item in assets], [2, 1])
        self.assertEqual(sum(bool(item["is_active"]) for item in assets), 1)
        self.assertNotEqual(assets[0]["file_path"], assets[1]["file_path"])
        self.repository.update_chapter(
            self.project["uuid"], self.chapter["id"], content="Текст изменён."
        )
        changed = self.repository.get_project(
            self.project["uuid"], include_details=True
        )
        self.assertTrue(all(item["is_stale"] for item in changed["audio_assets"]))

    def test_video_master_uses_active_chapter_audio_in_book_order(self) -> None:
        second = self.repository.create_chapter(
            self.project["uuid"],
            title="Вторая глава",
            content="Вторая нейтральная глава.",
        )
        with (
            patch.object(self.service, "require_available"),
            patch.object(self.service, "_synthesize", self.fake_synthesize),
            patch.object(self.service, "_audio_duration", return_value=2.5),
        ):
            first_job = self.wait_for_job(
                self.service.queue_chapter(
                    self.project["uuid"], self.chapter["id"]
                )["uuid"]
            )
            second_job = self.wait_for_job(
                self.service.queue_chapter(
                    self.project["uuid"], second["id"]
                )["uuid"]
            )
        self.assertEqual(first_job["status"], "done")
        self.assertEqual(second_job["status"], "done")

        def fake_concat(parts: list[Path], output: Path, **_: object) -> None:
            output.write_bytes(b"".join(path.read_bytes() for path in parts))

        with patch.object(self.service, "_concat_mp3_files", fake_concat):
            master = self.service.build_video_master(self.project["uuid"])
        self.assertEqual(len(master["source_asset_ids"]), 2)
        self.assertEqual(
            [item["chapter_id"] for item in master["chapters"]],
            [self.chapter["id"], second["id"]],
        )
        self.assertEqual(master["chapters"][0]["start_seconds"], 0)
        self.assertEqual(master["chapters"][1]["start_seconds"], 2.5)
        self.assertEqual(master["duration"], 5.0)
        self.assertTrue((self.user_data / master["file_path"]).is_file())


if __name__ == "__main__":
    unittest.main()
