"""
Template for AI enrichment integration tests — product catalogue v2.
The AI enrichment job generates a similar file adapted to the PR diff.

Expected output format (one line per test):
  PASS: test_name
  FAIL: test_name — reason

Run locally:
  pip install requests
  APP_URL=http://localhost:80 python tests/example_test.py
"""
import os
import requests

BASE_URL = os.environ.get("APP_URL", "http://localhost:80").rstrip("/")


def test_health():
    r = requests.get(f"{BASE_URL}/healthz", timeout=5)
    assert r.status_code == 200
    assert r.text.strip() == "ok"


def test_version():
    r = requests.get(f"{BASE_URL}/api/version", timeout=5)
    assert r.status_code == 200
    data = r.json()
    assert data["version"] == "2.0.0"
    assert data["feature"] == "product-catalogue"


def test_list_categories_returns_json():
    r = requests.get(f"{BASE_URL}/api/categories", timeout=5)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_create_category():
    r = requests.post(
        f"{BASE_URL}/api/categories",
        json={"name": "Test Category", "slug": "test-category-ci"},
        timeout=5,
    )
    assert r.status_code in (201, 500)  # 500 if slug already exists (idempotent test runs)
    if r.status_code == 201:
        cat = r.json()
        assert cat["name"] == "Test Category"
        assert cat["id"] > 0


def test_list_products_returns_json():
    r = requests.get(f"{BASE_URL}/api/products", timeout=5)
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list)


def test_create_product():
    r = requests.post(
        f"{BASE_URL}/api/products",
        json={"name": "CI Test Product", "price": 9.99, "stock": 5, "discount_pct": 10},
        timeout=5,
    )
    assert r.status_code == 201
    p = r.json()
    assert p["name"] == "CI Test Product"
    assert p["price"] == 9.99
    assert p["id"] > 0


def test_get_product():
    create = requests.post(
        f"{BASE_URL}/api/products",
        json={"name": "CI Get Product", "price": 14.99, "stock": 3},
        timeout=5,
    )
    assert create.status_code == 201
    pid = create.json()["id"]

    r = requests.get(f"{BASE_URL}/api/products/{pid}", timeout=5)
    assert r.status_code == 200
    assert r.json()["name"] == "CI Get Product"


def test_get_nonexistent_product():
    r = requests.get(f"{BASE_URL}/api/products/999999", timeout=5)
    assert r.status_code == 404


def test_delete_product():
    create = requests.post(
        f"{BASE_URL}/api/products",
        json={"name": "CI Delete Product", "price": 1.00, "stock": 1},
        timeout=5,
    )
    assert create.status_code == 201
    pid = create.json()["id"]

    r = requests.delete(f"{BASE_URL}/api/products/{pid}", timeout=5)
    assert r.status_code == 204

    r2 = requests.get(f"{BASE_URL}/api/products/{pid}", timeout=5)
    assert r2.status_code == 404


def test_create_product_requires_price():
    r = requests.post(
        f"{BASE_URL}/api/products",
        json={"name": "Missing Price"},
        timeout=5,
    )
    assert r.status_code == 400


def test_create_review():
    create = requests.post(
        f"{BASE_URL}/api/products",
        json={"name": "CI Review Product", "price": 29.99, "stock": 10},
        timeout=5,
    )
    assert create.status_code == 201
    pid = create.json()["id"]

    r = requests.post(
        f"{BASE_URL}/api/products/{pid}/reviews",
        json={"author": "ci-bot", "rating": 5, "comment": "Excellent product"},
        timeout=5,
    )
    assert r.status_code == 201
    rev = r.json()
    assert rev["rating"] == 5
    assert rev["author"] == "ci-bot"


def test_review_rating_validation():
    create = requests.post(
        f"{BASE_URL}/api/products",
        json={"name": "CI Rating Validation", "price": 5.00, "stock": 1},
        timeout=5,
    )
    assert create.status_code == 201
    pid = create.json()["id"]

    r = requests.post(
        f"{BASE_URL}/api/products/{pid}/reviews",
        json={"author": "ci-bot", "rating": 6},
        timeout=5,
    )
    assert r.status_code == 400


def test_list_reviews():
    r_prods = requests.get(f"{BASE_URL}/api/products", timeout=5)
    assert r_prods.status_code == 200
    prods = r_prods.json()
    if prods:
        pid = prods[0]["id"]
        r = requests.get(f"{BASE_URL}/api/products/{pid}/reviews", timeout=5)
        assert r.status_code == 200
        assert isinstance(r.json(), list)


def test_create_order():
    create = requests.post(
        f"{BASE_URL}/api/products",
        json={"name": "CI Order Product", "price": 49.99, "stock": 20},
        timeout=5,
    )
    assert create.status_code == 201
    pid = create.json()["id"]

    r = requests.post(
        f"{BASE_URL}/api/orders",
        json={"product_id": pid, "quantity": 2},
        timeout=5,
    )
    assert r.status_code == 201
    order = r.json()
    assert order["product_id"] == pid
    assert order["quantity"] == 2
    assert order["status"] == "pending"


def test_order_insufficient_stock():
    create = requests.post(
        f"{BASE_URL}/api/products",
        json={"name": "CI Low Stock Product", "price": 9.99, "stock": 1},
        timeout=5,
    )
    assert create.status_code == 201
    pid = create.json()["id"]

    r = requests.post(
        f"{BASE_URL}/api/orders",
        json={"product_id": pid, "quantity": 99},
        timeout=5,
    )
    assert r.status_code == 409


def test_list_orders():
    r = requests.get(f"{BASE_URL}/api/orders", timeout=5)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_stats():
    r = requests.get(f"{BASE_URL}/api/stats", timeout=5)
    assert r.status_code == 200
    data = r.json()
    for key in ("total_products", "total_categories", "total_reviews", "total_orders",
                "out_of_stock", "low_stock", "categories"):
        assert key in data, f"missing key: {key}"
    assert isinstance(data["total_products"], int)
    assert isinstance(data["categories"], list)


def test_seeded_data():
    r = requests.get(f"{BASE_URL}/api/seeded-data", timeout=5)
    assert r.status_code == 200
    data = r.json()
    assert "products" in data
    assert "categories" in data
    assert "reviews" in data
    assert "total_orders" in data
    assert isinstance(data["products"], list)
    assert isinstance(data["categories"], list)
    assert isinstance(data["reviews"], list)


TESTS = [
    test_health,
    test_version,
    test_list_categories_returns_json,
    test_create_category,
    test_list_products_returns_json,
    test_create_product,
    test_get_product,
    test_get_nonexistent_product,
    test_delete_product,
    test_create_product_requires_price,
    test_create_review,
    test_review_rating_validation,
    test_list_reviews,
    test_create_order,
    test_order_insufficient_stock,
    test_list_orders,
    test_stats,
    test_seeded_data,
]

if __name__ == "__main__":
    passed = 0
    failed = 0
    for fn in TESTS:
        name = fn.__name__
        try:
            fn()
            print(f"PASS: {name}")
            passed += 1
        except Exception as exc:
            print(f"FAIL: {name} — {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
