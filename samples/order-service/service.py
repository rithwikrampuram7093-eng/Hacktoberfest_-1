"""A deliberately failing, network-free order API used by the RootCause demo.

Run inside an isolated container. The application only needs the standard library;
its executable specification is in tests/test_service.py.
"""

from __future__ import annotations

import argparse
from decimal import Decimal, ROUND_HALF_UP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit


LOG = logging.getLogger("order_service")
SETTINGS_FILE = Path(__file__).with_name("settings.json")


def load_settings(path: Path = SETTINGS_FILE) -> dict[str, Any]:
    """Load the application configuration supplied with this project."""
    return json.loads(path.read_text(encoding="utf-8"))


def inventory_url(settings: dict[str, Any], sku: str) -> str:
    """Construct a URL; no outbound HTTP request is needed for the demo."""
    try:
        base_url = settings["inventory_url"].rstrip("/")
        return f"{base_url}/items/{quote(sku, safe='')}"
    except (KeyError, TypeError):
        LOG.exception("Inventory API configuration could not be loaded")
        raise


def connect_inventory() -> sqlite3.Connection:
    """Create a tiny inventory database with a stable, documented schema."""
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE inventory (sku TEXT PRIMARY KEY, stock_quantity INTEGER NOT NULL)"
    )
    connection.executemany(
        "INSERT INTO inventory (sku, stock_quantity) VALUES (?, ?)",
        [("SKU-42", 12), ("SKU-99", 0)],
    )
    connection.commit()
    return connection


def available_stock(connection: sqlite3.Connection, sku: str) -> int:
    """Return the persisted stock count, or zero for a missing SKU."""
    try:
        row = connection.execute(
            "SELECT quantity FROM inventory WHERE sku = ?", (sku,)
        ).fetchone()
        return int(row[0]) if row else 0
    except sqlite3.DatabaseError:
        LOG.exception("Inventory lookup failed for sku=%s", sku)
        raise


def order_total(items: list[dict[str, Any]], tax_rate: str) -> Decimal:
    """Return the tax-inclusive total in dollars, rounded to cents.

    Unit prices and tax rates are decimal strings. Every item must have a
    positive integer quantity; zero-item orders are allowed.
    """
    for item in items:
        if isinstance(item["quantity"], bool) or not isinstance(item["quantity"], int):
            raise ValueError("quantity must be an integer")
        if item["quantity"] <= 0:
            raise ValueError("quantity must be positive")
        if Decimal(item["unit_price"]) < 0:
            raise ValueError("unit_price must be nonnegative")
    subtotal = sum((Decimal(item["unit_price"]) for item in items), Decimal("0"))
    total = (subtotal * (Decimal("1") + Decimal(tax_rate))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    LOG.info("Calculated quote: items=%d subtotal=%s total=%s", len(items), subtotal, total)
    return total


class OrderHandler(BaseHTTPRequestHandler):
    """Small local API: /health, /api/inventory-url, /api/stock, /api/quote."""

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        request = urlsplit(self.path)
        params = parse_qs(request.query)
        try:
            if request.path == "/health":
                self._send_json(200, {"status": "ok"})
            elif request.path == "/api/inventory-url":
                sku = params.get("sku", ["SKU-42"])[0]
                self._send_json(200, {"url": inventory_url(load_settings(), sku)})
            elif request.path == "/api/stock":
                sku = params.get("sku", ["SKU-42"])[0]
                connection = connect_inventory()
                try:
                    stock = available_stock(connection, sku)
                finally:
                    connection.close()
                self._send_json(200, {"sku": sku, "available": stock})
            else:
                self._send_json(404, {"error": "Route not found"})
        except Exception:
            LOG.exception("Request failed: %s", request.path)
            self._send_json(500, {"error": "Request failed; see application log"})

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/api/quote":
            self._send_json(404, {"error": "Route not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 65536:
                self._send_json(400, {"error": "Provide a JSON body under 64 KiB"})
                return
            payload = json.loads(self.rfile.read(length))
            total = order_total(payload["items"], load_settings()["tax_rate"])
            self._send_json(200, {"total": str(total), "currency": "USD"})
        except (ValueError, KeyError, TypeError):
            LOG.exception("Invalid quote request")
            self._send_json(400, {"error": "Invalid quote request"})


def main() -> None:
    parser = argparse.ArgumentParser(description="RootCause sample order service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    LOG.info("Order service listening on %s:%d", args.host, args.port)
    ThreadingHTTPServer((args.host, args.port), OrderHandler).serve_forever()


if __name__ == "__main__":
    main()
