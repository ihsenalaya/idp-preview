#!/usr/bin/env bash
# open-demo-prs.sh — idempotently create all 6 demo branches and PRs
# Usage: bash scripts/open-demo-prs.sh [--dry-run]
set -euo pipefail

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=true
  echo "DRY RUN — no branches or PRs will be created"
fi

REPO="ihsenalaya/idp-preview"
BASE_BRANCH="main"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"

run() {
  if $DRY_RUN; then
    echo "  [dry-run] $*"
  else
    "$@"
  fi
}

create_demo_pr() {
  local branch="$1"
  local title="$2"
  local body="$3"

  echo ""
  echo "→ Branch: $branch"

  # Check if PR already exists
  existing=$(gh pr list --repo "$REPO" --head "$branch" --json number --jq '.[0].number' 2>/dev/null || echo "")
  if [[ -n "$existing" ]]; then
    echo "  PR #$existing already exists for $branch — skipping"
    return
  fi

  # Create branch from main if it doesn't exist
  if ! git ls-remote --exit-code --heads origin "$branch" >/dev/null 2>&1; then
    run git checkout -b "$branch" "origin/$BASE_BRANCH" 2>/dev/null || run git checkout -b "$branch" "$BASE_BRANCH"

    # Make a trivial commit so the branch differs from main
    run git commit --allow-empty -m "demo: $title"
    run git push origin "$branch"
    run git checkout -
  fi

  run gh pr create \
    --repo "$REPO" \
    --base "$BASE_BRANCH" \
    --head "$branch" \
    --title "$title" \
    --body "$body"
}

# PR 1 — docs only
create_demo_pr \
  "demo/docs-only-readme" \
  "docs: update README and kagent troubleshooting guide" \
  "$(cat <<'EOF'
## Summary

- Update README with AKS setup steps
- Add kagent troubleshooting entry for image pull errors

## Change context

No source code changed — preview operator should skip all test suites.

**Expected `detectedImpacts`:** *(none)*
EOF
)"

# PR 2 — frontend only
create_demo_pr \
  "demo/frontend-badge-color" \
  "feat(frontend): update preview badge colour to indigo" \
  "$(cat <<'EOF'
## Summary

- Change `preview-badge` background from `#7c3aed` (purple) to `#4f46e5` (indigo)

## Change context

Only `frontend.py` changed — operator should run Playwright E2E tests only.

**Expected `detectedImpacts`:** `["frontend"]`
**Expected suites:** `e2e`
EOF
)"

# PR 3 — API contract change
create_demo_pr \
  "demo/api-add-payments-endpoint" \
  "feat(api): add POST /api/payments and GET /api/payments endpoints" \
  "$(cat <<'EOF'
## Summary

- Add `POST /api/payments` to process an order payment
- Add `GET /api/payments` to list last 50 payments
- Update `api/openapi.yaml` with `PaymentCreate` and `PaymentResponse` schemas
- Add pricing pure functions: `calculate_discounted_price`, `calculate_order_total`, `apply_vat`

## Change context

**Expected `detectedImpacts`:** `["api_contract", "unit"]`
**Expected suites:** `unit`, `contract`
EOF
)"

# PR 4 — API contract mismatch (intentional failure)
create_demo_pr \
  "demo/api-contract-mismatch" \
  "feat(api): add total_price to order response [WIP - spec not updated]" \
  "$(cat <<'EOF'
## Summary

- Add `total_price` field to order response in `app.py`
- **NOTE: `api/openapi.yaml` not yet updated** — intentional schema mismatch for kagent demo

## Change context

**Expected `detectedImpacts`:** `["api_contract", "kagent_demo"]`
**Expected suites:** `unit`, `contract`
**Expected outcome:** contract tests FAIL → kagent posts analysis comment
EOF
)"

# PR 5 — database migration
create_demo_pr \
  "demo/payments-migration" \
  "feat(db): add payments table and discount_code column to orders" \
  "$(cat <<'EOF'
## Summary

- Migration 002: create `payments` table with `transaction_id`, `amount`, `method`
- Migration 003: add `discount_code` column to `orders`
- Intentionally failing regression tests trigger kagent AI analysis

## Change context

**Expected `detectedImpacts`:** `["database_migration", "regression", "api_contract"]`
**Expected suites:** `unit`, `migration`, `regression`, `contract`
EOF
)"

# PR 6 — performance optimisation
create_demo_pr \
  "demo/product-list-query-optimisation" \
  "perf(api): replace N+1 product query with single JOIN" \
  "$(cat <<'EOF'
## Summary

- Rewrite product list query to use a single SQL JOIN instead of N+1 selects
- No schema changes, no migration, no frontend changes

## Change context

**Expected `detectedImpacts`:** `["regression", "api_contract"]`
**Expected suites:** `unit`, `regression`, `contract`
EOF
)"

echo ""
echo "Done. Open PRs:"
gh pr list --repo "$REPO" --limit 10 --json number,title,headRefName \
  --jq '.[] | "  #\(.number) \(.headRefName) — \(.title)"' 2>/dev/null || true
