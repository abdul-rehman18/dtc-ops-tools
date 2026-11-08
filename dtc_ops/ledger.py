"""The ledger: the single source of truth every tool writes to and every brief reads from.

A Fact is one number (or date) with where it came from. If a number is not in the ledger,
it cannot appear in anything a person reads.
"""
from __future__ import annotations

import csv
import json
import pathlib
from dataclasses import asdict, dataclass, field

FACT_COLUMNS = ["fact_id", "metric", "sku", "channel", "value", "unit", "source", "source_ref", "method"]


@dataclass
class Fact:
    fact_id: str
    metric: str
    value: object
    unit: str
    source: str
    source_ref: str
    method: str
    sku: str = ""
    channel: str = ""

    def display(self) -> str:
        v = self.value
        if isinstance(v, float):
            v = f"{v:.2f}".rstrip("0").rstrip(".")
        elif isinstance(v, int):
            v = f"{v:,}"
        unit = self.unit
        if unit == "days" and self.value == 1:
            unit = "day"
        if unit in ("DKK", "USD", "EUR"):
            return f"{unit} {v}"
        return f"{v} {unit}".strip() if unit in ("units", "units/day", "days", "day") else str(v)


@dataclass
class FactLedger:
    facts: dict[str, Fact] = field(default_factory=dict)
    _n: int = 0

    def add(self, metric, value, unit, source, source_ref, method, sku="", channel="") -> Fact:
        self._n += 1
        fact = Fact(f"f{self._n:03d}", metric, value, unit, source, source_ref, method, sku, channel)
        self.facts[fact.fact_id] = fact
        return fact

    def validate(self) -> list[str]:
        """Return a list of problems. An empty list means the ledger is safe to use."""
        problems = []
        seen = set()
        for f in self.facts.values():
            key = (f.metric, f.sku, f.channel)
            if key in seen:
                problems.append(f"{f.fact_id}: duplicate fact for {key}")
            seen.add(key)
            if not f.source or not f.source_ref:
                problems.append(f"{f.fact_id}: {f.metric} has no source")
            if f.unit in ("units", "units/day", "days", "DKK", "USD", "EUR"):
                if not isinstance(f.value, (int, float)):
                    problems.append(f"{f.fact_id}: {f.metric} should be a number, got {f.value!r}")
                elif f.value < 0:
                    problems.append(f"{f.fact_id}: {f.metric} is negative ({f.value})")
        return problems

    def write_csv(self, path: pathlib.Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=FACT_COLUMNS)
            w.writeheader()
            for f in self.facts.values():
                w.writerow({k: asdict(f)[k] for k in FACT_COLUMNS})

    def for_prompt(self, ids: list[str]) -> str:
        """What Claude sees: ids, meaning and display value. Never the raw source rows."""
        rows = [{"id": i, "metric": self.facts[i].metric, "sku": self.facts[i].sku,
                 "channel": self.facts[i].channel, "shows_as": self.facts[i].display()} for i in ids]
        return json.dumps(rows, ensure_ascii=False, indent=1)


class OrderLineStore:
    """Every order line ever seen, keyed so the same line can never be counted twice.

    Key is (channel, order_id, sku). A later version of the same line (for example it got cancelled)
    replaces the earlier one instead of adding to it.
    """

    COLUMNS = ["channel", "order_id", "sku", "quantity", "purchase_date", "last_updated", "status", "source_ref"]

    def __init__(self, path: pathlib.Path):
        self.path = path
        self.rows: dict[tuple, dict] = {}
        if path.exists():
            with path.open(encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    r["quantity"] = int(r["quantity"])
                    self.rows[(r["channel"], r["order_id"], r["sku"])] = r

    def upsert(self, line: dict) -> str:
        key = (line["channel"], line["order_id"], line["sku"])
        old = self.rows.get(key)
        if old is None:
            self.rows[key] = line
            return "new"
        if line["last_updated"] >= old["last_updated"]:
            same = all(str(old[c]) == str(line[c]) for c in ("quantity", "status"))
            self.rows[key] = line
            return "duplicate" if same else "updated"
        return "stale"

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=self.COLUMNS)
            w.writeheader()
            for r in sorted(self.rows.values(), key=lambda r: (r["channel"], r["purchase_date"])):
                w.writerow(r)


class RunState:
    """Remembers how far each source has been read, so the next run only reads what changed."""

    def __init__(self, path: pathlib.Path):
        self.path = path
        self.data = json.loads(path.read_text()) if path.exists() else {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2))
