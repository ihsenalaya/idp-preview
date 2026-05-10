"""Regression: review ratings accepted only in range 1–5."""
import pytest

pytestmark = pytest.mark.requires_api


def _post_review(client, product_id, rating, comment="test"):
    return client.post(f"/api/products/{product_id}/reviews", json={
        "rating": rating,
        "comment": comment,
        "author": "regression-tester",
    })


def test_rating_1_accepted(client, seeded_product):
    resp = _post_review(client, seeded_product["id"], 1)
    assert resp.status_code in (200, 201)


def test_rating_5_accepted(client, seeded_product):
    resp = _post_review(client, seeded_product["id"], 5)
    assert resp.status_code in (200, 201)


def test_rating_3_accepted(client, seeded_product):
    resp = _post_review(client, seeded_product["id"], 3)
    assert resp.status_code in (200, 201)


def test_rating_0_rejected(client, seeded_product):
    resp = _post_review(client, seeded_product["id"], 0)
    assert resp.status_code in (400, 422)


def test_rating_6_rejected(client, seeded_product):
    resp = _post_review(client, seeded_product["id"], 6)
    assert resp.status_code in (400, 422)


def test_rating_negative_rejected(client, seeded_product):
    resp = _post_review(client, seeded_product["id"], -1)
    assert resp.status_code in (400, 422)
