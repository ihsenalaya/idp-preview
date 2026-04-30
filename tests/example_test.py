"""
Template for AI enrichment integration tests.
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


def test_list_messages_returns_json():
    r = requests.get(f"{BASE_URL}/api/messages", timeout=5)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_create_message():
    r = requests.post(
        f"{BASE_URL}/api/messages",
        json={"author": "ci-bot", "text": "hello from AI enrichment test"},
        timeout=5,
    )
    assert r.status_code == 201
    msg = r.json()
    assert msg["author"] == "ci-bot"
    assert msg["id"] > 0


def test_get_message():
    create = requests.post(
        f"{BASE_URL}/api/messages",
        json={"author": "ci-bot", "text": "get-test"},
        timeout=5,
    )
    assert create.status_code == 201
    msg_id = create.json()["id"]

    r = requests.get(f"{BASE_URL}/api/messages/{msg_id}", timeout=5)
    assert r.status_code == 200
    assert r.json()["text"] == "get-test"


def test_delete_message():
    create = requests.post(
        f"{BASE_URL}/api/messages",
        json={"author": "ci-bot", "text": "to-delete"},
        timeout=5,
    )
    assert create.status_code == 201
    msg_id = create.json()["id"]

    r = requests.delete(f"{BASE_URL}/api/messages/{msg_id}", timeout=5)
    assert r.status_code == 204

    r2 = requests.get(f"{BASE_URL}/api/messages/{msg_id}", timeout=5)
    assert r2.status_code == 404


def test_stats():
    r = requests.get(f"{BASE_URL}/api/stats", timeout=5)
    assert r.status_code == 200
    data = r.json()
    assert "total_messages" in data
    assert isinstance(data["total_messages"], int)


def test_create_message_requires_text():
    r = requests.post(
        f"{BASE_URL}/api/messages",
        json={"author": "ci-bot"},
        timeout=5,
    )
    assert r.status_code == 400


def test_get_nonexistent_message():
    r = requests.get(f"{BASE_URL}/api/messages/999999", timeout=5)
    assert r.status_code == 404


TESTS = [
    test_health,
    test_list_messages_returns_json,
    test_create_message,
    test_get_message,
    test_delete_message,
    test_stats,
    test_create_message_requires_text,
    test_get_nonexistent_message,
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
