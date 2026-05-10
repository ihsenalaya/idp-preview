"""Contract tests — validate API responses against api/openapi.yaml using schemathesis."""
import os
import pytest
import schemathesis

pytestmark = pytest.mark.requires_api

OPENAPI_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "api", "openapi.yaml",
)

schema = schemathesis.from_path(OPENAPI_PATH, base_url="http://localhost:8080")


@schema.parametrize()
def test_api_conforms_to_openapi_schema(case):
    response = case.call()
    case.validate_response(response)


def test_healthz_returns_200(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.data in (b"ok", b'"ok"', b"ok\n")


def test_readyz_returns_200_or_503(client):
    resp = client.get("/readyz")
    assert resp.status_code in (200, 503)


def test_products_list_returns_array(client):
    resp = client.get("/api/products")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list)


def test_stats_endpoint_returns_object(client):
    resp = client.get("/api/stats")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, dict)


def test_create_product_smoke(client, db):
    import psycopg2.extras
    cur = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "INSERT INTO categories (name, slug) VALUES ('Contract Cat', 'contract-cat') ON CONFLICT (slug) DO UPDATE SET name=EXCLUDED.name RETURNING id"
    )
    cat_id = cur.fetchone()["id"]
    db.commit()

    resp = client.post("/api/products", json={
        "name": "Contract Product",
        "slug": "contract-product-smoke",
        "description": "smoke test",
        "price": 19.99,
        "stock": 10,
        "category_id": cat_id,
    })
    assert resp.status_code in (200, 201)
    data = resp.get_json()
    assert "id" in data or "id" in data.get("data", {})


def test_payments_list_returns_array(client):
    resp = client.get("/api/payments")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list)
