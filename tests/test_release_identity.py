from __future__ import annotations

import json
import unittest
from pathlib import Path

import suviren_q
import suviren_q_server


ROOT = Path(__file__).resolve().parents[1]


class ReleaseIdentityTests(unittest.TestCase):
    def test_product_name_and_version_are_synchronized(self) -> None:
        self.assertEqual(suviren_q_server.APP_NAME, "Book Wunderwaffe Studio")
        self.assertEqual(suviren_q_server.APP_VERSION, "3.0.0")
        self.assertEqual(suviren_q.APP_VERSION, "3.0.0")
        self.assertEqual(
            suviren_q.APP_TITLE,
            "Book Wunderwaffe Studio 3.0.0",
        )

        package = json.loads(
            (ROOT / "ui" / "package.json").read_text(encoding="utf-8")
        )
        self.assertEqual(package["name"], "book-wunderwaffe-studio")
        self.assertEqual(package["version"], "3.0.0")

        interface = (ROOT / "ui" / "src" / "App.vue").read_text(encoding="utf-8")
        self.assertIn("BOOK WUNDERWAFFE STUDIO", interface)
        self.assertIn("backend.version || '3.0.0'", interface)


if __name__ == "__main__":
    unittest.main()
