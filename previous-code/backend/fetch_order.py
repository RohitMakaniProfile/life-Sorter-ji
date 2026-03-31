"""
fetch_order.py — Get full JusPay order response
================================================
Run: python fetch_order.py <order_id>

Copy the printed JSON and submit to JusPay for production approval.
"""

import base64
import json
import sys

import httpx

# ── Your sandbox credentials ───────────────────────────────────
MERCHANT_ID = "SG4280"
API_KEY     = "0001A71404D441AADF67639EF79943"
BASE_URL    = "https://smartgateway.hdfcuat.bank.in"

# ──────────────────────────────────────────────────────────────

def fetch(order_id: str):
    encoded = base64.b64encode(f"{API_KEY}:".encode()).decode()
    headers = {
        "Authorization": f"Basic {encoded}",
        "x-merchantid":  MERCHANT_ID,
        "x-routing-id":  order_id,
    }
    r = httpx.get(f"{BASE_URL}/orders/{order_id}", headers=headers, timeout=15)
    print(f"\nHTTP {r.status_code}\n")
    print(json.dumps(r.json(), indent=2))


if __name__ == "__main__":
    oid = sys.argv[1] if len(sys.argv) > 1 else input("Enter order_id: ").strip()
    fetch(oid)
