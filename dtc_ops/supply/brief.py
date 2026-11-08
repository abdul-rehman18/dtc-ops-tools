"""Turn findings into the morning brief. Claude writes it if available, otherwise a plain template does."""
from __future__ import annotations

from dtc_ops.llm import render
from dtc_ops.supply.metrics import CHANNEL_LABEL

ICON = {"red": "🔴", "amber": "🟡", "green": "🟢"}

SYSTEM = """You write the daily stock brief for the two founders of a small online brand.
They read it on their phone before work. They are not technical.

Rules you must follow:
- Every number and every date must be written ONLY as a placeholder like {{f012}}, using the ids you are given.
  Never type a digit yourself, not even in a product name or a time. Write sizes and names without digits.
- Use only the facts you are given. Do not guess, estimate, average or add anything.
- Do not add advice or options that are not in the facts (for example shipping speeds or carriers).
- Plain short sentences. Say what will happen to the business and what to do today.
- Reply with JSON only: {"items": [{"level": "red|amber|green", "headline": "...", "body": "..."}]}
- One item per red or amber finding, in the order given, then one green item that sums up everything else in one sentence.
"""


def _product(ledger, finding):
    name = finding.get("name") or finding["sku"]
    name = "".join(c for c in name if not c.isdigit()).replace(" cm", "").strip()  # sizes carry digits
    return f"{name} on {CHANNEL_LABEL.get(finding['channel'], finding['channel'])}"


def template_items(ledger, findings):
    """The fallback. Same facts, fixed wording. Never fails, never invents."""
    items = []
    F = ledger.facts
    for f in findings:
        if f["level"] == "green":
            continue
        ids = f["facts"]
        stock, rate, cover, runout = ids[:4]
        body = (f"{{{{{stock}}}}} left, selling {{{{{rate}}}}}, so about {{{{{cover}}}}} of stock. "
                f"At this pace it runs out around {{{{{runout}}}}}. Black Friday is {{{{{ids[4]}}}}}.")
        if f.get("action") == "transfer_from_awd":
            awd, send, ltmin, ltmax, af, aslow, gap = ids[6:13]
            body += (f" There are {{{{{awd}}}}} in AWD. Sending {{{{{send}}}}} today should arrive between "
                     f"{{{{{af}}}}} and {{{{{aslow}}}}}.")
            if F[gap].value > 0:
                body += f" In the slow case it is empty for {{{{{gap}}}}} before the stock lands, so send it today."
        items.append({"level": f["level"], "headline": f"{_product(ledger, f)} runs out around {{{{{runout}}}}}",
                      "body": body})
    greens = [f for f in findings if f["level"] == "green"]
    items.append({"level": "green", "headline": "Everything else is covered",
                  "body": "Every other product has enough stock past Cyber Monday plus two weeks."
                  if greens else "No other products to report."})
    return items


def build_brief(ledger, findings, writer=None):
    """Returns (markdown, how it was written, grounding log)."""
    attention = [f for f in findings if f["level"] != "green"]
    # Claude only sees the facts behind findings that need attention. Fewer tokens, less to misuse.
    allowed = {fid for f in attention for fid in f["facts"]}
    required = set()
    for f in attention:
        required |= set(f["facts"][:4])
        if f.get("action") == "transfer_from_awd":
            required |= {f["facts"][7]}  # the suggested transfer must always be in the brief

    items, log, how = None, [], "template"
    if writer is not None and writer.available:
        listing = "\n".join(
            f"- {f['level'].upper()} {_product(ledger, f)} ({f['kind']}): facts {', '.join(f['facts'])}"
            for f in attention) or "- nothing needs attention"
        greens = sum(1 for f in findings if f["level"] == "green")
        user = (f"Findings needing attention:\n{listing}\n\n{greens} other product and channel pairs are fine.\n\n"
                f"Facts you may use:\n{ledger.for_prompt(sorted(allowed))}")
        items, log = writer.write_items(SYSTEM, user, allowed, required)
        if items is not None:
            how = "claude"
        else:
            log.append("fell back to the template because Claude did not pass the check")
    if items is None:
        items = template_items(ledger, findings)

    lines = []
    for it in items:
        lines.append(f"{ICON.get(it['level'], '•')} *{render(it['headline'], ledger)}*")
        lines.append(render(it["body"], ledger))
        lines.append("")
    return "\n".join(lines).strip(), how, log
