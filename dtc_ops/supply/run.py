"""Supply chain sync: the daily run.

    python -m dtc_ops.supply.run                    # live Shopify, sample Amazon files, Claude if a key is set
    python -m dtc_ops.supply.run --offline          # saved Shopify snapshot instead of the live store
    python -m dtc_ops.supply.run --no-llm           # skip Claude, use the plain template
    python -m dtc_ops.supply.run --post             # also post to Slack (SLACK_WEBHOOK_URL)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import sys

import requests
from dotenv import load_dotenv

from dtc_ops.ledger import FactLedger, OrderLineStore, RunState
from dtc_ops.llm import ClaudeWriter
from dtc_ops.supply import amazon_source as amz
from dtc_ops.supply.brief import build_brief
from dtc_ops.supply.metrics import build_facts
from dtc_ops.supply.shopify_source import ShopifyClient, fixture_transport

ROOT = pathlib.Path(__file__).resolve().parents[2]
EPOCH = "2000-01-01T00:00:00+00:00"


def run(as_of: dt.date, data_dir: pathlib.Path, work_dir: pathlib.Path, shopify: ShopifyClient,
        writer=None, include_test_orders=True) -> dict:
    state = RunState(work_dir / "state.json")
    store = OrderLineStore(work_dir / "order_lines.csv")
    counts = {"new": 0, "updated": 0, "duplicate": 0, "stale": 0}

    # 1. Only what changed since last run.
    amz_lines, amz_newest, amz_skipped = amz.read_order_lines_since(
        data_dir / "amazon" / "all_orders_by_order_date.tsv", state.get("amazon_orders_cursor", EPOCH))
    shop_lines, shop_newest = shopify.order_lines_since(state.get("shopify_orders_cursor", "2000-01-01T00:00:00Z"),
                                                        include_test=include_test_orders)
    for line in amz_lines + shop_lines:
        counts[store.upsert(line)] += 1

    # 2. Current stock (small, read in full every run).
    stock = {
        "amazon_us": amz.read_fba_inventory(data_dir / "amazon" / "fba_inventory_US.tsv"),
        "amazon_de": amz.read_fba_inventory(data_dir / "amazon" / "fba_inventory_DE.tsv"),
        "shopify": shopify.inventory(),
    }
    awd = amz.read_awd_inventory(data_dir / "amazon" / "awd_inventory.json")
    transfers = amz.read_transfer_history(data_dir / "ledger" / "awd_transfers.csv")
    sources = {"amazon_us": "fba_inventory_US.tsv", "amazon_de": "fba_inventory_DE.tsv",
               "shopify": "Shopify Admin API", "awd": "awd_inventory.json"}

    # 3. Numbers into the ledger, then check the ledger before anything is written for people.
    ledger = FactLedger()
    findings = build_facts(ledger, store, stock, awd, transfers, as_of, sources)
    names = amz.read_product_names(data_dir / "amazon" / "fba_inventory_US.tsv")
    for f in findings:
        f["name"] = names.get(f["sku"], f["sku"])
    problems = ledger.validate()
    if problems:
        raise SystemExit("Ledger failed validation, brief NOT sent:\n" + "\n".join(problems))

    brief, how, log = build_brief(ledger, findings, writer)

    # 4. Save everything. Cursors move only after a clean run.
    stamp = as_of.isoformat()
    ledger.write_csv(work_dir / f"facts_{stamp}.csv")
    (work_dir / f"brief_{stamp}.md").write_text(brief, encoding="utf-8")
    store.save()
    state.set("amazon_orders_cursor", amz_newest)
    state.set("shopify_orders_cursor", shop_newest)
    state.set("last_run", stamp)
    state.save()

    report = {
        "as_of": stamp, "written_by": how, "grounding_log": log,
        "order_lines_read": len(amz_lines) + len(shop_lines), "amazon_rows_skipped_unchanged": amz_skipped,
        "merge": counts, "shopify_api_calls": shopify.calls, "facts": len(ledger.facts),
        "attention": sum(1 for f in findings if f["level"] != "green"),
        "claude_usage": getattr(writer, "usage", None),
    }
    (work_dir / f"run_{stamp}.json").write_text(json.dumps(report, indent=2))
    return {"brief": brief, "report": report}


def main():
    load_dotenv(ROOT / ".env")
    p = argparse.ArgumentParser(description="Daily supply chain sync and brief")
    p.add_argument("--as-of", default="2026-11-08", help="run date (sample data is built around 2026-11-08)")
    p.add_argument("--data-dir", default=str(ROOT / "data" / "sample"))
    p.add_argument("--work-dir", default=str(ROOT / "work" / "supply"))
    p.add_argument("--offline", action="store_true", help="use the saved Shopify snapshot in tests/fixtures")
    p.add_argument("--no-llm", action="store_true")
    p.add_argument("--post", action="store_true", help="post the brief to SLACK_WEBHOOK_URL")
    a = p.parse_args()

    transport = fixture_transport(ROOT / "tests" / "fixtures") if a.offline else None
    shopify = ShopifyClient(transport=transport)
    if not a.offline and not (shopify.store and shopify.client_id and shopify.client_secret):
        sys.exit("Shopify details missing in .env (or run with --offline)")
    writer = None if a.no_llm else ClaudeWriter()

    out = run(dt.date.fromisoformat(a.as_of), pathlib.Path(a.data_dir), pathlib.Path(a.work_dir), shopify, writer)
    print(out["brief"])
    print("\n---\n" + json.dumps(out["report"], indent=2))

    if a.post:
        url = os.environ.get("SLACK_WEBHOOK_URL")
        if not url:
            sys.exit("SLACK_WEBHOOK_URL not set, brief saved but not posted")
        requests.post(url, json={"text": out["brief"]}, timeout=15).raise_for_status()
        print("Posted to Slack.")


if __name__ == "__main__":
    main()
