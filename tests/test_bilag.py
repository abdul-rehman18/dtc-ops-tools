import json
import pathlib
import re
import shutil

from dtc_ops.bilag.extract import pdf_text, read_with_rules
from dtc_ops.bilag.run import run
from dtc_ops.llm import ClaudeWriter

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "sample"


def honest_claude(tweak=None):
    """A fake Claude that reads correctly and quotes real lines. `tweak` lets a test make it wrong."""
    def call(system, user):
        text = user.split("<<<\n", 1)[1].rsplit("\n>>>", 1)[0]
        data = read_with_rules(text)
        lines = text.splitlines()
        data["evidence"] = {
            "invoice_no": next(l for l in lines if data["invoice_no"] in l),
            "total": next(l for l in lines if re.search(r"total", l, re.I) and f"{data['total']:.2f}" in l),
            "lines": [l for l in lines if " qty " in l],
            "charges": [l for l in lines if any(f"{c['amount']:.2f}" in l for c in data["charges"])],
        }
        if tweak:
            tweak(data)
        return json.dumps(data)
    return ClaudeWriter(call=call)


def statuses(out):
    return {r["invoice_no"]: r["status"] for r in out["results"]}


def test_code_read_handles_a_charge_line_with_a_digit():
    inv = read_with_rules(pdf_text(DATA / "inbox" / "INV-NF-77102.pdf"))
    assert len(inv["charges"]) == 4
    assert sum(c["amount"] for c in inv["charges"]) == inv["total"]


def test_two_agreeing_reads_book_the_clean_invoices_and_hold_the_two_problems(tmp_path):
    out = run(DATA, tmp_path, honest_claude())
    assert statuses(out) == {"NF-77102": "HOLD", "NF-77118": "READY", "NST-88231": "HOLD",
                             "NST-88240": "READY", "YGP-4410": "READY"}
    text = out["summary"]
    assert "counted 1000, 60 units extra" in text
    assert "Port storage" in text and "1,500.00 more" in text


def test_a_misread_total_is_held_not_booked(tmp_path):
    def misread(d):
        if d["invoice_no"] == "NST-88240":
            d["total"] = 3670.00
    out = run(DATA, tmp_path, honest_claude(misread))
    r = next(r for r in out["results"] if r["invoice_no"] == "NST-88240")
    assert r["status"] == "HOLD"
    assert any("two reads disagree" in x for x in r["reasons"])


def test_claude_quoting_text_not_in_the_pdf_is_thrown_out(tmp_path):
    def invent(d):
        d["evidence"]["total"] = "Invoice total: USD 9999.00"
    out = run(DATA, tmp_path, honest_claude(invent))
    assert all(r["status"] == "HOLD" for r in out["results"])
    assert all(r["reads"] == "code" for r in out["results"])


def test_with_one_read_nothing_is_booked(tmp_path):
    out = run(DATA, tmp_path, writer=None)
    assert set(statuses(out).values()) == {"HOLD"}


def test_rerun_skips_processed_files_and_catches_a_resent_invoice(tmp_path):
    data = tmp_path / "data"
    shutil.copytree(DATA, data)
    run(data, tmp_path / "work", honest_claude())
    again = run(data, tmp_path / "work", honest_claude())
    assert again["results"] == []
    shutil.copy(data / "inbox" / "INV-YGP-4410.pdf", data / "inbox" / "INV-YGP-4410-resent.pdf")
    third = run(data, tmp_path / "work", honest_claude())
    assert third["results"][0]["status"] == "HOLD"
    assert "already booked" in third["results"][0]["reasons"][0]
