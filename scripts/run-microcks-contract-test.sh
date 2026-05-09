#!/usr/bin/env bash
# run-microcks-contract-test.sh
#
# Triggers an OPEN_API_SCHEMA contract test in Microcks against the live
# backend deployed inside a preview namespace, then polls for the result.
#
# Required env vars:
#   MICROCKS_URL            e.g. http://microcks.microcks.svc.cluster.local:8080
#   BACKEND_URL             e.g. http://svc-backend:8080
#   API_NAME                "Preview Catalog API"
#   API_VERSION             "1.0.0"
#   TEST_RUNNER             OPEN_API_SCHEMA
#
# Optional env vars (leave unset for open/anonymous Microcks):
#   MICROCKS_CLIENT_ID
#   MICROCKS_CLIENT_SECRET
#
# Exit codes:
#   0  All contract tests passed
#   1  Contract tests failed or error during execution

set -euo pipefail

# ── helpers ──────────────────────────────────────────────────────────────────

log()  { echo "[microcks] $*"; }
fail() { echo "[microcks] ERROR: $*" >&2; exit 1; }

require_env() {
  for var in "$@"; do
    [ -n "${!var:-}" ] || fail "Required env var '${var}' is not set."
  done
}

# ── configuration ─────────────────────────────────────────────────────────────

require_env MICROCKS_URL BACKEND_URL API_NAME API_VERSION TEST_RUNNER

POLL_INTERVAL="${POLL_INTERVAL:-5}"
POLL_MAX="${POLL_MAX:-36}"          # 36 × 5s = 3 min max wait
TEST_TIMEOUT_MS="${TEST_TIMEOUT_MS:-30000}"

log "Microcks URL  : ${MICROCKS_URL}"
log "Backend URL   : ${BACKEND_URL}"
log "API           : ${API_NAME} v${API_VERSION}"
log "Runner        : ${TEST_RUNNER}"

# ── 1. Obtain OAuth2 token (client_credentials) ───────────────────────────────

TOKEN=""
if [ -n "${MICROCKS_CLIENT_ID:-}" ] && [ -n "${MICROCKS_CLIENT_SECRET:-}" ]; then
  log "Authenticating with Microcks Keycloak …"

  # Keycloak token endpoint lives under /auth/realms/microcks for the default install
  KEYCLOAK_URL="${MICROCKS_KEYCLOAK_URL:-${MICROCKS_URL%:*}:18080}"
  TOKEN_URL="${KEYCLOAK_URL}/realms/microcks/protocol/openid-connect/token"

  TOKEN=$(curl -sf \
    --max-time 15 \
    -X POST "${TOKEN_URL}" \
    -d "grant_type=client_credentials" \
    -d "client_id=${MICROCKS_CLIENT_ID}" \
    --data-urlencode "client_secret=${MICROCKS_CLIENT_SECRET}" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])" \
  ) || fail "Failed to obtain OAuth2 token from ${TOKEN_URL}"

  log "OAuth2 token obtained."
else
  log "No MICROCKS_CLIENT_ID/SECRET — proceeding without authentication."
fi

# ── auth header helper ────────────────────────────────────────────────────────

auth_header() {
  if [ -n "${TOKEN}" ]; then
    echo "-H" "Authorization: Bearer ${TOKEN}"
  fi
}

# ── 2. Verify API exists in Microcks ─────────────────────────────────────────

log "Checking that '${API_NAME}' v${API_VERSION} is imported in Microcks …"

API_CHECK=$(curl -sf \
  --max-time 10 \
  $(auth_header) \
  "${MICROCKS_URL}/api/services?page=0&size=10&name=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "${API_NAME}")" \
  2>/dev/null || echo "[]")

if ! echo "${API_CHECK}" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for svc in data:
    if svc.get('name') == '${API_NAME}' and svc.get('version') == '${API_VERSION}':
        sys.exit(0)
sys.exit(1)
" 2>/dev/null; then
  log "WARNING: API not found in Microcks — it may need to be imported first."
  log "  Import command: POST ${MICROCKS_URL}/api/artifact/upload  (multipart/form-data, field=file)"
  log "  Artifact: api/openapi.yaml from repository root"
  # Do not abort — Microcks may still accept the test request by service name
fi

# ── 3. Submit test request ────────────────────────────────────────────────────

log "Submitting contract test …"

# Microcks identifies the API as "name:version" in the serviceId field
SERVICE_ID="${API_NAME}:${API_VERSION}"

TEST_REQUEST=$(python3 -c "
import json, sys
print(json.dumps({
  'serviceId':    sys.argv[1],
  'testEndpoint': sys.argv[2],
  'runnerType':   sys.argv[3],
  'timeout':      int(sys.argv[4]),
}))
" "${SERVICE_ID}" "${BACKEND_URL}" "${TEST_RUNNER}" "${TEST_TIMEOUT_MS}")

RESPONSE=$(curl -sf \
  --max-time 15 \
  -X POST "${MICROCKS_URL}/api/tests" \
  -H "Content-Type: application/json" \
  $(auth_header) \
  -d "${TEST_REQUEST}" \
) || fail "Failed to submit test request to Microcks."

TEST_ID=$(echo "${RESPONSE}" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])" 2>/dev/null) \
  || fail "Could not extract test ID from response: ${RESPONSE}"

log "Test submitted — ID: ${TEST_ID}"

# ── 4. Poll until complete ────────────────────────────────────────────────────

log "Polling for results (max $((POLL_MAX * POLL_INTERVAL))s) …"

i=0
while [ "${i}" -lt "${POLL_MAX}" ]; do
  i=$((i + 1))

  RESULT=$(curl -sf \
    --max-time 10 \
    $(auth_header) \
    "${MICROCKS_URL}/api/tests/${TEST_ID}" \
  ) || { log "Poll attempt ${i}/${POLL_MAX} failed — retrying"; sleep "${POLL_INTERVAL}"; continue; }

  IN_PROGRESS=$(echo "${RESULT}" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('true' if d.get('inProgress', True) else 'false')
") || IN_PROGRESS="true"

  if [ "${IN_PROGRESS}" = "false" ]; then
    break
  fi

  log "  [${i}/${POLL_MAX}] Still running …"
  sleep "${POLL_INTERVAL}"
done

if [ "${IN_PROGRESS:-true}" = "true" ]; then
  fail "Microcks test timed out after $((POLL_MAX * POLL_INTERVAL))s."
fi

# ── 5. Parse and report results ───────────────────────────────────────────────

log "Test complete — parsing results …"

python3 - "${RESULT}" <<'PYEOF'
import sys, json

result = json.loads(sys.argv[1])
success = result.get("success", False)
test_cases = result.get("testCaseResults", [])

print()
print("=" * 60)
print(f"  Microcks Contract Test — {'PASSED' if success else 'FAILED'}")
print("=" * 60)

total_requests = 0
failed_requests = 0

for tc in test_cases:
    op       = tc.get("operationName", "?")
    tc_pass  = tc.get("success", False)
    requests = tc.get("testStepResults", [])
    for req in requests:
        total_requests += 1
        req_ok = req.get("success", False)
        msg    = req.get("message", "")
        status = "PASS" if req_ok else "FAIL"
        if not req_ok:
            failed_requests += 1
            print(f"  {status}  {op}  — {msg}")
        else:
            print(f"  {status}  {op}")

print()
print(f"  {total_requests - failed_requests}/{total_requests} request(s) passed")
print("=" * 60)
print()

sys.exit(0 if success else 1)
PYEOF

exit $?
PYEOF_STATUS=$?
exit ${PYEOF_STATUS}
