"""Regression (INTENTIONAL FAIL): duplicate payments for same order must return 409.

This test is intentionally failing because the current implementation accepts
duplicate payments instead of rejecting them. kagent will analyse this failure.
"""
import pytest

pytestmark = [pytest.mark.requires_api, pytest.mark.kagent_demo]


def test_duplicate_payment_returns_409(client, seeded_product):
    order_resp = client.post("/api/orders", json={
        "product_id": seeded_product["id"],
        "quantity": 1,
    })
    assert order_resp.status_code in (200, 201)
    order_id = order_resp.get_json().get("id") or order_resp.get_json().get("order_id")

    pay_payload = {
        "order_id": order_id,
        "amount": seeded_product["price"],
        "method": "card",
    }

    first = client.post("/api/payments", json=pay_payload)
    assert first.status_code in (200, 201), f"First payment failed: {first.get_json()}"

    # INTENTIONAL FAIL: second payment should be rejected with 409
    second = client.post("/api/payments", json=pay_payload)
    assert second.status_code == 409, (
        f"Expected 409 for duplicate payment on order {order_id}, "
        f"got {second.status_code}: {second.get_json()}"
    )
