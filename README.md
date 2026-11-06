# ringkas — Claude Code remembers yesterday. Zero Claude tokens.

[![tests](https://github.com/OcangAmin/ringkas/actions/workflows/test.yml/badge.svg)](https://github.com/OcangAmin/ringkas/actions/workflows/test.yml)
![license](https://img.shields.io/badge/license-MIT-blue)
![python](https://img.shields.io/badge/python-3.9%2B-blue)

**English** · [Bahasa Indonesia](README.id.md)

*ringkas* (Indonesian for "concise") turns your Claude Code sessions into short daily and weekly notes, written by a **free** model (Gemini, or a local model through Ollama). Ask *"what did we do yesterday?"* and Claude reads the note instead of guessing.

- **Zero Claude tokens for summarizing.** Your Claude quota is for work, not for bookkeeping.
- **Nothing injected into your sessions.** Notes are read only when you ask. Cost per session: the skill's one-line description (~60 tokens).
- **No daemon, no cron.** One SessionStart hook that returns instantly and catches up on any missed days in the background.
- **Privacy first.** Only conversation text is summarized (no tool output, no files read by tools); messages about money, health or credentials are skipped; API keys and tokens are redacted.

## The problem

Every new Claude Code session starts from zero. Memory plugins fix that, but most of them summarize with Claude itself and load their memory into every session, so you pay for remembering on every single prompt.

ringkas does the remembering once a day with a free model and keeps the notes on disk until you need them.

## What you get

`~/.claude/ringkas/daily/2026-11-06.md` (example with made-up projects):

```markdown
# 2026-11-06 (Friday)
## Done
- [shop-api] Fixed the checkout race condition: added a row lock in `orders/service.py`, tests pass
- [shop-api] Added `scripts/backfill_totals.py` and ran it on staging
- [blog] Drafted "Postgres locks in 5 minutes", moved images to `static/img/locks/`
## Decisions
- [shop-api] Keep retries in the queue worker, not in the HTTP handler
## Open
- [blog] Proofread and publish on Monday
## Skipped
- 1 sensitive part(s)
```

Next morning:

> **You:** where did we leave off yesterday?
> **Claude:** *(reads the note)* On 6 Nov you fixed the checkout race in shop-api and ran the backfill on staging. The blog post on Postgres locks is drafted; proofreading and publishing were planned for Monday.

Every week (Monday by default) each finished week's daily notes are merged into one `weekly/<date>.md` and the dailies are removed, so the folder stays small.

## How it works

```
 Claude Code session starts
          │
          ▼
 1. hook: ringkas.py wake  ──► returns instantly, prints nothing
          │ (background)
          ▼
 2. finds days not yet summarized (within your transcript retention window)
          │
          ▼
 3. per day: collect conversation text of all projects → skip sensitive topics
    → redact secrets → summarize with Gemini / Ollama → daily/YYYY-MM-DD.md
          │
          ▼
 4. on your weekly day: daily notes → weekly/YYYY-MM-DD.md, dailies removed
```

When you ask about earlier work, the `ringkas` skill tells Claude which note to open.

## Compared with other memory plugins

As of Nov 2026, based on each project's README and source; details may change.

| | **ringkas** | claude-mem | remember | no plugin |
|---|---|---|---|---|
| Summarizes with | Gemini free tier or any OpenAI-compatible endpoint (e.g. local Ollama) | Claude (Haiku) through your subscription by default; Gemini/OpenRouter optional | `claude -p` (Haiku) | — |
| Claude quota used for memory | **0** | yes, by default | yes | 0 |
| Added to every session | ~60 tokens (skill description) | recent observations injected at start | memory files injected at start | 0 |
| Hooks | 1 (SessionStart) | 11 | 4 | 0 |
| Background process | short-lived, once per session start | long-running worker service (Bun) + SQLite/Chroma | none | none |
| Dependencies | Python 3.9+ standard library | Node, Bun, uv | Python, bash, jq | — |
| What leaves your machine | filtered conversation text, to the summarizer you choose | tool observations, to the summarizer | transcript excerpts, to Claude | nothing |

Pick claude-mem if you want semantic search over everything; pick ringkas if you want cheap, quiet, readable notes.

## Install

```bash
claude plugin marketplace add OcangAmin/ringkas
claude plugin install ringkas@ringkas
```

Then give it a free Gemini key (create one at <https://aistudio.google.com/apikey>) in the environment Claude Code starts from, e.g. in `~/.bashrc` or `~/.zshrc`:

```bash
export GEMINI_API_KEY="your-key"
```

That's it. The next session start summarizes the days you already have. Check with:

```bash
python3 "$(ls -d ~/.claude/plugins/cache/ringkas/ringkas/*/ | sort -V | tail -n 1)ringkas.py" status
```

Works on Linux, macOS and Termux (Android). Windows is untested.

### Keep everything local (Ollama)

`~/.claude/ringkas/config.json`:

```json
{ "provider": "openai", "openai_base_url": "http://localhost:11434/v1", "openai_model": "llama3.1" }
```

Any OpenAI-compatible endpoint works (OpenRouter, LM Studio, vLLM…). Set `OPENAI_API_KEY` if it needs one.

Small local models have small context windows (Ollama defaults to a few thousand tokens and silently cuts longer prompts). Either raise it (`OLLAMA_CONTEXT_LENGTH=32768 ollama serve`) or send less text per day (`"max_chars_per_day": 8000`).

## Privacy

- **Only conversation text** (your messages and Claude's replies) is collected. Tool calls, tool output, images and sub-agent transcripts are never sent. Claude's replies can still quote snippets of code or output, and project folder names are used as labels, so treat the notes as "what we talked about".
- **Sensitive topics are skipped.** Any message containing a word from `~/.claude/ringkas/sensitive-words.txt` is replaced by a placeholder, and so are Claude's replies to it. The default list covers credentials, money and health in English and Indonesian, including suffixes (`salary`/`salaries`, `saldo`/`saldonya`). Edit it freely.
- **Secrets are redacted** before sending: private keys, `sk-…`, `AIza…`, `ghp_…`, `tskey-…`, JWTs, `Bearer …`, `*_KEY=`, `token:`, `--password x`.
- **Ignore whole projects** with `"ignore_projects": ["*client*"]`.
- **Heads-up:** Google may use data sent to the Gemini *free tier* to improve its products. For confidential work, use a paid Gemini key or a local model.

## Configuration

Optional `~/.claude/ringkas/config.json`; every key can also be set as `RINGKAS_<KEY>` (e.g. `RINGKAS_LANGUAGE=en`). If you use `CLAUDE_CONFIG_DIR`, everything lives there instead of `~/.claude`.

| Key | Default | Meaning |
|---|---|---|
| `provider` | `"gemini"` | `"gemini"` or `"openai"` (any OpenAI-compatible endpoint) |
| `models` | `["gemini-flash-latest", "gemini-flash-lite-latest"]` | Gemini models tried in order; rate-limited models are skipped for a while |
| `openai_base_url` / `openai_model` | — | endpoint and model for `"openai"` |
| `language` | `"auto"` | summary language; `auto` follows the conversation |
| `timezone` | `"auto"` | where your day starts and ends, e.g. `"Asia/Jakarta"` |
| `weekly_day` | `"monday"` | day the weekly rollup runs |
| `ignore_projects` | `[]` | glob patterns for project folders to skip |
| `max_chars_per_day` | `40000` | cap on text sent per day |

Commands: `ringkas.py status`, `ringkas.py run --date YYYY-MM-DD [--dry-run]` (dry run prints exactly what would be sent), `ringkas.py run-pending`.

## FAQ

**My computer was off for a week.** The next session catches up on every day whose transcripts still exist (Claude Code's `cleanupPeriodDays`, 30 by default). Days already gone are listed under "Not recorded" in the weekly note.

**Gemini is rate-limited / down.** The day is retried later (1 h, 2 h, 4 h, up to 6 h between attempts). Nothing is lost while transcripts exist.

**Does it slow down session start?** No. The hook starts a detached process and returns in milliseconds.

**Can Claude see my notes all the time?** No. Notes are files on disk; Claude opens one only when your question calls for it.

## License

MIT. Built with Claude Code.
