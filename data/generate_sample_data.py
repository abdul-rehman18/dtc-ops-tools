"""Generate the sample Amazon, supplier and freight data used by the three tools.

Everything here is SAMPLE DATA for a fictional plush toy brand. Nothing comes from a real store.

Amazon files copy the shape of real Amazon reports so the same parsing code works on real exports:
  - FBA inventory  -> columns of the Manage FBA Inventory report (GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA)
  - AWD inventory  -> JSON shape of the AWD API getInventory response (awd/2024-05-09)
  - Amazon orders  -> the columns the tools use from the All Orders flat file report
                      (GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL)

Run:  python data/generate_sample_data.py
Output goes to data/sample/. Running it again gives the same files (fixed random seed).
"""
import csv
import datetime as dt
import json
import pathlib
import random

import yaml
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUT = pathlib.Path(__file__).resolve().parent / "sample"
RUN_DATE = dt.date(2026, 11, 8)
random.seed(42)

SKUS = {
    #  sku      name                         asin          fnsku          eur    usd
    "WPB40": ("Weighted Plush Bear 40cm", "B0DEMO0001", "X00DEMO001", 39.95, 42.99),
    "SBN30": ("Sleepy Bunny 30cm", "B0DEMO0002", "X00DEMO002", 29.95, 32.99),
    "CDN35": ("Calm Dino 35cm", "B0DEMO0003", "X00DEMO003", 34.95, 37.99),
    "CWH50": ("Cuddle Whale 50cm", "B0DEMO0004", "X00DEMO004", 49.95, 54.99),
    "GBT03": ("Gift Box Mini Trio", "B0DEMO0005", "X00DEMO005", 24.95, 27.99),
}

# Average units per day by marketplace. The bear on Amazon US is the story. AWD feeds the US Amazon warehouses.
DAILY = {
    "DE": {"WPB40": 11, "SBN30": 9, "CDN35": 6, "CWH50": 3, "GBT03": 12},
    "US": {"WPB40": 34, "SBN30": 7, "CDN35": 5, "CWH50": 4, "GBT03": 8},
}

FBA_STOCK = {
    "DE": {"WPB40": 520, "SBN30": 640, "CDN35": 380, "CWH50": 210, "GBT03": 900},
    "US": {"WPB40": 412, "SBN30": 470, "CDN35": 330, "CWH50": 260, "GBT03": 640},
}

MARKET = {
    "DE": {"sales_channel": "Amazon.de", "currency": "EUR", "country": "DE", "cities": [("Berlin", "10115"), ("Hamburg", "20095"), ("München", "80331"), ("Köln", "50667")]},
    "US": {"sales_channel": "Amazon.com", "currency": "USD", "country": "US", "cities": [("Austin", "78701"), ("Denver", "80202"), ("Columbus", "43215"), ("Portland", "97201")]},
}

ORDER_COLUMNS = [
    "amazon-order-id", "merchant-order-id", "purchase-date", "last-updated-date", "order-status",
    "fulfillment-channel", "sales-channel", "order-channel", "ship-service-level", "product-name",
    "sku", "asin", "item-status", "quantity", "currency", "item-price", "item-tax",
    "shipping-price", "shipping-tax", "ship-city", "ship-state", "ship-postal-code", "ship-country",
]

MYI_COLUMNS = [
    "sku", "fnsku", "asin", "product-name", "condition", "your-price", "mfn-listing-exists",
    "mfn-fulfillable-quantity", "afn-listing-exists", "afn-warehouse-quantity", "afn-fulfillable-quantity",
    "afn-unsellable-quantity", "afn-reserved-quantity", "afn-total-quantity", "per-unit-volume",
    "afn-inbound-working-quantity", "afn-inbound-shipped-quantity", "afn-inbound-receiving-quantity",
    "afn-researching-quantity", "afn-future-supply-buyable", "afn-reserved-future-supply",
]


def order_id():
    return f"{random.randint(300, 306)}-{random.randint(1000000, 9999999)}-{random.randint(1000000, 9999999)}"


def write_tsv(path, columns, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, delimiter="\t")
        w.writeheader()
        w.writerows(rows)


def amazon_orders():
    """28 days of order lines. Exactly 476 shipped bear units on Amazon US over the last 14 days (34 a day)."""
    rows = []
    start = RUN_DATE - dt.timedelta(days=28)
    for mk, rates in DAILY.items():
        m = MARKET[mk]
        for day in range(28):
            date = start + dt.timedelta(days=day)
            for sku, rate in rates.items():
                units = rate if (mk, sku) == ("US", "WPB40") else max(0, rate + random.randint(-2, 2))
                while units > 0:
                    q = min(units, random.choice([1, 1, 1, 2]))
                    units -= q
                    city, postal = random.choice(m["cities"])
                    ts = dt.datetime.combine(date, dt.time(random.randint(0, 23), random.randint(0, 59), random.randint(0, 59)))
                    price = SKUS[sku][3] if mk == "DE" else SKUS[sku][4]
                    rows.append({
                        "amazon-order-id": order_id(), "merchant-order-id": "",
                        "purchase-date": ts.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                        "last-updated-date": (ts + dt.timedelta(hours=random.randint(2, 30))).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                        "order-status": "Shipped", "fulfillment-channel": "Amazon", "sales-channel": m["sales_channel"],
                        "order-channel": "", "ship-service-level": "Standard", "product-name": SKUS[sku][0],
                        "sku": sku, "asin": SKUS[sku][1], "item-status": "Shipped", "quantity": q,
                        "currency": m["currency"], "item-price": f"{price * q:.2f}", "item-tax": "",
                        "shipping-price": "0.00", "shipping-tax": "", "ship-city": city, "ship-state": "",
                        "ship-postal-code": postal, "ship-country": m["country"],
                    })
    # Traps the tool must handle, added on purpose:
    # 1. A cancelled bear order in DE. It must NOT count toward sales speed.
    cancelled = dict(rows[0])
    cancelled.update({"amazon-order-id": "112-0000001-0000001", "order-status": "Cancelled", "item-status": "Cancelled",
                      "quantity": 40, "sku": "WPB40", "asin": SKUS["WPB40"][1], "product-name": SKUS["WPB40"][0],
                      "sales-channel": "Amazon.com", "currency": "USD", "ship-country": "US",
                      "purchase-date": "2026-11-05T10:12:00+00:00", "last-updated-date": "2026-11-05T11:00:00+00:00"})
    rows.append(cancelled)
    # 2. The same order line appearing twice (happens when report windows overlap). Must be counted once.
    dup_source = next(r for r in rows if r["sku"] == "WPB40" and r["sales-channel"] == "Amazon.com" and r["purchase-date"] >= "2026-11-06")
    rows.append(dict(dup_source))
    rows.sort(key=lambda r: r["purchase-date"])
    return rows


def fba_inventory(mk):
    rows = []
    for sku, (name, asin, fnsku, eur, usd) in SKUS.items():
        ful = FBA_STOCK[mk][sku]
        reserved = random.randint(5, 25)
        unsell = random.randint(0, 4)
        inbound_shipped = 0
        rows.append({
            "sku": sku, "fnsku": fnsku, "asin": asin, "product-name": name, "condition": "New",
            "your-price": f"{eur if mk == 'DE' else usd:.2f}", "mfn-listing-exists": "No", "mfn-fulfillable-quantity": "",
            "afn-listing-exists": "Yes", "afn-warehouse-quantity": ful + reserved + unsell,
            "afn-fulfillable-quantity": ful, "afn-unsellable-quantity": unsell, "afn-reserved-quantity": reserved,
            "afn-total-quantity": ful + reserved + unsell + inbound_shipped, "per-unit-volume": "0.12",
            "afn-inbound-working-quantity": 0, "afn-inbound-shipped-quantity": inbound_shipped,
            "afn-inbound-receiving-quantity": 0, "afn-researching-quantity": 0,
            "afn-future-supply-buyable": 0, "afn-reserved-future-supply": 0,
        })
    return rows


def awd_inventory():
    onhand = {"WPB40": 1850, "SBN30": 2200, "CDN35": 900, "CWH50": 600, "GBT03": 3100}
    return {
        "inventory": [
            {
                "sku": sku,
                "totalOnhandQuantity": q,
                "totalInboundQuantity": 0,
                "inventoryDetails": {
                    "availableDistributableQuantity": q - 50,
                    "reservedDistributableQuantity": 50,
                    "replenishmentQuantity": 0,
                },
            }
            for sku, q in onhand.items()
        ],
        "nextToken": None,
    }


def pdf(path, title, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=A4)
    w, h = A4
    c.setFont("Helvetica-Bold", 15)
    c.drawString(50, h - 60, title)
    c.setFont("Helvetica", 10)
    c.drawString(50, h - 78, "SAMPLE DOCUMENT FOR A DEMO. NOT A REAL INVOICE.")
    y = h - 110
    for line in lines:
        bold = line.startswith("**")
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 11)
        c.drawString(50, y, line.strip("*"))
        y -= 18
    c.save()


def supplier_and_freight():
    # Purchase orders the brand raised (the brand's own record of what it agreed to pay).
    pos = [
        {"po_number": "PO-2026-118", "supplier": "Ningbo Soft Toys Co (sample)", "sku": "WPB40", "qty": 1000, "unit_cost_usd": 6.40},
        {"po_number": "PO-2026-118", "supplier": "Ningbo Soft Toys Co (sample)", "sku": "CDN35", "qty": 600, "unit_cost_usd": 5.90},
        {"po_number": "PO-2026-121", "supplier": "Ningbo Soft Toys Co (sample)", "sku": "SBN30", "qty": 800, "unit_cost_usd": 4.70},
        {"po_number": "PO-2026-124", "supplier": "Yiwu Gift Pack Ltd (sample)", "sku": "GBT03", "qty": 1500, "unit_cost_usd": 3.10},
    ]
    with (OUT / "ledger" / "purchase_orders.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(pos[0]))
        w.writeheader()
        w.writerows(pos)

    # What the 3PL actually counted in at the warehouse.
    receipts = [
        {"receipt_id": "RCV-5531", "po_number": "PO-2026-118", "sku": "WPB40", "qty_received": 1000, "received_date": "2026-10-28"},
        {"receipt_id": "RCV-5531", "po_number": "PO-2026-118", "sku": "CDN35", "qty_received": 600, "received_date": "2026-10-28"},
        {"receipt_id": "RCV-5544", "po_number": "PO-2026-121", "sku": "SBN30", "qty_received": 800, "received_date": "2026-10-30"},
        {"receipt_id": "RCV-5550", "po_number": "PO-2026-124", "sku": "GBT03", "qty_received": 1500, "received_date": "2026-11-02"},
    ]
    with (OUT / "ledger" / "3pl_receipts.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(receipts[0]))
        w.writeheader()
        w.writerows(receipts)

    # Agreed freight bookings.
    freight = {"shipments": [
        {"shipment_id": "SH-0417", "forwarder": "Nordic Freight A/S (sample)", "po_numbers": ["PO-2026-118"], "agreed_dkk": 16900},
        {"shipment_id": "SH-0421", "forwarder": "Nordic Freight A/S (sample)", "po_numbers": ["PO-2026-121", "PO-2026-124"], "agreed_dkk": 21300},
    ]}
    (OUT / "ledger" / "freight_bookings.yaml").write_text(yaml.safe_dump(freight, sort_keys=False))

    # Past AWD to FBA transfers, used to estimate how long a transfer takes.
    transfers = [
        ("TR-201", "WPB40", 600, "2026-07-02", "2026-07-13"),
        ("TR-207", "WPB40", 500, "2026-07-29", "2026-08-07"),
        ("TR-214", "SBN30", 400, "2026-08-18", "2026-08-30"),
        ("TR-219", "WPB40", 700, "2026-09-04", "2026-09-17"),
        ("TR-226", "CDN35", 300, "2026-09-22", "2026-10-03"),
        ("TR-231", "WPB40", 650, "2026-10-06", "2026-10-16"),
    ]
    with (OUT / "ledger" / "awd_transfers.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["transfer_id", "sku", "qty", "sent_date", "available_in_fba_date"])
        w.writerows(transfers)

    # Invoices that arrive by email as PDFs.
    inv = OUT / "inbox"
    pdf(inv / "INV-NST-88231.pdf", "Ningbo Soft Toys Co (sample) - Commercial Invoice", [
        "Invoice no: NST-88231", "Invoice date: 2026-10-20", "Buyer PO: PO-2026-118", "",
        "**Line items", "WPB40  Weighted Plush Bear 40cm   qty 1060   unit USD 6.40   total USD 6784.00",
        "CDN35  Calm Dino 35cm             qty 600    unit USD 5.90   total USD 3540.00", "",
        "**Invoice total: USD 10324.00", "Payment terms: 30 days",
    ])
    pdf(inv / "INV-NST-88240.pdf", "Ningbo Soft Toys Co (sample) - Commercial Invoice", [
        "Invoice no: NST-88240", "Invoice date: 2026-10-23", "Buyer PO: PO-2026-121", "",
        "**Line items", "SBN30  Sleepy Bunny 30cm          qty 800    unit USD 4.70   total USD 3760.00", "",
        "**Invoice total: USD 3760.00", "Payment terms: 30 days",
    ])
    pdf(inv / "INV-YGP-4410.pdf", "Yiwu Gift Pack Ltd (sample) - Invoice", [
        "Invoice no: YGP-4410", "Invoice date: 2026-10-25", "Buyer PO: PO-2026-124", "",
        "**Line items", "GBT03  Gift Box Mini Trio         qty 1500   unit USD 3.10   total USD 4650.00", "",
        "**Invoice total: USD 4650.00", "Payment terms: 30 days",
    ])
    pdf(inv / "INV-NF-77102.pdf", "Nordic Freight A/S (sample) - Faktura", [
        "Faktura nr: NF-77102", "Dato: 2026-11-02", "Shipment: SH-0417", "",
        "**Ydelser", "Ocean freight CNNGB to DKAAR        DKK 12400.00",
        "Destination handling                DKK 3100.00",
        "Customs clearance                   DKK 1400.00",
        "Port storage 6 days                 DKK 1500.00", "",
        "**Total DKK 18400.00",
    ])
    pdf(inv / "INV-NF-77118.pdf", "Nordic Freight A/S (sample) - Faktura", [
        "Faktura nr: NF-77118", "Dato: 2026-11-04", "Shipment: SH-0421", "",
        "**Ydelser", "Ocean freight CNNGB to DKAAR        DKK 16200.00",
        "Destination handling                DKK 3700.00",
        "Customs clearance                   DKK 1400.00", "",
        "**Total DKK 21300.00",
    ])


def meeting_transcript():
    text = """Weekly ops call, Thursday 5 November 2026 (SAMPLE TRANSCRIPT, fictional people)
Attendees: Freja (founder), Jonas (founder), Sofie (customer service), Anders (3PL account manager)

[00:01] Freja: Okay, quick one today. Black Friday is three weeks out and I want the bear sorted.
[00:03] Jonas: Amazon US is moving fast on the bear. I'll check the AWD numbers and send a transfer if we need it, by Monday.
[00:05] Freja: Good. Sofie, how are returns?
[00:06] Sofie: Mostly the whale, people say it is bigger than they expected. I can rewrite the size text on the whale listing by Friday next week.
[00:08] Freja: Do it. Add a photo next to a pillow, that helps.
[00:09] Anders: On our side, the Ningbo container came in on the 28th. We counted 1,000 bears, not 1,060.
[00:10] Jonas: Then the supplier invoice is wrong. Don't pay the full amount, I'll email Ningbo about the 60 units.
[00:12] Freja: Also the freight bill from Nordic looked high. Someone should check it against the booking.
[00:13] Jonas: Yeah.
[00:14] Freja: And we talked about maybe trying TikTok Shop in Q1, let's think about it.
[00:15] Anders: One more thing, we need the Black Friday volume forecast from you by the 15th so we can staff the warehouse.
[00:16] Freja: Jonas, can you send Anders the forecast?
[00:16] Jonas: Sure, by the 13th.
[00:17] Freja: Great, thanks all.
"""
    (OUT / "meetings" / "2026-11-05-weekly-ops.txt").parent.mkdir(parents=True, exist_ok=True)
    (OUT / "meetings" / "2026-11-05-weekly-ops.txt").write_text(text, encoding="utf-8")


def main():
    (OUT / "amazon").mkdir(parents=True, exist_ok=True)
    (OUT / "ledger").mkdir(parents=True, exist_ok=True)
    orders = amazon_orders()
    write_tsv(OUT / "amazon" / "all_orders_by_order_date.tsv", ORDER_COLUMNS, orders)
    write_tsv(OUT / "amazon" / "fba_inventory_DE.tsv", MYI_COLUMNS, fba_inventory("DE"))
    write_tsv(OUT / "amazon" / "fba_inventory_US.tsv", MYI_COLUMNS, fba_inventory("US"))
    (OUT / "amazon" / "awd_inventory.json").write_text(json.dumps(awd_inventory(), indent=2))
    supplier_and_freight()
    meeting_transcript()
    (OUT / "README.txt").write_text(
        "All files in this folder are SAMPLE DATA for a fictional brand, generated by data/generate_sample_data.py.\n"
        f"Reference run date: {RUN_DATE.isoformat()}\n"
    )
    print(f"Wrote {len(orders)} Amazon order lines and supporting files to {OUT}")


if __name__ == "__main__":
    main()
