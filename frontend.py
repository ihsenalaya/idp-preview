import os
from flask import Flask, Response

app = Flask(__name__)

PR      = os.environ.get("PREVIEW_PR", "")
BRANCH  = os.environ.get("PREVIEW_BRANCH", "main")


@app.route("/healthz")
def healthz():
    return "ok", 200


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def index(path):
    pr_badge = f'<span data-testid="preview-badge" class="preview-badge">PR #{PR} &nbsp;·&nbsp; {BRANCH}</span>' if PR else ""
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Cellenza — Catalogue</title>
  <style>
    *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:system-ui,-apple-system,sans-serif;background:#f1f5f9;color:#1e293b}}
    header{{background:linear-gradient(135deg,#1e293b,#334155);color:#fff;padding:1.25rem 2rem;display:flex;align-items:center;gap:1rem;flex-wrap:wrap}}
    header h1{{font-size:1.3rem;flex:1}}
    .preview-badge{{background:#7c3aed;color:#fff;padding:.25rem .75rem;border-radius:999px;font-size:.78rem;font-weight:700;white-space:nowrap}}
    .container{{max-width:1100px;margin:2rem auto;padding:0 1rem;display:grid;gap:1.25rem}}
    .card{{background:#fff;border-radius:10px;padding:1.5rem;box-shadow:0 1px 4px rgba(0,0,0,.08)}}
    .card h2{{font-size:.82rem;text-transform:uppercase;letter-spacing:.8px;color:#94a3b8;margin-bottom:1rem;display:flex;align-items:center;gap:.5rem}}
    .form-row{{display:flex;gap:.5rem;flex-wrap:wrap}}
    input,select{{flex:1;min-width:120px;padding:.5rem .75rem;border:1px solid #e2e8f0;border-radius:6px;font-size:.88rem;outline:none;font-family:inherit}}
    input:focus,select:focus{{border-color:#7c3aed;box-shadow:0 0 0 3px rgba(124,58,237,.1)}}
    button{{background:#7c3aed;color:#fff;border:none;cursor:pointer;padding:.55rem 1.2rem;border-radius:6px;font-weight:700;font-size:.88rem;white-space:nowrap}}
    button:hover{{background:#6d28d9}}
    button.danger{{background:#ef4444}}
    button.danger:hover{{background:#dc2626}}
    .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:1rem;margin-top:1rem}}
    .prod-card{{border:1px solid #e2e8f0;border-radius:8px;padding:1rem;background:#fafafa;display:flex;flex-direction:column;gap:.35rem;cursor:pointer;transition:box-shadow .15s}}
    .prod-card:hover{{box-shadow:0 4px 12px rgba(0,0,0,.1);border-color:#c4b5fd}}
    .prod-cat{{font-size:.68rem;text-transform:uppercase;color:#7c3aed;font-weight:700}}
    .prod-name{{font-weight:700;font-size:.95rem}}
    .prod-desc{{font-size:.78rem;color:#64748b;flex:1}}
    .prod-foot{{display:flex;justify-content:space-between;align-items:center;margin-top:.4rem;flex-wrap:wrap;gap:.3rem}}
    .prod-price{{font-weight:700}}
    .disc{{background:#fef9c3;color:#854d0e;border-radius:4px;padding:.1rem .35rem;font-size:.7rem;margin-left:.3rem}}
    .stock{{color:#fff;font-size:.7rem;font-weight:700;padding:.15rem .5rem;border-radius:999px}}
    .stars{{color:#f59e0b;font-size:.85rem}}
    .empty{{color:#cbd5e1;font-style:italic;font-size:.88rem;padding:1.5rem 0;text-align:center}}
    .cat-section{{margin-bottom:.25rem}}
    .cat-title{{font-size:.95rem;font-weight:700;color:#334155;padding:.6rem 0 .2rem;border-bottom:2px solid #e2e8f0;display:flex;align-items:center;gap:.5rem}}
    .cat-count{{font-size:.72rem;font-weight:400;color:#94a3b8}}
    .ai-badge{{background:linear-gradient(135deg,#7c3aed,#2563eb);color:#fff;font-size:.65rem;font-weight:700;padding:.15rem .5rem;border-radius:999px;letter-spacing:.5px}}
    .panel-overlay{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:100;justify-content:flex-end}}
    .panel-overlay.open{{display:flex}}
    .panel{{background:#fff;width:min(460px,100%);height:100%;overflow-y:auto;padding:1.5rem;display:flex;flex-direction:column;gap:1rem}}
    .panel h3[data-testid="detail-name"]{{font-size:1.1rem;font-weight:700}}
    .panel .price[data-testid="detail-price"]{{font-size:1.2rem;font-weight:700;color:#7c3aed}}
    .panel .close-btn{{align-self:flex-end;background:none;border:1px solid #e2e8f0;color:#64748b;padding:.3rem .7rem;border-radius:6px;cursor:pointer;font-size:.85rem}}
    .section-title{{font-size:.75rem;text-transform:uppercase;letter-spacing:.7px;color:#94a3b8;margin-bottom:.5rem;font-weight:700}}
    .related-list{{display:flex;flex-direction:column;gap:.4rem}}
    .related-item{{padding:.5rem;border:1px solid #f1f5f9;border-radius:6px;font-size:.83rem;cursor:pointer}}
    .related-item:hover{{background:#f8f0ff;border-color:#c4b5fd}}
    .review-item{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:.75rem;display:flex;flex-direction:column;gap:.3rem}}
    .review-header{{display:flex;align-items:center;justify-content:space-between;gap:.5rem}}
    .review-author{{font-weight:700;font-size:.82rem}}
    .review-comment{{font-size:.83rem;color:#475569;line-height:1.45}}
    .stat-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:.75rem}}
    .stat-box{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:.75rem 1rem;text-align:center}}
    .stat-val{{font-size:1.5rem;font-weight:700;color:#7c3aed}}
    .stat-lbl{{font-size:.72rem;color:#94a3b8;text-transform:uppercase;margin-top:.2rem}}
    .error-msg{{color:#ef4444;font-size:.82rem;padding:.5rem 0}}
  </style>
</head>
<body>
  <header>
    <h1>&#128722; Cellenza — Catalogue Demo</h1>
    {pr_badge}
  </header>

  <div class="container">

    <div class="card" id="stats-card">
      <h2>Stats</h2>
      <div class="stat-grid" id="stats-grid"><p class="empty">Chargement…</p></div>
    </div>

    <div class="card">
      <h2>Ajouter un produit</h2>
      <div class="form-row">
        <input id="f-name"  type="text"   placeholder="Nom *" required>
        <select id="f-cat"><option value="">— Catégorie —</option></select>
        <input id="f-price" type="number" placeholder="Prix € *" step="0.01" min="0">
        <input id="f-stock" type="number" placeholder="Stock" min="0" value="10">
        <input id="f-disc"  type="number" placeholder="Remise %" min="0" max="100">
        <button onclick="addProduct()">Ajouter</button>
      </div>
      <p class="error-msg" id="form-error"></p>
    </div>

    <div class="card">
      <h2 id="catalog-title">Catalogue produits</h2>
      <div id="catalog-sections"><p class="empty">Chargement…</p></div>
    </div>

  </div>

  <!-- Detail panel -->
  <div class="panel-overlay" id="panel-overlay" onclick="closePanel(event)">
    <div class="panel" data-testid="product-detail" id="detail-panel">
      <button class="close-btn" onclick="closePanel()">✕ Fermer</button>
      <h3 data-testid="detail-name" id="detail-name"></h3>
      <div class="price" data-testid="detail-price" id="detail-price"></div>
      <p id="detail-desc" style="font-size:.85rem;color:#64748b"></p>
      <div id="detail-stock" style="font-size:.82rem;color:#64748b"></div>

      <div id="reviews-section">
        <div class="section-title">Avis clients</div>
        <div id="reviews-list"></div>
      </div>

      <div data-testid="related-products">
        <div class="section-title">Produits similaires</div>
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

    async function loadStats() {{
      try {{
        const s = await fetchJSON('/stats');
        const aiTag = s.total_reviews > 0 ? '<span class="ai-badge">✦ IA</span>' : '';
        document.getElementById('catalog-title').innerHTML = 'Catalogue produits ' + aiTag;
        document.getElementById('stats-grid').innerHTML = `
          <div class="stat-box"><div class="stat-val">${{s.total_products}}</div><div class="stat-lbl">Produits</div></div>
          <div class="stat-box"><div class="stat-val">${{s.total_categories}}</div><div class="stat-lbl">Catégories</div></div>
          <div class="stat-box"><div class="stat-val">${{s.total_reviews}}</div><div class="stat-lbl">Avis</div></div>
          <div class="stat-box"><div class="stat-val">${{s.total_orders}}</div><div class="stat-lbl">Commandes</div></div>
          <div class="stat-box"><div class="stat-val">${{s.out_of_stock}}</div><div class="stat-lbl">Rupture</div></div>
          ${{s.avg_rating ? `<div class="stat-box"><div class="stat-val stars">${{s.avg_rating.toFixed(1)}}★</div><div class="stat-lbl">Note moy.</div></div>` : ''}}
        `;
      }} catch(e) {{ document.getElementById('stats-grid').innerHTML = '<p class="error-msg">Stats indisponibles</p>'; }}
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
      const disc = parseFloat(p.discount_pct || 0);
      const final = (parseFloat(p.price) * (1 - disc / 100)).toFixed(2);
      const discBadge = disc ? `<span class="disc">-${{Math.round(disc)}}%</span>` : '';
      const avg = p.avg_rating
        ? `<div style="margin-top:.3rem"><span class="stars">${{stars(p.avg_rating)}}</span> <small style="color:#94a3b8">${{p.review_count}} avis</small></div>`
        : '';
      return `<div class="prod-card" data-testid="product-card" data-id="${{p.id}}" onclick="openPanel(${{p.id}})">
        <div class="prod-cat">${{p.category_name || 'Non classé'}}</div>
        <div class="prod-name">${{p.name}}</div>
        <div class="prod-desc">${{p.description || ''}}</div>
        <div class="prod-foot">
          <span class="prod-price">${{final}} € ${{discBadge}}</span>
          <span class="stock" style="background:${{stockColor(p.stock)}}">Stock ${{p.stock}}</span>
        </div>
        ${{avg}}
      </div>`;
    }}

    async function loadProducts() {{
      try {{
        const products = await fetchJSON('/products');
        const container = document.getElementById('catalog-sections');
        if (!products.length) {{
          container.innerHTML = '<p class="empty">Aucun produit — ajoutez-en un.</p>';
          return;
        }}
        const byCategory = {{}};
        products.forEach(p => {{
          const cat = p.category_name || 'Non classé';
          if (!byCategory[cat]) byCategory[cat] = [];
          byCategory[cat].push(p);
        }});
        const sorted = Object.keys(byCategory).sort();
        container.innerHTML = sorted.map(cat => `
          <div class="cat-section">
            <div class="cat-title">
              ${{cat}}
              <span class="cat-count">${{byCategory[cat].length}} produit${{byCategory[cat].length > 1 ? 's' : ''}}</span>
            </div>
            <div class="grid" data-testid="product-grid">
              ${{byCategory[cat].map(productCardHTML).join('')}}
            </div>
          </div>
        `).join('');
      }} catch(e) {{
        document.getElementById('catalog-sections').innerHTML = '<p class="error-msg">Erreur chargement produits</p>';
      }}
    }}

    async function openPanel(id) {{
      try {{
        const [p, relData] = await Promise.all([
          fetchJSON(`/products/${{id}}`),
          fetchJSON(`/products/${{id}}/related`).catch(() => ({{products:[]}}))
        ]);
        const disc = parseFloat(p.discount_pct || 0);
        const final = (parseFloat(p.price) * (1 - disc / 100)).toFixed(2);

        document.getElementById('detail-name').textContent = p.name;
        document.getElementById('detail-price').textContent =
          final + ' €' + (disc ? ` (-${{Math.round(disc)}}%)` : '');
        document.getElementById('detail-desc').textContent = p.description || '';
        document.getElementById('detail-stock').textContent =
          `Catégorie : ${{p.category_name || '—'}}  ·  Stock : ${{p.stock}}`;

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
          : '<p style="font-size:.82rem;color:#cbd5e1">Aucun avis pour ce produit</p>';

        const related = relData.products || relData || [];
        document.getElementById('related-list').innerHTML = related.length
          ? related.map(r => `<div class="related-item" onclick="openPanel(${{r.id}})">${{r.name}} — ${{parseFloat(r.price).toFixed(2)}} €</div>`).join('')
          : '<p style="font-size:.82rem;color:#cbd5e1">Aucun produit similaire</p>';

        document.getElementById('panel-overlay').classList.add('open');
      }} catch(e) {{}}
    }}

    function closePanel(e) {{
      if (!e || e.target === document.getElementById('panel-overlay') || e.currentTarget.classList.contains('close-btn')) {{
        document.getElementById('panel-overlay').classList.remove('open');
      }}
    }}

    async function addProduct() {{
      const name  = document.getElementById('f-name').value.trim();
      const price = document.getElementById('f-price').value;
      const err   = document.getElementById('form-error');
      if (!name || !price) {{ err.textContent = 'Nom et prix sont requis.'; return; }}
      err.textContent = '';
      try {{
        await fetchJSON('/products', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{
            name,
            price: parseFloat(price),
            stock: parseInt(document.getElementById('f-stock').value || 10),
            discount_pct: parseFloat(document.getElementById('f-disc').value || 0),
            category_id: document.getElementById('f-cat').value || null,
          }})
        }});
        document.getElementById('f-name').value = '';
        document.getElementById('f-price').value = '';
        loadProducts(); loadStats();
      }} catch(e) {{ err.textContent = "Erreur lors de l\\'ajout."; }}
    }}

    loadStats(); loadCategories(); loadProducts();
  </script>
</body>
</html>"""
    return Response(html, mimetype="text/html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000)
