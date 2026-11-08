"""Load sample orders into a Shopify TEST store.

Run once:  python seed/seed_orders.py
Needs a .env file in the project root with SHOPIFY_STORE, SHOPIFY_CLIENT_ID and SHOPIFY_CLIENT_SECRET.
Every order is tagged sample-data and marked as a test order.
Trial and development stores allow 5 new orders per minute, so this waits between orders.
"""
import json
import os
import pathlib
import sys
import time

import requests
from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

STORE = os.environ.get("SHOPIFY_STORE")  # e.g. 9dfpyi-9a.myshopify.com
CLIENT_ID = os.environ.get("SHOPIFY_CLIENT_ID")
CLIENT_SECRET = os.environ.get("SHOPIFY_CLIENT_SECRET")
API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "2026-10")
TOKEN = None


def get_token():
    """Dev Dashboard apps get a 24 hour token through the client credentials grant."""
    r = requests.post(
        f"https://{STORE}/admin/oauth/access_token",
        data={"grant_type": "client_credentials", "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET},
        timeout=30,
    )
    if r.status_code != 200:
        sys.exit(f"Token request failed ({r.status_code}): {r.text[:300]}")
    return r.json()["access_token"]

MUTATION = """
mutation Seed($order: OrderCreateOrderInput!) {
  orderCreate(order: $order, options: {inventoryBehaviour: BYPASS, sendReceipt: false, sendFulfillmentReceipt: false}) {
    order { name processedAt }
    userErrors { field message }
  }
}
"""

ALREADY = "{ orders(first: 1, query: \"tag:sample-data\") { edges { node { id } } } }"


def gql(query, variables=None):
    r = requests.post(
        f"https://{STORE}/admin/api/{API_VERSION}/graphql.json",
        headers={"X-Shopify-Access-Token": TOKEN, "Content-Type": "application/json"},
        json={"query": query, "variables": variables or {}},
        timeout=30,
    )
    r.raise_for_status()
    body = r.json()
    if body.get("errors"):
        raise RuntimeError(body["errors"])
    return body["data"]


def main():
    global TOKEN
    if not STORE or not CLIENT_ID or not CLIENT_SECRET:
        sys.exit("Missing SHOPIFY_STORE, SHOPIFY_CLIENT_ID or SHOPIFY_CLIENT_SECRET in .env")
    TOKEN = get_token()

    if gql(ALREADY)["orders"]["edges"]:
        sys.exit("Sample orders already exist in this store. Stopping so nothing is doubled.")

    orders = json.loads((ROOT / "seed" / "sample_orders.json").read_text())
    for i, order in enumerate(orders, 1):
        result = gql(MUTATION, {"order": order})["orderCreate"]
        if result["userErrors"]:
            sys.exit(f"Order {i} failed: {result['userErrors']}")
        print(f"{i}/{len(orders)} created {result['order']['name']} dated {result['order']['processedAt']}")
        if i < len(orders):
            time.sleep(13)
    print("Done. Check the Orders page in Shopify admin.")


if __name__ == "__main__":
    main()
