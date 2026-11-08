import datetime as dt
import json
import pathlib

import pytest

from dtc_ops.ledger import FactLedger, OrderLineStore
from dtc_ops.llm import ClaudeWriter, check_grounded
from dtc_ops.supply.metrics import peak_dates, units_in_window
from dtc_ops.supply.run import run
from dtc_ops.supply.shopify_source import ShopifyClient, fixture_transport

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "sample"
FIX = ROOT / "tests" / "fixtures"
AS_OF = dt.date(2026, 11, 8)


def fresh_run(tmp_path, writer=None):
    shop = ShopifyClient(transport=fixture_transport(FIX))
    return run(AS_OF, DATA, tmp_path, shop, writer)


def test_black_friday_2026():
    bf, cm = peak_dates(2026)
    assert bf == dt.date(2026, 11, 27) and cm == dt.date(2026, 11, 30)


def test_cancelled_and_duplicate_lines_do_not_inflate_sales(tmp_path):
    fresh_run(tmp_path)
    store = OrderLineStore(tmp_path / "order_lines.csv")
    units, counted, excluded = units_in_window(store, "amazon_us", "WPB40", AS_OF)
    assert units == 476          # 34 a day, the true figure
    assert excluded == 1         # the cancelled 40 unit order


def test_second_run_reads_only_changes(tmp_path):
    fresh_run(tmp_path)
    second = fresh_run(tmp_path)["report"]
    assert second["order_lines_read"] == 0
    assert second["amazon_rows_skipped_unchanged"] > 2000


def test_brief_flags_the_bear_and_suggests_a_transfer(tmp_path):
    out = fresh_run(tmp_path)
    assert "Weighted Plush Bear on Amazon US" in out["brief"]
    assert "850 units" in out["brief"] and "Fri 20 Nov" in out["brief"]
    assert out["report"]["attention"] == 1


def test_every_number_in_the_brief_is_in_the_ledger(tmp_path):
    out = fresh_run(tmp_path)
    facts = (tmp_path / "facts_2026-11-08.csv").read_text()
    for token in ["412", "850", "1800", "12.1"]:
        assert token in facts.replace(",", "")
        assert token in out["brief"].replace(",", "")


def test_ledger_rejects_negative_and_unsourced_numbers():
    led = FactLedger()
    led.add("on_hand", -5, "units", "x", "y", "z", "A", "c")
    led.add("on_hand", 3, "units", "", "", "z", "B", "c")
    problems = " ".join(led.validate())
    assert "negative" in problems and "no source" in problems


def test_grounding_check_catches_typed_numbers():
    assert check_grounded("{{f001}} left", {"f001"}) == []
    assert check_grounded("about 400 left", {"f001"})
    assert check_grounded("{{f999}} left", {"f001"})
    assert check_grounded("fine", {"f001"}, required_ids={"f001"})


def _fake_claude(answers):
    answers = list(answers)
    return ClaudeWriter(call=lambda system, user: answers.pop(0))


def test_claude_that_makes_up_a_number_is_rejected_then_template_used(tmp_path):
    bad = json.dumps({"items": [{"level": "red", "headline": "Bear runs out in about 2 weeks", "body": "Send 900."}]})
    writer = _fake_claude([bad, bad])
    out = fresh_run(tmp_path, writer)
    assert out["report"]["written_by"] == "template"
    assert any("typed itself" in line for line in out["report"]["grounding_log"])
    assert "900" not in out["brief"]


def test_claude_that_follows_the_rules_is_used(tmp_path):
    # Work out the fact ids the real run will produce, then answer with them.
    probe = fresh_run(tmp_path / "probe")
    facts = (tmp_path / "probe" / "facts_2026-11-08.csv").read_text().splitlines()
    ids = {}
    for row in facts[1:]:
        fid, metric, sku, channel = row.split(",")[:4]
        ids[(metric, sku, channel)] = fid
    k = lambda m: ids[(m, "WPB40", "amazon_us")]
    good = json.dumps({"items": [
        {"level": "red", "headline": f"The bear on Amazon US runs out around {{{{{k('runs_out_around')}}}}}",
         "body": f"{{{{{k('on_hand')}}}}} left at {{{{{k('sales_per_day')}}}}}, about {{{{{k('days_of_cover')}}}}}. "
                 f"Send {{{{{k('suggested_transfer')}}}}} from AWD today."},
        {"level": "green", "headline": "All else fine", "body": "Nothing else needs you today."}]})
    writer = _fake_claude([good])
    out = fresh_run(tmp_path / "real", writer)
    assert probe["report"]["written_by"] == "template"
    assert out["report"]["written_by"] == "claude"
    assert "850 units" in out["brief"]


def test_facts_agree_with_each_other_and_far_dates_show_the_year(tmp_path):
    """Found by Claude Desktop on the first live run: Shopify showed 0.4 a day, 392 days of cover and 'Sat 5 Dec'."""
    import csv
    fresh_run(tmp_path)
    rows = list(csv.DictReader((tmp_path / "facts_2026-11-08.csv").open()))
    get = lambda m, sku, ch: next(r["value"] for r in rows if (r["metric"], r["sku"], r["channel"]) == (m, sku, ch))
    for sku, ch in [("WPB40", "shopify"), ("WPB40", "amazon_us"), ("WPB40", "amazon_de")]:
        on_hand, rate, cover = float(get("on_hand", sku, ch)), float(get("sales_per_day", sku, ch)), float(get("days_of_cover", sku, ch))
        assert abs(on_hand / rate - cover) < 0.1, (sku, ch, on_hand, rate, cover)
    assert get("runs_out_around", "WPB40", "shopify").endswith("2027")
    assert get("runs_out_around", "WPB40", "amazon_us") == "Fri 20 Nov"
