"""A tiny inventory-client configuration scenario. No network request is made."""
import json
from pathlib import Path
from urllib.parse import quote


def load_settings():
    return json.loads(Path(__file__).with_name("settings.json").read_text(encoding="utf-8"))


def inventory_request_url(sku):
    if not isinstance(sku, str) or not sku.strip():
        raise ValueError("sku must be a nonempty string")
    settings = load_settings()
    base_url = settings["api_url"].rstrip("/")
    return f"{base_url}/items/{quote(sku, safe='')}"


if __name__ == "__main__":
    print(inventory_request_url("SKU-42"))
