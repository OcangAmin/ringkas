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


def urow(text, ts, **k):
    return {"type": "user", "timestamp": ts, "message": {"role": "user", "content": text}, **k}


def arow(text, ts, **k):
    return {"type": "assistant", "timestamp": ts,
            "message": {"content": [{"type": "text", "text": text}, {"type": "tool_use", "name": "Bash"}]}, **k}


class TestCollect(unittest.TestCase):
    def test_day_boundary_and_skips(self):
        with TempHome() as h:
            proj = h / ".claude" / "projects"
            write_jsonl(proj / "-home-ana-blog" / "s.jsonl", [
                urow("yesterday", "2026-11-05T15:59:00Z"),
                urow("morning", "2026-11-05T16:00:00Z"),
                '{"type":"user","timestamp":"2026-11-06T0',
                urow("side", "2026-11-06T01:00:00Z", isSidechain=True),
                {"type": "user", "timestamp": "2026-11-06T01:00:00Z",
                 "message": {"content": [{"type": "tool_result", "content": "out"}]}},
                urow("<command-name>/clear</command-name>", "2026-11-06T01:01:00Z"),
                arow("late night", "2026-11-06T15:59:59Z"),
                arow("x", "2026-11-06T02:00:00Z", isSidechain=True),
                urow("tomorrow", "2026-11-06T16:00:00Z"),
            ])
            msgs = ringkas.collect(date(2026, 11, 6), WITA, proj, [])
            self.assertEqual([(m.project, m.role, m.text) for m in msgs],
                             [("blog", "user", "morning"), ("blog", "assistant", "late night")])
            write_jsonl(proj / "-home-ana-blog" / "long.jsonl", [urow("x" * 2000, "2026-11-06T01:00:00Z")])
            self.assertTrue(all(len(m.text) <= 800 for m in ringkas.collect(date(2026, 11, 6), WITA, proj, [])))

    def test_project_label_and_ignore(self):
        self.assertEqual(ringkas.project_label("-home-ana-blog"), "blog")
        self.assertEqual(ringkas.project_label("-root-remote"), "remote")
        self.assertEqual(ringkas.project_label("plain"), "plain")
        self.assertEqual(ringkas.project_label("---"), "---")
        with TempHome() as h:
            proj = h / ".claude" / "projects"
            for name in ("-home-ana-blog", "-home-ana-secret", "-home-ana-my-shop"):
                write_jsonl(proj / name / "s.jsonl", [urow("hi " + name, "2026-11-06T01:00:00Z")])
            got = lambda ign: sorted(m.project for m in ringkas.collect(date(2026, 11, 6), WITA, proj, ign))
            self.assertEqual(got(["*blog*"]), ["secret", "shop"])
            self.assertEqual(got(["secret"]), ["blog", "shop"])
            self.assertEqual(got(["-home-ana-my-shop"]), ["blog", "secret"])


class TestFilter(unittest.TestCase):
    def test_words_and_carry_over(self):
        t = datetime(2026, 11, 6, 10, tzinfo=WITA)
        m = lambda role, text: ringkas.Msg(t, "blog", role, text)
        words = ["salary", "saldo", "PIN", "credit card"]
        for text in ["my salaries", "saldonya", "pin GPIO", "new Credit Card"]:
            self.assertEqual(ringkas.filter_sensitive([m("user", text)], words)[1], 1, text)
        for text in ["pinjam laptop", "opinion"]:
            self.assertEqual(ringkas.filter_sensitive([m("user", text)], words)[1], 0, text)
        out, n = ringkas.filter_sensitive([m("user", "my salary"), m("assistant", "it is 5000"),
                                           m("assistant", "more"), m("user", "fix the build"),
                                           m("assistant", "done")], words)
        self.assertEqual([x.text for x in out], [ringkas.MARKER, "fix the build", "done"])
        self.assertEqual(n, 3)

    def test_default_words_file(self):
        with TempHome():
            words = ringkas.load_words(ringkas.data_dir() / "sensitive-words.txt")
            self.assertIn("salary", words)
            self.assertIn("gaji", words)
            self.assertFalse(any(w.startswith("#") for w in words))


class TestRedact(unittest.TestCase):
    def test_secrets(self):
        for text, secret in [("GEMINI_API_KEY=abcdef123456", "abcdef123456"), ("token: qwe123rty", "qwe123rty"),
                             ("Authorization: Bearer abc.def.ghi", "abc.def.ghi"), ("tskey-auth-kAbC123", "kAbC123"),
                             ("--password hunter2", "hunter2"), ("-----BEGIN OPENSSH PRIVATE KEY-----", "OPENSSH"),
                             ("key AIza" + "x" * 35, "AIza"), ("ghp_" + "a" * 30, "ghp_"), ("sk-" + "b" * 20, "sk-b")]:
            self.assertNotIn(secret, ringkas.redact(text), text)

    def test_no_false_positives(self):
        for text in ["saved token 6,000 per session", "password manager", "key-only login", "Passkey 2026"]:
            self.assertEqual(ringkas.redact(text), text)


class TestMaterial(unittest.TestCase):
    def test_limit_and_format(self):
        t = datetime(2026, 11, 6, 10, tzinfo=WITA)
        many = [ringkas.Msg(t, "blog", "user", "x" * 800)] * 60
        material = ringkas.build_material(many, 40000, WITA)
        self.assertLessEqual(len(material), 40100)
        self.assertIn("more messages not included", material)
        self.assertEqual(ringkas.build_material([ringkas.Msg(t, "blog", "user", "hi")], 40000, WITA),
                         "[10:00] [blog] user: hi")


if __name__ == "__main__":
    unittest.main()
