import pytest

from service import available_stock, create_inventory


@pytest.fixture
def inventory():
    connection = create_inventory()
    yield connection
    connection.close()


@pytest.mark.parametrize("sku, expected", [("SKU-42", 12), ("SKU-99", 0), ("MISSING", 0)])
def test_stock_lookup(inventory, sku, expected):
    assert available_stock(inventory, sku) == expected


def test_seed_rows_are_present(inventory):
    assert inventory.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] == 2


def test_inventory_schema_preserves_stock_quantity(inventory):
    columns = [row[1] for row in inventory.execute("PRAGMA table_info(inventory)")]
    assert columns == ["sku", "stock_quantity"]
