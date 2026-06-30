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
from flask import Flask, Response, jsonify, request, send_from_directory

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
            "prep_structure": {
                "type": "object",
                "description": "PREP (Point→Reason→Example→Point-restate) structure analysis based on prep_stats output.",
                "properties": {
                    "rating": {"type": "string", "enum": ["good", "mixed", "poor"]},
                    "note": {"type": "string",
                             "description": "Korean explanation: which PREP elements the student uses or skips, with concrete quotes."},
                    "tip": {"type": "string",
                            "description": "One concrete drill or sentence-restructuring tip, in Korean."},
                    "examples": {
                        "type": "array",
                        "description": "1-2 actual student responses showing PREP issues, each with a rewritten version.",
                        "items": {"type": "object",
                                  "properties": {
                                      "original": {"type": "string"},
                                      "rewritten": {"type": "string",
                                                    "description": "The same idea restructured with P+R+E, in English."},
                                      "missing": {"type": "array", "items": {"type": "string"}}},
                                  "required": ["original", "rewritten", "missing"]}}},
                "required": ["rating", "note", "tip"]},
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
    "Call prep_stats to analyze whether the student structures answers using PREP (Point→Reason→"
    "Example→Point-restate). Fill the `prep_structure` field: rate it good/mixed/poor, explain "
    "which elements are missing, and give a rewritten example showing the ideal PREP structure. "
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
                 "vocab_stats", "pace_stats", "formality_stats", "find_pattern",
                 "search_grammar_ref", "prep_stats")]


class DiagnosisTruncated(Exception):
    """The structured diagnosis hit the token ceiling, so its JSON is incomplete.

    We refuse to persist or return a half-built diagnosis (it would show up as a
    broken card and pollute the DB); the route turns this into a clean error.
    """


def _force_diagnosis(messages: list, prompt: str):
    """Force the terminal record_diagnosis call; retry once with more headroom if
    the first attempt is cut off. Raise DiagnosisTruncated if it still won't fit."""
    messages = messages + [{"role": "user", "content": prompt}]
    for max_tokens in (6000, 8192):
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
        resp = client.messages.create(model=MODEL, max_tokens=8192, system=DIAGNOSIS_SYSTEM,
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


def _diagnosis_events(filename: str, speaker: str):
    """Generator version of run_diagnosis — yields SSE event dicts in real time."""
    messages = [{"role": "user", "content":
                 f"Analyze {filename} for speaker {speaker}. Gather stats, then call record_diagnosis."}]
    steps = []
    tools = GATHER_TOOLS + [DIAGNOSIS_TOOL]
    for _ in range(MAX_STEPS):
        resp = client.messages.create(model=MODEL, max_tokens=8192, system=DIAGNOSIS_SYSTEM,
                                      messages=messages, tools=tools)
        messages.append({"role": "assistant", "content": resp.content})
        calls = [b for b in resp.content if b.type == "tool_use"]
        diag = next((b for b in calls if b.name == "record_diagnosis"), None)
        if diag is not None:
            if resp.stop_reason == "max_tokens":
                messages.pop()
                yield {"type": "diagnosing"}
                try:
                    yield {"type": "diagnosis",
                           "diagnosis": _force_diagnosis(messages, "Call record_diagnosis with the full analysis."),
                           "steps": steps}
                except DiagnosisTruncated:
                    yield {"type": "error", "message": "진단이 너무 길어 잘렸어요. 더 짧은 전사본으로 다시 시도해 주세요."}
                return
            yield {"type": "diagnosis", "diagnosis": diag.input, "steps": steps}
            return
        if not calls:
            yield {"type": "diagnosing"}
            try:
                yield {"type": "diagnosis",
                       "diagnosis": _force_diagnosis(messages, "Now call record_diagnosis with the full analysis."),
                       "steps": steps}
            except DiagnosisTruncated:
                yield {"type": "error", "message": "진단이 너무 길어 잘렸어요. 더 짧은 전사본으로 다시 시도해 주세요."}
            return
        results = []
        for c in calls:
            yield {"type": "tool_call", "tool": c.name, "input": {k: str(v)[:80] for k, v in c.input.items()}}
            try:
                out = T.dispatch(c.name, c.input)
            except Exception as e:
                out = f"Tool error in {c.name}: {e}"
            steps.append({"tool": c.name, "input": c.input, "output": out})
            yield {"type": "tool_done", "tool": c.name}
            results.append({"type": "tool_result", "tool_use_id": c.id, "content": out})
        messages.append({"role": "user", "content": results})
    yield {"type": "diagnosing"}
    try:
        yield {"type": "diagnosis",
               "diagnosis": _force_diagnosis(messages, "Call record_diagnosis now with the full analysis."),
               "steps": steps}
    except DiagnosisTruncated:
        yield {"type": "error", "message": "진단이 너무 길어 잘렸어요. 더 짧은 전사본으로 다시 시도해 주세요."}


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


def _resolve_transcript(filename: str, text: str, date: str) -> str:
    """Return the transcript filename to analyse, saving new text if needed.

    - Existing sample selected and text unchanged → reuse the file as-is.
    - New/edited text → save to a timestamped file so nothing gets overwritten.
      Format: {date}_{HHMMSS}.txt  or  session_{YYYYMMDD_HHMMSS}.txt
    """
    from datetime import datetime
    path_dir = T.TRANSCRIPT_DIR

    if filename and os.path.isfile(os.path.join(path_dir, filename)):
        with open(os.path.join(path_dir, filename), encoding="utf-8") as f:
            existing = f.read()
        if not (text and text.strip()) or text.strip() == existing.strip():
            return filename  # unchanged sample — reuse

    if not (text and text.strip()):
        return filename  # no new text; caller will handle missing file

    ts = datetime.now().strftime("%H%M%S")
    if date:
        target = f"{_slug(date)}_{ts}.txt"
    else:
        target = f"session_{datetime.now().strftime('%Y%m%d')}_{ts}.txt"

    with open(os.path.join(path_dir, target), "w", encoding="utf-8") as f:
        f.write(text)
    return target


@app.get("/api/transcript/<name>")
def transcript(name):
    safe = _safe_name(name)
    path = os.path.join(T.TRANSCRIPT_DIR, safe)
    if not safe or not os.path.isfile(path):
        return jsonify({"error": "not found"}), 404
    with open(path, encoding="utf-8") as f:
        return jsonify({"name": safe, "text": f.read()})


@app.post("/api/analyze/stream")
def analyze_stream():
    body = request.get_json(force=True)
    speaker = body.get("speaker") or "Me"
    date = (body.get("date") or "").strip()
    filename = _safe_name(body.get("filename"))
    text = body.get("text")

    if text and len(text) > MAX_TRANSCRIPT_CHARS:
        return jsonify({"error": f"transcript too long (max {MAX_TRANSCRIPT_CHARS} chars)"}), 400

    filename = _resolve_transcript(filename, text, date)
    if not filename:
        return jsonify({"error": "provide a filename or pasted text"}), 400

    def generate():
        metrics = T.compute_metrics(filename, speaker)
        if metrics["total_words"] == 0:
            yield f"data: {json.dumps({'type': 'error', 'message': f'화자 {speaker!r}의 발화가 없습니다.'})}\n\n"
            return
        yield f"data: {json.dumps({'type': 'metrics', 'metrics': metrics})}\n\n"
        saved = T.save_session(date, filename, speaker) if date else None
        try:
            for event in _diagnosis_events(filename, speaker):
                if event["type"] == "diagnosis":
                    diagnosis = event["diagnosis"]
                    if not diagnosis:
                        yield f"data: {json.dumps({'type': 'error', 'message': '진단을 생성하지 못했어요.'})}\n\n"
                        return
                    if date and diagnosis.get("errors"):
                        T.log_errors(date, json.dumps(diagnosis["errors"]))
                    analysis_id = T.save_analysis(filename, speaker, metrics, json.dumps(diagnosis), date)
                    yield f"data: {json.dumps({'type': 'done', 'filename': filename, 'speaker': speaker, 'metrics': metrics, 'saved': saved, 'analysis_id': analysis_id, 'diagnosis': diagnosis, 'steps': event['steps']})}\n\n"
                else:
                    yield f"data: {json.dumps(event)}\n\n"
        except anthropic.APIError as e:
            yield f"data: {json.dumps({'type': 'error', 'message': f'분석 모델 호출 실패: {type(e).__name__}'})}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/analyze")
def analyze():
    body = request.get_json(force=True)
    speaker = body.get("speaker") or "Me"
    date = (body.get("date") or "").strip()
    filename = _safe_name(body.get("filename"))
    text = body.get("text")

    if text and len(text) > MAX_TRANSCRIPT_CHARS:
        return jsonify({"error": f"transcript too long (max {MAX_TRANSCRIPT_CHARS} chars)"}), 400

    filename = _resolve_transcript(filename, text, date)
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


# (en) used for embedding, (ko) displayed to the user.
# all-MiniLM-L6-v2 is English-only, so we embed the English label.
_VOCAB_TEST_SITUATIONS = [
    # ── formal / professional ──────────────────────────────────────────
    {"en": "writing a formal business email to a client",                       "ko": "클라이언트에게 격식 있는 비즈니스 이메일을 쓸 때"},
    {"en": "presenting quarterly results in a company meeting",                  "ko": "회사 회의에서 분기 결과를 발표할 때"},
    {"en": "job interview describing your strengths and achievements",           "ko": "면접에서 자신의 강점과 성과를 말할 때"},
    {"en": "writing a formal complaint letter to a company",                     "ko": "회사에 공식 불만 편지를 쓸 때"},
    {"en": "negotiating terms in a professional business deal",                  "ko": "비즈니스 협상에서 조건을 조율할 때"},
    {"en": "writing a performance review or evaluation report",                  "ko": "직원 성과 평가 보고서를 작성할 때"},
    {"en": "giving a speech at a formal ceremony or conference",                 "ko": "공식 행사나 컨퍼런스에서 연설할 때"},
    {"en": "writing a cover letter for a job application",                       "ko": "입사 지원서에 자기소개서를 쓸 때"},
    {"en": "politely declining a request or invitation in writing",              "ko": "요청이나 초대를 정중하게 거절하는 글을 쓸 때"},
    {"en": "recommending a colleague or employee in a reference letter",         "ko": "추천서에서 동료나 직원을 추천할 때"},
    # ── academic ──────────────────────────────────────────────────────
    {"en": "writing a university essay with a clear argument",                   "ko": "논거가 명확한 대학교 에세이를 쓸 때"},
    {"en": "academic debate defending your thesis or position",                  "ko": "학술 토론에서 자신의 논지를 방어할 때"},
    {"en": "explaining a complex scientific concept to a classmate",             "ko": "복잡한 과학 개념을 학우에게 설명할 때"},
    {"en": "writing a research paper introduction or abstract",                  "ko": "연구 논문의 서론이나 초록을 작성할 때"},
    {"en": "asking a professor a question after a lecture",                      "ko": "강의 후 교수님께 질문할 때"},
    {"en": "citing evidence to support a claim in an essay",                     "ko": "에세이에서 주장을 뒷받침하는 근거를 들 때"},
    # ── casual / social ────────────────────────────────────────────────
    {"en": "chatting casually with a close friend about your weekend",           "ko": "친한 친구에게 주말 이야기를 편하게 할 때"},
    {"en": "texting a friend to make plans for the evening",                     "ko": "친구에게 저녁 약속을 잡는 문자를 보낼 때"},
    {"en": "posting a fun caption on Instagram or social media",                 "ko": "인스타그램에 재미있는 캡션을 쓸 때"},
    {"en": "gossiping lightly with a coworker during a coffee break",            "ko": "커피 브레이크 때 동료와 가볍게 수다 떨 때"},
    {"en": "giving a friend honest advice about a personal problem",             "ko": "친구의 고민에 솔직한 조언을 줄 때"},
    {"en": "joking around with friends at a party",                              "ko": "파티에서 친구들과 장난치며 대화할 때"},
    {"en": "reacting to surprising or exciting news from a friend",              "ko": "친구의 놀랍거나 신나는 소식에 반응할 때"},
    {"en": "complimenting someone on their appearance or achievement",           "ko": "외모나 성취에 대해 칭찬할 때"},
    # ── travel / daily life ────────────────────────────────────────────
    {"en": "ordering food at a restaurant and asking about the menu",            "ko": "식당에서 음식을 주문하고 메뉴를 물어볼 때"},
    {"en": "asking for directions from a stranger on the street",                "ko": "길에서 낯선 사람에게 길을 물어볼 때"},
    {"en": "checking in at a hotel and asking about facilities",                 "ko": "호텔에서 체크인하며 시설을 물어볼 때"},
    {"en": "shopping for clothes and asking a store assistant for help",         "ko": "옷 가게에서 점원에게 도움을 요청할 때"},
    {"en": "making small talk with a stranger on a plane or train",              "ko": "비행기나 기차 안에서 옆 사람과 가볍게 대화할 때"},
    {"en": "describing your hometown or country to a foreign tourist",           "ko": "외국인 관광객에게 고향이나 나라를 소개할 때"},
    {"en": "reporting a problem to a doctor or pharmacist",                      "ko": "의사나 약사에게 증상을 설명할 때"},
    {"en": "explaining a misunderstanding or mix-up to someone",                 "ko": "오해나 착각을 상대방에게 설명할 때"},
    # ── emotions / personal ────────────────────────────────────────────
    {"en": "describing how a place or experience made you feel",                 "ko": "어떤 장소나 경험이 어떤 감정을 줬는지 묘사할 때"},
    {"en": "writing about a childhood memory in a personal essay",               "ko": "어린 시절 추억을 개인 에세이에 쓸 때"},
    {"en": "apologising sincerely for a mistake you made",                       "ko": "자신의 실수에 대해 진심으로 사과할 때"},
    {"en": "expressing excitement or enthusiasm about upcoming plans",           "ko": "다가올 계획에 대한 기대와 설렘을 표현할 때"},
    {"en": "describing someone you admire and why they inspire you",             "ko": "존경하는 사람과 그 이유를 이야기할 때"},
    {"en": "talking about your fears or worries with a trusted person",          "ko": "믿는 사람에게 두려움이나 걱정을 털어놓을 때"},
    # ── media / entertainment ──────────────────────────────────────────
    {"en": "reviewing a movie or TV show and recommending it to friends",        "ko": "영화나 드라마를 리뷰하며 친구에게 추천할 때"},
    {"en": "summarising the plot of a book you recently read",                   "ko": "최근 읽은 책의 줄거리를 요약할 때"},
    {"en": "discussing the outcome of a sports game with fans",                  "ko": "스포츠 경기 결과를 팬들과 이야기할 때"},
    {"en": "describing a song or album and why you love it",                     "ko": "좋아하는 노래나 앨범을 설명하며 이유를 말할 때"},
    {"en": "sharing a recipe or explaining how to cook a dish",                  "ko": "레시피를 공유하거나 요리 방법을 설명할 때"},
    # ── explaining / persuading ────────────────────────────────────────
    {"en": "explaining the cause and effect of a historical event",              "ko": "역사적 사건의 원인과 결과를 설명할 때"},
    {"en": "persuading someone to change their opinion with logic",              "ko": "논리적으로 상대방의 의견을 바꾸려 설득할 때"},
    {"en": "teaching a beginner how to use a device or software step by step",   "ko": "초보자에게 기기나 소프트웨어 사용법을 알려줄 때"},
    {"en": "comparing two options and recommending the better one",              "ko": "두 가지 선택지를 비교하며 더 나은 것을 추천할 때"},
    {"en": "describing the pros and cons of a decision",                         "ko": "어떤 결정의 장단점을 설명할 때"},
    {"en": "expressing a strong opinion about a social or political issue",      "ko": "사회적·정치적 이슈에 대해 강한 의견을 표현할 때"},
    {"en": "making a logical argument using examples and evidence",              "ko": "예시와 근거를 들어 논리적인 주장을 펼칠 때"},
]

_situation_vecs: list | None = None  # lazy-initialised on first request


def _get_situation_vecs():
    global _situation_vecs
    if _situation_vecs is None:
        from rag import _embed
        vecs = _embed([s["en"] for s in _VOCAB_TEST_SITUATIONS])
        _situation_vecs = vecs
    return _situation_vecs


@app.post("/api/vocab/test/prompts")
def vocab_test_prompts():
    b = request.get_json(force=True)
    word = (b.get("word") or "").strip()
    note = (b.get("note") or "").strip()
    if not word:
        return jsonify({"error": "단어를 입력하세요."}), 400
    from rag import _embed
    query = f"{word} {note}".strip()
    [qvec] = _embed([query])
    svecs = _get_situation_vecs()
    # cosine similarity (vectors are already unit-normalised by rag._embed)
    scored = sorted(range(len(svecs)),
                    key=lambda i: -sum(a * b for a, b in zip(qvec, svecs[i])))
    top3 = [_VOCAB_TEST_SITUATIONS[i]["ko"] for i in scored[:3]]
    return jsonify({"word": word, "prompts": top3})


@app.post("/api/vocab/test/grade")
def vocab_test_grade():
    b = request.get_json(force=True)
    word = (b.get("word") or "").strip()
    note = (b.get("note") or "").strip()
    sentences = b.get("sentences", [])
    if not word or len(sentences) != 3:
        return jsonify({"error": "단어와 예문 3개가 필요합니다."}), 400
    prompt = (
        f"Word: '{word}'" + (f" (meaning: {note})" if note else "") + "\n\n"
        "A Korean English learner wrote these 3 sentences. Judge if the word is used correctly "
        "in meaning and context. Minor grammar mistakes are OK — focus only on whether the word "
        "itself is used appropriately.\n\n"
        + "\n".join(f"{i+1}. {s}" for i, s in enumerate(sentences))
        + "\n\nReturn ONLY a JSON array of 3 objects, no explanation: "
        '[{"correct": true, "feedback": "Korean one-sentence reason"}, ...]'
    )
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=600,
            messages=[{"role": "user", "content": prompt}])
        text = resp.content[0].text.strip()
        m = re.search(r'\[.*\]', text, re.DOTALL)
        if not m:
            return jsonify({"error": "채점 실패"}), 500
        results = json.loads(m.group())[:3]
        score = sum(1 for r in results if r.get("correct"))
        passed = score >= 2
        T.mark_vocab(word, "known" if passed else "learning")
        return jsonify({"results": results, "score": score, "total": 3,
                        "passed": passed, "new_status": "known" if passed else "learning"})
    except anthropic.APIError as e:
        return jsonify({"error": f"모델 호출 실패: {type(e).__name__}"}), 502


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
