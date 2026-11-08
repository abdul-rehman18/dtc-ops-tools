"""Read stock and orders from Shopify through the Admin GraphQL API.

Orders are read as a delta: only orders updated after the last run, filtered on Shopify's side,
so a daily run touches a few dozen orders instead of the whole history.
"""
from __future__ import annotations

import json
import os
import pathlib

import requests

ORDERS_QUERY = """
query Orders($q: String!, $after: String) {
  orders(first: 100, after: $after, query: $q, sortKey: UPDATED_AT) {
    edges { node { id name processedAt updatedAt cancelledAt test
      lineItems(first: 50) { edges { node { sku quantity } } } } }
    pageInfo { hasNextPage endCursor }
  }
}"""

INVENTORY_QUERY = """
query Inventory($after: String) {
  productVariants(first: 100, after: $after) {
    edges { node { sku inventoryItem { inventoryLevels(first: 10) {
      edges { node { location { name } quantities(names: ["available"]) { quantity } } } } } } }
    pageInfo { hasNextPage endCursor }
  }
}"""


class ShopifyClient:
    def __init__(self, store=None, client_id=None, client_secret=None, api_version=None, transport=None):
        self.store = store or os.environ.get("SHOPIFY_STORE")
        self.client_id = client_id or os.environ.get("SHOPIFY_CLIENT_ID")
        self.client_secret = client_secret or os.environ.get("SHOPIFY_CLIENT_SECRET")
        self.api_version = api_version or os.environ.get("SHOPIFY_API_VERSION", "2026-10")
        self._transport = transport
        self._token = None
        self.calls = 0

    def _gql(self, query, variables):
        self.calls += 1
        if self._transport:
            return self._transport(query, variables)
        if self._token is None:
            r = requests.post(f"https://{self.store}/admin/oauth/access_token", timeout=30, data={
                "grant_type": "client_credentials", "client_id": self.client_id, "client_secret": self.client_secret})
            r.raise_for_status()
            self._token = r.json()["access_token"]
        r = requests.post(f"https://{self.store}/admin/api/{self.api_version}/graphql.json", timeout=30,
                          headers={"X-Shopify-Access-Token": self._token},
                          json={"query": query, "variables": variables})
        r.raise_for_status()
        body = r.json()
        if body.get("errors"):
            raise RuntimeError(f"Shopify returned errors: {body['errors']}")
        return body

    def inventory(self) -> dict[str, int]:
        """Available units per SKU, summed over locations."""
        out, after = {}, None
        while True:
            page = self._gql(INVENTORY_QUERY, {"after": after})["data"]["productVariants"]
            for e in page["edges"]:
                n = e["node"]
                if not n["sku"]:
                    continue
                total = sum(q["quantity"] for lvl in n["inventoryItem"]["inventoryLevels"]["edges"]
                            for q in lvl["node"]["quantities"])
                out[n["sku"]] = out.get(n["sku"], 0) + total
            if not page["pageInfo"]["hasNextPage"]:
                return out
            after = page["pageInfo"]["endCursor"]

    def order_lines_since(self, updated_after: str, include_test: bool = False) -> tuple[list[dict], str]:
        """Order lines from orders updated after `updated_after`. Returns (lines, newest updatedAt seen)."""
        lines, newest, after = [], updated_after, None
        q = f"updated_at:>'{updated_after}'"
        while True:
            page = self._gql(ORDERS_QUERY, {"q": q, "after": after})["data"]["orders"]
            for e in page["edges"]:
                o = e["node"]
                newest = max(newest, o["updatedAt"])
                if o["test"] and not include_test:
                    continue
                status = "Cancelled" if o["cancelledAt"] else "Open"
                for li in o["lineItems"]["edges"]:
                    li = li["node"]
                    if not li["sku"]:
                        continue
                    lines.append({"channel": "shopify", "order_id": o["name"], "sku": li["sku"],
                                  "quantity": int(li["quantity"]), "purchase_date": o["processedAt"],
                                  "last_updated": o["updatedAt"], "status": status,
                                  "source_ref": f"Shopify order {o['name']}"})
            if not page["pageInfo"]["hasNextPage"]:
                return lines, newest
            after = page["pageInfo"]["endCursor"]


def fixture_transport(fixture_dir: pathlib.Path):
    """Replays saved Shopify responses. Used for tests and offline runs, never for live use."""
    orders = json.loads((fixture_dir / "shopify_orders_page.json").read_text())
    inventory = json.loads((fixture_dir / "shopify_inventory_page.json").read_text())

    def call(query, variables):
        if "productVariants" in query:
            return inventory
        cutoff = variables["q"].split("'")[1]
        edges = [e for e in orders["data"]["orders"]["edges"] if e["node"]["updatedAt"] > cutoff]
        return {"data": {"orders": {"edges": edges, "pageInfo": {"hasNextPage": False, "endCursor": None}}}}

    return call
