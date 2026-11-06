import contextlib
import io
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ringkas  # noqa: E402

WITA = ZoneInfo("Asia/Makassar")


@contextlib.contextmanager
def TempHome():
    old = os.environ.get("HOME")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["HOME"] = tmp
        try:
            yield Path(tmp)
        finally:
            if old is None:
                del os.environ["HOME"]
            else:
                os.environ["HOME"] = old


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(r if isinstance(r, str) else json.dumps(r, separators=(",", ":")) for r in rows) + "\n")


class TestConfig(unittest.TestCase):
    def test_defaults(self):
        with TempHome():
            cfg = ringkas.load_config(env={})
            self.assertEqual(cfg["provider"], "gemini")
            self.assertEqual(cfg["models"], ["gemini-flash-latest", "gemini-flash-lite-latest"])
            self.assertEqual(cfg["weekly_day"], "monday")
            self.assertEqual(cfg["max_chars_per_day"], 40000)

    def test_file_and_env_override(self):
        with TempHome():
            ringkas.data_dir().mkdir(parents=True)
            (ringkas.data_dir() / "config.json").write_text('{"weekly_day": "friday"}')
            cfg = ringkas.load_config(env={"RINGKAS_MODELS": '["a"]', "RINGKAS_MAX_CHARS_PER_DAY": "100",
                                           "RINGKAS_LANGUAGE": "id"})
            self.assertEqual((cfg["weekly_day"], cfg["models"], cfg["max_chars_per_day"], cfg["language"]),
                             ("friday", ["a"], 100, "id"))

    def test_broken_config_falls_back(self):
        with TempHome():
            ringkas.data_dir().mkdir(parents=True)
            (ringkas.data_dir() / "config.json").write_text("{broken")
            self.assertEqual(ringkas.load_config(env={})["provider"], "gemini")

    def test_timezone(self):
        self.assertEqual(ringkas.tz({"timezone": "Asia/Makassar"}), WITA)
        self.assertIsNotNone(ringkas.tz({"timezone": "auto"}))


class TestRetention(unittest.TestCase):
    def check(self, content, expected):
        with TempHome() as h:
            p = h / ".claude" / "settings.json"
            if content is not None:
                p.parent.mkdir(parents=True)
                p.write_text(content)
            self.assertEqual(ringkas.retention_days(), expected)

    def test_values(self):
        self.check(None, 29)
        self.check('{"cleanupPeriodDays": 3}', 2)
        self.check('{"cleanupPeriodDays": "x"}', 29)
        self.check('{broken', 29)
        self.check('{"cleanupPeriodDays": 0}', 29)


if __name__ == "__main__":
    unittest.main()
