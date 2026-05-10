"""Regression (INTENTIONAL FAIL): order response should include total_price field.

This test is intentionally failing because the API currently does not return
a `total_price` field in the order response. kagent will analyse this failure.
"""
import pytest

pytestmark = [pytest.mark.requires_api, pytest.mark.kagent_demo]


def test_order_response_includes_total_price(client, seeded_product):
    resp = client.post("/api/orders", json={
        "product_id": seeded_product["id"],
        "quantity": 2,
    })
    assert resp.status_code in (200, 201)
    data = resp.get_json()
    # INTENTIONAL FAIL: total_price is not implemented yet
    assert "total_price" in data, (
        "Order response missing 'total_price' field — "
        "API must return the computed total including any discount"
    )


def test_order_total_reflects_quantity(client, seeded_product):
    resp = client.post("/api/orders", json={
        "product_id": seeded_product["id"],
        "quantity": 3,
    })
    assert resp.status_code in (200, 201)
    data = resp.get_json()
    # INTENTIONAL FAIL: field missing
    total = data.get("total_price")
    assert total is not None, "total_price missing from order response"
    expected = round(seeded_product["price"] * 3, 2)
    assert float(total) == expected, f"Expected total_price={expected}, got {total}"
