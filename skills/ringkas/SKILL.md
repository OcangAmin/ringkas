---
name: ringkas
description: Recall past Claude Code work from ringkas daily/weekly notes. Use when the user asks what was done yesterday, last week or on a date, or to continue where they left off ("kemarin kita ngapain", "minggu lalu", "lanjutkan yang kemarin").
---

# ringkas: recall past sessions

Notes are written automatically by the ringkas plugin (one file per day across all projects, rolled up weekly):

- Yesterday or a specific day: `~/.claude/ringkas/daily/YYYY-MM-DD.md`
- Earlier weeks: `~/.claude/ringkas/weekly/*.md` (named after the rollup day; daily notes of that week are deleted)

Steps:
1. Work out the date(s) the user means (local time) and read the matching file(s). List the folders when unsure.
2. If nothing is there, run `python3 "${CLAUDE_PLUGIN_ROOT}/ringkas.py" status` and tell the user what it says
   (no API key, not summarized yet, or day not recorded).
3. Answer from the notes, citing the date.

Keep in mind:
- Notes are AI summaries. Check files, git history or commands before acting on a detail.
- Sensitive topics (money, health, credentials) are skipped on purpose; they will not be in the notes.
