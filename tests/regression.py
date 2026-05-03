"""
Regression tests — verifies that all existing endpoints still work correctly.
Run by the Cellenza operator after each PR deployment.
Output lines starting with PASS/FAIL are parsed by the operator.
"""
import os
import sys
import requests

BASE = os.environ.get("APP_URL", "http://app:80")

tests = [
    # (name, method, path, expected_status, extra_check)
    ("homepage_html", "GET", "/", 200, lambda r: "Cellenza" in r.text and "Catalogue" in r.text),
    ("health", "GET", "/health", 200, None),
    ("products_list", "GET", "/api/products", 200, lambda r: isinstance(r.json(), list)),
    ("product_detail", "GET", "/api/products/1", 200, lambda r: "id" in r.json()),
    ("product_not_found", "GET", "/api/products/99999", 404, None),
    ("discounted_products", "GET", "/api/products/discounted?min_discount=0", 200, lambda r: isinstance(r.json(), list)),
    ("discounted_with_filter", "GET", "/api/products/discounted?min_discount=50", 200, None),
    ("related_products", "GET", "/api/products/1/related", 200, lambda r: isinstance(r.json(), list)),
    ("related_invalid", "GET", "/api/products/99999/related", 404, None),
]

passed = 0
failed = 0

for name, method, path, expected_status, check in tests:
    try:
        r = requests.request(method, BASE + path, timeout=10)
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
