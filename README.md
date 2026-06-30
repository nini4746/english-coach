# English-habit coach — a multi-tool agent over conversation transcripts

An AI agent that analyzes a conversation transcript (speech-to-text) and
diagnoses your recurring English-speaking habits, tracks improvement across
sessions, builds a vocabulary notebook, and generates practice drills.

It's the lecture's agent loop (ask Claude → run the tools it requests → feed
results back → repeat) wired to a set of tools over your transcripts, plus a
Flask web UI. Design principle: **measurement is deterministic Python code; only
judgement (grammar, Konglish, register) is the LLM.**

```
english-coach/
├── agent.py            agent loop + CLI (interactive or one-shot)
├── tools.py            the tools + SQLite persistence
├── transcripts/        sample STT transcripts (Tutor / Me dialogue)
├── sessions.db         metrics, errors, vocab, practice, saved analyses
├── web/
│   ├── app.py          Flask backend (JSON API + serves the SPA)
│   └── static/         index.html / style.css / app.js (single-page UI)
├── .env.example
└── requirements.txt    anthropic, python-dotenv, flask
```

## The tools

| Tool | Kind | What it does |
|---|---|---|
| `list_transcripts` / `load_transcript` | local | List files / preview one speaker's lines (filters to `Me`) |
| `filler_stats` | deterministic | Filler count + rate per 100 words (um, uh, you know, like…) |
| `vocab_stats` | deterministic | Type-token ratio + most-repeated content words |
| `pace_stats` | deterministic | Avg sentence length + short-fragment count |
| `formality_stats` | deterministic | Casual-marker rate → advise for a target register |
| `find_pattern` | local | Regex search to confirm a suspected habit |
| `save_session` / `get_trend` | SQLite | Store a fixed metric schema per date / trend over time |
| `log_errors` / `my_weaknesses` | SQLite | Record classified mistakes / recurring-mistake profile |
| `add_vocab` / `list_vocab` / `mark_vocab` | SQLite | Vocabulary notebook, grouped by meaning theme |
| `create_practice` / `grade_practice` | SQLite | Generate a targeted drill / grade answers (score saved) |

Grammar/Konglish judgement is the agent's reasoning (quotes the phrase +
correction). All counting is deterministic so numbers are reproducible.

## External APIs

Only one: the **Anthropic API** (Claude `claude-sonnet-4-6`). Every tool is
local — pure-Python analyzers + a local SQLite file. STT is out of scope:
transcripts are plain `.txt` from elsewhere (Whisper / Zoom / captions).

## Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # put your real ANTHROPIC_API_KEY in .env
```

## Run — web app (recommended)

```bash
cd web
python app.py               # http://127.0.0.1:5050
```

Paste a transcript (or load a sample), set a date to track trends, hit 분석하기.
You get: metric cards, a Korean coach report, a recurring-mistake profile, a
trend chart, a themed vocabulary notebook, and a practice drill you can answer
and have graded. Past analyses are saved and reloadable from "지난 분석".

Set `COACH_DEBUG=1` to enable Flask debug/reload (off by default).

## Run — CLI

```bash
python agent.py             # interactive (type 'exit' to quit)
python agent.py "Analyze session-2026-06-20.txt and list my top 3 habits."
```

## How persistence is controlled (a bug we fixed)

The web backend — not the model — owns what gets written. The agent must never
call `save_session`, and may only `log_errors` under the real date the server
passes. Early on, analyzing without a date let the model invent dates
(`2026-07-04`, …) and pollute the DB; locking persistence to the server fixed it.
Likewise `save_session` computes a fixed metric schema itself instead of trusting
LLM-authored JSON, so every session is directly comparable. Lesson: keep
measurement and persistence in deterministic code; let the LLM judge, not count.

## Demo data

`sessions.db` ships with two sample sessions (2026-06-20 → 2026-06-27) showing a
clean improvement story: filler rate 20.0 → 2.8, TTR 0.532 → 0.682, and grammar
mistakes dropping to zero in the later session. Delete `sessions.db` to start
fresh (tables are recreated on first write).
