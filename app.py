import os
from flask import Flask

app = Flask(__name__)

BRANCH = os.environ.get("PREVIEW_BRANCH", "unknown")
PR = os.environ.get("PREVIEW_PR", "?")


@app.route("/")
def index():
    return f"""<!DOCTYPE html>
<html>
<head><title>IDP Testing — PR #{PR}</title>
<style>
  body {{ font-family: system-ui; background: #0f172a; color: #f1f5f9;
          display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }}
  .card {{ background: #1e293b; padding: 2rem 3rem; border-radius: 12px; text-align: center; }}
  h1 {{ font-size: 2rem; margin: 0 0 .5rem; }}
  p  {{ color: #94a3b8; margin: .25rem 0; }}
  .badge {{ display: inline-block; background: #7c3aed; padding: .25rem .75rem;
             border-radius: 999px; font-size: .85rem; margin-top: 1rem; }}
</style>
</head>
<body>
  <div class="card">
    <h1>&#128640; Preview Ready</h1>
    <p>Branch : <strong>{BRANCH}</strong></p>
    <p>Pull Request : <strong>#{PR}</strong></p>
    <span class="badge">Cellenza Operator</span>
  </div>
</body>
</html>"""


@app.route("/healthz")
def healthz():
    return "ok", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
