import os
import psycopg2
from flask import Flask, request, redirect, jsonify, render_template

app = Flask(__name__)

DATABASE_URL  = os.environ.get("DATABASE_URL", "")
POSTGRES_DB   = os.environ.get("POSTGRES_DB", "")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "")


def log(message, **fields):
    details = " ".join(f"{k}={v}" for k, v in fields.items() if v)
    print(f"[db] {message}" + (f" {details}" if details else ""), flush=True)


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
            id         SERIAL PRIMARY KEY,
            product_id INTEGER REFERENCES products(id),
            quantity   INTEGER NOT NULL DEFAULT 1,
            status     TEXT    NOT NULL DEFAULT 'pending',
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()
    conn.close()
    log("Schema ready", tables="categories,products,reviews,orders")


# ── helpers ───────────────────────────────────────────────────────────────────

def stars(n):
    n = int(n or 0)
    return "★" * n + "☆" * (5 - n)


def stock_color(n):
    if n == 0:   return "#ef4444"
    if n < 5:    return "#f97316"
    return "#22c55e"


def fetch_all_dicts(cur):
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


# ── HTML ──────────────────────────────────────────────────────────────────────

def render_page(db_ok, pg_version, products, categories, ai_data=None, error=""):
    status_color = "#22c55e" if db_ok else "#ef4444"
    status_label = "Connecté"  if db_ok else "Erreur"

    # env block
    env_items = ""
    for key in ("POSTGRES_USER", "POSTGRES_DB", "PREVIEW_BRANCH", "PREVIEW_PR", "ENVIRONMENT"):
        env_items += f'<div class="env-item"><span class="key">{key}</span>{os.environ.get(key,"—")}</div>'

    # category <select>
    cat_opts = '<option value="">— Sans catégorie —</option>'
    for c in categories:
        cat_opts += f'<option value="{c["id"]}">{c["name"]}</option>'

    # product cards
    prod_cards = ""
    for p in products:
        disc    = float(p.get("discount_pct") or 0)
        final   = float(p["price"]) * (1 - disc / 100)
        disc_lbl = f'<span class="disc-badge">-{int(disc)}%</span>' if disc else ""
        avg     = p.get("avg_rating")
        rev_lbl = f'<div class="stars">{stars(avg)} <span class="rev-count">({p["review_count"]} avis)</span></div>' if avg else ""
        prod_cards += f"""
      <div class="prod-card">
        <div class="prod-cat">{p.get("category_name") or "Non classé"}</div>
        <div class="prod-name">{p["name"]}</div>
        <div class="prod-desc">{p.get("description") or ""}</div>
        <div class="prod-foot">
          <span class="prod-price">{final:.2f} € {disc_lbl}</span>
          <span class="stock-badge" style="background:{stock_color(p['stock'])}">Stock&nbsp;{p['stock']}</span>
        </div>
        {rev_lbl}
      </div>"""
    if not prod_cards:
        prod_cards = '<p class="empty">Aucun produit — ajoutez-en un ou attendez que l\'IA enrichisse la preview.</p>'

    # AI enrichment card
    ai_card = ""
    if ai_data and ai_data.get("products"):
        chips = "".join(f'<span class="chip">{c}</span>' for c in (ai_data.get("categories") or []))
        ai_rows = ""
        for p in ai_data["products"]:
            disc    = float(p.get("discount_pct") or 0)
            d_label = f'-{int(disc)}%' if disc else "—"
            avg_r   = p.get("avg_rating")
            r_label = f'{stars(avg_r)} ({p.get("review_count",0)})' if avg_r else "—"
            ai_rows += f"""
          <tr>
            <td>{p["id"]}</td>
            <td><strong>{p["name"]}</strong></td>
            <td>{p.get("category_name") or "—"}</td>
            <td>{float(p["price"]):.2f} €</td>
            <td>{d_label}</td>
            <td>{p["stock"]}</td>
            <td class="stars-cell">{r_label}</td>
          </tr>"""
        model = os.environ.get("AI_MODEL", "gpt-4o")
        ai_card = f"""
    <div class="card ai-card">
      <h2><span class="ai-badge">&#129302; AI</span> Catalogue généré par enrichissement IA</h2>
      <p class="ai-meta">
        Données seed générées par <strong>{model}</strong> à partir du diff de la PR
        et du schéma PostgreSQL. &nbsp;·&nbsp;
        <strong>{ai_data["total_products"]}</strong> produit(s) &nbsp;·&nbsp;
        <strong>{ai_data["total_reviews"]}</strong> avis &nbsp;·&nbsp;
        <strong>{ai_data["total_orders"]}</strong> commande(s)
      </p>
      <div class="chips">{chips}</div>
      <div class="table-wrap">
        <table>
          <thead><tr>
            <th>#</th><th>Produit</th><th>Catégorie</th>
            <th>Prix</th><th>Remise</th><th>Stock</th><th>Note</th>
          </tr></thead>
          <tbody>{ai_rows}</tbody>
        </table>
      </div>
    </div>"""

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Cellenza — Catalogue Demo</title>
  <style>
    *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:system-ui,-apple-system,sans-serif;background:#f1f5f9;color:#1e293b}}
    header{{background:linear-gradient(135deg,#1e293b,#334155);color:#fff;padding:1.5rem 2rem}}
    header h1{{font-size:1.4rem}}
    header p{{font-size:.85rem;opacity:.65;margin-top:.2rem}}
    .badge{{display:inline-block;background:{status_color};color:#fff;padding:.2rem .65rem;
            border-radius:999px;font-size:.75rem;font-weight:700;letter-spacing:.5px}}
    .ai-badge{{background:#7c3aed;color:#fff;padding:.2rem .65rem;border-radius:999px;
               font-size:.75rem;font-weight:700;margin-right:.5rem}}
    .container{{max-width:1020px;margin:2rem auto;padding:0 1rem;display:grid;gap:1.25rem}}
    .card{{background:#fff;border-radius:10px;padding:1.5rem;box-shadow:0 1px 4px rgba(0,0,0,.08)}}
    .ai-card{{border-left:4px solid #7c3aed}}
    .card h2{{font-size:.85rem;text-transform:uppercase;letter-spacing:.8px;color:#94a3b8;margin-bottom:1rem}}
    .ai-meta{{font-size:.82rem;color:#64748b;margin-bottom:.75rem;line-height:1.6}}
    .db-info{{display:flex;align-items:center;gap:.75rem;flex-wrap:wrap}}
    .version{{font-family:monospace;font-size:.82rem;color:#64748b}}
    .error{{color:#ef4444;font-size:.82rem;margin-top:.5rem;font-family:monospace}}
    .env-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:.5rem;margin-top:1rem}}
    .env-item{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:.5rem .75rem;font-size:.8rem}}
    .env-item .key{{display:block;font-family:monospace;color:#7c3aed;font-weight:700;margin-bottom:.15rem}}
    .chips{{display:flex;flex-wrap:wrap;gap:.35rem;margin-bottom:.85rem}}
    .chip{{background:#ede9fe;color:#6d28d9;border:1px solid #c4b5fd;border-radius:999px;
           padding:.15rem .6rem;font-size:.78rem}}
    .table-wrap{{overflow-x:auto}}
    table{{width:100%;border-collapse:collapse;margin-top:.5rem}}
    thead th{{text-align:left;padding:.5rem .6rem;font-size:.73rem;font-weight:700;
              text-transform:uppercase;letter-spacing:.5px;color:#94a3b8;border-bottom:2px solid #f1f5f9}}
    tbody td{{padding:.6rem .6rem;border-bottom:1px solid #f8fafc;font-size:.85rem}}
    tbody tr:hover td{{background:#fafafa}}
    .stars-cell{{color:#f59e0b;white-space:nowrap}}
    .empty{{color:#cbd5e1;font-style:italic;font-size:.88rem;padding:1rem 0}}
    .prod-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:1rem;margin-top:1rem}}
    .prod-card{{border:1px solid #e2e8f0;border-radius:8px;padding:1rem;background:#fafafa;
                display:flex;flex-direction:column;gap:.4rem}}
    .prod-cat{{font-size:.7rem;text-transform:uppercase;color:#7c3aed;font-weight:700}}
    .prod-name{{font-weight:700;font-size:.95rem}}
    .prod-desc{{font-size:.8rem;color:#64748b;flex:1}}
    .prod-foot{{display:flex;justify-content:space-between;align-items:center;margin-top:.4rem;flex-wrap:wrap;gap:.3rem}}
    .prod-price{{font-weight:700}}
    .disc-badge{{background:#fef9c3;color:#854d0e;border-radius:4px;padding:.1rem .35rem;font-size:.7rem;margin-left:.3rem}}
    .stock-badge{{color:#fff;font-size:.72rem;font-weight:700;padding:.15rem .5rem;border-radius:999px;white-space:nowrap}}
    .stars{{font-size:.82rem;color:#f59e0b}}
    .rev-count{{color:#94a3b8;font-size:.75rem}}
    form{{display:flex;gap:.5rem;flex-wrap:wrap;margin-top:.75rem}}
    input,select,textarea{{flex:1;min-width:120px;padding:.5rem .75rem;border:1px solid #e2e8f0;
      border-radius:6px;font-size:.88rem;outline:none;transition:border-color .2s;font-family:inherit}}
    input:focus,select:focus{{border-color:#7c3aed}}
    button{{background:#7c3aed;color:#fff;border:none;cursor:pointer;padding:.55rem 1.2rem;
            border-radius:6px;font-weight:700;font-size:.88rem;transition:background .2s;white-space:nowrap}}
    button:hover{{background:#6d28d9}}
    footer{{text-align:center;color:#94a3b8;font-size:.78rem;padding:2rem}}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>&#128722; Cellenza — Catalogue Demo</h1>
      <p>Preview environment · PostgreSQL · OpenTelemetry · AI Enrichment</p>
    </div>
  </header>

  <div class="container">

    <div class="card">
      <h2>Statut PostgreSQL</h2>
      <div class="db-info">
        <span class="badge">{status_label}</span>
        <span class="version">{pg_version}</span>
      </div>
      {f'<p class="error">{error}</p>' if error else ''}
      <div class="env-grid">{env_items}</div>
    </div>

    {ai_card}

    <div class="card">
      <h2>Catalogue produits</h2>
      <div class="prod-grid">{prod_cards}</div>
    </div>

    <div class="card">
      <h2>Ajouter un produit</h2>
      <form method="POST" action="/add-product">
        <input  type="text"   name="name"         placeholder="Nom du produit *" required>
        <select name="category_id">{cat_opts}</select>
        <input  type="number" name="price"         placeholder="Prix € *" step="0.01" min="0" required>
        <input  type="number" name="stock"         placeholder="Stock"    min="0"  value="10">
        <input  type="number" name="discount_pct"  placeholder="Remise %" min="0"  max="100">
        <input  type="text"   name="description"   placeholder="Description">
        <button type="submit">Ajouter</button>
      </form>
    </div>

  </div>
  <footer>Cellenza Operator · catalogue-demo v2.0.0</footer>
</body>
</html>"""


# ── UI routes ─────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    try:
        conn = get_conn()
        cur  = conn.cursor()

        cur.execute("SELECT version()")
        pg_version = cur.fetchone()[0].split(",")[0]

        cur.execute("""
            SELECT p.id, p.name, p.description, p.price, p.stock, p.discount_pct,
                   c.name AS category_name,
                   ROUND(AVG(r.rating)::numeric, 1) AS avg_rating,
                   COUNT(r.id) AS review_count
            FROM products p
            LEFT JOIN categories c ON c.id = p.category_id
            LEFT JOIN reviews r    ON r.product_id = p.id
            GROUP BY p.id, p.name, p.description, p.price, p.stock, p.discount_pct, c.name
            ORDER BY p.created_at DESC LIMIT 24
        """)
        products = fetch_all_dicts(cur)

        cur.execute("SELECT id, name, slug FROM categories ORDER BY name")
        categories = [{"id": r[0], "name": r[1], "slug": r[2]} for r in cur.fetchall()]

        # data for AI enrichment card
        cur.execute("SELECT COUNT(*) FROM products");  total_p = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM reviews");   total_r = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM orders");    total_o = cur.fetchone()[0]

        cur.execute("""
            SELECT p.id, p.name, p.price, p.stock, p.discount_pct,
                   c.name AS category_name,
                   ROUND(AVG(r.rating)::numeric,1) AS avg_rating,
                   COUNT(r.id) AS review_count
            FROM products p
            LEFT JOIN categories c ON c.id = p.category_id
            LEFT JOIN reviews r    ON r.product_id = p.id
            GROUP BY p.id, p.name, p.price, p.stock, p.discount_pct, c.name
            ORDER BY p.created_at ASC
        """)
        all_products = fetch_all_dicts(cur)

        cur.execute("SELECT DISTINCT name FROM categories ORDER BY name")
        cat_names = [r[0] for r in cur.fetchall()]

        cur.close(); conn.close()

        ai_data = {
            "total_products": total_p, "total_reviews": total_r, "total_orders": total_o,
            "products": all_products,  "categories": cat_names,
        }
        env = {k: os.environ.get(k, "—") for k in
               ("POSTGRES_USER", "POSTGRES_DB", "PREVIEW_BRANCH", "PREVIEW_PR", "ENVIRONMENT")}
        return render_template(
            "catalog.html",
            db_ok=True,
            pg_version=pg_version,
            products=products,
            categories=categories,
            ai_data=ai_data,
            ai_model=os.environ.get("AI_MODEL", "gpt-4o"),
            env=env,
            pr_number=os.environ.get("PREVIEW_PR", ""),
            branch=os.environ.get("PREVIEW_BRANCH", "main"),
            error="",
        )
    except Exception as e:
        log("Query failed", error=str(e))
        env = {k: os.environ.get(k, "—") for k in
               ("POSTGRES_USER", "POSTGRES_DB", "PREVIEW_BRANCH", "PREVIEW_PR", "ENVIRONMENT")}
        return render_template(
            "catalog.html",
            db_ok=False,
            pg_version="n/a",
            products=[],
            categories=[],
            ai_data=None,
            ai_model="",
            env=env,
            pr_number=os.environ.get("PREVIEW_PR", ""),
            branch=os.environ.get("PREVIEW_BRANCH", "main"),
            error=str(e),
        ), 500


@app.route("/add-product", methods=["POST"])
def add_product():
    name        = request.form.get("name", "").strip()[:100]
    description = request.form.get("description", "").strip()[:500] or None
    category_id = request.form.get("category_id") or None
    price       = request.form.get("price", "0")
    stock       = request.form.get("stock", "0")
    discount    = request.form.get("discount_pct", "0") or "0"
    if name:
        conn = get_conn(); cur = conn.cursor()
        cur.execute(
            "INSERT INTO products (name,description,category_id,price,stock,discount_pct) VALUES (%s,%s,%s,%s,%s,%s)",
            (name, description, category_id, price, stock, discount)
        )
        conn.commit(); cur.close(); conn.close()
        log("Product added", name=name)
    return redirect("/")


@app.route("/healthz")
def healthz():
    return "ok", 200


@app.route("/ping")
def ping():
    return "pong", 200


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
    return jsonify({"version": "3.0.0", "feature": "frontend-with-e2e"})


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=80)
