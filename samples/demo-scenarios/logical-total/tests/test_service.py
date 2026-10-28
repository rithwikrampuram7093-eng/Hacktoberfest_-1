from decimal import Decimal

import pytest

from service import order_total


def test_total_includes_every_purchased_unit():
    items = [{"unit_price": "19.95", "quantity": 2}, {"unit_price": "5.00", "quantity": 3}]
    assert order_total(items) == Decimal("60.39")


def test_single_unit_total_is_preserved():
    assert order_total([{"unit_price": "10.00", "quantity": 1}]) == Decimal("11.00")


def test_empty_order_is_zero():
    assert order_total([]) == Decimal("0.00")


@pytest.mark.parametrize("quantity", [0, -1])
def test_invalid_quantities_are_rejected(quantity):
    with pytest.raises(ValueError):
        order_total([{"unit_price": "10.00", "quantity": quantity}])
