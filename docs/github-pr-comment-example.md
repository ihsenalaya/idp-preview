# GitHub PR Comment Examples

This file shows the exact JSON payloads used to post PR comments via the
GitHub REST API, plus rendered Markdown examples of what the developer sees.

---

## 1. Preview ready comment (posted by operator)

### API call

```bash
curl -X POST \
  "https://api.github.com/repos/ihsenalaya/idp-preview/issues/42/comments" \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  -H "Content-Type: application/json" \
  -d @- <<'EOF'
{
  "body": "## Preview Ready ✅\n\n**URL:** http://pr-42.preview.localtest.me:8080\n\n| Suite | Status | Passed | Failed |\n|-------|--------|--------|--------|\n| Smoke | ✅ Succeeded | 2 | 0 |\n| Contract (Microcks) | ✅ Succeeded | 12 | 0 |\n| Regression | ✅ Succeeded | 9 | 0 |\n| E2E | ✅ Succeeded | 6 | 0 |\n\n**Namespace:** `preview-pr-42`\n**Expires:** 2026-05-11T10:00:00Z"
}
EOF
```

### Rendered output

---

## Preview Ready ✅

**URL:** http://pr-42.preview.localtest.me:8080

| Suite | Status | Passed | Failed |
|-------|--------|--------|--------|
| Smoke | ✅ Succeeded | 2 | 0 |
| Contract (Microcks) | ✅ Succeeded | 12 | 0 |
| Regression | ✅ Succeeded | 9 | 0 |
| E2E | ✅ Succeeded | 6 | 0 |

**Namespace:** `preview-pr-42`
**Expires:** 2026-05-11T10:00:00Z

---

## 2. Contract failure comment (posted by kagent)

### API call

```bash
curl -X POST \
  "https://api.github.com/repos/ihsenalaya/idp-preview/issues/42/comments" \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  -H "Content-Type: application/json" \
  -d @- <<'EOF'
{
  "body": "## AI Failure Analysis by kagent\n\n**Risk level:** HIGH\n\n**Failed suite:** Microcks contract test (OPEN_API_SCHEMA)\n\n**Evidence:**\n- Namespace: `preview-pr-42`\n- Job: `microcks-contract-tests`\n- Endpoint: `POST /api/orders`\n- Expected: HTTP `201` with field `id`\n- Actual: HTTP `201` with field `order_id`\n\n```\nFAIL POST /api/orders — Response body field 'id' missing (found 'order_id')\n```\n\n**Likely cause:**\nThe backend renamed `id` to `order_id` in the order response but `api/openapi.yaml` was not updated.\n\n**Suggested fix:**\nRestore `id` in `app.py` line 293, or update `api/openapi.yaml` `OrderResponse` schema.\n\n**Commands to reproduce:**\n```bash\nkubectl logs -n preview-pr-42 job/microcks-contract-tests --tail=50\n```\n\n**Confidence:** HIGH"
}
EOF
```

### Rendered output

---

## AI Failure Analysis by kagent

**Risk level:** HIGH

**Failed suite:** Microcks contract test (OPEN_API_SCHEMA)

**Evidence:**
- Namespace: `preview-pr-42`
- Job: `microcks-contract-tests`
- Endpoint: `POST /api/orders`
- Expected: HTTP `201` with field `id`
- Actual: HTTP `201` with field `order_id`

```
FAIL POST /api/orders — Response body field 'id' missing (found 'order_id')
```

**Likely cause:**
The backend renamed `id` to `order_id` in the order response but
`api/openapi.yaml` was not updated.

**Suggested fix:**
Restore `id` in `app.py` line 293, or update `api/openapi.yaml`
`OrderResponse` schema.

**Commands to reproduce:**
```bash
kubectl logs -n preview-pr-42 job/microcks-contract-tests --tail=50
```

**Confidence:** HIGH

---

## 3. Update existing comment (idempotent)

The operator stores `commentId` in `status.github.commentId` and patches the
comment instead of creating a new one on every reconcile.

```bash
COMMENT_ID=987654321

curl -X PATCH \
  "https://api.github.com/repos/ihsenalaya/idp-preview/issues/comments/${COMMENT_ID}" \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"body": "<updated body>"}'
```
