import os
import json
import uuid
import datetime
import psycopg2
from flask import Flask, request, jsonify

app = Flask(__name__)


@app.after_request
def cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,DELETE,OPTIONS"
    return response

DATABASE_URL  = os.environ.get("DATABASE_URL", "")
POSTGRES_DB   = os.environ.get("POSTGRES_DB", "")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "")


def log(message, **fields):
    if os.environ.get("LOG_FORMAT") == "json":
        record = {"ts": datetime.datetime.utcnow().isoformat(), "msg": message}
        record.update(fields)
        print(json.dumps(record), flush=True)
    else:
        details = " ".join(f"{k}={v}" for k, v in fields.items() if v)
        print(f"[db] {message}" + (f" {details}" if details else ""), flush=True)


# ── Pure business-logic functions (testable without DB) ──────────────────────

def calculate_discounted_price(price: float, discount_pct: float) -> float:
    """Apply percentage discount to a unit price. Returns value rounded to 2dp."""
    if discount_pct < 0 or discount_pct > 100:
        raise ValueError(f"discount_pct must be 0–100, got {discount_pct}")
    return round(price * (1 - discount_pct / 100), 2)


def calculate_order_total(price: float, discount_pct: float, quantity: int) -> float:
    """Return the total cost for quantity units after applying the discount."""
    if quantity < 1:
        raise ValueError(f"quantity must be >= 1, got {quantity}")
    unit = calculate_discounted_price(price, discount_pct)
    return round(unit * quantity, 2)


def apply_vat(amount: float, rate: float = 0.20) -> float:
    """Add VAT at the given rate (default 20 %). Result rounded to 2dp."""
    if rate < 0:
        raise ValueError(f"VAT rate must be >= 0, got {rate}")
    return round(amount * (1 + rate), 2)


def validate_stock(available: int, requested: int) -> bool:
    """Return True if sufficient stock exists for the order."""
    return available >= requested and requested >= 1


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id   SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id           SERIAL PRIMARY KEY,
            name         TEXT NOT NULL,
            description  TEXT,
            category_id  INTEGER REFERENCES categories(id),
            price        NUMERIC(10,2) NOT NULL,
            stock        INTEGER       NOT NULL DEFAULT 0,
            discount_pct NUMERIC(5,2)  DEFAULT 0,
            created_at   TIMESTAMPTZ   DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id         SERIAL PRIMARY KEY,
            product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
            author     TEXT    NOT NULL DEFAULT 'anonymous',
            rating     INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
            comment    TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id            SERIAL PRIMARY KEY,
            product_id    INTEGER REFERENCES products(id),
            quantity      INTEGER NOT NULL DEFAULT 1,
            status        TEXT    NOT NULL DEFAULT 'pending',
            discount_code TEXT,
            created_at    TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id             SERIAL PRIMARY KEY,
            order_id       INTEGER REFERENCES orders(id),
            amount         NUMERIC(10,2) NOT NULL,
            method         TEXT NOT NULL DEFAULT 'card',
            transaction_id TEXT UNIQUE,
            status         TEXT NOT NULL DEFAULT 'completed',
            created_at     TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()
    conn.close()
    log("Schema ready", tables="categories,products,reviews,orders,payments")


def fetch_all_dicts(cur):
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@app.route("/healthz")
def healthz():
    return "ok", 200


@app.route("/readyz")
def readyz():
    try:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        return "ready", 200
    except Exception as e:
        return jsonify({"error": str(e)}), 503


@app.route("/ping")
def ping():
    return "pong", 200


# ── Pipeline / environment info ───────────────────────────────────────────────

@app.route("/api/pipeline-info", methods=["GET"])
def api_pipeline_info():
    """Returns preview environment metadata injected by the operator."""
    return jsonify({
        "version":     "1.0.1",
        "pr":          os.environ.get("PREVIEW_PR", ""),
        "branch":      os.environ.get("PREVIEW_BRANCH", ""),
        "environment": os.environ.get("ENVIRONMENT", "preview"),
        "namespace":   os.environ.get("PREVIEW_NAMESPACE", ""),
        "pipeline": {
            "stages": ["smoke", "contract (Microcks)", "regression", "e2e"],
            "contract_testing": {
                "tool":        "Microcks",
                "runner":      "OPEN_API_SCHEMA",
                "description": "Validates all API endpoints against the OpenAPI 3.0.3 contract"
            },
            "kagent": {
                "enabled":     True,
                "agent":       "preview-troubleshooter-agent",
                "trigger":     "Automatic on test suite failure",
                "description": "AI agent powered by Azure OpenAI gpt-4o-mini that inspects "
                               "failed jobs and posts a structured diagnosis as a GitHub PR comment"
            }
        }
    })


# ── REST API ──────────────────────────────────────────────────────────────────

@app.route("/api/categories", methods=["GET"])
def api_list_categories():
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("""
            SELECT c.id, c.name, c.slug, COUNT(p.id) AS product_count
            FROM categories c LEFT JOIN products p ON p.category_id = c.id
            GROUP BY c.id, c.name, c.slug ORDER BY c.name
        """)
        rows = fetch_all_dicts(cur)
        cur.close(); conn.close()
        return jsonify(rows)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/categories", methods=["POST"])
def api_create_category():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()[:100]
    slug = str(data.get("slug", "")).strip()[:100]
    if not name or not slug:
        return jsonify({"error": "name and slug are required"}), 400
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO categories (name,slug) VALUES (%s,%s) RETURNING id,name,slug",
            (name, slug)
        )
        r = cur.fetchone()
        conn.commit(); cur.close(); conn.close()
        return jsonify({"id": r[0], "name": r[1], "slug": r[2]}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/products", methods=["GET"])
def api_list_products():
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("""
            SELECT p.id, p.name, p.description, p.price, p.stock, p.discount_pct,
                   p.created_at, c.name AS category_name,
                   ROUND(AVG(r.rating)::numeric, 2) AS avg_rating,
                   COUNT(r.id) AS review_count
            FROM products p
            LEFT JOIN categories c ON c.id = p.category_id
            LEFT JOIN reviews r    ON r.product_id = p.id
            GROUP BY p.id,p.name,p.description,p.price,p.stock,p.discount_pct,p.created_at,c.name
            ORDER BY p.created_at DESC LIMIT 50
        """)
        rows = fetch_all_dicts(cur)
        cur.close(); conn.close()
        for r in rows:
            r["price"]        = float(r["price"])
            r["discount_pct"] = float(r["discount_pct"] or 0)
            r["avg_rating"]   = float(r["avg_rating"]) if r["avg_rating"] else None
            r["created_at"]   = r["created_at"].isoformat()
        return jsonify(rows)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/products", methods=["POST"])
def api_create_product():
    data = request.get_json(silent=True) or {}
    name    = str(data.get("name", "")).strip()[:100]
    price   = data.get("price")
    if not name or price is None:
        return jsonify({"error": "name and price are required"}), 400
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO products (name,description,category_id,price,stock,discount_pct) "
            "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id,name,price,stock,discount_pct,created_at",
            (name, data.get("description"), data.get("category_id"),
             price, int(data.get("stock", 0)), float(data.get("discount_pct", 0)))
        )
        r = cur.fetchone()
        conn.commit(); cur.close(); conn.close()
        return jsonify({"id": r[0], "name": r[1], "price": float(r[2]),
                        "stock": r[3], "discount_pct": float(r[4]),
                        "created_at": r[5].isoformat()}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/products/<int:pid>", methods=["GET"])
def api_get_product(pid):
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("""
            SELECT p.id,p.name,p.description,p.price,p.stock,p.discount_pct,p.created_at,c.name
            FROM products p LEFT JOIN categories c ON c.id=p.category_id WHERE p.id=%s
        """, (pid,))
        row = cur.fetchone()
        if not row:
            cur.close(); conn.close()
            return jsonify({"error": "not found"}), 404
        cur.execute(
            "SELECT id,author,rating,comment,created_at FROM reviews WHERE product_id=%s ORDER BY created_at DESC",
            (pid,)
        )
        reviews = [{"id": r[0], "author": r[1], "rating": r[2],
                    "comment": r[3], "created_at": r[4].isoformat()} for r in cur.fetchall()]
        cur.close(); conn.close()
        return jsonify({"id": row[0], "name": row[1], "description": row[2],
                        "price": float(row[3]), "stock": row[4],
                        "discount_pct": float(row[5] or 0),
                        "created_at": row[6].isoformat(),
                        "category_name": row[7], "reviews": reviews})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/products/<int:pid>", methods=["DELETE"])
def api_delete_product(pid):
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("DELETE FROM products WHERE id=%s RETURNING id", (pid,))
        deleted = cur.fetchone()
        conn.commit(); cur.close(); conn.close()
        if not deleted:
            return jsonify({"error": "not found"}), 404
        return "", 204
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/products/<int:pid>/reviews", methods=["GET"])
def api_list_reviews(pid):
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT id FROM products WHERE id=%s", (pid,))
        if not cur.fetchone():
            cur.close(); conn.close()
            return jsonify({"error": "product not found"}), 404
        cur.execute(
            "SELECT id,author,rating,comment,created_at FROM reviews WHERE product_id=%s ORDER BY created_at DESC",
            (pid,)
        )
        rows = [{"id": r[0], "author": r[1], "rating": r[2],
                 "comment": r[3], "created_at": r[4].isoformat()} for r in cur.fetchall()]
        cur.close(); conn.close()
        return jsonify(rows)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/products/<int:pid>/reviews", methods=["POST"])
def api_create_review(pid):
    data   = request.get_json(silent=True) or {}
    author = str(data.get("author", "anonymous"))[:50]
    rating = int(data.get("rating", 0))
    if rating < 1 or rating > 5:
        return jsonify({"error": "rating must be between 1 and 5"}), 400
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT id FROM products WHERE id=%s", (pid,))
        if not cur.fetchone():
            cur.close(); conn.close()
            return jsonify({"error": "product not found"}), 404
        cur.execute(
            "INSERT INTO reviews (product_id,author,rating,comment) VALUES (%s,%s,%s,%s) "
            "RETURNING id,author,rating,comment,created_at",
            (pid, author, rating, str(data.get("comment", ""))[:500] or None)
        )
        r = cur.fetchone()
        conn.commit(); cur.close(); conn.close()
        return jsonify({"id": r[0], "author": r[1], "rating": r[2],
                        "comment": r[3], "created_at": r[4].isoformat()}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/orders", methods=["POST"])
def api_create_order():
    data       = request.get_json(silent=True) or {}
    product_id = data.get("product_id")
    quantity   = int(data.get("quantity", 1))
    if not product_id or quantity < 1:
        return jsonify({"error": "product_id and quantity >= 1 are required"}), 400
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT id,stock FROM products WHERE id=%s", (product_id,))
        prod = cur.fetchone()
        if not prod:
            cur.close(); conn.close()
            return jsonify({"error": "product not found"}), 404
        if prod[1] < quantity:
            cur.close(); conn.close()
            return jsonify({"error": "insufficient stock"}), 409
        cur.execute(
            "INSERT INTO orders (product_id,quantity) VALUES (%s,%s) "
            "RETURNING id,product_id,quantity,status,created_at",
            (product_id, quantity)
        )
        r = cur.fetchone()
        cur.execute("UPDATE products SET stock=stock-%s WHERE id=%s", (quantity, product_id))
        conn.commit(); cur.close(); conn.close()
        return jsonify({"id": r[0], "product_id": r[1], "quantity": r[2],
                        "status": r[3], "created_at": r[4].isoformat()}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/orders", methods=["GET"])
def api_list_orders():
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("""
            SELECT o.id, o.product_id, p.name AS product_name, o.quantity, o.status, o.created_at
            FROM orders o LEFT JOIN products p ON p.id=o.product_id
            ORDER BY o.created_at DESC LIMIT 50
        """)
        rows = fetch_all_dicts(cur)
        cur.close(); conn.close()
        for r in rows:
            r["created_at"] = r["created_at"].isoformat()
        return jsonify(rows)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/payments", methods=["POST"])
def api_create_payment():
    """Process a payment for an existing order via the fake PSP."""
    data     = request.get_json(silent=True) or {}
    order_id = data.get("order_id")
    amount   = data.get("amount")
    method   = str(data.get("method", "card"))[:20]

    if not order_id or amount is None:
        return jsonify({"error": "order_id and amount are required"}), 400
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT id, status FROM orders WHERE id=%s", (order_id,))
        order = cur.fetchone()
        if not order:
            cur.close(); conn.close()
            return jsonify({"error": "order not found"}), 404

        txn_id = str(uuid.uuid4())
        cur.execute("""
            INSERT INTO payments (order_id, amount, method, transaction_id, status)
            VALUES (%s, %s, %s, %s, 'completed')
            RETURNING id, order_id, amount, method, transaction_id, status, created_at
        """, (order_id, amount, method, txn_id))
        r = cur.fetchone()
        cur.execute("UPDATE orders SET status='paid' WHERE id=%s", (order_id,))
        conn.commit(); cur.close(); conn.close()
        return jsonify({
            "id":             r[0],
            "order_id":       r[1],
            "amount":         float(r[2]),
            "method":         r[3],
            "transaction_id": r[4],
            "status":         r[5],
            "created_at":     r[6].isoformat(),
        }), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/payments", methods=["GET"])
def api_list_payments():
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("""
            SELECT id, order_id, amount, method, transaction_id, status, created_at
            FROM payments ORDER BY created_at DESC LIMIT 50
        """)
        rows = fetch_all_dicts(cur)
        cur.close(); conn.close()
        for r in rows:
            r["amount"]     = float(r["amount"])
            r["created_at"] = r["created_at"].isoformat()
        return jsonify(rows)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/stats", methods=["GET"])
def api_stats():
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM products");   total_products    = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM categories"); total_categories  = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM reviews");    total_reviews     = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM orders");     total_orders      = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM products WHERE stock=0");      out_of_stock = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM products WHERE stock>0 AND stock<5"); low_stock = cur.fetchone()[0]
        cur.execute("SELECT ROUND(AVG(rating)::numeric,2) FROM reviews"); avg_rating = cur.fetchone()[0]
        cur.execute("SELECT DISTINCT name FROM categories ORDER BY name")
        categories = [r[0] for r in cur.fetchall()]
        cur.close(); conn.close()
        return jsonify({
            "total_products":   total_products,
            "total_categories": total_categories,
            "total_reviews":    total_reviews,
            "total_orders":     total_orders,
            "out_of_stock":     out_of_stock,
            "low_stock":        low_stock,
            "avg_rating":       float(avg_rating) if avg_rating else None,
            "categories":       categories,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/seeded-data", methods=["GET"])
def api_seeded_data():
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("""
            SELECT p.id,p.name,p.description,p.price,p.stock,p.discount_pct,
                   p.created_at, c.name AS category_name
            FROM products p LEFT JOIN categories c ON c.id=p.category_id
            ORDER BY p.created_at ASC
        """)
        products = fetch_all_dicts(cur)
        for p in products:
            p["price"]        = float(p["price"])
            p["discount_pct"] = float(p["discount_pct"] or 0)
            p["created_at"]   = p["created_at"].isoformat()

        cur.execute("SELECT id,name,slug FROM categories ORDER BY name")
        categories = [{"id": r[0], "name": r[1], "slug": r[2]} for r in cur.fetchall()]

        cur.execute("""
            SELECT r.id,r.product_id,p.name AS product_name,r.author,r.rating,r.comment,r.created_at
            FROM reviews r JOIN products p ON p.id=r.product_id
            ORDER BY r.created_at ASC
        """)
        reviews = fetch_all_dicts(cur)
        for r in reviews:
            r["created_at"] = r["created_at"].isoformat()

        cur.execute("SELECT COUNT(*) FROM orders"); total_orders = cur.fetchone()[0]
        cur.close(); conn.close()

        return jsonify({
            "products":     products,
            "categories":   categories,
            "reviews":      reviews,
            "total_orders": total_orders,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/products/discounted", methods=["GET"])
def api_discounted_products():
    try:
        min_discount = request.args.get("min_discount", 0, type=float)
        conn = get_conn(); cur = conn.cursor()
        cur.execute("""
            SELECT p.id, p.name, p.description, p.price, p.stock, p.discount_pct,
                   ROUND(p.price * (1 - p.discount_pct / 100), 2) AS discounted_price,
                   c.name AS category_name
            FROM products p
            LEFT JOIN categories c ON c.id = p.category_id
            WHERE p.discount_pct >= %s AND p.stock > 0
            ORDER BY p.discount_pct DESC
        """, (min_discount,))
        products = fetch_all_dicts(cur)
        for p in products:
            p["price"]            = float(p["price"])
            p["discount_pct"]     = float(p["discount_pct"] or 0)
            p["discounted_price"] = float(p["discounted_price"] or p["price"])
        cur.close(); conn.close()
        return jsonify({"products": products, "count": len(products)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/products/<int:product_id>/related", methods=["GET"])
def api_related_products(product_id):
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT category_id FROM products WHERE id = %s", (product_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Product not found"}), 404
        category_id = row[0]
        cur.execute("""
            SELECT p.id, p.name, p.price, p.stock, p.discount_pct,
                   ROUND(p.price * (1 - p.discount_pct / 100), 2) AS discounted_price
            FROM products p
            WHERE p.category_id = %s AND p.id != %s AND p.stock > 0
            ORDER BY p.created_at DESC
            LIMIT 5
        """, (category_id, product_id))
        products = fetch_all_dicts(cur)
        for p in products:
            p["price"]            = float(p["price"])
            p["discount_pct"]     = float(p["discount_pct"] or 0)
            p["discounted_price"] = float(p["discounted_price"] or p["price"])
        cur.close(); conn.close()
        return jsonify({"products": products, "count": len(products)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/version", methods=["GET"])
def api_version():
    return jsonify({
        "version":  "1.0.1",
        "operator": "preview-operator",
        "features": ["contract-testing", "kagent-ai-analysis", "ai-enrichment"]
    })


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8080)
