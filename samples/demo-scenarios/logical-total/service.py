"""Decimal order-total scenario. Prices are strings; quantities are integers."""
from decimal import Decimal, ROUND_HALF_UP


def order_total(items, tax_rate="0.10"):
    for item in items:
        if type(item["quantity"]) is not int or item["quantity"] <= 0:
            raise ValueError("quantity must be a positive integer")
    subtotal = sum((Decimal(item["unit_price"]) for item in items), Decimal("0"))
    return (subtotal * (Decimal("1") + Decimal(tax_rate))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


if __name__ == "__main__":
    print(order_total([{"unit_price": "19.95", "quantity": 2}, {"unit_price": "5.00", "quantity": 3}]))
