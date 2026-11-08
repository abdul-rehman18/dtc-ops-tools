"""Read an invoice PDF twice, independently, and only trust what both reads agree on.

Read A: plain code (pdfplumber text + patterns). Predictable, but only knows layouts it was written for.
Read B: Claude, given the PDF text. Handles new layouts, but can misread.
Every value Claude returns must also appear word for word in the PDF text, or it is thrown out.
If the two reads disagree on any number, the invoice is held for a person.
"""
from __future__ import annotations

import json
import re

import pdfplumber

from dtc_ops.llm import parse_json_reply

NUM = r"([\d.,]+)"


def pdf_text(path) -> str:
    with pdfplumber.open(str(path)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def read_with_rules(text: str) -> dict | None:
    """Read A. Returns None if the layout is not one it knows."""
    inv = re.search(r"(?:Invoice no|Faktura nr):\s*(\S+)", text)
    date = re.search(r"(?:Invoice date|Dato):\s*(\d{4}-\d{2}-\d{2})", text)
    total = re.search(r"(?:Invoice total|Total)\s*:?\s*(USD|DKK|EUR)\s*" + NUM, text)
    if not (inv and date and total):
        return None
    out = {"invoice_no": inv.group(1), "date": date.group(1), "currency": total.group(1),
           "total": _num(total.group(2)), "po_number": None, "shipment_id": None, "lines": [], "charges": []}
    if m := re.search(r"Buyer PO:\s*(\S+)", text):
        out["po_number"] = m.group(1)
    if m := re.search(r"Shipment:\s*(\S+)", text):
        out["shipment_id"] = m.group(1)
    for m in re.finditer(r"^([A-Z]{3}\d{2})\s.*?qty\s+(\d+)\s+unit\s+(USD|DKK|EUR)\s+" + NUM + r"\s+total\s+\3\s+" + NUM,
                         text, re.M):
        out["lines"].append({"sku": m.group(1), "qty": int(m.group(2)), "unit_price": _num(m.group(4)),
                             "line_total": _num(m.group(5))})
    for m in re.finditer(r"^(?!Total)([A-Za-z][A-Za-z0-9 ]+?)\s+(DKK|EUR|USD)\s+" + NUM + r"$", text, re.M):
        out["charges"].append({"description": m.group(1).strip(), "amount": _num(m.group(3))})
    return out


EXTRACT_SYSTEM = """You read supplier and freight invoices for a small online brand.
Return JSON only, with this shape:
{"invoice_no": str, "date": "YYYY-MM-DD", "currency": str, "total": number,
 "po_number": str or null, "shipment_id": str or null,
 "lines": [{"sku": str, "qty": int, "unit_price": number, "line_total": number}],
 "charges": [{"description": str, "amount": number}],
 "evidence": {"invoice_no": str, "total": str, "lines": [str], "charges": [str]}}
"lines" are product lines with a SKU. "charges" are service lines without a SKU (freight, handling, storage).
"evidence" must hold the exact line of text each value was copied from, unchanged.
Copy values exactly as printed. Do not calculate, correct or fill anything in. If a value is not printed, use null."""


def read_with_claude(text: str, writer) -> tuple[dict | None, list[str]]:
    """Read B. Returns (result, problems). Rejects anything not backed by the PDF text."""
    if writer is None or not writer.available:
        return None, ["Claude not available, only one read"]
    writer.usage["calls"] += 1
    raw = writer._call(EXTRACT_SYSTEM, f"Invoice text:\n<<<\n{text}\n>>>")
    try:
        data = parse_json_reply(raw)
    except ValueError as e:
        return None, [f"Claude reply was not JSON ({e})"]
    problems = []
    ev = data.get("evidence") or {}
    quoted = [ev.get("invoice_no", ""), ev.get("total", "")] + list(ev.get("lines", [])) + list(ev.get("charges", []))
    flat = " ".join(text.split())
    for q in quoted:
        if q and " ".join(str(q).split()) not in flat:
            problems.append(f"Claude quoted text that is not in the PDF: {q!r}")
    if data.get("invoice_no") and data["invoice_no"] not in text:
        problems.append(f"invoice number {data['invoice_no']!r} is not in the PDF")
    return (None if problems else data), problems


def compare_reads(a: dict, b: dict) -> list[str]:
    """Every field that matters must match between the two reads."""
    diffs = []
    for k in ("invoice_no", "date", "currency", "total", "po_number", "shipment_id"):
        if _norm(a.get(k)) != _norm(b.get(k)):
            diffs.append(f"{k}: code read {a.get(k)!r}, Claude read {b.get(k)!r}")
    la = {(l["sku"], l["qty"], _norm(l["unit_price"]), _norm(l["line_total"])) for l in a["lines"]}
    lb = {(l["sku"], int(l["qty"]), _norm(l["unit_price"]), _norm(l["line_total"])) for l in b.get("lines", [])}
    if la != lb:
        diffs.append(f"product lines differ: code {sorted(la)}, Claude {sorted(lb)}")
    ca = sorted(_norm(c["amount"]) for c in a["charges"])
    cb = sorted(_norm(c["amount"]) for c in b.get("charges", []))
    if ca != cb:
        diffs.append(f"charge amounts differ: code {ca}, Claude {cb}")
    return diffs


def _norm(v):
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    return v
