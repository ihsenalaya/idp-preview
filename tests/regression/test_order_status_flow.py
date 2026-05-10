"""Regression: order status transitions pending → paid via POST /api/payments."""
import pytest

pytestmark = pytest.mark.requires_api


def test_new_order_is_pending(client, seeded_product):
    resp = client.post("/api/orders", json={"product_id": seeded_product["id"], "quantity": 1})
    assert resp.status_code in (200, 201)
    data = resp.get_json()
    order_id = data.get("id") or data.get("order_id")
    assert order_id is not None

    order_resp = client.get(f"/api/orders/{order_id}")
    assert order_resp.status_code == 200
    order = order_resp.get_json()
    assert order.get("status") == "pending"


def test_payment_transitions_order_to_paid(client, seeded_product):
    order_resp = client.post("/api/orders", json={"product_id": seeded_product["id"], "quantity": 1})
    assert order_resp.status_code in (200, 201)
    order_id = order_resp.get_json().get("id") or order_resp.get_json().get("order_id")

    pay_resp = client.post("/api/payments", json={
        "order_id": order_id,
        "amount": seeded_product["price"],
        "method": "card",
    })
    assert pay_resp.status_code in (200, 201)
    pay_data = pay_resp.get_json()
    assert "transaction_id" in pay_data

    order_resp2 = client.get(f"/api/orders/{order_id}")
    assert order_resp2.status_code == 200
    assert order_resp2.get_json().get("status") == "paid"
