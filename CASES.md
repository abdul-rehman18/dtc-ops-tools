# Case write ups

To be clear up front: these three were built over one weekend for this application, on a Shopify test store and Amazon style sample files. They are not past client work. Every result below was measured on that test data, and every number can be checked by running the code.

---

## Case 1. Supply chain sync and morning stock brief

### The business problem
Stock lives in three places: the Shopify warehouse, Amazon FBA in each country, and AWD bulk storage. A founder has to pull each report, work out how fast each product sells, and spot what runs out before the big days. Done by hand it is slow and easy to get wrong. Amazon order reports include cancelled orders and, when report windows overlap, the same order line twice, so a quick sum makes a product look like it sells faster than it does.

### What I built
- **Sources:** Shopify Admin GraphQL API (stock and orders, through a Dev Dashboard app using the client credentials grant), Amazon Manage FBA Inventory report for US and DE, the AWD inventory API response, and the All Orders report. The Amazon files use the real report columns, so an SP-API MCP server or a scheduled download can drop real files in place.
- **Delta reads:** each run remembers how far it read. Shopify is asked only for orders updated since the last run, and Amazon rows older than the cursor are skipped. Order lines are stored by channel, order id and SKU, so a line seen twice is merged, and a later status (for example cancelled) replaces the earlier one.
- **Ledger** (a file listing every number and where it came from): plain Python works out sales per day, days of cover, run out date and how many units to move from AWD. Each result is saved as a fact with its source and how it was calculated.
- **Claude's job:** write the brief, using the Anthropic Messages API. It is given fact ids, not raw data, and must write every number as a reference like `{{f031}}`.
- **Where it runs and how it is triggered:** a command line run on a schedule (`python -m dtc_ops.supply.run --post` posts to Slack), or on demand from Claude Desktop through the MCP server.

### How I made it trustworthy
- The ledger is checked before anything is written: no duplicate facts, no missing sources, no negative stock.
- Claude's draft is rejected if it contains any digit it typed itself, uses a fact id that does not exist, or leaves out the run out date or the suggested transfer. It gets one retry, then a fixed template is used and the brief still goes out.
- Claude only sees the facts behind the products that need attention.
- Any number can be traced back. Asking Claude Desktop where "850 units" came from walks the chain: sales of 34 a day (476 units over 14 days, from 371 counted order lines with 1 cancelled order left out and duplicates merged), times 36 days to cover Cyber Monday plus two weeks, is 1,224. Minus the 412 already in FBA is 812, rounded up to 850, and AWD has 1,800, so it can be sent.

### The result (on test data)
- Found the one problem that mattered: the bear on Amazon US runs out around Fri 20 Nov, a week before Black Friday, and 850 units should move from AWD today.
- Sales speed counted correctly at 476 units over 14 days. A plain sum gives 518, about 9% too high, because of one cancelled 40 unit order and one doubled line.
- Second run the same day read 0 changed order lines and skipped all 2,246 unchanged Amazon rows. Shopify took 2 API calls per run.
- First live Claude brief passed the number check on the first try. That call used about 6,100 input and 900 output tokens, before I cut what Claude sees down to the attention items only.

### What broke
1. **Claude added advice that was not in the data.** Its first live brief told the founders to "choose the fastest option" for the transfer. It had no numbers, so the number check let it through. I tightened the instructions and reduced what Claude sees. The lesson: a number check does not catch invented advice, so the brief needs a rule for that too.
2. **My own numbers disagreed with each other.** I rounded sales per day for display but used the unrounded value for the maths, so Shopify showed 0.4 a day and 392 days of cover, which do not match. The run out date also had no year, so a date in December 2027 read as "Sat 5 Dec". Claude Desktop caught this while tracing the numbers. Now one rounded value is stored and used for every later step, any date outside the current year shows the year, and a test checks that stock divided by sales per day equals days of cover.

---

## Case 2. Invoice (bilag) reconciliation

### The business problem
Supplier and freight invoices arrive as PDFs. Before paying, someone has to check the price against the purchase order, the quantity against what the warehouse actually counted in, and the freight against the agreed booking. Errors here are real money paid out, and they are easy to miss in a busy week.

### What I built
- **Read A, code:** pdfplumber pulls the text and fixed patterns read invoice number, date, PO or shipment reference, product lines and service charges.
- **Read B, Claude:** the Messages API reads the same text and returns JSON, plus the exact line of text it took each value from.
- **Matching, code:** each invoice is checked against `purchase_orders.csv`, `3pl_receipts.csv` and `freight_bookings.yaml`, plus a register of invoices already booked.
- **Output:** READY to book or HOLD with plain reasons, appended to a CSV register. Each PDF is processed once.

### How I made it trustworthy
- Any line Claude says it read must exist in the PDF text, or its whole read is thrown out.
- If the two reads disagree on any number, the invoice is held.
- If only one read works, nothing is booked.
- The invoice must add up on its own before it is compared with anything else.
- An invoice number already booked is held as a likely duplicate.

### The result (on test data)
- 5 invoices: 3 ready to book, 2 held.
- Held: a supplier invoice billing 1,060 bears when the warehouse counted 1,000, which is 60 units or USD 384 too much.
- Held: a freight invoice of DKK 18,400 against an agreed DKK 16,900. The tool points out that the DKK 1,500 gap is exactly the "Port storage 6 days" line.
- The live Claude read agreed with the code read on all 5 invoices. 5 calls, about 2,500 input and 1,500 output tokens in total.

### What broke
The code reader missed the "Port storage 6 days" line because its pattern did not allow a digit inside a charge name. The tool's own sum check caught it, because the lines added up to DKK 16,900 while the invoice said DKK 18,400, so the invoice was held, not booked. I fixed the pattern and added a test. This is the case for two independent reads plus a sum check: no single reader is trusted.

---

## Case 3. Meeting action item digest

### The business problem
After the weekly ops call, tasks get lost. The worst ones are the things everyone agrees should happen and nobody takes on.

### What I built
- Claude, through the Messages API, reads the transcript and proposes actions, unowned items and ideas, quoting the lines each one comes from.
- Code checks every item against the transcript, and code, not Claude, turns spoken deadlines like "by Monday" into dates.

### How I made it trustworthy
- Every quote must match a transcript line word for word.
- The owner must have said they will do it, or said yes when asked. "Someone should check it" followed by "Yeah" does not make anyone the owner.
- A deadline must appear in the quoted words.
- Items that fail are not dropped. They move to "No owner yet" so a founder sees them.

### The result (on test data)
- 4 actions with owners. 3 had a deadline said out loud, and each became a real date, for example "Send Anders the Black Friday volume forecast (by Fri 13 Nov)".
- 2 items with no owner in the live run, including "Check the Nordic freight bill against the booking", the one the meeting agreed on and nobody took.
- 1 idea kept as an idea (TikTok Shop in Q1), not turned into a task.
- One call, about 950 input and 1,650 output tokens.

### What broke
The first live run crashed. Claude's full answer needed about 1,650 tokens and my output limit was 1,200, so the JSON was cut off. Now the limit is higher, a broken reply is retried once, and if it fails twice the founders get a clear note that the meeting needs a person this week instead of a crash. I applied the same safer reading to the other two tools.

---

## MCP experience

- **Built from scratch:** `dtc_ops/mcp_server.py` speaks MCP over stdio as plain JSON-RPC: `initialize` with version negotiation, `tools/list`, `tools/call`, `ping`, and tool errors returned as results so Claude can recover. I wrote it without the SDK because the current official Python SDK needs Python 3.10 or newer, and the laptop I built this on runs 3.9. Written this way it runs on any Python from 3.9 up.
- **Tested** with the official MCP Python client (`tests/check_with_official_client.py`, needs Python 3.10 or newer) and in Claude Desktop on macOS, where a founder can ask "will the bear last through Black Friday?" and get the brief.
- `find_fact` and `explain_number` exist so Claude looks numbers up instead of guessing them.

## Next steps for a real store
- Feed the Amazon readers from your existing SP-API MCP server instead of files.
- AWD launched in Germany, France, Italy, Spain and the UK on 20 August 2026, so the AWD transfer suggestion can be switched on for Amazon DE as well as the US.
- Post the three outputs to Slack on a schedule, which the stock brief already supports with `--post`.
