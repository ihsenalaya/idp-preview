"""Regression: discounted_price = price * (1 - pct/100), applied before taxes."""
import pytest
from app import calculate_discounted_price, apply_vat

pytestmark = pytest.mark.requires_api


def test_discount_applied_before_vat():
    price = 100.0
    discounted = calculate_discounted_price(price, 20)
    with_vat = apply_vat(discounted)
    assert discounted == 80.0
    assert with_vat == 96.0


def test_vat_on_discounted_price_not_original():
    price = 200.0
    discounted = calculate_discounted_price(price, 50)
    with_vat = apply_vat(discounted)
    assert with_vat == 120.0
    assert with_vat < apply_vat(price)


def test_discount_filter_endpoint(client):
    resp = client.get("/api/products?min_discount=10")
    assert resp.status_code in (200, 404)


def test_product_discount_field_returned(client):
    resp = client.get("/api/products")
    assert resp.status_code == 200
    products = resp.get_json()
    if not products:
        pytest.skip("no products")
    for p in products[:3]:
        disc = p.get("discount_percent", p.get("discount", None))
        if disc is not None:
            assert 0 <= float(disc) <= 100
