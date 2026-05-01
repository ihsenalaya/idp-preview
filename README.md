# idp-testing

Demo application for validating the Cellenza preview environment workflow.  
Each pull request gets an isolated Kubernetes environment with its own PostgreSQL database, a public URL, and automatic GitHub Deployment status. Traces are collected by OpenTelemetry and visible in Jaeger.

---

## Architecture

```
PR opened / updated
       │
       ▼
GitHub Actions (preview.yaml) — self-hosted runner inside the cluster
       │
       ├─ Kaniko ──► builds image ──► pushes to GHCR
       ├─ github.rest.repos.createDeployment() ──► returns deploymentId
       ├─ kubectl apply secret (CELLENZA_GITHUB_TOKEN)
       └─ kubectl apply Cellenza CR ──► spec.github.deploymentId = <id>
                              │
                              ▼
                    Cellenza Operator (reconcile loop)
                              │
              ┌───────────────┼─────────────────────────┐
         Namespace        PostgreSQL               OTel injection
         Deployment     Migration Job           (auto-instrumentation)
         Service           Seed Job                    │
         Ingress         Secret + Service               ▼
         ResourceQuota                           Jaeger (traces)
              │
              ├─ Phase Provisioning → GitHub: in_progress + PR comment
              ├─ Phase Running      → GitHub: success + URL + PR comment
              └─ Phase Terminating  → GitHub: inactive

PR closed → cleanup.yaml → kubectl delete Cellenza → finalizer teardown
```

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Docker | 24+ | https://docs.docker.com/get-docker/ |
| Kind | 0.25+ | `go install sigs.k8s.io/kind@latest` |
| kubectl | 1.28+ | https://kubernetes.io/docs/tasks/tools/ |
| Helm | 3.14+ | https://helm.sh/docs/intro/install/ |
| gh CLI | 2.0+ | https://cli.github.com/ |

---

## Step 1 — Create the Kind cluster

```bash
kind create cluster --name testing
kubectl get nodes
# NAME                    STATUS   ROLES           AGE   VERSION
# testing-control-plane   Ready    control-plane   ...   v1.35.0
```

---

## Step 2 — Install cert-manager

```bash
helm install cert-manager cert-manager \
  --repo https://charts.jetstack.io \
  --namespace cert-manager \
  --create-namespace \
  --version v1.20.2 \
  --set crds.enabled=true

kubectl -n cert-manager rollout status deployment/cert-manager --timeout=120s
kubectl -n cert-manager rollout status deployment/cert-manager-webhook --timeout=120s
```

---

## Step 3 — Install ingress-nginx

```bash
helm install ingress-nginx ingress-nginx/ingress-nginx \
  --repo https://kubernetes.github.io/ingress-nginx \
  --namespace ingress-nginx \
  --create-namespace \
  --version 4.15.1

kubectl -n ingress-nginx rollout status deployment/ingress-nginx-controller --timeout=120s
```

---

## Step 4 — Install the Cellenza Operator

```bash
helm install cellenza-operator \
  oci://ghcr.io/ihsenalaya/charts/cellenza-operator \
  --version 0.11.1 \
  --namespace cellenza-operator-system \
  --create-namespace

kubectl -n cellenza-operator-system rollout status deployment/cellenza-operator --timeout=120s
kubectl get crd cellenzas.platform.company.io
```

---

## Step 5 — Install OpenTelemetry Operator

```bash
helm install opentelemetry-operator open-telemetry/opentelemetry-operator \
  --repo https://open-telemetry.github.io/opentelemetry-helm-charts \
  --namespace opentelemetry-operator-system \
  --create-namespace \
  --version 0.110.0 \
  --set admissionWebhooks.certManager.enabled=true \
  --set manager.collectorImage.repository=otel/opentelemetry-collector-contrib

kubectl -n opentelemetry-operator-system rollout status deployment/opentelemetry-operator --timeout=120s
```

---

## Step 6 — Deploy Jaeger and OTel Collector

```bash
kubectl apply -f https://raw.githubusercontent.com/ihsenalaya/idp-testing/main/jaeger.yaml
kubectl -n observability rollout status deployment/jaeger --timeout=120s

kubectl apply -f https://raw.githubusercontent.com/ihsenalaya/idp-testing/main/otel.yaml
kubectl -n observability rollout status deployment/otel-collector --timeout=120s
```

Verify:

```bash
kubectl get otelcol -n observability
kubectl get instrumentation -n observability
```

---

## Step 7 — Deploy the self-hosted GitHub Actions runner

### 7.1 Generate a runner registration token

> Tokens expire after **1 hour**. Regenerate if the runner pod restarts.

```bash
gh api -X POST repos/<YOUR_OWNER>/<YOUR_REPO>/actions/runners/registration-token --jq '.token'
```

### 7.2 Create and apply `runner.yaml`

Replace `<YOUR_OWNER>`, `<YOUR_REPO>`, `<TOKEN>`:

```yaml
---
apiVersion: v1
kind: Namespace
metadata:
  name: github-runner
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: github-runner
  namespace: github-runner
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: github-runner-admin
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin
subjects:
  - kind: ServiceAccount
    name: github-runner
    namespace: github-runner
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: github-runner
  namespace: github-runner
spec:
  replicas: 1
  selector:
    matchLabels:
      app: github-runner
  template:
    metadata:
      labels:
        app: github-runner
    spec:
      serviceAccountName: github-runner
      containers:
        - name: runner
          image: myoung34/github-runner:latest
          env:
            - name: REPO_URL
              value: https://github.com/<YOUR_OWNER>/<YOUR_REPO>
            - name: RUNNER_TOKEN
              value: <TOKEN>
            - name: RUNNER_NAME
              value: kind-cluster-runner
            - name: RUNNER_WORKDIR
              value: /tmp/runner
            - name: LABELS
              value: self-hosted,kind
            - name: EPHEMERAL
              value: "false"
          resources:
            requests:
              cpu: 100m
              memory: 256Mi
            limits:
              cpu: 1000m
              memory: 1Gi
          volumeMounts:
            - name: docker-sock
              mountPath: /var/run/docker.sock
      volumes:
        - name: docker-sock
          hostPath:
            path: /var/run/docker.sock
```

```bash
kubectl apply -f runner.yaml
kubectl -n github-runner rollout status deployment/github-runner --timeout=60s
kubectl logs -n github-runner deployment/github-runner --tail=5
# Expected last line: "Listening for Jobs"
```

### 7.3 Create the long-lived GitHub token secret for the workflow

The preview workflow uses a repository or organization Actions secret named `CELLENZA_GITHUB_TOKEN`.
This must be a long-lived GitHub token, not the ephemeral workflow `GITHUB_TOKEN`, because the operator updates GitHub Deployments and fetches PR diffs after the workflow has finished.

Recommended: store it as an organization Actions secret if multiple repositories reuse the same preview platform.

Minimum repository permissions for a fine-grained token:

- `Contents`: read
- `Pull requests`: read
- `Issues`: write
- `Deployments`: write

The workflow materializes that token into the cluster as `Secret/cellenza-github-token` in `cellenza-operator-system`.

---

## Step 8 — Open a pull request

```bash
git checkout -b my-feature
echo "# test" >> app.py
git add app.py
git commit -m "test: trigger preview"
git push origin my-feature
gh pr create --title "test: trigger preview" --body "Testing the preview flow"
```

> **Important:** Do not modify `.github/workflows/` files in your PR branch.

---

## Complete Cellenza CR example

This is the full CR applied by `preview.yaml`. It shows every operator feature.

```yaml
apiVersion: platform.company.io/v1alpha1
kind: Cellenza
metadata:
  name: pr-42
spec:
  # ── App ──────────────────────────────────────────────────────────────────
  branch: feature/my-feature
  prNumber: 42
  image: ghcr.io/ihsenalaya/idp-testing:pr-42
  replicas: 1
  ttl: 48h
  resourceTier: medium        # small | medium | large

  # ── Approval gate (optional) ──────────────────────────────────────────────
  requiresApproval: false
  # approvedBy: platform-team # unblocks provisioning when requiresApproval=true

  # ── Database ──────────────────────────────────────────────────────────────
  database:
    enabled: true
    version: "16"
    databaseName: appdb

    migration:
      enabled: true
      command: ["python", "manage.py", "migrate"]
      # image: defaults to spec.image

    seed:
      enabled: true
      command: ["python", "manage.py", "loaddata", "fixtures/dev.json"]
      # image: defaults to spec.image

    # resetRequested: true    # set by @cellenza reset-db — re-runs migration+seed

  # ── Telemetry ─────────────────────────────────────────────────────────────
  telemetry:
    enabled: true
    serviceName: idp-testing-pr-42
    autoInstrumentation:
      language: python
      instrumentationRef: observability/python

  # ── GitHub integration ────────────────────────────────────────────────────
  github:
    enabled: true
    owner: ihsenalaya
    repo: idp-testing
    deploymentId: 123456789   # returned by github.rest.repos.createDeployment()
    environment: pr-42
    commentOnReady: true
    tokenSecretRef:
      name: cellenza-github-token
      namespace: cellenza-operator-system
      key: token

  # ── AI Enrichment ─────────────────────────────────────────────────────────
  aiEnrichment:
    enabled: true
    apiSecretRef:
      name: ai-api-key        # kubectl create secret generic ai-api-key --from-literal=api-key=sk-...
      key: api-key
    githubTokenSecretRef:
      name: cellenza-github-token
      namespace: cellenza-operator-system
      key: token
    model: gpt-4o             # gpt-4o-mini (default), gpt-4o, etc.
    seed:
      enabled: true           # runs ai-seed Job: psql seed.sql against the preview DB
    tests:
      enabled: true           # runs ai-tests Job: python test.py with APP_URL=http://app:80
```

### Environment variables injected automatically

| Variable | Value |
|---|---|
| `DATABASE_URL` | `postgresql://preview_42:<pw>@postgres:5432/appdb` |
| `POSTGRES_USER` | `preview_42` |
| `POSTGRES_PASSWORD` | auto-generated |
| `POSTGRES_DB` | `appdb` |
| `PREVIEW_BRANCH` | `feature/my-feature` |
| `PREVIEW_PR` | `42` |
| `OTEL_SERVICE_NAME` | `idp-testing-pr-42` |
| `OTEL_RESOURCE_ATTRIBUTES` | `cellenza.name=pr-42,cellenza.pr_number=42,...` |

### Lifecycle phases

```
Pending       → waiting for approval (requiresApproval: true)
Provisioning  → namespace, PostgreSQL, migration, seed running
Running       → all resources ready, URL reachable
Terminating   → PR closed, finalizer cleaning up
Failed        → reconciliation error (diagnostics + pod logs in status)
```

---

## Inspect environment status

```bash
# Overview
kubectl get cz
# NAME    PHASE     BRANCH            TIER     URL                                    EXPIRES                AGE
# pr-42   Running   feature/my-feat   medium   http://pr-42.preview.localtest.me...   2026-05-01T10:00:00Z   2h

# Full status
kubectl get cz pr-42 -o jsonpath='{.status}' | jq .
```

```json
{
  "phase": "Running",
  "url": "http://pr-42.preview.localtest.me:8080",
  "namespaceName": "preview-pr-42",
  "readyAt": "2026-04-29T10:00:00Z",
  "expiresAt": "2026-05-01T10:00:00Z",
  "database": {
    "ready": true,
    "host": "postgres",
    "databaseName": "appdb",
    "migration": "Succeeded",
    "seed": "Succeeded"
  },
  "github": {
    "deploymentState": "success",
    "lastNotifiedPhase": "Running",
    "lastEnvironmentUrl": "http://pr-42.preview.localtest.me:8080",
    "commentId": 987654321
  },
  "aiEnrichment": {
    "phase": "Succeeded",
    "seedStatus": "Succeeded",
    "testStatus": "Succeeded",
    "testResults": ["PASS: test_health", "PASS: test_create_product", "PASS: test_stats"],
    "completedAt": "2026-05-01T12:00:00Z"
  }
}
```

---

## GitHub Integration

The operator calls the GitHub API directly from its reconciliation loop — no external webhook needed.

### Phase → GitHub Deployment state mapping

| Phase | GitHub state | PR comment |
|---|---|---|
| `Pending` | `queued` | — |
| `Provisioning` | `in_progress` | `🔄 Provisioning en cours...` |
| `Running` | `success` + URL | `## Cellenza Preview Ready` + URL + DB evidence |
| `Failed` | `failure` | `## Cellenza Preview Failed` + diagnostics + pod logs |
| `Terminating` | `inactive` | — (posted by cleanup.yaml) |

### Idempotence

Before every API call the operator checks `status.github.deploymentState`, `lastNotifiedPhase`, and `commentId`. If already written → zero API call, even across multiple reconcile loops.

```bash
# Current GitHub state
kubectl get cz pr-42 -o jsonpath='{.status.github}' | jq .

# Non-blocking errors
kubectl get cz pr-42 -o jsonpath='{.status.github.lastError}'
```

### spec fields

```yaml
spec:
  github:
    enabled: true
    owner: ihsenalaya
    repo: idp-testing
    deploymentId: 123456789
    environment: pr-42
    commentOnReady: true
    tokenSecretRef:
      name: github-token-pr-42
      namespace: cellenza-operator-system
      key: token
```

---

## Accessing the preview

### Port-forward ingress (required for Kind)

```bash
kubectl port-forward -n ingress-nginx svc/ingress-nginx-controller 8080:80
```

Preview URL printed in PR comment:

```
http://pr-<NUMBER>.preview.localtest.me:8080
```

> **WSL2:** Run the port-forward inside WSL2. Windows browsers reach `localhost:8080` via WSL2 localhost forwarding.

### Jaeger UI

```bash
kubectl port-forward -n observability svc/jaeger 16686:16686
```

Open [http://localhost:16686](http://localhost:16686) → select service **`idp-testing-pr-42`**.

---

## GitHub Copilot Extension

The Cellenza Extension lets developers manage preview environments directly from GitHub Copilot Chat in VS Code — no `kubectl` needed.

### Available commands

| Command | Description |
|---|---|
| `@cellenza list` | List all active environments |
| `@cellenza status pr-42` | Phase, URL, DB state, TTL remaining |
| `@cellenza logs pr-42` | Last 40 lines from the app pod |
| `@cellenza extend pr-42 24h` | Extend TTL immediately |
| `@cellenza wake pr-42` | Restart a scaled-down environment |
| `@cellenza reset-db pr-42` | Delete + re-run migration and seed |
| `@cellenza help` | Show all commands |

### Deploy

```bash
kubectl apply -f config/extension/rbac.yaml
kubectl apply -f config/extension/deployment.yaml
kubectl -n cellenza-operator-system rollout status deployment/cellenza-extension --timeout=60s
```

### Expose for local Kind (ngrok)

```bash
kubectl port-forward -n cellenza-operator-system svc/cellenza-extension 8090:8090 &
ngrok http 8090
# Copy the HTTPS URL → paste as webhook URL in your GitHub App settings
```

---

## Troubleshooting

### Workflow does not trigger — runner token expired

```bash
NEW_TOKEN=$(gh api -X POST repos/<OWNER>/<REPO>/actions/runners/registration-token --jq '.token')
kubectl set env deployment/github-runner -n github-runner RUNNER_TOKEN="$NEW_TOKEN"
kubectl rollout restart deployment/github-runner -n github-runner
kubectl logs -n github-runner deployment/github-runner --tail=5
# Expected: "Listening for Jobs"
```

### No traces in Jaeger

```bash
kubectl get pod -n preview-pr-<N> -l app=cellenza-preview \
  -o jsonpath='{.items[0].metadata.annotations}' | grep instrumentation
# Expected: instrumentation.opentelemetry.io/inject-python: observability/python
```

### Preview stuck in Provisioning

```bash
kubectl describe cz pr-<N>
kubectl get events -n preview-pr-<N> --sort-by='.lastTimestamp'
```

### Preview Failed — read diagnostics

The operator captures pod logs, Kubernetes events, and debug commands automatically:

```bash
kubectl get cz pr-<N> -o jsonpath='{.status.diagnostics}' | jq .
# .podLogs    → last 30 lines of the crashed app container
# .lastEvents → recent Warning events from the namespace
# .debugCommands → kubectl commands to run for further investigation
```

---

## Application

The demo app is a **product catalogue** (v2.0.0) backed by PostgreSQL — designed to showcase AI enrichment with a realistic business schema.

### Database schema

```sql
categories (id, name, slug)
products   (id, name, description, category_id, price NUMERIC, stock INT, discount_pct NUMERIC, created_at)
reviews    (id, product_id, author, rating INT CHECK(1..5), comment, created_at)
orders     (id, product_id, quantity, status, created_at)
```

### HTML UI

| Route | Description |
|---|---|
| `GET /` | PostgreSQL status, env vars, product grid with ratings and stock badges, AI enrichment card |
| `POST /add-product` | Add a product via the HTML form |
| `GET /healthz` | Returns `ok` — liveness/readiness probe |
| `GET /ping` | Returns `pong` |

The AI enrichment card appears on the homepage once `ai-seed` has run. It shows a table of AI-generated products with category, price, discount, stock, and star rating — along with totals for products, reviews, and orders.

### JSON REST API

| Route | Method | Description |
|---|---|---|
| `/api/categories` | GET | List categories with `product_count` |
| `/api/categories` | POST | Create `{"name":"…","slug":"…"}` → 201 |
| `/api/products` | GET | List last 50 products with ratings |
| `/api/products` | POST | Create `{"name":"…","price":9.99,"stock":10,"discount_pct":0}` → 201 |
| `/api/products/<id>` | GET | Product detail with reviews → 200 or 404 |
| `/api/products/<id>` | DELETE | Delete product → 204 or 404 |
| `/api/products/<id>/reviews` | GET | List reviews for a product |
| `/api/products/<id>/reviews` | POST | Create review `{"author":"…","rating":5,"comment":"…"}` → 201 |
| `/api/orders` | GET | List last 50 orders |
| `/api/orders` | POST | Create order `{"product_id":1,"quantity":2}` — checks stock, returns 409 if insufficient → 201 |
| `/api/stats` | GET | `{"total_products":N,"total_categories":N,"total_reviews":N,"total_orders":N,"out_of_stock":N,"low_stock":N,"avg_rating":4.2,"categories":[…]}` |
| `/api/seeded-data` | GET | All products, categories, reviews and order count — used by the AI enrichment UI card |
| `/api/version` | GET | `{"version":"2.0.0","feature":"product-catalogue"}` |

---

## AI Enrichment

When `spec.aiEnrichment.enabled: true`, the operator automatically generates seed data and integration tests **after the preview environment reaches Running phase**.
If the `seed` or `tests` blocks are omitted, the operator treats them as enabled by default. Set `enabled: false` explicitly to skip one of the tasks.

### How it works

```
PR opened → preview Running
                │
                ▼
    Operator fetches PR diff (GitHub API)
    Operator dumps DB schema (pg_dump --schema-only Job)
                │
                ▼
    AI generates:
      ├── seed.sql   → coherent test data adapted to the PR changes
      └── test.py    → integration tests targeting modified code paths
                │
                ▼
    ai-seed Job  → psql seed.sql against the preview database
    ai-tests Job → pip install requests && python test.py
                │
                ▼
    Results visible in PR comment and @cellenza status pr-N
```

### Enable in Cellenza CR

```yaml
spec:
  aiEnrichment:
    enabled: true
    apiSecretRef:
      name: ai-api-key          # kubectl create secret generic ai-api-key --from-literal=api-key=sk-...
      key: api-key
    model: gpt-4o-mini          # optional, defaults to gpt-4o-mini
    seed:
      enabled: true            # optional, defaults to true when omitted
    tests:
      enabled: true            # optional, defaults to true when omitted
```

### Create the API key secret

```bash
# OpenAI
kubectl create secret generic ai-api-key \
  --from-literal=api-key=sk-... \
  -n cellenza-operator-system

# GitHub Models (free tier)
kubectl create secret generic ai-api-key \
  --from-literal=api-key=<GITHUB_TOKEN> \
  -n cellenza-operator-system
# Also set AI_API_URL=https://models.inference.ai.azure.com in operator env
```

### Trigger manually

```bash
# Re-run AI enrichment on an existing environment
@cellenza enrich pr-42
# or via kubectl
kubectl patch cz pr-42 --type=json \
  -p='[{"op":"remove","path":"/status/aiEnrichment"}]'
```

### Test format (tests/example_test.py)

`tests/example_test.py` is a template of 18 integration tests that the AI uses as a model when generating `test.py` for a new PR:

| # | Test | What it verifies |
|---|------|-----------------|
| 1 | `test_health` | `GET /healthz` → 200 `ok` |
| 2 | `test_version` | `GET /api/version` → `2.0.0`, `product-catalogue` |
| 3 | `test_list_categories_returns_json` | `GET /api/categories` → list |
| 4 | `test_create_category` | `POST /api/categories` → 201 |
| 5 | `test_list_products_returns_json` | `GET /api/products` → list |
| 6 | `test_create_product` | `POST /api/products` → 201 |
| 7 | `test_get_product` | `GET /api/products/<id>` → 200 |
| 8 | `test_get_nonexistent_product` | `GET /api/products/999999` → 404 |
| 9 | `test_delete_product` | `DELETE /api/products/<id>` → 204, then 404 |
| 10 | `test_create_product_requires_price` | `POST` without price → 400 |
| 11 | `test_create_review` | `POST /api/products/<id>/reviews` → 201 |
| 12 | `test_review_rating_validation` | Review with rating 6 → 400 |
| 13 | `test_list_reviews` | `GET /api/products/<id>/reviews` → list |
| 14 | `test_create_order` | `POST /api/orders` → 201, stock decremented |
| 15 | `test_order_insufficient_stock` | Order qty > stock → 409 |
| 16 | `test_list_orders` | `GET /api/orders` → list |
| 17 | `test_stats` | `GET /api/stats` → all keys present |
| 18 | `test_seeded_data` | `GET /api/seeded-data` → products, categories, reviews |

Each test prints `PASS: test_name` or `FAIL: test_name — reason`. The AI-generated `test.py` follows the same format but is adapted to the specific changes in the PR.

Run locally against a live environment:

```bash
APP_URL=http://pr-42.preview.localtest.me:8080 python tests/example_test.py
```

---

## Installed components

| Component | Namespace | Version |
|-----------|-----------|---------|
| cert-manager | `cert-manager` | v1.20.2 |
| ingress-nginx | `ingress-nginx` | 4.15.1 |
| Cellenza Operator | `cellenza-operator-system` | **0.11.1** |
| OpenTelemetry Operator | `opentelemetry-operator-system` | 0.110.0 |
| Jaeger (all-in-one) | `observability` | 1.67.0 |
| OTel Collector + Instrumentation | `observability` | 0.148.0 |
| GitHub Runner | `github-runner` | `myoung34/github-runner:latest` |
| Cellenza Extension | `cellenza-operator-system` | **0.11.1** |
