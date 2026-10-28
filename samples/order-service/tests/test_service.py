"""Behavioral requirements. Repair application source; do not edit these tests."""

from decimal import Decimal

import pytest

from service import available_stock, connect_inventory, inventory_url, load_settings, order_total


def test_inventory_endpoint_uses_supplied_configuration():
    settings = load_settings()
    assert inventory_url(settings, "SKU-42") == "https://inventory.example.test/v1/items/SKU-42"


def test_inventory_endpoint_encodes_sku_path_component():
    assert inventory_url(load_settings(), "SKU 42/BLUE") == (
        "https://inventory.example.test/v1/items/SKU%2042%2FBLUE"
    )


@pytest.mark.parametrize("sku, expected", [("SKU-42", 12), ("SKU-99", 0), ("MISSING", 0)])
def test_inventory_lookup_uses_database_stock(sku, expected):
    connection = connect_inventory()
    try:
        assert available_stock(connection, sku) == expected
    finally:
        connection.close()


def test_quote_charges_for_every_unit_and_applies_tax():
    items = [
        {"unit_price": "19.95", "quantity": 2},
        {"unit_price": "5.00", "quantity": 3},
    ]
    assert order_total(items, "0.10") == Decimal("60.39")


def test_quote_rounds_half_up_to_cents():
    assert order_total([{"unit_price": "0.05", "quantity": 3}], "0.10") == Decimal("0.17")


def test_single_item_quote():
    assert order_total([{"unit_price": "10.00", "quantity": 1}], "0.10") == Decimal("11.00")


def test_empty_order_is_zero():
    assert order_total([], "0.10") == Decimal("0.00")


@pytest.mark.parametrize("quantity", [0, -1, True, "2", 1.5])
def test_invalid_quantities_are_rejected(quantity):
    with pytest.raises(ValueError):
        order_total([{"unit_price": "10.00", "quantity": quantity}], "0.10")
