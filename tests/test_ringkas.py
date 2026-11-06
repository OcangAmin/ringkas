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


class FakePost:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, headers, body))
        return self.replies.pop(0)


def gemini_ok(text):
    return 200, {"candidates": [{"content": {"parts": [{"text": text}]}}]}


class TestSummarize(unittest.TestCase):
    def test_no_key(self):
        with TempHome():
            post = FakePost([])
            with self.assertRaises(ringkas.NoKeyError):
                ringkas.summarize("p", ringkas.load_config(env={}), env={}, post=post)
            self.assertEqual(post.calls, [])

    def test_model_ladder_and_skip_memory(self):
        with TempHome():
            cfg = ringkas.load_config(env={})
            post = FakePost([(429, {}), gemini_ok("ok"), gemini_ok("again")])
            self.assertEqual(ringkas.summarize("p", cfg, env={"GEMINI_API_KEY": "k"}, post=post, now=lambda: 1000), "ok")
            self.assertIn("gemini-flash-latest:generateContent", post.calls[0][0])
            self.assertEqual(post.calls[0][1]["x-goog-api-key"], "k")
            self.assertIn("gemini-flash-lite-latest", post.calls[1][0])
            skip = json.loads((ringkas.state_dir() / "models.json").read_text())
            self.assertEqual(skip["gemini-flash-latest"], 1000 + 6 * 3600)
            ringkas.summarize("p", cfg, env={"GEMINI_API_KEY": "k"}, post=post, now=lambda: 2000)
            self.assertIn("gemini-flash-lite-latest", post.calls[2][0])

    def test_blocked_and_broken(self):
        with TempHome():
            cfg = ringkas.load_config(env={})
            post = FakePost([(200, {"promptFeedback": {"blockReason": "SAFETY"}}), (0, None)])
            with self.assertRaises(ringkas.SummarizerError):
                ringkas.summarize("p", cfg, env={"GEMINI_API_KEY": "k"}, post=post, now=lambda: 1000)
            skip = json.loads((ringkas.state_dir() / "models.json").read_text())
            self.assertNotIn("gemini-flash-latest", skip)  # blocked answer: not the model's fault
            self.assertEqual(skip["gemini-flash-lite-latest"], 1000 + 1800)

    def test_openai_compatible(self):
        with TempHome():
            cfg = dict(ringkas.load_config(env={}), provider="openai", openai_base_url="http://x/v1/",
                       openai_model="llama3.1")
            post = FakePost([(200, {"choices": [{"message": {"content": "hai"}}]})])
            self.assertEqual(ringkas.summarize("p", cfg, env={}, post=post), "hai")
            url, headers, body = post.calls[0]
            self.assertEqual(url, "http://x/v1/chat/completions")
            self.assertNotIn("Authorization", headers)
            self.assertEqual(body["model"], "llama3.1")
            post = FakePost([(200, {"choices": [{"message": {"content": "x"}}]})])
            ringkas.summarize("p", cfg, env={"OPENAI_API_KEY": "s"}, post=post)
            self.assertEqual(post.calls[0][1]["Authorization"], "Bearer s")
            with self.assertRaises(ringkas.NoKeyError):
                ringkas.summarize("p", dict(cfg, openai_base_url=""), env={}, post=post)
            with self.assertRaises(ringkas.SummarizerError):
                ringkas.summarize("p", cfg, env={}, post=FakePost([(500, None)]))


def make_day(h, text="fix the build", ts="2026-11-06T02:00:00Z", project="-home-ana-blog"):
    write_jsonl(h / ".claude" / "projects" / project / "s.jsonl", [urow(text, ts), arow("done, tests pass", ts)])


def wita_cfg(**k):
    return dict(ringkas.load_config(env={}), timezone="Asia/Makassar", **k)


class FakeSummarizer:
    def __init__(self, answer="# x\n## Done\n- [blog] fixed the build"):
        self.answer, self.prompts = answer, []

    def __call__(self, prompt, cfg):
        self.prompts.append(prompt)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


class TestDaily(unittest.TestCase):
    def test_writes_note(self):
        with TempHome() as h:
            make_day(h)
            write_jsonl(h / ".claude" / "projects" / "-home-ana-blog" / "t.jsonl",
                        [urow("my salary is low", "2026-11-06T03:00:00Z")])
            fake = FakeSummarizer("```markdown\n# whatever\n## Done\n- [blog] fixed the build\n```")
            path = ringkas.summarize_day(date(2026, 11, 6), wita_cfg(), summarizer=fake)
            self.assertEqual(path, ringkas.data_dir() / "daily" / "2026-11-06.md")
            self.assertEqual(path.read_text(), "# 2026-11-06 (Friday)\n## Done\n- [blog] fixed the build\n")
            self.assertIn("<conversation>", fake.prompts[0])
            self.assertIn("] [blog] user: fix the build", fake.prompts[0])
            self.assertNotIn("salary", fake.prompts[0])

    def test_dry_run_empty_and_bad_answer(self):
        with TempHome() as h:
            make_day(h)
            fake = FakeSummarizer()
            material = ringkas.summarize_day(date(2026, 11, 6), wita_cfg(), summarizer=fake, dry_run=True)
            self.assertIn("fix the build", material)
            self.assertEqual(fake.prompts, [])
            self.assertIsNone(ringkas.summarize_day(date(2026, 11, 1), wita_cfg(), summarizer=fake))
            with self.assertRaises(ringkas.SummarizerError):
                ringkas.summarize_day(date(2026, 11, 6), wita_cfg(), summarizer=FakeSummarizer("sorry"))
            self.assertFalse((ringkas.data_dir() / "daily" / "2026-11-06.md").exists())


class TestDue(unittest.TestCase):
    def test_due_days(self):
        w = lambda *a: datetime(*a, tzinfo=WITA)
        due = lambda now, done=(), attempts=None, window=29: ringkas.due_days(now, set(done), attempts or {}, window)
        self.assertNotIn(date(2026, 11, 6), due(w(2026, 11, 7, 0, 29))[0])
        self.assertIn(date(2026, 11, 6), due(w(2026, 11, 7, 0, 30))[0])
        self.assertEqual(len(due(w(2026, 11, 7, 9))[0]), 29)
        t = w(2026, 11, 7, 9).timestamp()
        self.assertNotIn(date(2026, 11, 6), due(w(2026, 11, 7, 9), attempts={"2026-11-06": {"time": t - 5400, "n": 2}})[0])
        self.assertIn(date(2026, 11, 6), due(w(2026, 11, 7, 9), attempts={"2026-11-06": {"time": t - 5400, "n": 1}})[0])
        missing = due(w(2026, 11, 7, 9), done=[date(2026, 10, 1)], window=2)[1]
        self.assertEqual((missing[0], missing[-1]), (date(2026, 10, 8), date(2026, 11, 4)))
        self.assertEqual(due(w(2026, 11, 7, 9), window=2)[1], [date(2026, 11, 4)])


class TestRunPending(unittest.TestCase):
    def test_no_key(self):
        with TempHome() as h:
            make_day(h)
            os.environ.pop("GEMINI_API_KEY", None)
            ringkas.run_pending(datetime(2026, 11, 7, 9, tzinfo=WITA), weekly=False)
            self.assertIn("no API key", (ringkas.state_dir() / "last-result").read_text())
            self.assertFalse((ringkas.state_dir() / "attempts.json").exists())

    def test_lock_and_no_transcripts(self):
        with TempHome() as h:
            (h / ".claude").mkdir()
            (h / ".claude" / "settings.json").write_text('{"cleanupPeriodDays": 3}')
            ringkas.data_dir().mkdir(parents=True)
            (ringkas.data_dir() / "config.json").write_text('{"timezone": "Asia/Makassar"}')
            fake = FakeSummarizer()
            ringkas.state_dir().mkdir(parents=True)
            (ringkas.state_dir() / "lock").write_text("1")
            ringkas.run_pending(datetime(2026, 11, 7, 9, tzinfo=WITA), summarizer=fake, weekly=False)
            self.assertEqual(fake.prompts, [])
            (ringkas.state_dir() / "lock").unlink()
            make_day(h)  # transcript written now: counts as present for every recent day
            os.utime(next((h / ".claude" / "projects").rglob("*.jsonl")), (0, 0))  # pretend it is old
            ringkas.run_pending(datetime(2026, 11, 7, 9, tzinfo=WITA), summarizer=fake, weekly=False)
            missing = (ringkas.state_dir() / "missing").read_text()
            self.assertIn("2026-11-06\tno transcripts", missing)
            self.assertFalse((ringkas.state_dir() / "lock").exists())

    def test_failure_then_success(self):
        with TempHome() as h:
            (h / ".claude").mkdir()
            (h / ".claude" / "settings.json").write_text('{"cleanupPeriodDays": 2}')
            ringkas.data_dir().mkdir(parents=True)
            (ringkas.data_dir() / "config.json").write_text('{"timezone": "Asia/Makassar"}')
            make_day(h)
            now = datetime(2026, 11, 7, 9, tzinfo=WITA)
            ringkas.run_pending(now, summarizer=FakeSummarizer(ringkas.SummarizerError("429")), weekly=False)
            attempts = json.loads((ringkas.state_dir() / "attempts.json").read_text())
            self.assertEqual(attempts["2026-11-06"]["n"], 1)
            ringkas.run_pending(now.replace(hour=10, minute=1), summarizer=FakeSummarizer(), weekly=False)
            self.assertTrue((ringkas.data_dir() / "daily" / "2026-11-06.md").exists())
            self.assertIn("2026-11-06", (ringkas.state_dir() / "done").read_text())
            self.assertNotIn("2026-11-06", json.loads((ringkas.state_dir() / "attempts.json").read_text()))


class TestCli(unittest.TestCase):
    def test_status(self):
        with TempHome():
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(ringkas.main(["status"]), 0)
            self.assertIn("Last summarized", out.getvalue())


if __name__ == "__main__":
    unittest.main()
