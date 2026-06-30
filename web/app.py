"""Web backend for the English-habit coach.

Wraps the CLI agent (agent.py / tools.py) in a Flask JSON API and serves a
single-page frontend. The agent loop here is the same ask→tools→repeat loop,
but it collects the tool-call log so the UI can show what the agent did.
"""
import json
import os
import re
import sqlite3
import sys

# Make the parent package (tools.py, agent.py) importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anthropic
from anthropic import Anthropic
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

import tools as T
from agent import MODEL, SYSTEM, LLM_TOOLS

load_dotenv()
client = Anthropic()

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
MAX_STEPS = 12

# Structured diagnosis schema — the agent must emit THIS (forced tool_use) instead
# of free-text markdown, so the report is detailed, consistent, and renderable.
DIAGNOSIS_TOOL = {
    "name": "record_diagnosis",
    "description": "Record the final structured English-habit diagnosis. Write all prose "
                   "fields in Korean (한국어); keep quoted English phrases/corrections in English.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "2-3 sentence Korean overview of the speaker's English."},
            "cefr_estimate": {
                "type": "object",
                "properties": {
                    "level": {"type": "string", "description": "Rough CEFR level, e.g. A2/B1/B2"},
                    "reason": {"type": "string", "description": "1-sentence Korean justification"}},
                "required": ["level", "reason"]},
            "priority": {"type": "string", "description": "The single most important thing to fix next, in Korean."},
            "top_habits": {
                "type": "array",
                "description": "3-5 habits to fix, most impactful first.",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Short Korean title of the habit"},
                        "category": {"type": "string",
                                     "enum": ["filler", "verb_agreement", "tense", "article", "preposition",
                                              "plural", "word_choice", "word_order", "formality", "pace", "other"]},
                        "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                        "evidence": {"type": "string", "description": "Concrete counts/quotes from the tools, in Korean."},
                        "why": {"type": "string", "description": "Why it happens (e.g. Korean L1 interference), in Korean."},
                        "examples": {
                            "type": "array",
                            "items": {"type": "object",
                                      "properties": {"original": {"type": "string"}, "correction": {"type": "string"}},
                                      "required": ["original", "correction"]}},
                        "practice_tip": {"type": "string", "description": "One concrete drill/tip in Korean."}},
                    "required": ["title", "category", "severity", "evidence", "practice_tip"]}},
            "conversation": {
                "type": "object",
                "description": "Quality of the student as a conversation partner, judged from the FULL dialogue.",
                "properties": {
                    "comprehension": {
                        "type": "object",
                        "properties": {
                            "rating": {"type": "string", "enum": ["good", "mixed", "poor"]},
                            "note": {"type": "string", "description": "Did they understand the tutor's questions and answer them? Korean."},
                            "examples": {"type": "array", "items": {"type": "object", "properties": {
                                "question": {"type": "string"}, "response": {"type": "string"},
                                "issue": {"type": "string", "description": "What was off (misunderstood / off-topic / didn't answer), Korean."}}}}},
                        "required": ["rating", "note"]},
                    "engagement": {
                        "type": "object",
                        "properties": {
                            "rating": {"type": "string", "enum": ["good", "mixed", "poor"]},
                            "note": {"type": "string", "description": "Do they elaborate / ask back, or give short answers? Korean."}},
                        "required": ["rating", "note"]},
                    "coherence": {
                        "type": "object",
                        "properties": {
                            "rating": {"type": "string", "enum": ["good", "mixed", "poor"]},
                            "note": {"type": "string", "description": "Logical flow, use of connectors. Korean."}},
                        "required": ["rating", "note"]}},
                "required": ["comprehension", "engagement", "coherence"],
            },
            "references": {
                "type": "array",
                "description": "Grammar-reference sources you cited via search_grammar_ref (RAG).",
                "items": {"type": "object", "properties": {
                    "source": {"type": "string", "description": "Source filename, e.g. verb-agreement.md"},
                    "note": {"type": "string", "description": "What rule it supports, in Korean."}},
                    "required": ["source"]}},
            "strengths": {"type": "array", "items": {"type": "string"},
                          "description": "2-3 genuine strengths, in Korean."},
            "register": {
                "type": "object",
                "properties": {
                    "level": {"type": "string", "description": "casual / neutral / formal-leaning"},
                    "advice": {"type": "string", "description": "Korean advice for the target setting (e.g. business)."}},
                "required": ["level", "advice"]},
            "vocabulary_upgrades": {
                "type": "array",
                "items": {"type": "object",
                          "properties": {
                              "overused": {"type": "string", "description": "A word the speaker overused"},
                              "suggestions": {"type": "array", "items": {"type": "string"}},
                              "example": {"type": "string", "description": "An example sentence using an upgrade"}},
                          "required": ["overused", "suggestions"]}},
            "errors": {
                "type": "array",
                "description": "Every concrete grammar/usage error found, for tracking. category from the fixed set.",
                "items": {"type": "object",
                          "properties": {
                              "category": {"type": "string",
                                           "enum": ["verb_agreement", "tense", "article", "preposition",
                                                    "plural", "word_choice", "word_order", "formality", "other"]},
                              "original": {"type": "string"}, "correction": {"type": "string"}},
                          "required": ["category", "original", "correction"]}},
        },
        "required": ["summary", "priority", "top_habits", "conversation", "references", "strengths", "errors"],
    },
}

app = Flask(__name__, static_folder=STATIC, static_url_path="")


# ── agent loop that records its tool calls ────────────────────────────────
def run_agent(question: str) -> dict:
    messages = [{"role": "user", "content": question}]
    steps = []
    for _ in range(MAX_STEPS):
        resp = client.messages.create(
            model=MODEL, max_tokens=2048, system=SYSTEM,
            messages=messages, tools=LLM_TOOLS,
        )
        messages.append({"role": "assistant", "content": resp.content})
        calls = [b for b in resp.content if b.type == "tool_use"]
        if not calls:
            text = "".join(b.text for b in resp.content if b.type == "text").strip()
            return {"report": text, "steps": steps}
        results = []
        for c in calls:
            try:
                out = T.dispatch(c.name, c.input)
            except Exception as e:  # never crash the loop on a tool error
                out = f"Tool error in {c.name}: {e}"
            steps.append({"tool": c.name, "input": c.input, "output": out})
            results.append({"type": "tool_result", "tool_use_id": c.id, "content": out})
        messages.append({"role": "user", "content": results})
    return {"report": "(stopped: hit the step budget)", "steps": steps}


DIAGNOSIS_SYSTEM = (
    "You are a real English tutor giving a student honest, personal feedback. First use the "
    "analyzer tools (filler_stats, vocab_stats, pace_stats, formality_stats, find_pattern) to "
    "gather hard numbers — ground every claim in a tool result. ALSO call read_dialogue to see "
    "the FULL Tutor↔Me exchange, and judge the student as a conversation partner: did they "
    "understand and actually answer the tutor's questions (comprehension), do they elaborate or "
    "just give short answers (engagement), and does their speech flow logically (coherence)? Fill "
    "the `conversation` field with concrete examples (quote a question and the off-target response). "
    "For each major grammar/usage error, call search_grammar_ref to pull the matching rule from the "
    "reference corpus, base your 'why' on it, and list the cited source files in `references` (RAG — "
    "don't rely on memory for grammar rules). "
    "Distinguish real learner mistakes from natural spoken disfluency / STT artifacts. Do NOT call "
    "save_session or log_errors. When ready, call record_diagnosis ONCE.\n\n"
    "VOICE — write like a human tutor actually talking to this student, in natural Korean 존댓말. "
    "This must NOT read like AI-generated text. Hard rules:\n"
    "- 금지 표현: '전반적으로', '~하는 경향이 있습니다', '~라고 할 수 있습니다', '~인 것으로 보입니다', "
    "'중요합니다', 영혼 없는 칭찬('훌륭해요!'), 이모지 남발, 매 문장 똑같은 '~습니다' 끝맺음.\n"
    "- 구체적으로: 두루뭉술한 일반론 말고 이 학생이 실제로 한 말을 인용해 콕 집어 말하기. "
    "숫자는 그대로 ('you know 9번 썼어요' 처럼).\n"
    "- 짧고 직설적으로. 과외쌤이 옆에서 말해주듯 자연스러운 문장. 번역투 금지.\n"
    "- 칭찬은 근거 있을 때만, 담백하게. 잘한 건 잘했다고, 고칠 건 솔직하게.\n"
    "Keep quoted English phrases and their corrections in English; everything else in Korean."
)

# Tools the agent may use while gathering (read-only analyzers), plus the terminal schema.
GATHER_TOOLS = [t for t in T.TOOLS if t["name"] in
                ("list_transcripts", "load_transcript", "read_dialogue", "filler_stats",
                 "vocab_stats", "pace_stats", "formality_stats", "find_pattern", "search_grammar_ref")]


class DiagnosisTruncated(Exception):
    """The structured diagnosis hit the token ceiling, so its JSON is incomplete.

    We refuse to persist or return a half-built diagnosis (it would show up as a
    broken card and pollute the DB); the route turns this into a clean error.
    """


def _force_diagnosis(messages: list, prompt: str):
    """Force the terminal record_diagnosis call; retry once with more headroom if
    the first attempt is cut off. Raise DiagnosisTruncated if it still won't fit."""
    messages = messages + [{"role": "user", "content": prompt}]
    for max_tokens in (3000, 4096):
        resp = client.messages.create(
            model=MODEL, max_tokens=max_tokens, system=DIAGNOSIS_SYSTEM, messages=messages,
            tools=[DIAGNOSIS_TOOL], tool_choice={"type": "tool", "name": "record_diagnosis"})
        block = next((b for b in resp.content if b.type == "tool_use"), None)
        if block is not None and resp.stop_reason != "max_tokens":
            return block.input
    raise DiagnosisTruncated("diagnosis exceeded the token budget")


def run_diagnosis(filename: str, speaker: str) -> dict:
    """Agent gathers stats via tools, then emits a structured diagnosis (forced)."""
    messages = [{"role": "user", "content":
                 f"Analyze {filename} for speaker {speaker}. Gather stats, then call record_diagnosis."}]
    steps = []
    tools = GATHER_TOOLS + [DIAGNOSIS_TOOL]
    for _ in range(MAX_STEPS):
        resp = client.messages.create(model=MODEL, max_tokens=3000, system=DIAGNOSIS_SYSTEM,
                                       messages=messages, tools=tools)
        messages.append({"role": "assistant", "content": resp.content})
        calls = [b for b in resp.content if b.type == "tool_use"]
        diag = next((b for b in calls if b.name == "record_diagnosis"), None)
        if diag is not None:
            if resp.stop_reason == "max_tokens":  # truncated tool_use — its JSON is incomplete
                messages.pop()  # drop the broken assistant turn (dangling tool_use)
                return {"diagnosis": _force_diagnosis(messages, "Call record_diagnosis with the full analysis."),
                        "steps": steps}
            return {"diagnosis": diag.input, "steps": steps}
        if not calls:
            # Agent answered in prose — force the structured call.
            return {"diagnosis": _force_diagnosis(messages, "Now call record_diagnosis with the full analysis."),
                    "steps": steps}
        results = []
        for c in calls:
            try:
                out = T.dispatch(c.name, c.input)
            except Exception as e:
                out = f"Tool error in {c.name}: {e}"
            steps.append({"tool": c.name, "input": c.input, "output": out})
            results.append({"type": "tool_result", "tool_use_id": c.id, "content": out})
        messages.append({"role": "user", "content": results})
    # Out of steps — force structured output from what we have.
    return {"diagnosis": _force_diagnosis(messages, "Call record_diagnosis now with the full analysis."),
            "steps": steps}


def _slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip()).strip("-")
    return s or "session"


# ── API ───────────────────────────────────────────────────────────────────
@app.get("/api/transcripts")
def transcripts():
    files = sorted(f for f in os.listdir(T.TRANSCRIPT_DIR) if f.endswith(".txt"))
    return jsonify(files)


MAX_TRANSCRIPT_CHARS = 100_000  # cap pasted text so the disk can't be filled


def _safe_name(name: str) -> str:
    """Basename-only .txt name inside the transcripts dir (blocks path traversal)."""
    base = os.path.basename(name or "")
    return base if base.endswith(".txt") else ""


@app.get("/api/transcript/<name>")
def transcript(name):
    safe = _safe_name(name)
    path = os.path.join(T.TRANSCRIPT_DIR, safe)
    if not safe or not os.path.isfile(path):
        return jsonify({"error": "not found"}), 404
    with open(path, encoding="utf-8") as f:
        return jsonify({"name": safe, "text": f.read()})


@app.post("/api/analyze")
def analyze():
    body = request.get_json(force=True)
    speaker = body.get("speaker") or "Me"
    date = (body.get("date") or "").strip()
    filename = _safe_name(body.get("filename"))
    text = body.get("text")

    if text and len(text) > MAX_TRANSCRIPT_CHARS:
        return jsonify({"error": f"transcript too long (max {MAX_TRANSCRIPT_CHARS} chars)"}), 400

    # Pasted/edited text becomes a new session file ONLY if it differs from the
    # named sample — so picking an unchanged sample reuses it (no duplicate, no
    # overwriting sample data). All file names are basename-sanitized.
    target = None
    if filename and os.path.isfile(os.path.join(T.TRANSCRIPT_DIR, filename)):
        with open(os.path.join(T.TRANSCRIPT_DIR, filename), encoding="utf-8") as f:
            existing = f.read()
        if not (text and text.strip()) or text.strip() == existing.strip():
            target = filename
    if target is None and text and text.strip():
        target = f"{_slug(date or 'pasted')}.txt"
        with open(os.path.join(T.TRANSCRIPT_DIR, target), "w", encoding="utf-8") as f:
            f.write(text)
    filename = target or filename
    if not filename:
        return jsonify({"error": "provide a filename or pasted text"}), 400

    metrics = T.compute_metrics(filename, speaker)
    if metrics["total_words"] == 0:
        return jsonify({"error": f"no words for speaker {speaker!r} in {filename}"}), 400

    saved = None
    if date:
        saved = T.save_session(date, filename, speaker)

    # Structured diagnosis (JSON), not free-text markdown.
    try:
        result = run_diagnosis(filename, speaker)
    except DiagnosisTruncated:
        return jsonify({"error": "진단이 너무 길어 잘렸어요. 더 짧은 전사본으로 다시 시도해 주세요."}), 502
    except anthropic.APIError as e:
        return jsonify({"error": f"분석 모델 호출 실패 (잠시 후 다시 시도): {type(e).__name__}"}), 502
    diagnosis = result["diagnosis"]
    if not diagnosis:  # never persist or return an empty "successful" analysis
        return jsonify({"error": "진단을 생성하지 못했어요. 다시 시도해 주세요."}), 502

    # The server owns persistence: log the diagnosis's errors under the real date
    # only (the model never invents a date or calls save_session).
    if date and diagnosis.get("errors"):
        T.log_errors(date, json.dumps(diagnosis["errors"]))

    analysis_id = T.save_analysis(filename, speaker, metrics, json.dumps(diagnosis), date)
    return jsonify({
        "filename": filename, "speaker": speaker,
        "metrics": metrics, "saved": saved, "analysis_id": analysis_id,
        "diagnosis": diagnosis, "steps": result["steps"],
    })


@app.get("/api/sessions")
def sessions():
    """All saved sessions as rows of metrics, for the trend chart."""
    if not os.path.exists(T.DB_PATH):
        return jsonify([])
    conn = sqlite3.connect(T.DB_PATH)
    try:
        rows = conn.execute(
            "SELECT session_date, metrics_json FROM sessions ORDER BY session_date"
        ).fetchall()
    except sqlite3.OperationalError:
        return jsonify([])
    finally:
        conn.close()
    return jsonify([{"date": d, **json.loads(m)} for d, m in rows])


@app.get("/api/weaknesses")
def weaknesses():
    """Recurring-mistake profile aggregated from error_log, as JSON."""
    if not os.path.exists(T.DB_PATH):
        return jsonify([])
    conn = sqlite3.connect(T.DB_PATH)
    try:
        rows = conn.execute("SELECT category, COUNT(*) FROM error_log "
                            "GROUP BY category ORDER BY COUNT(*) DESC").fetchall()
        dates = [r[0] for r in conn.execute(
            "SELECT DISTINCT session_date FROM error_log ORDER BY session_date")]
        latest = dates[-1] if dates else None
        latest_counts = dict(conn.execute(
            "SELECT category, COUNT(*) FROM error_log WHERE session_date=? GROUP BY category",
            (latest,)).fetchall()) if latest else {}
    except sqlite3.OperationalError:
        return jsonify([])
    finally:
        conn.close()
    return jsonify({"sessions": len(dates), "latest": latest,
                    "categories": [{"category": c, "total": n,
                                    "latest": latest_counts.get(c, 0)} for c, n in rows]})


@app.get("/api/vocab")
def vocab():
    if not os.path.exists(T.DB_PATH):
        return jsonify([])
    conn = sqlite3.connect(T.DB_PATH)
    try:
        rows = conn.execute(
            "SELECT word, note, status, COALESCE(theme,'') FROM vocab ORDER BY theme, word").fetchall()
    except sqlite3.OperationalError:
        return jsonify([])
    finally:
        conn.close()
    return jsonify([{"word": w, "note": n, "status": s, "theme": t or "기타"} for w, n, s, t in rows])


@app.post("/api/vocab/mark")
def vocab_mark():
    b = request.get_json(force=True)
    return jsonify({"msg": T.mark_vocab(b["word"], b["status"])})


@app.post("/api/vocab")
def vocab_add():
    b = request.get_json(force=True)
    word = (b.get("word") or "").strip()
    if not word:
        return jsonify({"error": "단어를 입력하세요."}), 400
    return jsonify({"msg": T.add_vocab(word, b.get("note", ""), b.get("theme", ""))})


@app.get("/api/practice/history")
def practice_history():
    """Recent practice scores, to show the feedback loop closing over time."""
    if not os.path.exists(T.DB_PATH):
        return jsonify([])
    conn = sqlite3.connect(T.DB_PATH)
    try:
        rows = conn.execute("SELECT id, practice_id, focus, score, total FROM practice_result "
                            "ORDER BY id DESC LIMIT 20").fetchall()
    except sqlite3.OperationalError:
        return jsonify([])
    finally:
        conn.close()
    return jsonify([{"id": r[0], "practice_id": r[1], "focus": r[2], "score": r[3], "total": r[4]} for r in rows])


@app.post("/api/practice")
def practice_new():
    """Ask the agent to generate a drill for a focus area; return id + questions."""
    focus = (request.get_json(force=True).get("focus") or "verb_agreement").strip()
    try:
        result = run_agent(
            f"Create a 5-question fill-in-the-blank practice drill focused on '{focus}' for a "
            f"Korean learner of English. Use create_practice to save it. Then just confirm.")
    except anthropic.APIError as e:
        return jsonify({"error": f"연습 생성 모델 호출 실패 (잠시 후 다시): {type(e).__name__}"}), 502

    # Find the drill THIS run created (not just the newest row, which could be a
    # leftover from a previous request if create_practice never fired this time).
    pid = None
    for s in result["steps"]:
        if s["tool"] == "create_practice":
            m = re.search(r"Created practice #(\d+)", s["output"])
            if m:
                pid = int(m.group(1))
    if pid is None:
        return jsonify({"error": "drill was not created"}), 500
    conn = sqlite3.connect(T.DB_PATH)
    row = conn.execute("SELECT id, focus, items_json FROM practice WHERE id=?", (pid,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "drill was not created"}), 500
    items = json.loads(row[2])
    return jsonify({"practice_id": row[0], "focus": row[1],
                    "questions": [it["question"] for it in items]})


@app.post("/api/practice/grade")
def practice_grade():
    b = request.get_json(force=True)
    out = T.grade_practice(b["practice_id"], json.dumps(b["responses"]))
    return jsonify({"result": out})


@app.get("/api/analyses")
def analyses():
    """Recent saved analyses for the history dropdown."""
    return jsonify(T.list_analyses(20))


@app.get("/")
def index():
    return send_from_directory(STATIC, "index.html")


if __name__ == "__main__":
    debug = os.environ.get("COACH_DEBUG", "").lower() in ("1", "true", "yes")
    app.run(port=5050, debug=debug)
