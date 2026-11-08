"""An MCP server for the three ops tools, written from scratch on the protocol itself.

MCP over stdio is JSON-RPC 2.0, one JSON message per line. This file handles the handshake
(initialize), lists the tools (tools/list) and runs them (tools/call). No SDK, so it runs on
Python 3.9 and every line of it can be read and maintained by the team.

Claude Desktop config (claude_desktop_config.json):
  "mcpServers": {
    "dtc-ops": {
      "command": "/full/path/to/python3",
      "args": ["/full/path/to/dtc-ops-tools/dtc_ops/mcp_server.py"]
    }
  }
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os
import pathlib
import sys
import traceback

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

SUPPORTED_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]
SERVER_INFO = {"name": "dtc-ops", "version": "0.1.0"}
DATA = ROOT / "data" / "sample"
WORK = pathlib.Path(os.environ.get("DTC_WORK_DIR", str(ROOT / "work")))


# ---------- the tools -------------------------------------------------------------------------

def tool_stock_brief(as_of: str = "2026-11-08", offline: bool = False) -> str:
    from dtc_ops.llm import ClaudeWriter
    from dtc_ops.supply.run import run
    from dtc_ops.supply.shopify_source import ShopifyClient, fixture_transport

    shop = ShopifyClient(transport=fixture_transport(ROOT / "tests" / "fixtures") if offline else None)
    out = run(dt.date.fromisoformat(as_of), DATA, WORK / "supply", shop, ClaudeWriter())
    r = out["report"]
    return (f"{out['brief']}\n\n(run {r['as_of']}: written by {r['written_by']}, "
            f"{r['order_lines_read']} changed order lines read, {r['amazon_rows_skipped_unchanged']} unchanged skipped, "
            f"{r['facts']} facts in the ledger)")


def tool_explain_number(fact_id: str, as_of: str = "2026-11-08") -> str:
    """Follow a number back to its source, one step at a time."""
    path = WORK / "supply" / f"facts_{as_of}.csv"
    if not path.exists():
        return f"No ledger for {as_of}. Run stock_brief first."
    with path.open(encoding="utf-8") as fh:
        facts = {r["fact_id"]: r for r in csv.DictReader(fh)}
    lines, todo, seen = [], [fact_id], set()
    while todo:
        fid = todo.pop(0)
        if fid in seen or fid not in facts:
            continue
        seen.add(fid)
        f = facts[fid]
        lines.append(f"{fid}  {f['metric']} {f['sku']} {f['channel']} = {f['value']} {f['unit']}\n"
                     f"      source: {f['source']} ({f['source_ref']}); method: {f['method']}")
        todo += [t.strip(" ,()x/-") for t in f"{f['source_ref']} {f['method']}".split() if t.strip(" ,()x/-") in facts]
    return "\n".join(lines) if lines else f"{fact_id} is not in the ledger for {as_of}."


def tool_find_fact(metric: str, sku: str = "", channel: str = "", as_of: str = "2026-11-08") -> str:
    path = WORK / "supply" / f"facts_{as_of}.csv"
    if not path.exists():
        return f"No ledger for {as_of}. Run stock_brief first."
    with path.open(encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["metric"] == metric
                and (not sku or r["sku"] == sku) and (not channel or r["channel"] == channel)]
    if not rows:
        return "No matching facts."
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["fact_id", "metric", "sku", "channel", "value", "unit", "source"])
    w.writeheader()
    for r in rows:
        w.writerow({k: r[k] for k in w.fieldnames})
    return buf.getvalue()


def tool_invoice_check() -> str:
    from dtc_ops.bilag.run import run
    from dtc_ops.llm import ClaudeWriter

    out = run(DATA, WORK / "bilag", ClaudeWriter())
    return out["summary"]


def tool_meeting_actions(transcript: str = "") -> str:
    from dtc_ops.llm import ClaudeWriter
    from dtc_ops.meetings.digest import build_digest, render

    path = pathlib.Path(transcript) if transcript else DATA / "meetings" / "2026-11-05-weekly-ops.txt"
    if not path.is_absolute():
        path = ROOT / path
    return render(build_digest(path.read_text(encoding="utf-8"), ClaudeWriter()))


TOOLS = {
    "stock_brief": {
        "fn": tool_stock_brief,
        "description": "Run the daily stock check across Shopify, Amazon FBA and AWD and return the brief. "
                       "Every number in the result comes from the ledger. Only reads what changed since the last run.",
        "schema": {"type": "object", "properties": {
            "as_of": {"type": "string", "description": "Run date YYYY-MM-DD. Sample data is built around 2026-11-08."},
            "offline": {"type": "boolean", "description": "Use the saved Shopify snapshot instead of the live store."}}},
    },
    "explain_number": {
        "fn": tool_explain_number,
        "description": "Show where a number in the brief came from: its source file or API and how it was calculated, "
                       "following each step back to raw data.",
        "schema": {"type": "object", "required": ["fact_id"], "properties": {
            "fact_id": {"type": "string", "description": "Ledger id like f012"},
            "as_of": {"type": "string"}}},
    },
    "find_fact": {
        "fn": tool_find_fact,
        "description": "Look up numbers in the ledger by metric (on_hand, sales_per_day, days_of_cover, runs_out_around, "
                       "suggested_transfer, awd_available), optionally filtered by SKU and channel "
                       "(amazon_us, amazon_de, shopify). Use this instead of guessing any number.",
        "schema": {"type": "object", "required": ["metric"], "properties": {
            "metric": {"type": "string"}, "sku": {"type": "string"}, "channel": {"type": "string"},
            "as_of": {"type": "string"}}},
    },
    "invoice_check": {
        "fn": tool_invoice_check,
        "description": "Read new invoice PDFs twice (code and Claude), match them to purchase orders, warehouse counts and "
                       "freight bookings, and return which are ready to book and which are held, with the reason.",
        "schema": {"type": "object", "properties": {}},
    },
    "meeting_actions": {
        "fn": tool_meeting_actions,
        "description": "Turn a meeting transcript into a checked action list: who agreed to what and by when, "
                       "plus things nobody took on and ideas that are not tasks.",
        "schema": {"type": "object", "properties": {
            "transcript": {"type": "string", "description": "Path to a transcript file. Defaults to the sample meeting."}}},
    },
}


# ---------- the protocol ----------------------------------------------------------------------

def handle(msg: dict):
    """Return a response dict, or None for notifications (which get no reply)."""
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if mid is None:
        return None  # notifications such as notifications/initialized

    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def err(code, message):
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}

    if method == "initialize":
        asked = params.get("protocolVersion")
        version = asked if asked in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
        return ok({"protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": SERVER_INFO,
                   "instructions": "Ops tools for a DTC brand. Never state a stock, sales or money number that did not "
                                   "come from one of these tools. Use find_fact or explain_number when asked about a number."})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": [{"name": n, "description": t["description"], "inputSchema": t["schema"]}
                             for n, t in TOOLS.items()]})
    if method == "tools/call":
        name = params.get("name")
        if name not in TOOLS:
            return err(-32602, f"Unknown tool: {name}")
        try:
            text = TOOLS[name]["fn"](**(params.get("arguments") or {}))
            return ok({"content": [{"type": "text", "text": text}], "isError": False})
        except Exception as e:  # tool errors go back to Claude as a result, not a protocol error
            traceback.print_exc(file=sys.stderr)
            return ok({"content": [{"type": "text", "text": f"{name} failed: {e}"}], "isError": True})
    return err(-32601, f"Method not found: {method}")


def main():
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            reply = handle(msg)
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
