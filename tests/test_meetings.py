import datetime as dt
import json
import pathlib

from dtc_ops.llm import ClaudeWriter
from dtc_ops.meetings.digest import build_digest, render, resolve_due

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEXT = (ROOT / "data/sample/meetings/2026-11-05-weekly-ops.txt").read_text(encoding="utf-8")
MEETING = dt.date(2026, 11, 5)  # a Thursday


def claude_says(payload):
    return ClaudeWriter(call=lambda s, u: json.dumps(payload))


GOOD = {
    "actions": [
        {"owner": "Jonas", "task": "Check AWD stock for the bear and send a transfer if needed", "due_text": "by Monday",
         "quotes": ["Amazon US is moving fast on the bear. I'll check the AWD numbers and send a transfer if we need it, by Monday."]},
        {"owner": "Sofie", "task": "Rewrite the size text on the whale listing and add a photo next to a pillow",
         "due_text": "by Friday next week",
         "quotes": ["Mostly the whale, people say it is bigger than they expected. I can rewrite the size text on the whale listing by Friday next week.",
                    "Do it. Add a photo next to a pillow, that helps."]},
        {"owner": "Jonas", "task": "Email Ningbo about the 60 extra units and do not pay the full invoice", "due_text": None,
         "quotes": ["Then the supplier invoice is wrong. Don't pay the full amount, I'll email Ningbo about the 60 units."]},
        {"owner": "Jonas", "task": "Send Anders the Black Friday volume forecast", "due_text": "by the 13th",
         "quotes": ["Jonas, can you send Anders the forecast?", "Sure, by the 13th."]},
    ],
    "unowned": [{"task": "Check the Nordic freight bill against the booking",
                 "quotes": ["Also the freight bill from Nordic looked high. Someone should check it against the booking."]}],
    "ideas": [{"idea": "Try TikTok Shop in Q1",
               "quotes": ["And we talked about maybe trying TikTok Shop in Q1, let's think about it."]}],
}


def test_due_dates_are_worked_out_by_code():
    assert resolve_due("by Monday", MEETING) == "Mon 09 Nov"
    assert resolve_due("by Friday next week", MEETING) == "Fri 13 Nov"
    assert resolve_due("by the 13th", MEETING) == "Fri 13 Nov"
    assert resolve_due("soon", MEETING) is None


def test_good_answer_is_accepted_with_real_dates():
    d = build_digest(TEXT, claude_says(GOOD))
    assert len(d["actions"]) == 4 and len(d["unowned"]) == 1 and len(d["ideas"]) == 1
    text = render(d)
    assert "Send Anders the Black Friday volume forecast (by Fri 13 Nov)" in text
    assert "Email Ningbo" in text and "(no date said)" in text


def test_yeah_does_not_make_someone_the_owner():
    bad = json.loads(json.dumps(GOOD))
    bad["unowned"] = []
    bad["actions"].append({"owner": "Jonas", "task": "Check the freight bill", "due_text": None,
                           "quotes": ["Also the freight bill from Nordic looked high. Someone should check it against the booking.",
                                      "Yeah."]})
    d = build_digest(TEXT, claude_says(bad))
    assert not any("freight" in a["task"].lower() for a in d["actions"])
    assert any("freight" in u["task"].lower() and "never clearly took this on" in u["why"] for u in d["unowned"])


def test_invented_quote_is_not_accepted():
    bad = json.loads(json.dumps(GOOD))
    bad["actions"][0]["quotes"] = ["I'll send the transfer of 900 units tonight."]
    d = build_digest(TEXT, claude_says(bad))
    assert not any("AWD" in a["task"] for a in d["actions"])
    assert any("not in the transcript" in u["why"] for u in d["unowned"])


def test_deadline_must_come_from_what_was_said():
    bad = json.loads(json.dumps(GOOD))
    bad["actions"][2]["due_text"] = "by Wednesday"
    d = build_digest(TEXT, claude_says(bad))
    assert not any("Ningbo" in a["task"] for a in d["actions"])


def test_cut_off_reply_is_retried_then_used():
    replies = ['{"actions": [{"owner": "Jonas", "task": "Check AWD', json.dumps(GOOD)]
    d = build_digest(TEXT, ClaudeWriter(call=lambda s, u: replies.pop(0)))
    assert len(d["actions"]) == 4
    assert len(d["failures"]) == 1


def test_two_broken_replies_give_a_clear_note_not_a_crash():
    d = build_digest(TEXT, ClaudeWriter(call=lambda s, u: '{"actions": ['))
    assert d["actions"] == [] and len(d["failures"]) == 2
    assert "needs a person" in render(d)
