import os
import urllib.request
import urllib.error
from flask import Flask, Response, request

app = Flask(__name__)

PR          = os.environ.get("PREVIEW_PR", "")
BRANCH      = os.environ.get("PREVIEW_BRANCH", "main")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://app:8080")


@app.route("/healthz")
def healthz():
    return "ok", 200


@app.route("/api", defaults={"api_path": ""})
@app.route("/api/<path:api_path>")
def proxy_api(api_path):
    target = f"{BACKEND_URL}/api/{api_path}"
    if request.query_string:
        target += "?" + request.query_string.decode()
    try:
        req = urllib.request.Request(target, method=request.method)
        for key, value in request.headers:
            if key.lower() not in ("host", "content-length"):
                req.add_header(key, value)
        if request.data:
            req.data = request.data
        with urllib.request.urlopen(req, timeout=10) as resp:
            return Response(resp.read(), status=resp.status,
                            content_type=resp.headers.get("Content-Type", "application/json"))
    except urllib.error.HTTPError as e:
        return Response(e.read(), status=e.code, content_type="application/json")
    except Exception as e:
        return Response(str(e), status=502)


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def index(path):
    pr_label = f"PR #{PR}" if PR else ""
    branch_label = BRANCH

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Preview Environment{f" — PR #{PR}" if PR else ""}</title>
  <style>
    *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
    :root{{
      --bg:#f1f5f9;--surface:#fff;--border:#e2e8f0;
      --text:#1e293b;--muted:#64748b;--muted2:#94a3b8;
      --purple:#7c3aed;--purple-light:#ede9fe;
      --green:#16a34a;--green-light:#dcfce7;
      --orange:#ea580c;--orange-light:#ffedd5;
      --red:#dc2626;--red-light:#fee2e2;
      --blue:#2563eb;--blue-light:#dbeafe;
      --yellow:#d97706;--yellow-light:#fef9c3;
    }}
    body{{font-family:system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--text);min-height:100vh}}

    /* ── Header ── */
    header{{
      background:linear-gradient(135deg,#0f172a,#1e293b);
      color:#fff;padding:1rem 2rem;
      display:flex;align-items:center;gap:1rem;flex-wrap:wrap;
      box-shadow:0 2px 8px rgba(0,0,0,.3)
    }}
    .logo{{font-size:1.15rem;font-weight:800;letter-spacing:-.3px;flex:1}}
    .logo span{{color:#a78bfa}}
    .badge{{
      background:#7c3aed;color:#fff;padding:.3rem .8rem;
      border-radius:999px;font-size:.75rem;font-weight:700;white-space:nowrap
    }}
    .badge.branch{{background:#334155;border:1px solid #475569}}

    /* ── Layout ── */
    .container{{max-width:1200px;margin:1.5rem auto;padding:0 1rem;display:grid;gap:1.25rem}}

    /* ── Card ── */
    .card{{background:var(--surface);border-radius:12px;padding:1.5rem;box-shadow:0 1px 4px rgba(0,0,0,.07);border:1px solid var(--border)}}
    .card-title{{font-size:.75rem;text-transform:uppercase;letter-spacing:.9px;color:var(--muted2);margin-bottom:1rem;font-weight:700;display:flex;align-items:center;gap:.5rem}}
    .card-title .icon{{font-size:1rem}}

    /* ── Pipeline ── */
    .pipeline{{display:flex;align-items:stretch;gap:0;overflow-x:auto;padding-bottom:.25rem}}
    .stage{{
      flex:1;min-width:140px;display:flex;flex-direction:column;align-items:center;
      gap:.5rem;padding:.85rem .5rem;border-right:1px solid var(--border);position:relative
    }}
    .stage:last-child{{border-right:none}}
    .stage-icon{{font-size:1.5rem}}
    .stage-name{{font-size:.78rem;font-weight:700;text-align:center;color:var(--text)}}
    .stage-desc{{font-size:.68rem;color:var(--muted);text-align:center;line-height:1.4}}
    .stage-status{{
      font-size:.68rem;font-weight:700;padding:.2rem .55rem;
      border-radius:999px;margin-top:.25rem;white-space:nowrap
    }}
    .status-pending{{background:#f1f5f9;color:var(--muted)}}
    .status-running{{background:var(--blue-light);color:var(--blue);animation:pulse 1.5s infinite}}
    .status-passed{{background:var(--green-light);color:var(--green)}}
    .status-failed{{background:var(--red-light);color:var(--red)}}
    .status-skipped{{background:#f8fafc;color:var(--muted2)}}
    @keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.6}}}}

    .arrow{{
      position:absolute;right:-10px;top:50%;transform:translateY(-50%);
      width:20px;height:20px;z-index:1;color:var(--muted2);font-size:.9rem;
      display:flex;align-items:center;justify-content:center
    }}

    /* ── kagent ── */
    .kagent-row{{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:1rem}}
    .kagent-icon{{width:48px;height:48px;background:linear-gradient(135deg,#7c3aed,#2563eb);border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:1.4rem;flex-shrink:0}}
    .kagent-info h3{{font-size:.95rem;font-weight:700;margin-bottom:.2rem}}
    .kagent-info p{{font-size:.8rem;color:var(--muted);line-height:1.5}}
    .kagent-trigger{{
      background:var(--purple-light);color:var(--purple);
      border:1px solid #c4b5fd;border-radius:8px;padding:.5rem .85rem;
      font-size:.75rem;font-weight:700;text-align:center;min-width:110px
    }}

    /* ── Microcks ── */
    .microcks-row{{display:flex;align-items:center;gap:.75rem;flex-wrap:wrap}}
    .microcks-badge{{
      background:var(--blue-light);color:var(--blue);border:1px solid #93c5fd;
      border-radius:6px;padding:.3rem .7rem;font-size:.75rem;font-weight:700
    }}
    .endpoint-table{{width:100%;border-collapse:collapse;margin-top:.75rem;font-size:.78rem}}
    .endpoint-table th{{background:#f8fafc;padding:.5rem .75rem;text-align:left;color:var(--muted);font-weight:600;border-bottom:2px solid var(--border)}}
    .endpoint-table td{{padding:.45rem .75rem;border-bottom:1px solid var(--border)}}
    .method{{font-weight:700;font-size:.7rem;padding:.15rem .4rem;border-radius:4px;white-space:nowrap}}
    .method.GET{{background:#dcfce7;color:#15803d}}
    .method.POST{{background:#dbeafe;color:#1d4ed8}}
    .method.DELETE{{background:#fee2e2;color:#b91c1c}}

    /* ── Stats ── */
    .stat-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:.75rem}}
    .stat-box{{background:#f8fafc;border:1px solid var(--border);border-radius:10px;padding:.85rem 1rem;text-align:center}}
    .stat-val{{font-size:1.6rem;font-weight:800;color:var(--purple)}}
    .stat-lbl{{font-size:.68rem;color:var(--muted2);text-transform:uppercase;letter-spacing:.5px;margin-top:.15rem}}

    /* ── Catalog ── */
    .toolbar{{display:flex;gap:.5rem;flex-wrap:wrap;margin-bottom:.85rem}}
    input,select{{flex:1;min-width:120px;padding:.5rem .75rem;border:1px solid var(--border);border-radius:7px;font-size:.85rem;outline:none;font-family:inherit;background:#fff}}
    input:focus,select:focus{{border-color:var(--purple);box-shadow:0 0 0 3px rgba(124,58,237,.12)}}
    button{{background:var(--purple);color:#fff;border:none;cursor:pointer;padding:.5rem 1.1rem;border-radius:7px;font-weight:700;font-size:.85rem;white-space:nowrap;transition:background .15s}}
    button:hover{{background:#6d28d9}}
    button.secondary{{background:#64748b}}
    button.secondary:hover{{background:#475569}}
    button.danger{{background:var(--red)}}
    button.danger:hover{{background:#b91c1c}}
    .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:1rem;margin-top:.85rem}}
    .prod-card{{border:1px solid var(--border);border-radius:10px;padding:1rem;background:#fafafa;display:flex;flex-direction:column;gap:.3rem;cursor:pointer;transition:box-shadow .15s,border-color .15s}}
    .prod-card:hover{{box-shadow:0 4px 14px rgba(0,0,0,.1);border-color:#c4b5fd}}
    .prod-cat{{font-size:.65rem;text-transform:uppercase;color:var(--purple);font-weight:700}}
    .prod-name{{font-weight:700;font-size:.92rem}}
    .prod-desc{{font-size:.76rem;color:var(--muted);flex:1;line-height:1.4}}
    .prod-foot{{display:flex;justify-content:space-between;align-items:center;margin-top:.35rem;flex-wrap:wrap;gap:.25rem}}
    .prod-price{{font-weight:700}}
    .disc{{background:var(--yellow-light);color:var(--yellow);border-radius:4px;padding:.1rem .35rem;font-size:.68rem;margin-left:.25rem}}
    .stock-badge{{color:#fff;font-size:.67rem;font-weight:700;padding:.12rem .45rem;border-radius:999px}}
    .stars{{color:#f59e0b;font-size:.82rem}}
    .cat-title{{font-size:.92rem;font-weight:700;color:#334155;padding:.6rem 0 .3rem;border-bottom:2px solid var(--border);display:flex;align-items:center;gap:.5rem;margin-bottom:.5rem}}
    .cat-count{{font-size:.7rem;font-weight:400;color:var(--muted2)}}
    .cat-section{{margin-bottom:.75rem}}
    .empty{{color:var(--muted2);font-style:italic;font-size:.85rem;padding:1.5rem 0;text-align:center}}
    .error-msg{{color:var(--red);font-size:.8rem;padding:.4rem 0}}

    /* ── Detail panel ── */
    .panel-overlay{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:100;justify-content:flex-end}}
    .panel-overlay.open{{display:flex}}
    .panel{{background:#fff;width:min(460px,100%);height:100%;overflow-y:auto;padding:1.5rem;display:flex;flex-direction:column;gap:1rem;box-shadow:-4px 0 20px rgba(0,0,0,.15)}}
    .panel h3{{font-size:1.05rem;font-weight:700}}
    .panel .price{{font-size:1.2rem;font-weight:700;color:var(--purple)}}
    .close-btn{{align-self:flex-end;background:none;border:1px solid var(--border);color:var(--muted);padding:.3rem .7rem;border-radius:6px;cursor:pointer;font-size:.82rem}}
    .section-title{{font-size:.72rem;text-transform:uppercase;letter-spacing:.7px;color:var(--muted2);margin-bottom:.5rem;font-weight:700}}
    .related-list{{display:flex;flex-direction:column;gap:.35rem}}
    .related-item{{padding:.5rem;border:1px solid #f1f5f9;border-radius:7px;font-size:.82rem;cursor:pointer}}
    .related-item:hover{{background:#f8f0ff;border-color:#c4b5fd}}
    .review-item{{background:#f8fafc;border:1px solid var(--border);border-radius:8px;padding:.75rem;display:flex;flex-direction:column;gap:.25rem}}
    .review-header{{display:flex;align-items:center;justify-content:space-between;gap:.5rem}}
    .review-author{{font-weight:700;font-size:.8rem}}
    .review-comment{{font-size:.82rem;color:#475569;line-height:1.45}}
    .ai-badge{{background:linear-gradient(135deg,#7c3aed,#2563eb);color:#fff;font-size:.62rem;font-weight:700;padding:.15rem .5rem;border-radius:999px;letter-spacing:.5px}}
  </style>
</head>
<body>

<header>
  <div class="logo">&#128683; Preview<span>Platform</span></div>
  {"" if not PR else f'<span class="badge">{pr_label}</span>'}
  <span class="badge branch">&#127944; {branch_label}</span>
</header>

<div class="container">

  <!-- ── Pipeline Status ── -->
  <div class="card">
    <div class="card-title"><span class="icon">&#9654;</span> CI/CD Pipeline</div>
    <div class="pipeline" id="pipeline">
      <div class="stage">
        <div class="stage-icon">&#128195;</div>
        <div class="stage-name">Provisioning</div>
        <div class="stage-desc">Namespace, quota, PostgreSQL, migration</div>
        <span class="stage-status status-passed" id="stage-provision">Completed</span>
      </div>
      <div class="stage">
        <div class="stage-icon">&#128168;</div>
        <div class="stage-name">Smoke</div>
        <div class="stage-desc">/healthz, /ping, /api/stats</div>
        <span class="stage-status status-pending" id="stage-smoke">Pending</span>
      </div>
      <div class="stage">
        <div class="stage-icon">&#128196;</div>
        <div class="stage-name">Contract</div>
        <div class="stage-desc">Microcks — OpenAPI 3.0.3 validation</div>
        <span class="stage-status status-pending" id="stage-contract">Pending</span>
      </div>
      <div class="stage">
        <div class="stage-icon">&#128260;</div>
        <div class="stage-name">Regression</div>
        <div class="stage-desc">All 13 API endpoints</div>
        <span class="stage-status status-pending" id="stage-regression">Pending</span>
      </div>
      <div class="stage">
        <div class="stage-icon">&#128064;</div>
        <div class="stage-name">E2E</div>
        <div class="stage-desc">Full user flows</div>
        <span class="stage-status status-skipped" id="stage-e2e">Skipped</span>
      </div>
    </div>
  </div>

  <!-- ── kagent AI Analysis ── -->
  <div class="card">
    <div class="card-title"><span class="icon">&#129302;</span> kagent — AI Failure Analysis</div>
    <div class="kagent-row">
      <div class="kagent-icon">&#129302;</div>
      <div class="kagent-info">
        <h3>preview-troubleshooter-agent</h3>
        <p>
          Powered by <strong>Azure OpenAI gpt-4o-mini</strong> via kagent 0.9.2.<br>
          Automatically triggered when a test suite fails — inspects pods, job logs,
          and events in the preview namespace, then posts a structured diagnosis
          directly as a <strong>GitHub PR comment</strong>.
        </p>
        <p style="margin-top:.5rem;font-size:.75rem;color:#7c3aed;font-weight:600">
          Analysis format: Risk level · Failed suite · Evidence · Likely cause · Suggested fix · Confidence
        </p>
      </div>
      <div class="kagent-trigger" id="kagent-status">
        <div style="font-size:1.2rem;margin-bottom:.25rem">&#128274;</div>
        Standby<br>
        <span style="font-size:.65rem;font-weight:400;color:var(--muted)">triggers on failure</span>
      </div>
    </div>
  </div>

  <!-- ── Contract Testing — Microcks ── -->
  <div class="card">
    <div class="card-title"><span class="icon">&#128196;</span> Contract Testing — Microcks</div>
    <div class="microcks-row">
      <span class="microcks-badge">Microcks 1.14.0</span>
      <span class="microcks-badge" style="background:var(--green-light);color:var(--green);border-color:#86efac">OPEN_API_SCHEMA</span>
      <span style="font-size:.78rem;color:var(--muted)">Validates every response against the OpenAPI 3.0.3 spec</span>
    </div>
    <table class="endpoint-table">
      <thead>
        <tr><th>Method</th><th>Path</th><th>Description</th></tr>
      </thead>
      <tbody>
        <tr><td><span class="method GET">GET</span></td><td>/healthz</td><td>Health check</td></tr>
        <tr><td><span class="method GET">GET</span></td><td>/api/stats</td><td>Catalogue statistics</td></tr>
        <tr><td><span class="method GET">GET</span></td><td>/api/categories</td><td>List categories</td></tr>
        <tr><td><span class="method POST">POST</span></td><td>/api/categories</td><td>Create category</td></tr>
        <tr><td><span class="method GET">GET</span></td><td>/api/products</td><td>List products</td></tr>
        <tr><td><span class="method POST">POST</span></td><td>/api/products</td><td>Create product</td></tr>
        <tr><td><span class="method GET">GET</span></td><td>/api/products/&#123;id&#125;</td><td>Get product</td></tr>
        <tr><td><span class="method DELETE">DELETE</span></td><td>/api/products/&#123;id&#125;</td><td>Delete product</td></tr>
        <tr><td><span class="method GET">GET</span></td><td>/api/products/&#123;id&#125;/reviews</td><td>List reviews</td></tr>
        <tr><td><span class="method POST">POST</span></td><td>/api/products/&#123;id&#125;/reviews</td><td>Create review</td></tr>
        <tr><td><span class="method POST">POST</span></td><td>/api/orders</td><td>Create order</td></tr>
        <tr><td><span class="method GET">GET</span></td><td>/api/orders</td><td>List orders</td></tr>
        <tr><td><span class="method GET">GET</span></td><td>/api/products/discounted</td><td>Discounted products</td></tr>
      </tbody>
    </table>
  </div>

  <!-- ── Stats ── -->
  <div class="card" id="stats-card">
    <div class="card-title"><span class="icon">&#128200;</span> Live Data</div>
    <div class="stat-grid" id="stats-grid"><p class="empty">Loading…</p></div>
  </div>

  <!-- ── Catalog ── -->
  <div class="card">
    <div class="card-title"><span class="icon">&#128722;</span> Product Catalogue <span id="ai-indicator"></span></div>
    <div class="toolbar">
      <input id="f-name"  type="text"   placeholder="Name *" required>
      <select id="f-cat"><option value="">— Category —</option></select>
      <input id="f-price" type="number" placeholder="Price € *" step="0.01" min="0">
      <input id="f-stock" type="number" placeholder="Stock" min="0" value="10">
      <input id="f-disc"  type="number" placeholder="Discount %" min="0" max="100">
      <button onclick="addProduct()">Add product</button>
    </div>
    <p class="error-msg" id="form-error"></p>
    <div style="display:flex;gap:.5rem;flex-wrap:wrap;margin-bottom:.5rem">
      <input id="discount-filter" type="number" placeholder="Min discount %" min="0" max="100" style="max-width:160px">
      <button onclick="applyDiscount()">Filter discounts</button>
      <button class="secondary" onclick="loadProducts()">Show all</button>
    </div>
    <div id="catalog-sections"><p class="empty">Loading…</p></div>
  </div>

</div>

<!-- ── Detail panel ── -->
<div class="panel-overlay" id="panel-overlay" onclick="closePanel(event)">
  <div class="panel" id="detail-panel">
    <button class="close-btn" onclick="closePanel()">✕ Close</button>
    <h3 id="detail-name"></h3>
    <div class="price" id="detail-price"></div>
    <p id="detail-desc" style="font-size:.84rem;color:var(--muted)"></p>
    <div id="detail-stock" style="font-size:.8rem;color:var(--muted)"></div>
    <div>
      <div class="section-title">Customer reviews</div>
      <div id="reviews-list"></div>
    </div>
    <div>
      <div class="section-title">Related products</div>
      <div class="related-list" id="related-list"></div>
    </div>
  </div>
</div>

<script>
  const API = '/api';

  async function fetchJSON(path, opts) {{
    const r = await fetch(API + path, opts);
    if (!r.ok) throw new Error(r.status);
    return r.json();
  }}

  function stars(n) {{
    n = Math.round(n || 0);
    return '★'.repeat(n) + '☆'.repeat(5 - n);
  }}

  function stockColor(n) {{
    if (n === 0) return '#ef4444';
    if (n < 5)  return '#f97316';
    return '#22c55e';
  }}

  // ── Pipeline status from /api/pipeline-info ──
  async function loadPipelineInfo() {{
    try {{
      const info = await fetchJSON('/pipeline-info');
      // Once app is up, provisioning is done
      setStage('stage-provision', 'passed', 'Completed');
    }} catch(e) {{}}
  }}

  function setStage(id, status, label) {{
    const el = document.getElementById(id);
    if (!el) return;
    el.className = 'stage-status status-' + status;
    el.textContent = label;
  }}

  // ── Stats ──
  async function loadStats() {{
    try {{
      const s = await fetchJSON('/stats');
      const hasAI = s.total_reviews > 0;
      if (hasAI) {{
        document.getElementById('ai-indicator').innerHTML = '<span class="ai-badge">✦ AI-enriched</span>';
      }}
      document.getElementById('stats-grid').innerHTML = `
        <div class="stat-box"><div class="stat-val">${{s.total_products}}</div><div class="stat-lbl">Products</div></div>
        <div class="stat-box"><div class="stat-val">${{s.total_categories}}</div><div class="stat-lbl">Categories</div></div>
        <div class="stat-box"><div class="stat-val">${{s.total_reviews}}</div><div class="stat-lbl">Reviews</div></div>
        <div class="stat-box"><div class="stat-val">${{s.total_orders}}</div><div class="stat-lbl">Orders</div></div>
        <div class="stat-box"><div class="stat-val">${{s.out_of_stock}}</div><div class="stat-lbl">Out of stock</div></div>
        ${{s.avg_rating ? `<div class="stat-box"><div class="stat-val stars">${{s.avg_rating.toFixed(1)}}★</div><div class="stat-lbl">Avg rating</div></div>` : ''}}
      `;
    }} catch(e) {{
      document.getElementById('stats-grid').innerHTML = '<p class="error-msg">Stats unavailable</p>';
    }}
  }}

  async function loadCategories() {{
    try {{
      const cats = await fetchJSON('/categories');
      const sel = document.getElementById('f-cat');
      cats.forEach(c => {{
        const o = document.createElement('option');
        o.value = c.id; o.textContent = c.name;
        sel.appendChild(o);
      }});
    }} catch(e) {{}}
  }}

  function productCardHTML(p) {{
    const disc  = parseFloat(p.discount_pct || 0);
    const final = (parseFloat(p.price) * (1 - disc / 100)).toFixed(2);
    const discBadge = disc ? `<span class="disc">-${{Math.round(disc)}}%</span>` : '';
    const avg = p.avg_rating
      ? `<div style="margin-top:.25rem"><span class="stars">${{stars(p.avg_rating)}}</span> <small style="color:var(--muted2)">${{p.review_count}}</small></div>`
      : '';
    return `<div class="prod-card" data-id="${{p.id}}" onclick="openPanel(${{p.id}})">
      <div class="prod-cat">${{p.category_name || 'Uncategorised'}}</div>
      <div class="prod-name">${{p.name}}</div>
      <div class="prod-desc">${{p.description || ''}}</div>
      <div class="prod-foot">
        <span class="prod-price">${{final}} € ${{discBadge}}</span>
        <span class="stock-badge" style="background:${{stockColor(p.stock)}}">Stock ${{p.stock}}</span>
      </div>
      ${{avg}}
    </div>`;
  }}

  async function loadProducts() {{
    try {{
      const products = await fetchJSON('/products');
      const container = document.getElementById('catalog-sections');
      if (!products.length) {{
        container.innerHTML = '<p class="empty">No products yet — add one above.</p>';
        return;
      }}
      const byCategory = {{}};
      products.forEach(p => {{
        const cat = p.category_name || 'Uncategorised';
        if (!byCategory[cat]) byCategory[cat] = [];
        byCategory[cat].push(p);
      }});
      container.innerHTML = Object.keys(byCategory).sort().map(cat => `
        <div class="cat-section">
          <div class="cat-title">
            ${{cat}}
            <span class="cat-count">${{byCategory[cat].length}} product${{byCategory[cat].length > 1 ? 's' : ''}}</span>
          </div>
          <div class="grid">${{byCategory[cat].map(productCardHTML).join('')}}</div>
        </div>
      `).join('');
    }} catch(e) {{
      document.getElementById('catalog-sections').innerHTML = '<p class="error-msg">Failed to load products</p>';
    }}
  }}

  async function openPanel(id) {{
    try {{
      const [p, relData] = await Promise.all([
        fetchJSON(`/products/${{id}}`),
        fetchJSON(`/products/${{id}}/related`).catch(() => ({{products:[]}}))
      ]);
      const disc  = parseFloat(p.discount_pct || 0);
      const final = (parseFloat(p.price) * (1 - disc / 100)).toFixed(2);
      document.getElementById('detail-name').textContent  = p.name;
      document.getElementById('detail-price').textContent =
        final + ' €' + (disc ? ` (-${{Math.round(disc)}}%)` : '');
      document.getElementById('detail-desc').textContent  = p.description || '';
      document.getElementById('detail-stock').textContent =
        `Category: ${{p.category_name || '—'}}  ·  Stock: ${{p.stock}}`;
      const reviews = p.reviews || [];
      document.getElementById('reviews-list').innerHTML = reviews.length
        ? reviews.map(r => `
            <div class="review-item">
              <div class="review-header">
                <span class="review-author">${{r.author}}</span>
                <span class="stars">${{stars(r.rating)}}</span>
              </div>
              ${{r.comment ? `<div class="review-comment">"${{r.comment}}"</div>` : ''}}
            </div>`).join('')
        : '<p style="font-size:.8rem;color:var(--muted2)">No reviews yet</p>';
      const related = relData.products || relData || [];
      document.getElementById('related-list').innerHTML = related.length
        ? related.map(r => `<div class="related-item" onclick="openPanel(${{r.id}})">${{r.name}} — ${{parseFloat(r.price).toFixed(2)}} €</div>`).join('')
        : '<p style="font-size:.8rem;color:var(--muted2)">No related products</p>';
      document.getElementById('panel-overlay').classList.add('open');
    }} catch(e) {{}}
  }}

  function closePanel(e) {{
    if (!e || e.target === document.getElementById('panel-overlay')) {{
      document.getElementById('panel-overlay').classList.remove('open');
    }}
  }}

  async function addProduct() {{
    const name  = document.getElementById('f-name').value.trim();
    const price = document.getElementById('f-price').value;
    const err   = document.getElementById('form-error');
    if (!name || !price) {{ err.textContent = 'Name and price are required.'; return; }}
    err.textContent = '';
    try {{
      await fetchJSON('/products', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{
          name,
          price:        parseFloat(price),
          stock:        parseInt(document.getElementById('f-stock').value || 10),
          discount_pct: parseFloat(document.getElementById('f-disc').value || 0),
          category_id:  document.getElementById('f-cat').value || null,
        }})
      }});
      document.getElementById('f-name').value  = '';
      document.getElementById('f-price').value = '';
      loadProducts(); loadStats();
    }} catch(e) {{ err.textContent = 'Error adding product.'; }}
  }}

  async function applyDiscount() {{
    const min = document.getElementById('discount-filter').value || 0;
    try {{
      const data     = await fetchJSON(`/products/discounted?min_discount=${{min}}`);
      const products = data.products || data;
      const container = document.getElementById('catalog-sections');
      container.innerHTML = products.length
        ? products.map(productCardHTML).join('')
        : '<p class="empty">No products with that discount.</p>';
    }} catch(e) {{
      document.getElementById('catalog-sections').innerHTML = '<p class="error-msg">Filter error</p>';
    }}
  }}

  loadPipelineInfo();
  loadStats();
  loadCategories();
  loadProducts();
</script>

</body>
</html>"""
    return Response(html, mimetype="text/html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000)
