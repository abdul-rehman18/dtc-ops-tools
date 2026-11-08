"""Talks to the MCP server over stdio exactly like Claude Desktop does: JSON-RPC, one message per line."""
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVER = ROOT / "dtc_ops" / "mcp_server.py"


def converse(messages, work_dir="/tmp/dtc-ops-mcp-test"):
    env = {**os.environ, "ANTHROPIC_API_KEY": "", "DTC_WORK_DIR": str(work_dir)}  # no live Claude calls in tests
    proc = subprocess.run([sys.executable, str(SERVER)], input="\n".join(json.dumps(m) for m in messages) + "\n",
                          capture_output=True, text=True, timeout=60, cwd=str(ROOT), env=env)
    return [json.loads(l) for l in proc.stdout.splitlines() if l.strip()]


def test_handshake_list_and_call(tmp_path):
    replies = converse([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "stock_brief", "arguments": {"offline": True}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "find_fact", "arguments": {"metric": "suggested_transfer"}}},
        {"jsonrpc": "2.0", "id": 5, "method": "nonsense"},
    ], work_dir=tmp_path)
    by_id = {r["id"]: r for r in replies}
    assert len(replies) == 5  # the notification gets no reply
    assert by_id[1]["result"]["protocolVersion"] == "2025-06-18"
    assert {t["name"] for t in by_id[2]["result"]["tools"]} >= {"stock_brief", "invoice_check", "meeting_actions"}
    assert "850 units" in by_id[3]["result"]["content"][0]["text"]
    assert ",850,units," in by_id[4]["result"]["content"][0]["text"]
    assert by_id[5]["error"]["code"] == -32601


def test_unknown_protocol_version_gets_the_servers_own(tmp_path):
    r = converse([{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}}],
                 work_dir=tmp_path)
    assert r[0]["result"]["protocolVersion"] == "2025-11-25"
