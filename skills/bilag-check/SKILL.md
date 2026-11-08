---
name: bilag-check
description: Check new supplier and freight invoices (bilag) against purchase orders, warehouse counts and agreed freight prices before anything is booked. Use when invoices arrive, before paying a supplier, or when someone asks what is on hold.
---

# Invoice (bilag) check

## When to use
"Can I pay Ningbo?", "check this week's invoices", "why is this invoice on hold", "what's ready to book".

## Steps
1. Call the `invoice_check` tool from the `dtc-ops` MCP server.
2. Show held invoices first, each with its reason exactly as returned, then the list that is ready to book.
3. If nothing new came back, say there were no new invoices since the last check.

## Rules
- Never say an invoice is fine, paid or booked unless the tool returned it as ready to book.
- Do not suggest paying part of a held invoice or work out a new amount. Point the person to the reason and let them decide.
- Each invoice is read twice, once by code and once by Claude. If the tool says the reads disagreed, treat it as unread and say so.

## Example
Person: "Anything I shouldn't pay this week?"
You: call `invoice_check`, list the held ones with their reasons, then "Ready to book:" with the rest.
