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
- log_errors — after you diagnose grammar/usage mistakes, record them classified into the \
fixed categories so recurring mistakes are tracked over time. Always log what you found.
- my_weaknesses — see which mistakes recur across sessions; use it to personalize advice \
('this is the 3rd session with verb-agreement slips').
- add_vocab / list_vocab / mark_vocab — maintain a vocabulary notebook. When the student \
overuses a word, add an upgrade word with a note; track learning vs known.
- create_practice / grade_practice — close the loop: generate a short targeted drill for \
the student's top weakness (fill-in-the-blank with answers), and grade their responses.

When diagnosing, give the student's top habits to fix (counts/quotes as evidence) and one \
concrete practice tip each, then log the errors. Be encouraging, specific, personalized."""


def answer_turn(messages: list) -> str:
    for _ in range(MAX_STEPS):
        resp = client.messages.create(
            model=MODEL, max_tokens=2048, system=SYSTEM,
            messages=messages, tools=TOOLS,
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
