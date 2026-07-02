"""English-habit coach — an agent that analyzes a conversation transcript (STT)
and diagnoses your recurring English-speaking habits.

The agent loop from the lecture: ask Claude, run any tools it requests, feed the
results back, repeat until it stops calling tools. Deterministic analyzer tools
supply the numbers; the agent adds qualitative grammar/Konglish judgement and
writes the final report.

Interactive (multi-turn — remembers the conversation):
    python agent.py

One-shot:
    python agent.py "Analyze session-2026-06-20.txt and list my top 3 habits."
"""
import sys

from anthropic import Anthropic
from dotenv import load_dotenv

from tools import TOOLS, dispatch

load_dotenv()
client = Anthropic()

MODEL = "claude-sonnet-4-6"
MAX_STEPS = 12

# Persistence is server-owned. The model never gets save_session / log_errors:
# left in its hands it could invent a session_date and pollute the DB. The server
# calls those functions directly with a real date.
LLM_TOOLS = [t for t in TOOLS if t["name"] not in ("save_session", "log_errors")]


# ── Anthropic ephemeral prompt caching ────────────────────────────────
# Static prefixes (system prompt, tool definitions) and the growing conversation
# prefix inside an agent loop are marked with cache_control so subsequent calls
# within the 5-min TTL are billed at 10% of the input rate. In a diagnosis run
# the tool-result history dominates input tokens, so caching it across the loop
# is the biggest single cost win short of switching models.
def _cached_system(text: str) -> list:
    """Turn a system prompt string into a cacheable structured block."""
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def _cached_tools(tools: list) -> list:
    """Mark the end of the tools list as a cache breakpoint so the whole
    schema block is cached."""
    if not tools:
        return tools
    return [*tools[:-1], {**tools[-1], "cache_control": {"type": "ephemeral"}}]


def _cache_messages_tail(messages: list) -> list:
    """Mark the last content block of the last message so the next iteration
    of an agent loop hits cache on the entire prior conversation. Plain-string
    message content (the very first user turn) can't take cache_control; the
    function returns the list unchanged in that case."""
    if not messages:
        return messages
    last = messages[-1]
    content = last.get("content")
    if not isinstance(content, list) or not content:
        return messages
    new_tail = {**content[-1], "cache_control": {"type": "ephemeral"}}
    return [*messages[:-1], {**last, "content": [*content[:-1], new_tail]}]


SYSTEM = """You are an English-speaking coach. You analyze a transcript of the \
student's conversation (often from speech-to-text) and diagnose their recurring \
habits and weaknesses.

Workflow:
- Start with list_transcripts / load_transcript so you know the file and which \
speaker is the student (default speaker label is 'Me'; never analyze the tutor's lines).
- Use the analyzer tools (filler_stats, vocab_stats, pace_stats, find_pattern) to \
gather hard numbers before making claims. Always ground a claim in a tool result.
- For grammar and Konglish (L1-interference) issues, reason over the transcript \
yourself and quote the exact phrase, then give the natural correction.

Important caveats you must respect:
- The transcript is speech-to-text. Disfluencies, false starts, and casual spoken \
grammar are normal in speech — do NOT flag every informal construction as an error. \
Distinguish a genuine learner mistake (e.g. 'he go', missing article) from natural \
spoken style. When unsure whether something is an STT artifact, say so.

You have tools beyond raw stats:
- formality_stats — gauge how casual the speech is, then advise for the target register \
(casual chat vs business/formal). Flag mismatches (e.g. 'gonna', 'yeah' in a work context).
- my_weaknesses — see which mistakes recur across sessions; use it to personalize advice \
('this is the 3rd session with verb-agreement slips').
- add_vocab / list_vocab / mark_vocab — maintain a vocabulary notebook. When the student \
overuses a word, add an upgrade word with a note; track learning vs known.
- create_practice / grade_practice — close the loop: generate a short targeted drill for \
the student's top weakness (fill-in-the-blank with answers), and grade their responses.

When diagnosing, give the student's top habits to fix (counts/quotes as evidence) and one \
concrete practice tip each. Be encouraging, specific, personalized. (Saving metrics and \
logging errors is handled by the server, not by you — just diagnose.)"""


SYSTEM_CACHED = _cached_system(SYSTEM)
LLM_TOOLS_CACHED = _cached_tools(LLM_TOOLS)


def answer_turn(messages: list) -> str:
    for _ in range(MAX_STEPS):
        resp = client.messages.create(
            model=MODEL, max_tokens=2048, system=SYSTEM_CACHED,
            messages=_cache_messages_tail(messages), tools=LLM_TOOLS_CACHED,
        )
        messages.append({"role": "assistant", "content": resp.content})

        tool_calls = [b for b in resp.content if b.type == "tool_use"]
        if not tool_calls:
            return "".join(b.text for b in resp.content if b.type == "text").strip()

        results = []
        for call in tool_calls:
            print(f"  → {call.name}({_fmt(call.input)})")
            try:
                output = dispatch(call.name, call.input)
            except Exception as e:
                output = f"Tool error in {call.name}: {e}"
            results.append({"type": "tool_result", "tool_use_id": call.id, "content": output})
        messages.append({"role": "user", "content": results})

    return "(stopped: hit the step budget without finishing)"


def _fmt(ti: dict) -> str:
    parts = []
    for k, v in ti.items():
        s = str(v).replace("\n", " ")
        parts.append(f"{k}={s[:57] + '...' if len(s) > 60 else s}")
    return ", ".join(parts)


def repl() -> None:
    print("English-habit coach. Give me a transcript and I'll diagnose your habits.")
    print("Commands:  exit / quit  ·  reset (clear the conversation)\n")
    messages: list = []
    while True:
        try:
            q = input("you › ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not q:
            continue
        if q.lower() in {"exit", "quit", ":q"}:
            break
        if q.lower() in {"reset", "clear", "new"}:
            messages.clear()
            print("(conversation reset)\n")
            continue
        messages.append({"role": "user", "content": q})
        print(f"\n{answer_turn(messages)}\n")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
        print(f"Q: {question}\n")
        print(answer_turn([{"role": "user", "content": question}]))
    else:
        repl()
