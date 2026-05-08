"""
Regression tests — verifies that all existing endpoints still work correctly.
Run by the Cellenza operator after each PR deployment.
Output lines starting with PASS/FAIL are parsed by the operator.
"""
import os
import sys
import requests

BASE         = os.environ.get("APP_URL", "http://app:80")
FRONTEND_URL = os.environ.get("FRONTEND_URL", BASE)

# Discover a real product id from the API (AI seed uses SERIAL, id may not start at 1).
def _first_product_id():
    try:
        r = requests.get(BASE + "/api/products", timeout=10)
        products = r.json()
        if products:
            return products[0]["id"]
    except Exception:
        pass
    return 1

_pid = _first_product_id()

tests = [
    # (name, method, url, expected_status, extra_check)
    ("homepage_html",      "GET", FRONTEND_URL + "/",                              200, lambda r: "Cellenza" in r.text or "catalogue" in r.text.lower()),
    ("health",             "GET", BASE + "/healthz",                               200, None),
    ("products_list",      "GET", BASE + "/api/products",                          200, lambda r: isinstance(r.json(), list)),
    ("product_detail",     "GET", BASE + f"/api/products/{_pid}",                  200, lambda r: "id" in r.json()),
    ("product_not_found",  "GET", BASE + "/api/products/99999",                    404, None),
    ("discounted_products","GET", BASE + "/api/products/discounted?min_discount=0",200, lambda r: isinstance(r.json(), list)),
    ("discounted_with_filter","GET",BASE + "/api/products/discounted?min_discount=50",200, None),
    ("related_products",   "GET", BASE + f"/api/products/{_pid}/related",          200, lambda r: isinstance(r.json(), list)),
    ("related_invalid",    "GET", BASE + "/api/products/99999/related",            404, None),
]

passed = 0
failed = 0

for name, method, url, expected_status, check in tests:
    try:
        r = requests.request(method, url, timeout=10)
        status_ok = r.status_code == expected_status
        check_ok = True
        if check and status_ok:
            try:
                check_ok = check(r)
            except Exception as e:
                check_ok = False
                print(f"FAIL regression {name}: check error — {e}")
                failed += 1
                continue

        if status_ok and check_ok:
            print(f"PASS regression {name}: {r.status_code}")
            passed += 1
        else:
            reason = f"expected {expected_status} got {r.status_code}" if not status_ok else "response check failed"
            print(f"FAIL regression {name}: {reason}")
            failed += 1
    except Exception as e:
        print(f"FAIL regression {name}: {e}")
        failed += 1

print(f"Results: {passed} passed, {failed} failed")
sys.exit(1 if failed > 0 else 0)
