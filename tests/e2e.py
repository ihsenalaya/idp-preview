"""
End-to-end tests — validates complete user flows, not isolated endpoints.
Run by the Cellenza operator after regression tests pass.
Output lines starting with PASS/FAIL are parsed by the operator.
"""
import os
import sys
import requests

BASE = os.environ.get("APP_URL", "http://app:80")

passed = 0
failed = 0


def run(name, fn):
    global passed, failed
    try:
        fn()
        print(f"PASS e2e {name}")
        passed += 1
    except AssertionError as e:
        print(f"FAIL e2e {name}: {e}")
        failed += 1
    except Exception as e:
        print(f"FAIL e2e {name}: {e}")
        failed += 1


def test_product_browsing_flow():
    """Browse products list → open detail → check related."""
    r = requests.get(f"{BASE}/api/products", timeout=10)
    assert r.status_code == 200, f"products list: expected 200 got {r.status_code}"
    products = r.json()
    assert len(products) > 0, "products list is empty"

    pid = products[0]["id"]

    r = requests.get(f"{BASE}/api/products/{pid}", timeout=10)
    assert r.status_code == 200, f"product detail: expected 200 got {r.status_code}"
    detail = r.json()
    assert detail.get("id") == pid, "product detail id mismatch"

    r = requests.get(f"{BASE}/api/products/{pid}/related", timeout=10)
    assert r.status_code == 200, f"related products: expected 200 got {r.status_code}"
    assert isinstance(r.json(), list), "related products should be a list"


def test_discount_filter_flow():
    """Apply discount filter and verify all returned products respect the threshold."""
    threshold = 10
    r = requests.get(f"{BASE}/api/products/discounted?min_discount={threshold}", timeout=10)
    assert r.status_code == 200, f"discounted: expected 200 got {r.status_code}"
    products = r.json()
    for p in products:
        discount = p.get("discount", 0)
        assert discount >= threshold, f"product {p.get('id')} has discount {discount} < {threshold}"


def test_not_found_flow():
    """Non-existent resources should return 404, not 500."""
    r = requests.get(f"{BASE}/api/products/999999", timeout=10)
    assert r.status_code == 404, f"missing product: expected 404 got {r.status_code}"

    r = requests.get(f"{BASE}/api/products/999999/related", timeout=10)
    assert r.status_code == 404, f"missing product related: expected 404 got {r.status_code}"


def test_zero_discount_boundary():
    """min_discount=0 should return all products (or at least not crash)."""
    r = requests.get(f"{BASE}/api/products/discounted?min_discount=0", timeout=10)
    assert r.status_code == 200, f"zero discount: expected 200 got {r.status_code}"


run("product_browsing_flow", test_product_browsing_flow)
run("discount_filter_flow", test_discount_filter_flow)
run("not_found_flow", test_not_found_flow)
run("zero_discount_boundary", test_zero_discount_boundary)

print(f"Results: {passed} passed, {failed} failed")
sys.exit(1 if failed > 0 else 0)
