# DTC ops tools: Claude automations for a Shopify and Amazon brand

Three working tools built over one weekend for a sample plush toy brand that sells on Shopify and Amazon (US and DE).
**All data is sample data** from a Shopify test store and Amazon style report files. No real store, customer or supplier is involved.

| Tool | What the founders get | How it stays honest |
|---|---|---|
| Supply chain sync | A short morning brief saying what runs out before Black Friday and how many units to move from AWD | Code works out every number and keeps it in a ledger. Claude writes the sentences and may only refer to ledger numbers |
| Invoice (bilag) check | Each new invoice is either ready to book or held, with the reason in one line | Every invoice is read twice, by code and by Claude, and both reads must agree |
| Meeting action list | Who agreed to do what and by when, plus anything nobody took on | Every task must quote real lines from the transcript, and the owner must have actually agreed |

All three are also available inside Claude Desktop through an MCP server written from scratch, with three Claude Skills that tell Claude when to use them.

Case write ups with problems, architecture, safeguards, results and what broke are in [CASES.md](CASES.md).

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # add Shopify app details and an Anthropic API key
python -m pytest -q             # 25 tests

python -m dtc_ops.supply.run            # morning stock brief (add --post to send to Slack)
python -m dtc_ops.bilag.run             # invoice check
python -m dtc_ops.meetings.digest       # action list from the sample meeting
```

Without a Shopify app, add `--offline` to the supply run to use a saved snapshot of the test store.
Without an Anthropic key, the stock brief uses a fixed template and the invoice check holds everything, because one read is not enough.

## Claude Desktop

Add this to `claude_desktop_config.json`, using the Python from your virtual environment:

```json
"mcpServers": {
  "dtc-ops": {
    "command": "/path/to/dtc-ops-tools/.venv/bin/python",
    "args": ["/path/to/dtc-ops-tools/dtc_ops/mcp_server.py"]
  }
}
```

Tools exposed: `stock_brief`, `find_fact`, `explain_number`, `invoice_check`, `meeting_actions`.
The Skills are in `skills/`, one folder each.

## Layout

```
dtc_ops/
  ledger.py            facts with sources, order line store, run cursors
  llm.py               Claude wrapper and the grounding check
  supply/              Shopify and Amazon readers, the maths, the brief
  bilag/               two way invoice reading and matching
  meetings/            action list with transcript checks
  mcp_server.py        MCP over stdio, JSON-RPC by hand
skills/                three SKILL.md files for Claude
data/generate_sample_data.py   rebuilds all sample files
seed/                  loads sample orders into a Shopify test store
tests/                 25 tests
```
