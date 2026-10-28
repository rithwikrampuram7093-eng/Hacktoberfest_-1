import pytest

from service import inventory_request_url, load_settings


def test_url_uses_configured_inventory_api():
    assert inventory_request_url("SKU 42/BLUE") == (
        "https://inventory.example.test/v1/items/SKU%2042%2FBLUE"
    )


def test_configuration_keeps_currency():
    assert load_settings()["currency"] == "USD"


@pytest.mark.parametrize("sku", ["", "   ", None])
def test_invalid_sku_is_rejected(sku):
    with pytest.raises(ValueError):
        inventory_request_url(sku)
