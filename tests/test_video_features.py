from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from suviren_q import (
    build_music_mix_filter,
    escape_drawtext_text,
    load_chapters,
    mux_master_audio,
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

    def test_caption_wrap_width_follows_the_movable_layer(self) -> None:
        text = " ".join(["длинныйфрагмент"] * 12)
        narrow = reading_caption_chunks(
            text,
            4.0,
            words_per_card=12,
            line_width=18,
        )
        wide = reading_caption_chunks(
            text,
            4.0,
            words_per_card=12,
            line_width=120,
        )
        self.assertGreater(narrow[0][2].count("\n"), wide[0][2].count("\n"))

    def test_music_mix_has_volume_three_band_eq_and_limiter(self) -> None:
        audio_filter = build_music_mix_filter(
            {"volume": 0.22, "bass": 3, "mid": -2, "treble": 4},
            20.0,
        )
        self.assertIn("volume=0.2200", audio_filter)
        self.assertIn("f=120:t=q:w=1:g=3.00", audio_filter)
        self.assertIn("f=1100:t=q:w=1:g=-2.00", audio_filter)
        self.assertIn("f=7000:t=q:w=1:g=4.00", audio_filter)
        self.assertIn("amix=inputs=2", audio_filter)
        self.assertIn("alimiter=limit=0.95", audio_filter)

    def test_music_mux_loops_and_maps_the_mixed_audio(self) -> None:
        with patch("suviren_q.run_cmd") as run:
            mux_master_audio(
                Path("video.mp4"),
                Path("voice.mp3"),
                Path("result.mp4"),
                music=Path("music.flac"),
                music_config={"enabled": True, "loop": True, "volume": 0.16},
                duration=30.0,
                dry_run=True,
            )
        command = run.call_args.args[0]
        self.assertIn("-stream_loop", command)
        self.assertIn("music.flac", command)
        self.assertIn("-filter_complex", command)
        self.assertIn("[mixed]", command)

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
