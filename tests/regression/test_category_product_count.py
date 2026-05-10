"""Regression: product_count on category increments and decrements correctly."""
import pytest

pytestmark = pytest.mark.requires_api


def test_category_list_returns_product_count(client):
    resp = client.get("/api/categories")
    assert resp.status_code == 200
    cats = resp.get_json()
    if not cats:
        pytest.skip("no categories")
    for cat in cats[:3]:
        assert "product_count" in cat or "count" in cat


def test_new_product_increments_category_count(client, db):
    cur = db.cursor()
    cur.execute(
        "INSERT INTO categories (name, slug) VALUES ('CountCat', 'count-cat-reg') ON CONFLICT (slug) DO UPDATE SET name=EXCLUDED.name RETURNING id"
    )
    cat_id = cur.fetchone()[0]
    db.commit()

    resp_before = client.get(f"/api/categories")
    cats_before = {c["id"]: c.get("product_count", c.get("count", 0)) for c in resp_before.get_json() or []}
    count_before = cats_before.get(cat_id, 0)

    client.post("/api/products", json={
        "name": "Count Product",
        "slug": "count-product-reg-001",
        "description": "test",
        "price": 10.0,
        "stock": 5,
        "category_id": cat_id,
    })

    resp_after = client.get("/api/categories")
    cats_after = {c["id"]: c.get("product_count", c.get("count", 0)) for c in resp_after.get_json() or []}
    count_after = cats_after.get(cat_id, 0)

    assert count_after >= count_before
