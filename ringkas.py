#!/usr/bin/env python3
"""ringkas — daily & weekly notes of your Claude Code sessions, summarized by a free model.

Commands:
  ringkas.py status                          last summarized day, last result, missing days
  ringkas.py run --date YYYY-MM-DD [--dry-run]
                                             summarize one day (dry run prints what would be sent)
  ringkas.py run-pending                     summarize every pending day, then the weekly rollup
  ringkas.py wake                            used by the SessionStart hook: starts run-pending in
                                             the background and exits silently
"""
import datetime as dt
import fnmatch
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import NamedTuple
from zoneinfo import ZoneInfo

DEFAULTS = {
    "provider": "gemini",
    "models": ["gemini-flash-latest", "gemini-flash-lite-latest"],
    "openai_base_url": "",
    "openai_model": "",
    "language": "auto",
    "timezone": "auto",
    "weekly_day": "monday",
    "ignore_projects": [],
    "max_chars_per_day": 40000,
}
DEFAULT_RETENTION = 30  # Claude Code's default cleanupPeriodDays


def home():
    return Path(os.environ.get("HOME", "~")).expanduser()


def data_dir():
    return home() / ".claude" / "ringkas"


def state_dir():
    return data_dir() / "state"


def load_config(env=os.environ):
    """DEFAULTS, then ~/.claude/ringkas/config.json, then RINGKAS_<KEY> environment variables."""
    cfg = dict(DEFAULTS)
    try:
        user = json.loads((data_dir() / "config.json").read_text())
        if isinstance(user, dict):
            cfg.update({k: v for k, v in user.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    for key, default in DEFAULTS.items():
        raw = env.get(f"RINGKAS_{key.upper()}")
        if raw is None:
            continue
        if isinstance(default, str):
            cfg[key] = raw
        else:
            try:
                cfg[key] = json.loads(raw)
            except ValueError:
                pass
    return cfg


def tz(cfg):
    name = cfg.get("timezone", "auto")
    return dt.datetime.now().astimezone().tzinfo if name in ("", "auto") else ZoneInfo(name)


def retention_days(settings_path=None):
    """How many past days still have transcripts: cleanupPeriodDays minus one day of safety margin."""
    days = DEFAULT_RETENTION
    try:
        value = json.loads(Path(settings_path or home() / ".claude" / "settings.json").read_text())["cleanupPeriodDays"]
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            days = value
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return max(1, days - 1)


# ---------------------------------------------------------------- transcripts

MAX_PER_MESSAGE = 800
MARKER = "(sensitive topic, skipped)"


class Msg(NamedTuple):
    time: dt.datetime
    project: str
    role: str  # "user" | "assistant"
    text: str


def _blocks_text(content):
    if isinstance(content, list):
        content = "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return content.strip() if isinstance(content, str) else ""


def user_text(d):
    """Text the user actually typed, or None (tool results, local commands, reminders, interruptions)."""
    if d.get("type") != "user" or d.get("isMeta") or d.get("isSidechain"):
        return None
    text = _blocks_text((d.get("message") or {}).get("content"))
    if not text or text.startswith(("<", "[Request interrupted")) or "[SYSTEM NOTIFICATION" in text:
        return None
    return text


def assistant_text(d):
    """Assistant reply text without tool calls, or None."""
    if d.get("type") != "assistant" or d.get("isSidechain"):
        return None
    return _blocks_text((d.get("message") or {}).get("content")) or None


def project_label(folder_name):
    """Claude Code stores /home/ana/blog as -home-ana-blog; the last segment is a readable label."""
    parts = [p for p in folder_name.split("-") if p]
    return parts[-1] if parts else folder_name


def collect(day, tzinfo, projects_dir, ignore):
    """All conversation messages of `day` (local time) across projects, oldest first."""
    start = dt.datetime.combine(day, dt.time(), tzinfo)
    end = start + dt.timedelta(days=1)
    found = set()
    for folder in sorted(Path(projects_dir).glob("*")):
        if not folder.is_dir():
            continue
        label = project_label(folder.name)
        if any(fnmatch.fnmatch(folder.name, pat) or fnmatch.fnmatch(label, pat) for pat in ignore):
            continue
        for f in folder.glob("*.jsonl"):
            if f.stat().st_mtime < start.timestamp():
                continue
            with open(f, errors="replace") as fh:
                for line in fh:
                    if '"type":"user"' not in line and '"type":"assistant"' not in line:
                        continue
                    try:
                        d = json.loads(line)
                        when = dt.datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")).astimezone(tzinfo)
                    except (ValueError, KeyError, TypeError, AttributeError):
                        continue  # partial line of a transcript that is still being written
                    if not start <= when < end:
                        continue
                    text, role = user_text(d), "user"
                    if text is None:
                        text, role = assistant_text(d), "assistant"
                    if text:
                        found.add(Msg(when, label, role, text[:MAX_PER_MESSAGE]))
    return sorted(found)


# ---------------------------------------------------------------- privacy

DEFAULT_WORDS = """# ringkas: messages containing any of these words/phrases are NEVER sent to the summarizer.
# One per line, whole word, case-insensitive. Edit freely.
# Credentials
password
passcode
PIN
OTP
CVV
seed phrase
private key
kata sandi
# Money
bank account
account number
routing number
IBAN
credit card
salary
balance
loan
debt
invoice amount
rekening
saldo
gaji
utang
hutang
pinjaman
cicilan
tagihan
mutasi
transfer
# Health
diagnosis
medication
blood pressure
heart rate
weight
detak jantung
tekanan darah
berat badan
gula darah
"""


def load_words(path):
    path = Path(path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_WORDS)
    return [w.strip() for w in path.read_text().splitlines() if w.strip() and not w.strip().startswith("#")]


def filter_sensitive(msgs, words):
    """Replace messages containing a sensitive word (plus Indonesian/English suffixes) with MARKER.
    Assistant replies after a filtered user message are filtered too, until the next user message."""
    def variants(w):  # "salary" also matches "salaries"
        return [re.escape(w)] + ([re.escape(w[:-1]) + "ies"] if w.lower().endswith("y") else [])

    pattern = re.compile("|".join(rf"(?<!\w)(?:{'|'.join(variants(w))})(?:nya|ku|mu|an|lah|kah|s|es)?(?!\w)"
                                  for w in words), re.IGNORECASE) if words else None
    out, skipped, carry = [], 0, False
    for m in msgs:
        hit = bool(pattern and pattern.search(m.text))
        if m.role == "user":
            carry = hit
        if hit or (m.role == "assistant" and carry):
            skipped += 1
            if not (out and out[-1].text == MARKER):
                out.append(m._replace(text=MARKER))
        else:
            out.append(m)
    return out, skipped


_SECRETS = [
    (re.compile(r"-----BEGIN [A-Z ]+-----.*?(-----END [A-Z ]+-----|$)", re.DOTALL), "▒"),
    (re.compile(r"sk-[A-Za-z0-9_-]{16,}"), "▒"),
    (re.compile(r"AIza[0-9A-Za-z_-]{30,}"), "▒"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "▒"),
    (re.compile(r"tskey-[A-Za-z0-9-]+"), "▒"),
    (re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+"), "▒"),
    (re.compile(r"(Bearer|Basic)\s+\S+", re.IGNORECASE), r"\1 ▒"),
    (re.compile(r"(\w*(?:key|token|secret|password|passwd|pass|sandi|kunci)\w*)(\s*[:=]\s*)(\S+)", re.IGNORECASE),
     r"\1\2▒"),
    (re.compile(r"(--?(?:password|pass|token|key|secret)\s+)(\S+)", re.IGNORECASE), r"\1▒"),
]


def redact(text):
    for pattern, repl in _SECRETS:
        text = pattern.sub(repl, text)
    return text


def build_material(msgs, max_chars, tzinfo):
    lines, total, left = [], 0, 0
    for m in msgs:
        line = f"[{m.time.astimezone(tzinfo):%H:%M}] [{m.project}] {m.role}: {m.text}"
        if total + len(line) > max_chars:
            left += 1
            continue
        lines.append(line)
        total += len(line) + 1
    if left:
        lines.append(f"(… {left} more messages not included)")
    return "\n".join(lines)


# ---------------------------------------------------------------- summarizers

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class NoKeyError(Exception):
    """No API key / endpoint configured for the chosen provider."""


class SummarizerError(Exception):
    """Every model failed."""


def http_post(url, headers, body, timeout):
    """(status, parsed JSON or None). Network errors and timeouts give (0, None)."""
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"content-type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    except (OSError, ValueError):
        return 0, None
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, None


def _skip_seconds(status):
    if status == 429:
        return 6 * 3600
    if status in (400, 403, 404):
        return 24 * 3600
    return 30 * 60  # 5xx, timeout, network


def summarize(prompt, cfg, *, env=os.environ, post=http_post, now=time.time):
    if cfg.get("provider") == "openai":
        base = (cfg.get("openai_base_url") or "").rstrip("/")
        if not base:
            raise NoKeyError("set openai_base_url (e.g. http://localhost:11434/v1)")
        headers = {"Authorization": f"Bearer {env['OPENAI_API_KEY']}"} if env.get("OPENAI_API_KEY") else {}
        status, data = post(f"{base}/chat/completions", headers,
                            {"model": cfg.get("openai_model"), "messages": [{"role": "user", "content": prompt}]}, 180)
        try:
            text = data["choices"][0]["message"]["content"].strip()
        except (TypeError, KeyError, IndexError, AttributeError):
            text = ""
        if status != 200 or not text:
            raise SummarizerError(f"openai-compatible endpoint: HTTP {status}")
        return text

    key = env.get("GEMINI_API_KEY")
    if not key:
        raise NoKeyError("set GEMINI_API_KEY (free key: https://aistudio.google.com/apikey)")
    skip_file = state_dir() / "models.json"
    try:
        skip = json.loads(skip_file.read_text())
    except (OSError, ValueError):
        skip = {}
    models = list(cfg.get("models") or DEFAULTS["models"])
    order = [m for m in models if skip.get(m, 0) <= now()] or models
    reasons = []
    for model in order:
        status, data = post(GEMINI_URL.format(model=model), {"x-goog-api-key": key},
                            {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}, 90)
        if status == 200:
            try:
                text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"]).strip()
            except (TypeError, KeyError, IndexError, AttributeError):
                text = ""
            if text:
                if skip.pop(model, None) is not None:
                    _write_json(skip_file, skip)
                return text
            reasons.append(f"{model}: empty answer")
            continue
        skip[model] = now() + _skip_seconds(status)
        _write_json(skip_file, skip)
        reasons.append(f"{model}: HTTP {status or 'timeout/network'}")
    raise SummarizerError("; ".join(reasons))


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
