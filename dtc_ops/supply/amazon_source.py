"""Read Amazon report files: FBA inventory, AWD inventory and the All Orders report.

The files have the same columns as the real Amazon reports, so the brand's existing SP-API MCP server
(or a scheduled report download) can drop real files in the same folder and nothing else changes.
"""
from __future__ import annotations

import csv
import json
import pathlib

CHANNEL_BY_SALES_CHANNEL = {"Amazon.com": "amazon_us", "Amazon.de": "amazon_de"}


def read_fba_inventory(path: pathlib.Path) -> dict[str, int]:
    with path.open(encoding="utf-8") as fh:
        return {r["sku"]: int(r["afn-fulfillable-quantity"] or 0) for r in csv.DictReader(fh, delimiter="\t")}


def read_product_names(path: pathlib.Path) -> dict[str, str]:
    with path.open(encoding="utf-8") as fh:
        return {r["sku"]: r["product-name"] for r in csv.DictReader(fh, delimiter="\t")}


def read_awd_inventory(path: pathlib.Path) -> dict[str, int]:
    body = json.loads(path.read_text())
    return {i["sku"]: int(i["inventoryDetails"]["availableDistributableQuantity"]) for i in body["inventory"]}


def read_order_lines_since(path: pathlib.Path, updated_after: str) -> tuple[list[dict], str, int]:
    """Order lines whose last-updated-date is after the cursor.

    Returns (lines, newest last-updated-date seen, number of rows skipped as unchanged).
    In live use the report is requested with dataStartTime set to the cursor, so Amazon only
    sends the changed rows. Reading a full file and skipping old rows gives the same result here.
    """
    lines, newest, skipped = [], updated_after, 0
    with path.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            if r["last-updated-date"] <= updated_after:
                skipped += 1
                continue
            channel = CHANNEL_BY_SALES_CHANNEL.get(r["sales-channel"])
            if channel is None:
                continue
            newest = max(newest, r["last-updated-date"])
            lines.append({"channel": channel, "order_id": r["amazon-order-id"], "sku": r["sku"],
                          "quantity": int(r["quantity"]), "purchase_date": r["purchase-date"],
                          "last_updated": r["last-updated-date"], "status": r["order-status"],
                          "source_ref": f"{path.name} order {r['amazon-order-id']}"})
    return lines, newest, skipped


def read_transfer_history(path: pathlib.Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))
