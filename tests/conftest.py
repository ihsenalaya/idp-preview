import os
import pytest
import psycopg2
import psycopg2.extras

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import app as application


@pytest.fixture(scope="session")
def db_url():
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set — skipping DB tests")
    return url


@pytest.fixture
def db(db_url):
    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    yield conn
    conn.rollback()
    conn.close()


@pytest.fixture
def flask_app():
    application.app.config["TESTING"] = True
    application.app.config["DATABASE_URL"] = os.environ.get(
        "DATABASE_URL", "postgresql://test:test@localhost/testdb"
    )
    yield application.app


@pytest.fixture
def client(flask_app):
    with flask_app.test_client() as c:
        yield c


@pytest.fixture
def api_base(flask_app):
    return ""


@pytest.fixture
def seeded_product(db):
    cur = db.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        """
        INSERT INTO categories (name, slug, description)
        VALUES ('Test Category', 'test-category', 'desc')
        ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
        RETURNING id
        """
    )
    cat_id = cur.fetchone()["id"]
    cur.execute(
        """
        INSERT INTO products (name, slug, description, price, stock, category_id)
        VALUES ('Test Product', 'test-product-conftest', 'desc', 99.99, 100, %s)
        ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
        RETURNING id
        """,
        (cat_id,),
    )
    product_id = cur.fetchone()["id"]
    db.commit()
    yield {"id": product_id, "category_id": cat_id, "price": 99.99, "stock": 100}
