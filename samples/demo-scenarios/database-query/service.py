"""In-memory inventory database scenario, with no external dependencies."""
import sqlite3


def create_inventory():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE inventory (sku TEXT PRIMARY KEY, stock_quantity INTEGER NOT NULL)")
    connection.executemany("INSERT INTO inventory VALUES (?, ?)", [("SKU-42", 12), ("SKU-99", 0)])
    connection.commit()
    return connection


def available_stock(connection, sku):
    row = connection.execute("SELECT quantity FROM inventory WHERE sku = ?", (sku,)).fetchone()
    return row[0] if row else 0


if __name__ == "__main__":
    inventory = create_inventory()
    try:
        print(available_stock(inventory, "SKU-42"))
    finally:
        inventory.close()
