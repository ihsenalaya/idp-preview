# AI Failure Report Template

This document shows the exact format that `preview-troubleshooter-agent` (kagent)
posts to the GitHub PR after a test failure.

---

## Sample: Microcks contract violation

> Posted automatically by `preview-troubleshooter-agent` on PR #42 after
> `microcks-contract-tests` job failed.

---

## AI Failure Analysis by kagent

**Risk level:** HIGH

**Failed suite:** Microcks contract test (OPEN_API_SCHEMA)

**Evidence:**
- Namespace: `preview-pr-42`
- Job: `microcks-contract-tests`
- Endpoint: `POST /api/orders`
- Expected: HTTP `201` with body containing field `id` (integer)
- Actual: HTTP `200` with body containing field `order_id` (integer)
- Raw log excerpt:
  ```
  [microcks] Test complete — parsing results …
  FAIL  POST /api/orders — Response status 200 does not match expected 201
  FAIL  POST /api/orders — Response body field 'id' missing (found 'order_id')
  0/2 request(s) passed
  ```

**Likely cause:**
The backend changed its response payload for `POST /api/orders` — the field
was renamed from `id` to `order_id` — but `api/openapi.yaml` was not updated
to reflect this change. Microcks validated the live response against the
contract and rejected it.

**Suggested fix:**
Either:
1. Restore the original field name in `app.py` line 293 (`"id": r[0]`) — this
   is the safer option if the API has external consumers.
2. Or update `api/openapi.yaml` under `components/schemas/OrderResponse` to
   rename `id` to `order_id`, then rerun the preview pipeline.

**Commands to reproduce:**
```bash
# Inspect the failed job
kubectl logs -n preview-pr-42 job/microcks-contract-tests --tail=50

# Check what the live backend actually returns
kubectl exec -n preview-pr-42 deploy/svc-backend -- \
  curl -sf -X POST http://localhost:8080/api/orders \
    -H 'Content-Type: application/json' \
    -d '{"product_id":1,"quantity":1}' | python3 -m json.tool

# Diff the live response against the OpenAPI schema
kubectl get preview pr-42 -o jsonpath='{.status}' | jq .
```

**Confidence:** HIGH
Full Microcks test log is available and clearly identifies the mismatched field.
No ambiguity in the root cause.

---

## Sample: Regression test failure (endpoint 500)

---

## AI Failure Analysis by kagent

**Risk level:** MEDIUM

**Failed suite:** Regression tests

**Evidence:**
- Namespace: `preview-pr-42`
- Job: `regression-tests`
- Endpoint: `GET /api/products/discounted`
- Expected: HTTP `200`
- Actual: HTTP `500`
- Raw log excerpt:
  ```
  FAIL regression discounted_products: expected 200 got 500
  Results: 8 passed, 1 failed
  ```
- Backend log excerpt:
  ```
  [db] ERROR: column "discount_pct" does not exist
  LINE 1: WHERE p.discount_pct >= %s AND p.stock > 0
  ```

**Likely cause:**
The database migration in this PR renamed or dropped the `discount_pct` column
in the `products` table. The Alembic migration applied successfully but the
backend SQL query was not updated to match the new column name.

**Suggested fix:**
In `app.py` around line 393, update the SQL query to use the new column name.
Alternatively, verify whether the migration is reversible and roll it back if
the rename was unintentional.

**Commands to reproduce:**
```bash
kubectl logs -n preview-pr-42 job/regression-tests --tail=30
kubectl logs -n preview-pr-42 deploy/svc-backend --tail=30
kubectl exec -n preview-pr-42 deploy/postgres -- \
  psql -U preview_42 -d appdb -c '\d products'
```

**Confidence:** MEDIUM
Column error is confirmed in backend logs. The exact migration file causing
this was not inspected — check `migrations/versions/` for the latest migration.

---

## Risk level reference

| Level | When to use |
|-------|-------------|
| HIGH | API contract broken, data loss, security regression |
| MEDIUM | Functional regression, partial feature failure |
| LOW | Cosmetic issue, non-critical path, minor test flakiness |
| INFO | Transient infrastructure issue (node pressure, DNS timeout) |
