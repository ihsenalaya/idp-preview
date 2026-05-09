# Microcks Integration

This document explains how Microcks is integrated into the Preview Platform
for API contract validation.

---

## Overview

[Microcks](https://microcks.io) is an open-source API mocking and contract
testing tool. In the Preview Platform it runs OPEN_API_SCHEMA validation:
the live backend inside each preview namespace is tested against the contract
defined in `api/openapi.yaml`. Any deviation — wrong status code, missing
field, wrong type — fails the contract test and triggers kagent troubleshooting.

---

## Architecture

```
GitHub PR opened / updated
         │
         ▼
GitHub Actions (preview.yaml)
  └── Apply Preview CR
         │
         ▼
Preview Operator
  ├── Namespace preview-pr-<N>
  ├── Backend (svc-backend:8080)
  ├── AI enrichment + seed
  ├── Regression + E2E tests
  └── [NEW] microcks-contract-tests Job
         │
         ▼
Microcks (in-cluster or external)
  POST /api/tests
  Runner: OPEN_API_SCHEMA
  Target: http://svc-backend:8080
         │
         ▼
  PASS → PR comment updated ✅
  FAIL → kagent agent triggered 🤖
         └── Structured PR comment with diagnosis
```

---

## Contract file

`api/openapi.yaml` is the single source of truth.

| Field | Value |
|-------|-------|
| API name | Preview Catalog API |
| API version | 1.0.0 |
| Runner | OPEN_API_SCHEMA |
| Target (in-cluster) | `http://svc-backend:8080` |

The spec covers all endpoints exposed by `app.py`:

| Method | Path | Validates |
|--------|------|-----------|
| GET | `/healthz` | 200 + `ok` body |
| GET | `/api/categories` | 200 + array schema |
| POST | `/api/categories` | 201 + Category schema |
| GET | `/api/products` | 200 + array schema |
| POST | `/api/products` | 201 + ProductCreated schema |
| GET | `/api/products/{id}` | 200 + ProductDetail schema / 404 |
| DELETE | `/api/products/{id}` | 204 / 404 |
| GET | `/api/products/discounted` | 200 + DiscountedProductList |
| GET | `/api/products/{id}/reviews` | 200 + Review array |
| POST | `/api/products/{id}/reviews` | 201 + Review schema |
| POST | `/api/orders` | 201 + OrderResponse schema / 400 / 404 / 409 |
| GET | `/api/orders` | 200 + Order array |
| GET | `/api/stats` | 200 + Stats schema |

---

## Running contract tests manually

### Prerequisites

- Microcks running (in-cluster or port-forwarded)
- `api/openapi.yaml` imported in Microcks
- Backend reachable at `BACKEND_URL`

### Import the OpenAPI spec into Microcks

```bash
# Via Microcks UI
# Settings → Importers → "Direct Upload" → upload api/openapi.yaml
# API name: "Preview Catalog API", version: "1.0.0"

# Via Microcks API
curl -sf -X POST http://localhost:8080/api/artifact/upload \
  -F "file=@api/openapi.yaml;type=application/yaml" \
  -H "Authorization: Bearer ${TOKEN}"
```

### Run the contract test

```bash
# Using the shell script (requires MICROCKS_URL and BACKEND_URL)
export MICROCKS_URL=http://localhost:8080
export BACKEND_URL=http://localhost:8080
export API_NAME="Preview Catalog API"
export API_VERSION="1.0.0"
export TEST_RUNNER=OPEN_API_SCHEMA

bash scripts/run-microcks-contract-test.sh

# Or via make
make microcks-contract-test
```

### Deploy the Kubernetes Job inside a preview namespace

```bash
# Apply with overridden env for your Microcks URL
kubectl apply -f k8s/microcks/microcks-contract-test-job.yaml \
  -n preview-pr-42

# Watch the result
kubectl logs -n preview-pr-42 job/microcks-contract-tests -f

# Check job status
kubectl get job microcks-contract-tests -n preview-pr-42
```

---

## Secrets required in the preview namespace

| Secret name | Keys | Description |
|-------------|------|-------------|
| `microcks-credentials` | `client_id`, `client_secret` | OAuth2 client for authenticated Microcks |

Create before applying the Job:

```bash
kubectl create secret generic microcks-credentials \
  --namespace preview-pr-42 \
  --from-literal=client_id=<CLIENT_ID> \
  --from-literal=client_secret=<CLIENT_SECRET>
```

If Microcks is configured without authentication, no secret is needed — the
`optional: true` flag in the Job spec makes the secret optional.

---

## Installing Microcks in Kind

```bash
helm repo add microcks https://microcks.io/helm
helm repo update

helm install microcks microcks/microcks \
  --namespace microcks \
  --create-namespace \
  --set microcks.url=microcks.localtest.me \
  --set keycloak.url=keycloak.localtest.me \
  --wait

kubectl -n microcks rollout status deployment/microcks --timeout=120s
```

> For the KubeCon demo, Microcks can be run as a standalone Docker container
> on the host and reached from Kind via host networking or port-forward:
>
> ```bash
> docker run -d -p 8080:8080 -p 9090:9090 quay.io/microcks/microcks-uber:latest
> kubectl port-forward -n microcks svc/microcks 8080:8080
> ```

---

## Operator integration proposal

The Preview Operator (`preview-operator`) needs the following additions to
trigger Microcks contract tests as part of the reconcile pipeline:

### New CRD field

```yaml
spec:
  contractTesting:
    enabled: true
    microcksUrl: http://microcks.microcks.svc.cluster.local:8080
    apiName: "Preview Catalog API"
    apiVersion: "1.0.0"
    runner: OPEN_API_SCHEMA
    secretRef:
      name: microcks-credentials    # optional — omit for open Microcks
```

### New reconcile step

After `reconcileTestSuite()` step `smoke`, add:

```
step "microcks" → create Job microcks-contract-tests
                → wait for completion (RequeueAfter=10s)
                → persist result in status.contractTests
                → post result to PR comment
```

### New status fields

```yaml
status:
  contractTests:
    phase: Succeeded | Failed | Skipped
    passedRequests: 12
    failedRequests: 0
    completedAt: "2026-05-09T10:00:00Z"
    microcksTestId: "abc123"
```

These fields are tracked in etcd and survive operator restarts — the pipeline
resumes at the exact step after a crash, consistent with the existing pattern.
