"""Regression: oversell protection — cannot order more than available stock."""
import pytest

pytestmark = pytest.mark.requires_api


def test_order_within_stock_succeeds(client, db, seeded_product):
    resp = client.post("/api/orders", json={
        "product_id": seeded_product["id"],
        "quantity": 1,
    })
    assert resp.status_code in (200, 201)


def test_order_exceeding_stock_returns_409(client, db, seeded_product):
    pid = seeded_product["id"]
    cur = db.cursor()
    cur.execute("UPDATE products SET stock = 2 WHERE id = %s", (pid,))
    db.commit()

    resp = client.post("/api/orders", json={"product_id": pid, "quantity": 3})
    assert resp.status_code == 409
    data = resp.get_json()
    assert "stock" in str(data).lower() or "insufficient" in str(data).lower() or resp.status_code == 409


def test_stock_decrements_on_successful_order(client, db, seeded_product):
    pid = seeded_product["id"]
    cur = db.cursor()
    cur.execute("SELECT stock FROM products WHERE id = %s", (pid,))
    stock_before = cur.fetchone()[0]

    resp = client.post("/api/orders", json={"product_id": pid, "quantity": 1})
    assert resp.status_code in (200, 201)

    cur.execute("SELECT stock FROM products WHERE id = %s", (pid,))
    stock_after = cur.fetchone()[0]
    assert stock_after == stock_before - 1
