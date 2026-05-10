# Demo PR Narratives — idp-preview

Six curated PR scenarios that showcase the `spec.changeContext` diff-aware feature
of the idp-preview operator. Each PR has a distinct impact profile so the operator
selects the minimum viable test suite.

---

## PR 1 — Docs-only change

**Branch:** `demo/docs-only-readme`
**Files changed:** `README.md`, `docs/troubleshooting-kagent.txt`

**Expected `detectedImpacts`:** *(empty — no code changed)*
**Expected test suites:** none (or smoke only)

**Narrative:**
A documentation-only PR that updates the README and adds a troubleshooting entry.
The operator detects no source code changed and skips all test suites. The preview
environment is still spun up so reviewers can validate the docs render correctly,
but CI completes in under 10 seconds.

---

## PR 2 — Frontend-only change

**Branch:** `demo/frontend-badge-color`
**Files changed:** `frontend.py`

**Expected `detectedImpacts`:** `["frontend"]`
**Expected test suites:** `e2e`

**Narrative:**
A designer changes the preview badge colour from purple to indigo. The operator sees
only `frontend.py` changed and triggers the Playwright E2E suite to verify the
`data-testid="preview-badge"` element is visible and styled correctly. No backend
or database tests run.

---

## PR 3 — API contract change (backward-compatible)

**Branch:** `demo/api-add-payments-endpoint`
**Files changed:** `app.py`, `api/openapi.yaml`

**Expected `detectedImpacts`:** `["api_contract", "unit"]`
**Expected test suites:** `unit`, `contract`

**Narrative:**
A new `POST /api/payments` and `GET /api/payments` endpoint is added. The operator
detects changes to `api/openapi.yaml` and `app.py` and triggers unit tests (for
the pricing functions) and contract tests (schemathesis validates the spec). The
migration suite is skipped because no migration file changed.

---

## PR 4 — API contract mismatch (intentional failure)

**Branch:** `demo/api-contract-mismatch`
**Files changed:** `app.py` (response schema changed), `api/openapi.yaml` (not updated)

**Expected `detectedImpacts`:** `["api_contract", "kagent_demo"]`
**Expected test suites:** `unit`, `contract`
**Expected outcome:** contract tests FAIL → kagent analyses and posts a PR comment

**Narrative:**
A developer changes the order response in `app.py` to add a `total_price` field
but forgets to update `api/openapi.yaml`. The schemathesis contract test detects
the schema mismatch and fails. kagent reads the test-reports JSON, identifies the
failing contract test, and posts a structured analysis comment on the PR explaining
which field is missing from the spec and how to fix it.

---

## PR 5 — Database migration

**Branch:** `demo/payments-migration`
**Files changed:** `migrations/versions/002_add_payments.py`, `migrations/versions/003_add_discount_code.py`, `app.py`

**Expected `detectedImpacts`:** `["database_migration", "regression", "api_contract"]`
**Expected test suites:** `unit`, `migration`, `regression`, `contract`

**Narrative:**
Two new Alembic migrations are introduced: one adds the `payments` table, another
adds `discount_code` to `orders`. The operator triggers the full migration test
suite (upgrade + downgrade roundtrip) plus regression tests to verify existing
order flows are not broken. The intentionally failing regression tests
(`test_order_total_includes_discount`, `test_payment_idempotency`) trigger kagent
analysis which posts a detailed comment with root cause and suggested fixes.

---

## PR 6 — Performance-sensitive path

**Branch:** `demo/product-list-query-optimisation`
**Files changed:** `app.py` (product list query refactor)

**Expected `detectedImpacts`:** `["regression", "api_contract"]`
**Expected test suites:** `unit`, `regression`, `contract`

**Narrative:**
A backend engineer rewrites the product list query to use a single JOIN instead
of N+1 queries. The operator triggers regression tests (to verify behaviour is
unchanged) and contract tests (to verify the response schema is identical). Unit
tests for pricing functions also run because `app.py` was touched. No migration
or E2E tests are needed.
