"""Tools for the English-habit coach agent.

Quantitative analyzers are deterministic (regex / counting) so the numbers are
trustworthy and reproducible. Qualitative judgement (grammar, Konglish) is left
to the agent's reasoning over the transcript — the tools hand it the raw signal.

Every tool reads a transcript file and (optionally) filters to one speaker, so
the agent only analyzes *your* utterances, not the tutor's.
"""
import json
import os
import re
import sqlite3
from collections import Counter

BASE = os.path.dirname(__file__)
TRANSCRIPT_DIR = os.path.join(BASE, "transcripts")
DB_PATH = os.path.join(BASE, "sessions.db")

# Multi-word fillers checked first, then single words. Ambiguous discourse
# markers (like / so / well / right) are deliberately excluded: they're real
# words at least as often as fillers ("I feel like going", "so that…"), so
# counting them anywhere produced large false positives.
FILLER_PATTERNS = [
    r"you know", r"i mean", r"sort of", r"kind of", r"\bum\b", r"\buh\b",
    r"\ber\b", r"\bhmm\b", r"\bactually\b", r"\bbasically\b",
    r"\bliterally\b", r"\bkinda\b", r"\bsorta\b",
]

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "i", "you", "he", "she", "it", "we",
    "they", "to", "of", "in", "on", "at", "for", "is", "am", "are", "was",
    "were", "be", "my", "your", "so", "with", "that", "this", "have", "has",
    "do", "did", "not", "no", "yes", "me", "him", "her", "them", "as", "if",
}


def _safe_path(file: str) -> str:
    """Resolve a transcript filename to a path INSIDE TRANSCRIPT_DIR only.

    Forcing basename neutralizes path traversal (../) and absolute paths, so no
    tool can be tricked into reading files outside the transcripts folder.
    """
    return os.path.join(TRANSCRIPT_DIR, os.path.basename(file))


def _read(file: str, speaker: str = "Me") -> str:
    """Return the text of one speaker's lines from a transcript file."""
    path = _safe_path(file)
    if not os.path.exists(path):
        return ""
    lines = []
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            if speaker is None:
                lines.append(raw.rstrip("\n"))
                continue
            m = re.match(r"\s*([^:]+):\s?(.*)", raw)
            if m and m.group(1).strip().lower() == speaker.lower():
                lines.append(m.group(2))
    return "\n".join(lines)


def _words(text: str) -> list[str]:
    # Unicode-aware: normalize curly apostrophes, then match letters (any script)
    # with internal apostrophes, so "café", "naïve", "don't", "I'm" stay whole
    # instead of being shredded by an ASCII-only [a-zA-Z'] class.
    text = text.lower().replace("’", "'")
    return re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)*", text)


def list_transcripts() -> str:
    """List available transcript files in the transcripts/ folder."""
    files = sorted(f for f in os.listdir(TRANSCRIPT_DIR) if f.endswith(".txt"))
    return "\n".join(files) if files else "(no transcripts found)"


def load_transcript(file: str, speaker: str = "Me") -> str:
    """Preview one speaker's utterances + the speakers present in the file."""
    path = _safe_path(file)
    if not os.path.exists(path):
        return f"No such transcript: {file!r}. Call list_transcripts first."
    speakers = set()
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            m = re.match(r"\s*([^:]+):", raw)
            if m:
                speakers.add(m.group(1).strip())
    text = _read(file, speaker)
    wc = len(_words(text))
    return (f"Speakers in file: {', '.join(sorted(speakers)) or 'none detected'}\n"
            f"Analyzing speaker: {speaker} ({wc} words)\n"
            f"--- {speaker}'s utterances ---\n{text}")


def search_grammar_ref(query: str, k: int = 3) -> str:
    """Retrieve relevant grammar/usage reference passages (RAG over docs/) so the
    agent can ground and CITE its explanations. Returns numbered chunks with source."""
    import rag
    hits = rag.search(query, k)
    if not hits:
        return "(no reference found)"
    out = []
    for i, h in enumerate(hits, 1):
        out.append(f"[{i}] source={h['source']}\n{h['text']}")
    return "\n\n".join(out)


def read_dialogue(file: str) -> str:
    """Return the FULL transcript (all speakers, in order) so comprehension and
    response-appropriateness can be judged from the Tutor↔Me exchange."""
    path = _safe_path(file)
    if not os.path.exists(path):
        return f"No such transcript: {file!r}."
    with open(path, encoding="utf-8") as fh:
        return fh.read().strip()


def filler_stats(file: str, speaker: str = "Me") -> str:
    """Count filler words/phrases and report a rate per 100 words."""
    text = _read(file, speaker).lower()
    total = len(_words(text))
    if total == 0:
        return "(no words for that speaker)"
    counts = {}
    for pat in FILLER_PATTERNS:
        n = len(re.findall(pat, text))
        if n:
            label = pat.replace(r"\b", "").replace("\\", "")
            counts[label] = n
    total_fillers = sum(counts.values())
    rate = round(total_fillers / total * 100, 1)
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    lines = [f"Total words: {total}",
             f"Total fillers: {total_fillers}  ({rate} per 100 words)",
             "By type:"]
    lines += [f"  {label}: {n}" for label, n in ranked]
    return "\n".join(lines)


def vocab_stats(file: str, speaker: str = "Me") -> str:
    """Lexical diversity (type-token ratio) and most-repeated content words."""
    words = _words(_read(file, speaker))
    total = len(words)
    if total == 0:
        return "(no words for that speaker)"
    types = len(set(words))
    ttr = round(types / total, 3)
    content = [w for w in words if w not in STOPWORDS and len(w) > 2]
    top = Counter(content).most_common(8)
    lines = [f"Tokens: {total}   Unique: {types}   Type-token ratio: {ttr}",
             "Most repeated content words:"]
    lines += [f"  {w}: {n}" for w, n in top]
    return "\n".join(lines)


def pace_stats(file: str, speaker: str = "Me") -> str:
    """Average sentence length and a count of likely incomplete fragments."""
    text = _read(file, speaker)
    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
    if not sentences:
        return "(no sentences for that speaker)"
    lengths = [len(_words(s)) for s in sentences]
    avg = round(sum(lengths) / len(lengths), 1)
    short = sum(1 for n in lengths if n <= 3)
    longest = max(lengths)
    return (f"Sentences: {len(sentences)}\n"
            f"Avg words/sentence: {avg}\n"
            f"Very short fragments (<=3 words): {short}\n"
            f"Longest sentence: {longest} words")


def find_pattern(file: str, pattern: str, speaker: str = "Me") -> str:
    """Search the speaker's text for a regex/phrase; return matching lines.

    Use this to confirm a specific suspected habit (e.g. 'so much', 'I think').
    """
    text = _read(file, speaker)
    if len(pattern) > 200:
        return "Pattern too long (max 200 chars)."
    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return f"Bad pattern: {e}"
    hits = [ln for ln in text.split("\n") if rx.search(ln)]
    if not hits:
        return f"No matches for /{pattern}/."
    return f"{len(hits)} line(s) match /{pattern}/:\n" + "\n".join(f"  {h}" for h in hits)


def compute_metrics(file: str, speaker: str = "Me") -> dict:
    """Deterministic metrics under a FIXED key schema, computed from the file.

    This is the single source of truth for saved metrics, so every session
    stores the same keys and get_trend can always line them up.
    """
    text = _read(file, speaker)
    words = _words(text)
    total = len(words)
    fillers = sum(len(re.findall(p, text.lower())) for p in FILLER_PATTERNS)
    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    lengths = [len(_words(s)) for s in sentences] or [0]
    return {
        "total_words": total,
        "filler_count": fillers,
        "filler_rate": round(fillers / total * 100, 1) if total else 0.0,
        "type_token_ratio": round(len(set(words)) / total, 3) if total else 0.0,
        "avg_sentence_length": round(sum(lengths) / len(lengths), 1),
        "short_fragments": sum(1 for n in lengths if n and n <= 3),
    }


def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_date TEXT, metrics_json TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS error_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_date TEXT, category TEXT, original TEXT, correction TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS vocab (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        word TEXT UNIQUE, note TEXT, added_date TEXT, status TEXT DEFAULT 'learning')""")
    # Migration: group words by meaning via a `theme` tag.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(vocab)")}
    if "theme" not in cols:
        conn.execute("ALTER TABLE vocab ADD COLUMN theme TEXT DEFAULT ''")
    conn.execute("""CREATE TABLE IF NOT EXISTS practice (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        focus TEXT, items_json TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS analyses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created TEXT, filename TEXT, speaker TEXT, metrics_json TEXT, report TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS practice_result (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        practice_id INTEGER, focus TEXT, score INTEGER, total INTEGER, created TEXT)""")
    return conn


def save_analysis(filename: str, speaker: str, metrics: dict, report: str, created: str = "") -> int:
    """Persist a full analysis result. One record per (filename, speaker): re-analyzing
    the same transcript replaces the old result instead of creating a duplicate."""
    with _db() as conn:
        conn.execute("DELETE FROM analyses WHERE filename=? AND speaker=?", (filename, speaker))
        cur = conn.execute(
            "INSERT INTO analyses(created, filename, speaker, metrics_json, report) VALUES(?,?,?,?,?)",
            (created, filename, speaker, json.dumps(metrics), report))
        return cur.lastrowid


def list_analyses(limit: int = 20) -> list[dict]:
    """Recent saved analyses (newest first), report text included."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT id, created, filename, speaker, metrics_json, report "
            "FROM analyses ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
    out = []
    for r in rows:
        try:
            diagnosis = json.loads(r[5]) if r[5] else {}
        except json.JSONDecodeError:
            diagnosis = {"summary": r[5]}  # legacy markdown rows
        out.append({"id": r[0], "created": r[1], "filename": r[2], "speaker": r[3],
                    "metrics": json.loads(r[4]), "diagnosis": diagnosis})
    return out


def save_session(session_date: str, file: str, speaker: str = "Me") -> str:
    """Compute this session's metrics from the transcript and persist them.

    The tool computes the metrics itself (fixed key schema) instead of trusting
    caller-supplied JSON, so every saved session is directly comparable.
    """
    metrics = compute_metrics(file, speaker)
    if metrics["total_words"] == 0:
        return f"No words found for speaker in {file!r}; nothing saved."
    with _db() as conn:
        # One row per date — re-analyzing a date overwrites it instead of duplicating.
        conn.execute("DELETE FROM sessions WHERE session_date=?", (session_date,))
        conn.execute("INSERT INTO sessions(session_date, metrics_json) VALUES(?,?)",
                     (session_date, json.dumps(metrics)))
    return f"Saved session {session_date} with metrics: {json.dumps(metrics)}"


def get_trend(metric: str) -> str:
    """Show one metric across all saved sessions, oldest to newest."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT session_date, metrics_json FROM sessions ORDER BY session_date"
        ).fetchall()
    if not rows:
        return "(no saved sessions yet)"
    out = [f"Trend for {metric!r}:"]
    for date, mj in rows:
        val = json.loads(mj).get(metric, "—")
        out.append(f"  {date}: {val}")
    return "\n".join(out)


# ════════════════════════════════════════════════════════════════════════
# Deeper analysis: structured grammar-error logging + recurring-mistake profile
# ════════════════════════════════════════════════════════════════════════
# Fixed category set so errors are comparable across sessions (the agent must
# classify into these; unknown categories are rejected).
ERROR_CATEGORIES = [
    "verb_agreement",  # he go -> he goes
    "tense",           # we know each other for 3 years -> have known
    "article",         # a / an / the missing or wrong
    "preposition",     # wrong/missing preposition
    "plural",          # missing plural -s
    "word_choice",     # Konglish / unnatural word
    "word_order",      # wrong order
    "formality",       # register mismatch (too casual / too stiff)
    "other",
]


def log_errors(session_date: str, errors_json: str) -> str:
    """Persist classified grammar/usage errors for a session.

    errors_json: JSON list of {category, original, correction}. `category` must
    be one of the fixed ERROR_CATEGORIES so the recurring-mistake profile is
    comparable across sessions.
    """
    try:
        errors = json.loads(errors_json)
        assert isinstance(errors, list)
    except (json.JSONDecodeError, AssertionError) as e:
        return f"errors_json must be a JSON list: {e}"
    bad = [e.get("category") for e in errors if e.get("category") not in ERROR_CATEGORIES]
    if bad:
        return f"Unknown categories {bad}. Use only: {', '.join(ERROR_CATEGORIES)}."
    with _db() as conn:
        # Re-logging a date replaces its errors instead of piling up duplicates.
        conn.execute("DELETE FROM error_log WHERE session_date=?", (session_date,))
        for e in errors:
            conn.execute(
                "INSERT INTO error_log(session_date, category, original, correction) VALUES(?,?,?,?)",
                (session_date, e["category"], e.get("original", ""), e.get("correction", "")))
    return f"Logged {len(errors)} error(s) for {session_date}."


def my_weaknesses() -> str:
    """Aggregate logged errors across all sessions: which categories recur, and
    whether they are improving (compares the latest session to earlier ones)."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT session_date, category FROM error_log ORDER BY session_date").fetchall()
    if not rows:
        return "(no errors logged yet — run an analysis that logs errors first)"
    by_cat = Counter(c for _, c in rows)
    dates = sorted({d for d, _ in rows})
    latest = dates[-1]
    latest_cat = Counter(c for d, c in rows if d == latest)
    earlier_cat = Counter(c for d, c in rows if d != latest)
    out = [f"Recurring mistakes across {len(dates)} session(s):"]
    for cat, n in by_cat.most_common():
        trend = ""
        if len(dates) > 1:
            e = earlier_cat.get(cat, 0) / max(len(dates) - 1, 1)
            trend = f"  (latest: {latest_cat.get(cat,0)}, earlier avg: {round(e,1)})"
        out.append(f"  {cat}: {n} total{trend}")
    return "\n".join(out)


def formality_stats(file: str, speaker: str = "Me") -> str:
    """Register/formality signal: count casual markers and estimate how casual
    the speech is, so the agent can advise for a target register."""
    text = _read(file, speaker)
    low = text.lower()
    total = len(_words(text)) or 1
    casual_words = ["gonna", "wanna", "gotta", "kinda", "sorta", "yeah", "yep",
                    "nah", "yup", "cool", "awesome", "stuff", "guys", "ok", "okay"]
    contractions = len(re.findall(r"\b\w+'(s|re|ve|ll|d|t|m)\b", low))
    slang = {w: len(re.findall(rf"\b{w}\b", low)) for w in casual_words}
    slang = {w: n for w, n in slang.items() if n}
    casual_total = contractions + sum(slang.values())
    rate = round(casual_total / total * 100, 1)
    level = "casual" if rate > 6 else "neutral" if rate > 2 else "formal-leaning"
    lines = [f"Casual markers: {casual_total}  ({rate} per 100 words) -> {level}",
             f"  contractions: {contractions}"]
    if slang:
        lines.append("  slang/informal: " + ", ".join(f"{w}:{n}" for w, n in slang.items()))
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════════
# Vocabulary notebook
# ════════════════════════════════════════════════════════════════════════
def add_vocab(word: str, note: str = "", theme: str = "", added_date: str = "") -> str:
    """Add a word/phrase to the vocabulary notebook.

    note = meaning or example. theme = a short meaning-group label so similar
    words cluster together (e.g. '흥미로움 표현', '격식체 대체어'). Reuse the same
    theme string for synonyms so they're shown together.
    """
    word = word.strip()
    if not word:
        return "Empty word."
    with _db() as conn:
        conn.execute(
            "INSERT INTO vocab(word, note, added_date, theme, status) VALUES(?,?,?,?,'learning') "
            "ON CONFLICT(word) DO UPDATE SET note=excluded.note, theme=excluded.theme",
            (word, note, added_date, theme))
    return f"Added/updated vocab: {word!r} (theme: {theme or '—'})."


def list_vocab(status: str = "") -> str:
    """List the vocabulary notebook, grouped by meaning theme."""
    q = "SELECT word, note, status, theme FROM vocab"
    params = ()
    if status in ("learning", "known"):
        q += " WHERE status=?"
        params = (status,)
    q += " ORDER BY theme, word"
    with _db() as conn:
        rows = conn.execute(q, params).fetchall()
    if not rows:
        return "(notebook is empty)"
    out, cur = [], None
    for w, note, st, theme in rows:
        theme = theme or "기타"
        if theme != cur:
            out.append(f"[{theme}]")
            cur = theme
        out.append(f"  [{st}] {w} — {note}")
    return "\n".join(out)


def mark_vocab(word: str, status: str) -> str:
    """Mark a vocab word as 'learning' or 'known'."""
    if status not in ("learning", "known"):
        return "status must be 'learning' or 'known'."
    with _db() as conn:
        cur = conn.execute("UPDATE vocab SET status=? WHERE word=?", (status, word.strip()))
    return f"Marked {word!r} as {status}." if cur.rowcount else f"No such word: {word!r}."


# ════════════════════════════════════════════════════════════════════════
# Practice loop: generate a drill targeting a weakness, then grade answers
# ════════════════════════════════════════════════════════════════════════
def create_practice(focus: str, items_json: str) -> str:
    """Save a practice drill. items_json: JSON list of {question, answer}.
    Returns a practice_id and the questions (answers hidden) for the student."""
    try:
        items = json.loads(items_json)
        assert isinstance(items, list) and items
        for it in items:
            assert "question" in it and "answer" in it
    except (json.JSONDecodeError, AssertionError) as e:
        return f"items_json must be a non-empty JSON list of {{question, answer}}: {e}"
    with _db() as conn:
        cur = conn.execute("INSERT INTO practice(focus, items_json) VALUES(?,?)",
                           (focus, json.dumps(items)))
        pid = cur.lastrowid
    out = [f"Created practice #{pid} (focus: {focus}). Questions:"]
    out += [f"  Q{i+1}. {it['question']}" for i, it in enumerate(items)]
    return "\n".join(out)


def grade_practice(practice_id: int, responses_json: str) -> str:
    """Grade a student's answers against a saved drill (case/space-insensitive).
    responses_json: JSON list of answer strings in question order."""
    try:
        responses = json.loads(responses_json)
        assert isinstance(responses, list)
    except (json.JSONDecodeError, AssertionError) as e:
        return f"responses_json must be a JSON list of strings: {e}"
    with _db() as conn:
        row = conn.execute("SELECT focus, items_json FROM practice WHERE id=?",
                           (int(practice_id),)).fetchone()
    if not row:
        return f"No such practice #{practice_id}."
    focus, items = row[0], json.loads(row[1])

    def norm(s):
        return re.sub(r"\s+", " ", str(s).strip().lower()).rstrip(".!?")

    correct = 0
    lines = [f"Practice #{practice_id} ({focus}):"]
    for i, it in enumerate(items):
        got = responses[i] if i < len(responses) else ""
        ok = norm(got) == norm(it["answer"])
        correct += ok
        mark = "✓" if ok else "✗"
        lines.append(f"  {mark} Q{i+1}: your={got!r} expected={it['answer']!r}")
    # Persist the score so practice progress is part of the saved record.
    with _db() as conn:
        conn.execute("INSERT INTO practice_result(practice_id, focus, score, total, created) "
                     "VALUES(?,?,?,?,?)", (int(practice_id), focus, correct, len(items), ""))
    lines.append(f"Score: {correct}/{len(items)}")
    return "\n".join(lines)


# ── Tool definitions sent to the Claude API ──────────────────────────────
TOOLS = [
    {"name": "list_transcripts",
     "description": "List available transcript files.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "load_transcript",
     "description": "Preview one speaker's utterances and see which speakers are in the file. Call this first.",
     "input_schema": {"type": "object", "properties": {
         "file": {"type": "string", "description": "Transcript filename"},
         "speaker": {"type": "string", "description": "Speaker label to analyze (default 'Me')"}},
         "required": ["file"]}},
    {"name": "read_dialogue",
     "description": "Return the FULL transcript (both speakers, in order). Use this to judge whether "
                    "the student understood the tutor's questions and responded appropriately/coherently.",
     "input_schema": {"type": "object", "properties": {"file": {"type": "string"}}, "required": ["file"]}},
    {"name": "search_grammar_ref",
     "description": "RAG: retrieve grammar/usage reference passages for an error or topic so you can "
                    "ground and cite your explanation. Returns chunks tagged with their source file. "
                    "Call this for each major error to back up the 'why'.",
     "input_schema": {"type": "object", "properties": {
         "query": {"type": "string"}, "k": {"type": "integer"}}, "required": ["query"]}},
    {"name": "filler_stats",
     "description": "Count filler words (um, uh, you know, like, actually...) and the rate per 100 words.",
     "input_schema": {"type": "object", "properties": {
         "file": {"type": "string"}, "speaker": {"type": "string"}}, "required": ["file"]}},
    {"name": "vocab_stats",
     "description": "Lexical diversity (type-token ratio) and the most-repeated content words.",
     "input_schema": {"type": "object", "properties": {
         "file": {"type": "string"}, "speaker": {"type": "string"}}, "required": ["file"]}},
    {"name": "pace_stats",
     "description": "Average sentence length and count of short/incomplete fragments.",
     "input_schema": {"type": "object", "properties": {
         "file": {"type": "string"}, "speaker": {"type": "string"}}, "required": ["file"]}},
    {"name": "find_pattern",
     "description": "Search the speaker's text for a regex/phrase to confirm a suspected habit.",
     "input_schema": {"type": "object", "properties": {
         "file": {"type": "string"}, "pattern": {"type": "string"},
         "speaker": {"type": "string"}}, "required": ["file", "pattern"]}},
    {"name": "save_session",
     "description": "Persist this session's metrics so progress can be tracked. The tool "
                    "computes a fixed set of metrics from the transcript itself (you only "
                    "give the date and file) — so every session is directly comparable.",
     "input_schema": {"type": "object", "properties": {
         "session_date": {"type": "string", "description": "YYYY-MM-DD"},
         "file": {"type": "string", "description": "Transcript filename"},
         "speaker": {"type": "string", "description": "Speaker label (default 'Me')"}},
         "required": ["session_date", "file"]}},
    {"name": "get_trend",
     "description": "Show one metric across all saved sessions to see improvement over time.",
     "input_schema": {"type": "object", "properties": {
         "metric": {"type": "string"}}, "required": ["metric"]}},
    {"name": "formality_stats",
     "description": "Register/formality signal: casual-marker rate (contractions, slang) so you can advise for a target register (casual vs business).",
     "input_schema": {"type": "object", "properties": {
         "file": {"type": "string"}, "speaker": {"type": "string"}}, "required": ["file"]}},
    {"name": "log_errors",
     "description": "Persist the grammar/usage errors you found for a session, classified into "
                    "fixed categories, so recurring mistakes can be tracked. Call after diagnosing.",
     "input_schema": {"type": "object", "properties": {
         "session_date": {"type": "string", "description": "YYYY-MM-DD"},
         "errors_json": {"type": "string",
                         "description": "JSON list of {category, original, correction}. category must be one of: "
                                        + ", ".join(ERROR_CATEGORIES)}},
         "required": ["session_date", "errors_json"]}},
    {"name": "my_weaknesses",
     "description": "Aggregate logged errors across all sessions: which mistake categories recur and whether they are improving. Use for personalized coaching.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "add_vocab",
     "description": "Add a word/phrase to the vocabulary notebook. note = meaning or example. "
                    "theme = a short meaning-group label (e.g. '흥미로움 표현', '격식체 대체어'); reuse "
                    "the same theme for synonyms so similar words are grouped together.",
     "input_schema": {"type": "object", "properties": {
         "word": {"type": "string"}, "note": {"type": "string"},
         "theme": {"type": "string"}, "added_date": {"type": "string"}}, "required": ["word"]}},
    {"name": "list_vocab",
     "description": "List the vocabulary notebook. status: 'learning', 'known', or empty for all.",
     "input_schema": {"type": "object", "properties": {"status": {"type": "string"}}}},
    {"name": "mark_vocab",
     "description": "Mark a vocabulary word as 'learning' or 'known'.",
     "input_schema": {"type": "object", "properties": {
         "word": {"type": "string"}, "status": {"type": "string"}}, "required": ["word", "status"]}},
    {"name": "create_practice",
     "description": "Generate and save a practice drill targeting a weakness. items_json: JSON list of "
                    "{question, answer} (e.g. fill-in-the-blank for present perfect). Returns a practice_id.",
     "input_schema": {"type": "object", "properties": {
         "focus": {"type": "string", "description": "Weakness this drill targets, e.g. 'verb_agreement'"},
         "items_json": {"type": "string"}}, "required": ["focus", "items_json"]}},
    {"name": "grade_practice",
     "description": "Grade the student's answers against a saved drill. responses_json: JSON list of answer strings in order.",
     "input_schema": {"type": "object", "properties": {
         "practice_id": {"type": "integer"}, "responses_json": {"type": "string"}},
         "required": ["practice_id", "responses_json"]}},
]


def dispatch(name: str, ti: dict) -> str:
    """Route a tool_use block to the matching function."""
    sp = ti.get("speaker", "Me")
    if name == "list_transcripts":
        return list_transcripts()
    if name == "load_transcript":
        return load_transcript(ti["file"], sp)
    if name == "read_dialogue":
        return read_dialogue(ti["file"])
    if name == "search_grammar_ref":
        return search_grammar_ref(ti["query"], ti.get("k", 3))
    if name == "filler_stats":
        return filler_stats(ti["file"], sp)
    if name == "vocab_stats":
        return vocab_stats(ti["file"], sp)
    if name == "pace_stats":
        return pace_stats(ti["file"], sp)
    if name == "find_pattern":
        return find_pattern(ti["file"], ti["pattern"], sp)
    if name == "save_session":
        return save_session(ti["session_date"], ti["file"], sp)
    if name == "get_trend":
        return get_trend(ti["metric"])
    if name == "formality_stats":
        return formality_stats(ti["file"], sp)
    if name == "log_errors":
        return log_errors(ti["session_date"], ti["errors_json"])
    if name == "my_weaknesses":
        return my_weaknesses()
    if name == "add_vocab":
        return add_vocab(ti["word"], ti.get("note", ""), ti.get("theme", ""), ti.get("added_date", ""))
    if name == "list_vocab":
        return list_vocab(ti.get("status", ""))
    if name == "mark_vocab":
        return mark_vocab(ti["word"], ti["status"])
    if name == "create_practice":
        return create_practice(ti["focus"], ti["items_json"])
    if name == "grade_practice":
        return grade_practice(ti["practice_id"], ti["responses_json"])
    return f"Unknown tool: {name}"
