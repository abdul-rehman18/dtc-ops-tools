"""Match each invoice against what the brand agreed and what actually arrived. Plain code, no AI.

Outcome per invoice:
  READY  every check passed, safe to book
  HOLD   at least one check failed, a person decides, nothing is booked
"""
from __future__ import annotations

import csv
import pathlib

import yaml

PRICE_TOLERANCE = 0.01   # currency units, for rounding only
FREIGHT_TOLERANCE = 0.0  # freight must match the booking exactly unless someone approves


def load_reference(ledger_dir: pathlib.Path) -> dict:
    with (ledger_dir / "purchase_orders.csv").open() as fh:
        pos = list(csv.DictReader(fh))
    with (ledger_dir / "3pl_receipts.csv").open() as fh:
        receipts = list(csv.DictReader(fh))
    freight = yaml.safe_load((ledger_dir / "freight_bookings.yaml").read_text())["shipments"]
    return {"pos": pos, "receipts": receipts, "freight": {s["shipment_id"]: s for s in freight}}


def check_arithmetic(inv: dict) -> list[str]:
    out = []
    for l in inv["lines"]:
        if abs(l["qty"] * l["unit_price"] - l["line_total"]) > PRICE_TOLERANCE:
            out.append(f"{l['sku']}: {l['qty']} x {l['unit_price']} is not {l['line_total']}")
    parts = sum(l["line_total"] for l in inv["lines"]) + sum(c["amount"] for c in inv["charges"])
    if abs(parts - inv["total"]) > PRICE_TOLERANCE:
        out.append(f"lines add up to {parts:.2f} but the invoice total says {inv['total']:.2f}")
    return out


def reconcile(inv: dict, ref: dict, already_booked: set[str]) -> dict:
    checks, reasons = [], []

    def check(name, ok, detail, reason=None):
        checks.append({"check": name, "ok": ok, "detail": detail})
        if not ok:
            reasons.append(reason or detail)

    check("not booked before", inv["invoice_no"] not in already_booked,
          f"{inv['invoice_no']} not in the booked register",
          f"{inv['invoice_no']} is already booked, this looks like a duplicate")
    for problem in check_arithmetic(inv):
        check("invoice adds up", False, problem)

    if inv.get("po_number"):
        po_lines = {r["sku"]: r for r in ref["pos"] if r["po_number"] == inv["po_number"]}
        received = {r["sku"]: int(r["qty_received"]) for r in ref["receipts"] if r["po_number"] == inv["po_number"]}
        check("purchase order exists", bool(po_lines), f"{inv['po_number']} in purchase_orders.csv",
              f"no purchase order {inv['po_number']} on file")
        for l in inv["lines"]:
            po = po_lines.get(l["sku"])
            if po is None:
                check(f"{l['sku']} was ordered", False, f"{l['sku']} not on {inv['po_number']}")
                continue
            agreed = float(po["unit_cost_usd"])
            check(f"{l['sku']} price", abs(l["unit_price"] - agreed) <= PRICE_TOLERANCE,
                  f"invoice {l['unit_price']:.2f}, agreed {agreed:.2f}",
                  f"{l['sku']} billed at {l['unit_price']:.2f} each, the order says {agreed:.2f}")
            got = received.get(l["sku"])
            if got is None:
                check(f"{l['sku']} received", False, "no warehouse receipt yet",
                      f"{l['sku']} has not been counted in at the warehouse yet")
            else:
                diff = l["qty"] - got
                check(f"{l['sku']} quantity", diff == 0, f"billed {l['qty']}, warehouse counted {got}",
                      f"{l['sku']} billed for {l['qty']} but the warehouse counted {got}, "
                      f"{diff} units extra worth {inv['currency']} {diff * l['unit_price']:,.2f}")
    elif inv.get("shipment_id"):
        booking = ref["freight"].get(inv["shipment_id"])
        if booking is None:
            check("freight booking exists", False, f"no booking {inv['shipment_id']}")
        else:
            agreed = float(booking["agreed_dkk"])
            diff = inv["total"] - agreed
            extra = ""
            if diff > 0:
                # Find which charge line explains the gap, if one does exactly.
                match = [c for c in inv["charges"] if abs(c["amount"] - diff) <= PRICE_TOLERANCE]
                if match:
                    extra = f", the gap is exactly the '{match[0]['description']}' line"
            check("freight matches booking", abs(diff) <= FREIGHT_TOLERANCE,
                  f"invoice {inv['total']:,.2f}, agreed {agreed:,.2f}",
                  f"freight for {inv['shipment_id']} is {inv['currency']} {inv['total']:,.2f} but the agreed price was "
                  f"{inv['currency']} {agreed:,.2f}, {inv['currency']} {diff:,.2f} more{extra}")
    else:
        check("linked to an order or shipment", False, "no PO or shipment reference on the invoice")

    return {"invoice_no": inv["invoice_no"], "status": "READY" if not reasons else "HOLD",
            "reasons": reasons, "checks": checks}
