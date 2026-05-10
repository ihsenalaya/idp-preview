"""Regression: prices stored and returned as floats rounded to 2 decimal places."""
import pytest

pytestmark = pytest.mark.requires_api


def test_product_price_has_two_decimal_places(client):
    resp = client.get("/api/products")
    assert resp.status_code == 200
    products = resp.get_json()
    if not products:
        pytest.skip("no products in DB")
    for p in products[:5]:
        price = p.get("price", 0)
        assert round(price, 2) == price, f"price {price!r} not rounded to 2dp"


def test_create_product_price_rounded(client, db):
    cur = db.cursor()
    cur.execute(
        "INSERT INTO categories (name, slug) VALUES ('RoundCat', 'round-cat') ON CONFLICT (slug) DO UPDATE SET name=EXCLUDED.name RETURNING id"
    )
    cat_id = cur.fetchone()[0]
    db.commit()

    resp = client.post("/api/products", json={
        "name": "Rounding Test",
        "slug": "rounding-test-reg",
        "description": "test",
        "price": 9.999,
        "stock": 5,
        "category_id": cat_id,
    })
    assert resp.status_code in (200, 201)
    data = resp.get_json()
    price = data.get("price", data.get("data", {}).get("price"))
    if price is not None:
        assert round(float(price), 2) == float(price)
