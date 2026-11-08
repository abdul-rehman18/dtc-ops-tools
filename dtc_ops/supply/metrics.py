"""All the maths. Plain code, no AI. Every result goes into the ledger with how it was worked out."""
from __future__ import annotations

import datetime as dt
import math

COUNTED_STATUSES = {"Shipped", "Open", "Pending", "Unshipped", "PartiallyShipped"}
CHANNEL_LABEL = {"amazon_us": "Amazon US (FBA)", "amazon_de": "Amazon DE (FBA)", "shopify": "Shopify warehouse"}
WINDOW_DAYS = 14
SAFETY_DAYS = 14


def peak_dates(year: int) -> tuple[dt.date, dt.date]:
    """Black Friday is the day after the fourth Thursday of November. Cyber Monday is three days later."""
    nov1 = dt.date(year, 11, 1)
    first_thu = nov1 + dt.timedelta(days=(3 - nov1.weekday()) % 7)
    bf = first_thu + dt.timedelta(days=22)
    return bf, bf + dt.timedelta(days=3)


def fmt_date(d: dt.date, ref: dt.date | None = None) -> str:
    """Short date. Adds the year whenever it is not the run's year, so a date next year is never mistaken for this year."""
    if ref is not None and d.year != ref.year:
        return d.strftime("%a %d %b %Y")
    return d.strftime("%a %d %b")


def units_in_window(store, channel, sku, as_of: dt.date) -> tuple[int, int, int]:
    """Units sold in the last WINDOW_DAYS full days. Returns (units, lines counted, lines excluded)."""
    start = (as_of - dt.timedelta(days=WINDOW_DAYS)).isoformat()
    end = as_of.isoformat()
    units = counted = excluded = 0
    for (ch, _oid, s), r in store.rows.items():
        if ch != channel or s != sku or not (start <= r["purchase_date"][:10] < end):
            continue
        if r["status"] in COUNTED_STATUSES:
            units += int(r["quantity"])
            counted += 1
        else:
            excluded += 1
    return units, counted, excluded


def lead_times(transfers: list[dict]) -> list[int]:
    out = []
    for t in transfers:
        a = dt.date.fromisoformat(t["sent_date"])
        b = dt.date.fromisoformat(t["available_in_fba_date"])
        out.append((b - a).days)
    return out


def build_facts(ledger, store, stock: dict, awd: dict, transfers: list[dict], as_of: dt.date, sources: dict):
    """Fill the ledger and return a list of findings. A finding points at fact ids, never at raw numbers."""
    bf, cm = peak_dates(as_of.year)
    findings = []
    lt = lead_times(transfers)
    lt_min = ledger.add("transfer_days_fastest", min(lt), "days", "awd_transfers.csv",
                        f"{len(lt)} past transfers", "shortest sent to available") if lt else None
    lt_max = ledger.add("transfer_days_slowest", max(lt), "days", "awd_transfers.csv",
                        f"{len(lt)} past transfers", "longest sent to available") if lt else None
    bf_fact = ledger.add("black_friday", fmt_date(bf, as_of), "date", "calendar", "fourth Thursday of November + 1", "rule")
    cm_fact = ledger.add("cyber_monday", fmt_date(cm, as_of), "date", "calendar", "Black Friday + 3", "rule")

    for channel, by_sku in stock.items():
        for sku, on_hand in sorted(by_sku.items()):
            units, counted, excluded = units_in_window(store, channel, sku, as_of)
            # Round once and use the SAME stored value for every later step, so the facts always agree with each other.
            rate = round(units / WINDOW_DAYS, 2)
            f_stock = ledger.add("on_hand", on_hand, "units", sources[channel], f"{sku} available", "as reported", sku, channel)
            f_units = ledger.add("units_sold_14d", units, "units", "order_lines.csv",
                                 f"{counted} order lines counted, {excluded} cancelled or other excluded, duplicates merged",
                                 f"sum of quantity, {WINDOW_DAYS} full days before run", sku, channel)
            f_rate = ledger.add("sales_per_day", rate, "units/day", "ledger", f"{f_units.fact_id}",
                                f"{f_units.fact_id} / {WINDOW_DAYS}", sku, channel)
            if rate <= 0:
                findings.append({"level": "green", "sku": sku, "channel": channel, "facts": [f_stock.fact_id], "kind": "no_sales"})
                continue
            cover = on_hand / rate
            f_cover = ledger.add("days_of_cover", round(cover, 1), "days", "ledger",
                                 f"{f_stock.fact_id} / {f_rate.fact_id}", "on hand / sales per day", sku, channel)
            runout = as_of + dt.timedelta(days=math.floor(cover))
            f_runout = ledger.add("runs_out_around", fmt_date(runout, as_of), "date", "ledger", f"{f_cover.fact_id}",
                                  "run date + days of cover, rounded down", sku, channel)
            base = {"sku": sku, "channel": channel,
                    "facts": [f_stock.fact_id, f_rate.fact_id, f_cover.fact_id, f_runout.fact_id]}

            if runout >= cm + dt.timedelta(days=SAFETY_DAYS):
                findings.append({**base, "level": "green", "kind": "covered"})
                continue

            level = "red" if runout <= cm else "amber"
            finding = {**base, "level": level, "kind": "runs_out_before_peak" if level == "red" else "thin_after_peak",
                       "facts": base["facts"] + [bf_fact.fact_id, cm_fact.fact_id]}
            if channel == "amazon_us" and sku in awd and lt_max:
                need_days = (cm - as_of).days + SAFETY_DAYS
                need = max(0, math.ceil(rate * need_days - on_hand))
                need = int(math.ceil(need / 50) * 50)
                f_awd = ledger.add("awd_available", awd[sku], "units", sources["awd"], f"{sku} availableDistributableQuantity",
                                   "as reported", sku, "awd")
                send = min(need, awd[sku])
                f_send = ledger.add("suggested_transfer", send, "units", "ledger",
                                    f"{f_rate.fact_id} x {need_days} days - {f_stock.fact_id}, rounded up to 50, capped by {f_awd.fact_id}",
                                    f"cover to {cm_fact.fact_id} plus {SAFETY_DAYS} safety days", sku, channel)
                arrive_fast = as_of + dt.timedelta(days=lt_min.value)
                arrive_slow = as_of + dt.timedelta(days=lt_max.value)
                f_af = ledger.add("arrives_if_sent_today_fastest", fmt_date(arrive_fast, as_of), "date", "ledger",
                                  f"run date + {lt_min.fact_id}", "rule", sku, channel)
                f_as = ledger.add("arrives_if_sent_today_slowest", fmt_date(arrive_slow, as_of), "date", "ledger",
                                  f"run date + {lt_max.fact_id}", "rule", sku, channel)
                gap = (arrive_slow - runout).days
                f_gap = ledger.add("days_empty_in_slowest_case", max(0, gap), "days", "ledger",
                                   f"{f_as.fact_id} - {f_runout.fact_id}", "rule", sku, channel)
                finding["facts"] += [f_awd.fact_id, f_send.fact_id, lt_min.fact_id, lt_max.fact_id,
                                     f_af.fact_id, f_as.fact_id, f_gap.fact_id]
                finding["action"] = "transfer_from_awd"
            findings.append(finding)
    return findings
