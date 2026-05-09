# KubeCon Demo Script

**Title:** AI-assisted Contract-aware Kubernetes Preview Environments

**Tagline:**
> "Every pull request gets an isolated Kubernetes preview environment,
> AI-generated test data, API contract validation with Microcks, automated
> regression/E2E tests, and kagent-powered failure explanation."

**Target audience:** Platform engineers, DevEx advocates, KubeCon attendees

**Estimated duration:** 12–15 minutes

---

## Speaker storyline

You are a platform engineer at a company with 30 developers. Every time
someone opens a pull request, the team used to:
- deploy manually to staging (shared, polluted)
- hope tests pass on the first try
- spend 45 minutes debugging cryptic CI logs when they don't

Today you will show the platform you built. Every PR gets its own isolated
Kubernetes environment, AI-seeded with realistic data, validated against an
API contract with Microcks, and when something breaks, an AI agent reads the
Kubernetes logs so the developer doesn't have to.

---

## Prerequisites

### Cluster

```bash
# Kind cluster is running
kind get clusters
# → testing

# Operator is installed
kubectl -n preview-operator-system get deployment preview-operator
# → Running

# Microcks is installed and API is imported
curl -s http://localhost:8080/api/services | python3 -m json.tool | grep '"name"'
# → "Preview Catalog API"

# kagent is installed
kubectl -n kagent-system get agent preview-troubleshooter-agent
# → SYNCED

# Self-hosted GitHub runner is ready
kubectl -n github-runner logs deploy/github-runner --tail=1
# → "Listening for Jobs"
```

### Secrets

```bash
# GitHub token for the operator
kubectl -n preview-operator-system get secret preview-github-token

# AI API key
kubectl -n preview-operator-system get secret ai-api-key

# Microcks credentials (in preview namespaces — created by operator)
# → applied automatically when contractTesting.secretRef is set
```

---

## Happy path — everything green

### Step 1: Open the PR

```bash
git checkout -b feat/add-featured-products
# (make a visible change, e.g., add a /api/products/featured endpoint stub)
git add app.py api/openapi.yaml
git commit -m "feat: add featured products endpoint"
git push origin feat/add-featured-products
gh pr create --title "Add featured products" --body "Adds /api/products/featured endpoint"
```

**Talk track:**
> "I just pushed a branch and opened a pull request. Watch what happens next —
> I haven't touched a single kubectl command."

### Step 2: Watch the pipeline

Open the GitHub PR tab. Show:

1. GitHub Actions starts — Kaniko builds and pushes the image to GHCR.
2. The Preview CR is applied — the operator creates namespace `preview-pr-<N>`.
3. The PR comment appears: _"Preview provisioning…"_
4. The comment updates: _"Preview Ready — http://pr-N.preview.localtest.me:8080"_

```bash
# In a terminal, watch the full pipeline live
kubectl get preview pr-<N> -w

# Watch jobs being created
kubectl get jobs -n preview-pr-<N> -w
```

**Talk track:**
> "The operator just created a full stack — PostgreSQL, backend, frontend,
> ingress — inside namespace preview-pr-N. Completely isolated from every
> other PR."

### Step 3: AI enrichment

```bash
kubectl logs -n preview-pr-<N> job/ai-generate --tail=20
# Shows: LLM called → seed.sql generated → 10 products, 3 categories

kubectl logs -n preview-pr-<N> job/ai-seed --tail=5
# Shows: INSERT INTO products … (10 rows)
```

Open the preview URL in a browser.

**Talk track:**
> "The AI generated realistic product data based on the PR diff. It read what
> code changed and invented a matching dataset. The catalogue is live."

### Step 4: Microcks contract test

```bash
kubectl logs -n preview-pr-<N> job/microcks-contract-tests -f
```

Expected output:

```
[microcks] Microcks URL  : http://microcks.microcks.svc.cluster.local:8080
[microcks] API           : Preview Catalog API v1.0.0
[microcks] Runner        : OPEN_API_SCHEMA
[microcks] Test submitted — ID: abc123
[microcks] Polling for results…
============================================================
  Microcks Contract Test — PASSED
============================================================
  PASS  GET /api/products
  PASS  POST /api/products
  PASS  GET /api/products/{id}
  PASS  DELETE /api/products/{id}
  PASS  POST /api/orders
  PASS  GET /api/stats
  12/12 request(s) passed
============================================================
```

**Talk track:**
> "Microcks just sent real HTTP requests to the live backend and validated every
> response against the OpenAPI contract I wrote in api/openapi.yaml. 12 requests,
> 12 passed. The API is contract-compliant."

### Step 5: Regression and E2E tests

```bash
kubectl get preview pr-<N> -o jsonpath='{.status.tests}' | jq .
```

Expected:

```json
{
  "phase": "Succeeded",
  "smoke":      { "phase": "Succeeded", "passed": 2, "failed": 0 },
  "regression": { "phase": "Succeeded", "passed": 9, "failed": 0 },
  "e2e":        { "phase": "Succeeded", "passed": 6, "failed": 0 }
}
```

**Talk track:**
> "Smoke tests, regression tests — 9 endpoint assertions — and 6 Playwright
> browser tests. All green. The PR is safe to review."

---

## Broken API contract path — the interesting case

### Setup: introduce a deliberate contract violation

```bash
git checkout -b feat/rename-order-field
```

Edit `app.py` line ~293 — rename `"id"` to `"order_id"` in `api_create_order`:

```python
# Before
return jsonify({"id": r[0], "product_id": r[1], ...}), 201

# After (deliberate contract break)
return jsonify({"order_id": r[0], "product_id": r[1], ...}), 201
```

```bash
git add app.py
git commit -m "refactor: rename order response field to order_id"
git push origin feat/rename-order-field
gh pr create --title "Rename order field" --body "Changes 'id' to 'order_id' in order response"
```

### Step 1: Wait for the contract test to fail

```bash
kubectl logs -n preview-pr-<N> job/microcks-contract-tests -f
```

Expected output:

```
============================================================
  Microcks Contract Test — FAILED
============================================================
  PASS  GET /api/products
  PASS  GET /api/stats
  FAIL  POST /api/orders — Response body field 'id' missing (found 'order_id')
  FAIL  POST /api/orders — Response status 201 expected, got 201 (field validation)
  10/12 request(s) passed
============================================================
```

**Talk track:**
> "The contract test caught it immediately. The backend returned `order_id`
> instead of `id` — which is what the OpenAPI spec requires. Microcks flagged it."

### Step 2: kagent produces the PR comment

In the PR, kagent automatically posts:

```markdown
## AI Failure Analysis by kagent

**Risk level:** HIGH

**Failed suite:** Microcks contract test (OPEN_API_SCHEMA)

**Evidence:**
- Namespace: preview-pr-43
- Job: microcks-contract-tests
- Endpoint: POST /api/orders
- Expected: HTTP 201 with body field `id` (integer)
- Actual: HTTP 201 with body field `order_id` (integer)
- Raw log excerpt:
  FAIL  POST /api/orders — Response body field 'id' missing (found 'order_id')

**Likely cause:**
The backend renamed the `id` field to `order_id` in the order creation response
but `api/openapi.yaml` was not updated. This is a breaking change for any API
consumer that reads `response.id`.

**Suggested fix:**
Either restore `id` in app.py line 293, or update api/openapi.yaml
components/schemas/OrderResponse to rename the field to `order_id`.

**Commands to reproduce:**
kubectl logs -n preview-pr-43 job/microcks-contract-tests --tail=50

**Confidence:** HIGH — Microcks log clearly identifies the mismatched field.
```

**Talk track:**
> "The developer didn't have to read a single log. kagent read the Kubernetes
> logs, cross-referenced the OpenAPI contract, and wrote a structured diagnosis
> directly in the PR. It even tells you which line of app.py to fix."

### Step 3: Fix and rerun

```bash
# Option A: restore the original field name
# Edit app.py line 293, restore "id": r[0]
git add app.py
git commit -m "fix: restore id field in order response"
git push

# Option B: update the contract to match
# Edit api/openapi.yaml, rename id → order_id in OrderResponse schema
git add api/openapi.yaml
git commit -m "contract: update OrderResponse field to order_id"
git push
```

A push to the same PR triggers a new preview cycle. The new contract test passes.

---

## Closing message

**Talk track:**
> "Let me summarise what just happened. One git push. GitHub Actions built the
> image, Kaniko pushed it to GHCR, the Preview Operator spun up an isolated
> Kubernetes environment with a real database, the AI seeded it with realistic
> data, Microcks validated the API contract, and when it failed, kagent wrote
> the diagnosis automatically.
>
> The developer got actionable feedback in minutes, not after a 2-hour debugging
> session with shared staging.
>
> This is contract-aware, AI-powered preview environments on Kubernetes."

---

## Troubleshooting the demo

### Preview stuck in Provisioning

```bash
kubectl describe preview pr-<N>
kubectl get events -n preview-pr-<N> --sort-by='.lastTimestamp'
```

### Microcks Job not created

Verify that `contractTesting.enabled: true` is set in the Preview CR spec.

### kagent agent not responding

```bash
kubectl -n kagent-system get agent preview-troubleshooter-agent
kubectl -n kagent-system logs deploy/kagent-controller --tail=30
```

### Runner token expired

```bash
NEW_TOKEN=$(gh api -X POST repos/<OWNER>/<REPO>/actions/runners/registration-token --jq '.token')
kubectl set env deployment/github-runner -n github-runner RUNNER_TOKEN="${NEW_TOKEN}"
kubectl rollout restart deployment/github-runner -n github-runner
```
