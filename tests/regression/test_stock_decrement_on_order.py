"""Regression: stock decrements correctly on sequential orders, never goes negative."""
import pytest

pytestmark = pytest.mark.requires_api


def test_stock_never_negative_on_sequential_orders(client, db, seeded_product):
    pid = seeded_product["id"]
    cur = db.cursor()
    cur.execute("UPDATE products SET stock = 3 WHERE id = %s", (pid,))
    db.commit()

    for i in range(3):
        resp = client.post("/api/orders", json={"product_id": pid, "quantity": 1})
        assert resp.status_code in (200, 201), f"order {i+1} failed: {resp.get_json()}"

    cur.execute("SELECT stock FROM products WHERE id = %s", (pid,))
    final_stock = cur.fetchone()[0]
    assert final_stock == 0

    resp = client.post("/api/orders", json={"product_id": pid, "quantity": 1})
    assert resp.status_code == 409


def test_stock_decrement_by_quantity(client, db, seeded_product):
    pid = seeded_product["id"]
    cur = db.cursor()
    cur.execute("UPDATE products SET stock = 10 WHERE id = %s", (pid,))
    db.commit()

    resp = client.post("/api/orders", json={"product_id": pid, "quantity": 4})
    assert resp.status_code in (200, 201)

    cur.execute("SELECT stock FROM products WHERE id = %s", (pid,))
    assert cur.fetchone()[0] == 6
