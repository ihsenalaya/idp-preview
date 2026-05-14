"""
Smoke tests — vérifie que les endpoints critiques répondent correctement.
Exécuté par le preview-operator après chaque déploiement de PR.
Les lignes PASS/FAIL sont parsées par l'opérateur.
"""
import requests, sys, os

BASE = os.environ.get("APP_URL", "http://app")

checks = [
    ("/healthz",      200),
    ("/api/products", 200),
]

passed = 0
failed = 0

for path, expected in checks:
    try:
        r = requests.get(BASE + path, timeout=5)
        ok = r.status_code == expected
        label = "PASS" if ok else "FAIL"
        print(f"{label} smoke {path}: {r.status_code}")
        if ok:
            passed += 1
        else:
            failed += 1
    except Exception as e:
        print(f"FAIL smoke {path}: {e}")
        failed += 1

print(f"Results: {passed} passed, {failed} failed")
sys.exit(1 if failed > 0 else 0)
