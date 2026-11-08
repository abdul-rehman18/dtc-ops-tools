---
name: stock-brief
description: Daily stock check across Shopify, Amazon FBA and AWD for the founders. Use when someone asks about stock, sell-outs, days of cover, Black Friday readiness, or whether to send an AWD transfer.
---

# Stock brief

## When to use
Someone asks "are we OK on stock", "what runs out first", "do we need to move stock from AWD", or wants the morning brief.

## Steps
1. Call the `stock_brief` tool from the `dtc-ops` MCP server. Use today's date for `as_of` unless the person names a date.
2. Show the brief as it comes back. Do not reword the numbers, round them, or add your own.
3. If the person asks "where does that number come from", call `find_fact` to get the fact id, then `explain_number`, and show the chain in plain words.
4. If the person asks a follow up that needs a number the brief does not contain, call `find_fact`. If it is not in the ledger, say it is not known. Never estimate it.

## Rules
- Every stock, sales, date or money figure you write must come from a tool result in this conversation.
- The brief only reads what changed since the last run. If it says 0 changed lines, that is normal on a second run the same day.
- A suggested transfer is a suggestion. Do not tell the person it has been sent.

## Example
Person: "Will the bear last through Black Friday?"
You: call `stock_brief`, then answer with the red item for the bear as written, and offer to explain any number.
