"""Invoice (bilag) reconciliation run.

    python -m dtc_ops.bilag.run            # Claude as second reader if ANTHROPIC_API_KEY is set
    python -m dtc_ops.bilag.run --no-llm   # code read only (invoices are held: one read is not enough)
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib

from dotenv import load_dotenv

from dtc_ops.bilag.extract import compare_reads, pdf_text, read_with_claude, read_with_rules
from dtc_ops.bilag.reconcile import load_reference, reconcile
from dtc_ops.llm import ClaudeWriter

ROOT = pathlib.Path(__file__).resolve().parents[2]
REGISTER_COLUMNS = ["invoice_no", "file", "status", "currency", "total", "reference", "reads", "reasons"]


def run(data_dir: pathlib.Path, work_dir: pathlib.Path, writer=None, require_two_reads=True) -> dict:
    ref = load_reference(data_dir / "ledger")
    register_path = work_dir / "bilag_register.csv"
    booked = set()
    seen_files = set()
    if register_path.exists():
        with register_path.open() as fh:
            for r in csv.DictReader(fh):
                seen_files.add(r["file"])
                if r["status"] == "READY":
                    booked.add(r["invoice_no"])

    results = []
    for pdf in sorted((data_dir / "inbox").glob("*.pdf")):
        if pdf.name in seen_files:
            continue  # delta: each PDF is processed once
        text = pdf_text(pdf)
        a = read_with_rules(text)
        b, b_problems = read_with_claude(text, writer)
        reads = "code" + ("+claude" if b else "")
        hold = []
        if a is None and b is None:
            results.append({"file": pdf.name, "invoice_no": "?", "status": "HOLD", "reads": "none",
                            "reasons": ["could not read this invoice"] + b_problems, "inv": None})
            continue
        if a is not None and b is not None:
            hold += [f"the two reads disagree: {d}" for d in compare_reads(a, b)]
        elif require_two_reads:
            hold.append("only one read succeeded (" + ("; ".join(b_problems) or "code could not read layout") + ")")
        inv = a or b
        rec = reconcile(inv, ref, booked)
        reasons = hold + rec["reasons"]
        status = "READY" if not reasons else "HOLD"
        if status == "READY":
            booked.add(inv["invoice_no"])
        results.append({"file": pdf.name, "invoice_no": inv["invoice_no"], "status": status, "reads": reads,
                        "reasons": reasons, "checks": rec["checks"], "inv": inv})

    work_dir.mkdir(parents=True, exist_ok=True)
    new_file = not register_path.exists()
    with register_path.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=REGISTER_COLUMNS)
        if new_file:
            w.writeheader()
        for r in results:
            inv = r["inv"] or {}
            w.writerow({"invoice_no": r["invoice_no"], "file": r["file"], "status": r["status"],
                        "currency": inv.get("currency", ""), "total": inv.get("total", ""),
                        "reference": inv.get("po_number") or inv.get("shipment_id") or "",
                        "reads": r["reads"], "reasons": " | ".join(r["reasons"])})
    (work_dir / "bilag_last_run.json").write_text(json.dumps(results, indent=2, default=str))
    return {"results": results, "summary": summary(results)}


def summary(results) -> str:
    held = [r for r in results if r["status"] == "HOLD"]
    ready = [r for r in results if r["status"] == "READY"]
    lines = []
    for r in held:
        lines.append(f"🟡 *Held, not booked: {r['invoice_no']}*")
        lines += [f"• {reason}" for reason in r["reasons"]]
        lines.append("")
    if ready:
        lines.append(f"🟢 *Ready to book: {len(ready)} invoice{'s' if len(ready) != 1 else ''}*")
        lines.append(", ".join(r["invoice_no"] for r in ready))
    if not results:
        lines.append("No new invoices since the last run.")
    return "\n".join(lines).strip()


def main():
    load_dotenv(ROOT / ".env")
    p = argparse.ArgumentParser(description="Invoice reconciliation")
    p.add_argument("--data-dir", default=str(ROOT / "data" / "sample"))
    p.add_argument("--work-dir", default=str(ROOT / "work" / "bilag"))
    p.add_argument("--no-llm", action="store_true")
    a = p.parse_args()
    writer = None if a.no_llm else ClaudeWriter()
    out = run(pathlib.Path(a.data_dir), pathlib.Path(a.work_dir), writer)
    print(out["summary"])
    if writer is not None:
        print(f"\nClaude calls: {writer.usage['calls']}, tokens in {writer.usage['input_tokens']}, out {writer.usage['output_tokens']}")


if __name__ == "__main__":
    main()
