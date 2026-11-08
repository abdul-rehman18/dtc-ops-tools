"""Meeting action item digest.

Claude proposes action items. Code then checks each one against the transcript:
  - every quote must be a real line of the transcript, word for word
  - the owner must have said one of the quoted lines, or be named in one
    ("Someone should check it" and "Yeah" do not make anyone the owner)
  - the due date must be in the quoted words, and code (not Claude) turns it into a calendar date
Items that fail are not dropped silently: they go to "No owner yet" so a person sees them.

    python -m dtc_ops.meetings.digest data/sample/meetings/2026-11-05-weekly-ops.txt
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re

from dotenv import load_dotenv

from dtc_ops.llm import ClaudeWriter, parse_json_reply

ROOT = pathlib.Path(__file__).resolve().parents[2]
LINE = re.compile(r"^\[(\d\d:\d\d)\]\s+([^:]+):\s+(.*)$")
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

SYSTEM = """You turn a meeting transcript into an action list for a small online brand.
Return JSON only:
{"actions": [{"owner": str, "task": str, "due_text": str or null, "quotes": [str]}],
 "unowned": [{"task": str, "quotes": [str]}],
 "ideas": [{"idea": str, "quotes": [str]}]}
Rules:
- "actions" are things a named person clearly agreed to do. Agreement means they said they will, or said yes when asked.
- "unowned" are things someone said should happen but nobody clearly took on. A reply like "Yeah" or "ok" is not taking it on.
- "ideas" are maybes and things to think about, not tasks.
- quotes: copy the full spoken text of each supporting line exactly, without the time stamp or speaker name.
  Include the owner's own line where they agree.
- due_text: copy the deadline words exactly as spoken (for example "by Monday"), or null if none was said.
- Write task in plain words, starting with a verb. Do not add details that were not said."""


def parse_transcript(text: str):
    first = text.splitlines()[0]
    m = re.search(r"(\d{1,2}) (January|February|March|April|May|June|July|August|September|October|November|December) (\d{4})", first)
    meeting_date = dt.datetime.strptime(" ".join(m.groups()), "%d %B %Y").date() if m else None
    lines = []
    for raw in text.splitlines():
        if (lm := LINE.match(raw.strip())):
            lines.append({"time": lm.group(1), "speaker": lm.group(2).strip(), "text": lm.group(3).strip()})
    return meeting_date, lines


def resolve_due(due_text: str | None, meeting: dt.date | None) -> str | None:
    """Turn spoken deadlines into dates with fixed rules. Anything it does not understand stays as words."""
    if not due_text or not meeting:
        return None
    t = due_text.lower()
    if m := re.search(r"the (\d{1,2})(?:st|nd|rd|th)", t):
        day = int(m.group(1))
        d = meeting.replace(day=day)
        if d < meeting:
            d = (d.replace(day=1) + dt.timedelta(days=32)).replace(day=day)
        return d.strftime("%a %d %b")
    for i, name in enumerate(WEEKDAYS):
        if name in t:
            ahead = (i - meeting.weekday()) % 7 or 7
            d = meeting + dt.timedelta(days=ahead)
            if "next week" in t and d - meeting < dt.timedelta(days=7) and (d.isocalendar()[1] == meeting.isocalendar()[1]):
                d += dt.timedelta(days=7)
            return d.strftime("%a %d %b")
    return None


def verify(item: dict, lines: list[dict], owner_required: bool) -> list[str]:
    problems = []
    found = []
    for q in item.get("quotes", []):
        hit = next((l for l in lines if " ".join(q.split()) == " ".join(l["text"].split())), None)
        if hit is None:
            problems.append(f"quote not in the transcript: {q!r}")
        else:
            found.append(hit)
    if not found:
        problems.append("no supporting line from the transcript")
    if owner_required:
        owner = item.get("owner", "").strip().lower()
        spoke = any(l["speaker"].lower() == owner and not re.fullmatch(r"(yeah|yes|ok|okay|sure)[.!]?", l["text"].lower())
                    for l in found)
        named = any(owner and re.search(rf"\b{re.escape(owner)}\b", l["text"].lower()) for l in found)
        agreed = any(l["speaker"].lower() == owner for l in found)
        if not (spoke or (named and agreed)):
            problems.append(f"{item.get('owner')} never clearly took this on")
        if item.get("due_text") and not any(item["due_text"].lower() in l["text"].lower() for l in found):
            problems.append(f"deadline {item['due_text']!r} is not in the quoted lines")
    return problems


def build_digest(text: str, writer) -> dict:
    meeting, lines = parse_transcript(text)
    if writer is None or not writer.available:
        return {"meeting": str(meeting), "actions": [], "unowned": [], "ideas": [], "rejected": [],
                "note": "Claude not available. No action items extracted, the transcript needs a person."}
    data, prompt, failures = None, f"Transcript:\n<<<\n{text}\n>>>", []
    for attempt in (1, 2):
        raw = writer._call(SYSTEM, prompt)
        writer.usage["calls"] += 1
        try:
            data = parse_json_reply(raw)
            break
        except ValueError as e:
            failures.append({"attempt": attempt, "error": str(e), "stop_reason": writer.last_stop_reason,
                             "reply_chars": len(raw), "reply": raw})
            prompt += "\n\nYour last reply was not complete, valid JSON. Reply again with JSON only, and keep task text short."
    if data is None:
        return {"meeting": str(meeting), "actions": [], "unowned": [], "ideas": [], "rejected": [],
                "failures": failures,
                "note": "Claude did not return a usable answer twice, so nothing was extracted. "
                        "The transcript needs a person this week. Details are saved in the work folder."}

    out = {"meeting": str(meeting), "actions": [], "unowned": [], "ideas": [], "rejected": []}
    if failures:
        out["failures"] = failures  # kept so a person can see Claude needed a second try
    for a in data.get("actions", []):
        problems = verify(a, lines, owner_required=True)
        if problems:
            # Not dropped: shown to a person as needing an owner, with the reason.
            out["unowned"].append({"task": a.get("task"), "quotes": a.get("quotes", []), "why": "; ".join(problems)})
            continue
        a["due"] = resolve_due(a.get("due_text"), meeting)
        out["actions"].append(a)
    for u in data.get("unowned", []):
        problems = verify(u, lines, owner_required=False)
        (out["rejected"] if problems else out["unowned"]).append({**u, "why": "; ".join(problems) or "nobody took it on"})
    for i in data.get("ideas", []):
        if not verify(i, lines, owner_required=False):
            out["ideas"].append(i)
    return out


def render(d: dict) -> str:
    lines = [f"*Actions from the meeting on {d['meeting']}*", ""]
    by_owner = {}
    for a in d["actions"]:
        by_owner.setdefault(a["owner"], []).append(a)
    for owner, items in by_owner.items():
        lines.append(f"*{owner}*")
        for a in items:
            due = f" (by {a['due']})" if a.get("due") else (f" ({a['due_text']})" if a.get("due_text") else " (no date said)")
            lines.append(f"• {a['task']}{due}")
        lines.append("")
    if d["unowned"]:
        lines.append("🟡 *No owner yet, someone needs to pick these up*")
        lines += [f"• {u['task']}" for u in d["unowned"]]
        lines.append("")
    if d["ideas"]:
        lines.append("💭 *Ideas mentioned, not tasks*")
        lines += [f"• {i['idea']}" for i in d["ideas"]]
    if d.get("note"):
        lines.append(d["note"])
    return "\n".join(lines).strip()


def main():
    load_dotenv(ROOT / ".env")
    p = argparse.ArgumentParser(description="Meeting action item digest")
    p.add_argument("transcript", nargs="?", default=str(ROOT / "data/sample/meetings/2026-11-05-weekly-ops.txt"))
    p.add_argument("--work-dir", default=str(ROOT / "work" / "meetings"))
    a = p.parse_args()
    writer = ClaudeWriter()
    d = build_digest(pathlib.Path(a.transcript).read_text(encoding="utf-8"), writer)
    work = pathlib.Path(a.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    (work / (pathlib.Path(a.transcript).stem + ".json")).write_text(json.dumps(d, indent=2))
    print(render(d))
    for f in d.get("failures", []):
        print(f"\nAttempt {f['attempt']} failed: {f['error']} (stop reason: {f['stop_reason']}, reply length {f['reply_chars']} characters)")
    if d["rejected"]:
        print(f"\n({len(d['rejected'])} suggestion(s) from Claude were thrown out because their quotes were not in the transcript)")
    print(f"\nClaude calls: {writer.usage['calls']}, tokens in {writer.usage['input_tokens']}, out {writer.usage['output_tokens']}")


if __name__ == "__main__":
    main()
