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
import json
import os
from pathlib import Path
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
