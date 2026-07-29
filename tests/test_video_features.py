from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from suviren_q import (
    escape_drawtext_text,
    load_chapters,
    reading_caption_chunks,
)


class VideoBookFeatureTests(unittest.TestCase):
    def test_caption_chunks_cover_the_whole_chapter(self) -> None:
        chunks = reading_caption_chunks(
            " ".join(f"слово{index}" for index in range(31)),
            12.0,
            words_per_card=10,
        )
        self.assertEqual(len(chunks), 4)
        self.assertEqual(chunks[0][0], 0)
        self.assertEqual(chunks[-1][1], 12.0)
        self.assertTrue(all(start < end for start, end, _ in chunks))
        self.assertIn(r"\:", escape_drawtext_text("реплика: тест"))

    def test_chapter_json_preserves_text_and_image(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chapters.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "title": "Глава",
                            "start_seconds": 0,
                            "end_seconds": 3,
                            "text": "Текст на экране",
                            "image_path": "chapter.png",
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            chapter = load_chapters(path)[0]
        self.assertEqual(chapter.text, "Текст на экране")
        self.assertEqual(chapter.image_path, "chapter.png")


if __name__ == "__main__":
    unittest.main()
