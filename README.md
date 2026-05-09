# idp-preview — Preview Platform

Demo application and reference implementation for the **Preview Operator** — a Kubernetes controller that turns every pull request into a fully isolated preview environment, complete with its own database, URL, test pipeline, and AI-generated seed data.

---

## Table of Contents

1. [General Architecture](#1-general-architecture)
2. [Prerequisites](#2-prerequisites)
3. [Cluster Installation](#3-cluster-installation)
4. [The Preview Custom Resource](#4-the-preview-custom-resource)
5. [Controller Deep Dive](#5-controller-deep-dive)
6. [Test Suite Orchestration](#6-test-suite-orchestration)
7. [AI Enrichment Orchestration](#7-ai-enrichment-orchestration)
8. [GitHub Integration](#8-github-integration)
9. [Copilot Extension](#9-copilot-extension)
10. [Application Reference](#10-application-reference)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. General Architecture

### End-to-end workflow — from PR to TTL expiry or close

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│  Developer                                                                      │
│   git push origin feat/my-feature                                               │
│   gh pr create                                                                  │
└────────────────────────────┬────────────────────────────────────────────────────┘
                             │ pull_request: opened / synchronize / reopened
                             ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  GitHub Actions  (.github/workflows/preview.yaml)                               │
│  runs-on: [self-hosted, kind]  ← runner pod inside the cluster                 │
│                                                                                 │
│  1. Kaniko Job  ──────► build image from git HEAD ──► push to GHCR             │
│  2. github.rest.repos.createDeployment() ──► returns deploymentId              │
│  3. kubectl apply Secret (PREVIEW_GITHUB_TOKEN)                                │
│  4. kubectl apply Preview CR ──► name: pr-<N>                                 │
│  5. kubectl wait phase=Running && deploymentState=success (poll 10s × 30)      │
└────────────────────────────┬────────────────────────────────────────────────────┘
                             │ CR created / updated in etcd
                             ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│  Preview Operator  (controller-runtime reconcile loop)                         │
│                                                                                 │
│  PHASE: Pending ──► (requiresApproval gate)                                    │
│                                                                                 │
│  PHASE: Provisioning                                                            │
│    ├── Create Namespace      preview-pr-<N>                                    │
│    ├── Create ResourceQuota  (tier: small / medium / large)                    │
│    ├── Provision PostgreSQL  (Deployment + Service + Secret)                   │
│    ├── Run Migration Job     (optional — if spec.database.migration)           │
│    ├── Run Seed Job          (optional — if spec.database.seed)                │
│    ├── Deploy Services       svc-backend (app.py:8080) + svc-frontend (3000)  │
│    ├── Create Ingress        /api → backend   / → frontend                    │
│    ├── Inject OTel           annotation → sidecar injected by OTel operator    │
│    └── Post GitHub comment   "🔄 Provisioning en cours…"                      │
│                                                                                 │
│  PHASE: Running                                                                 │
│    ├── Post GitHub Deployment: success + URL                                   │
│    ├── Post PR comment: "## Preview Preview Ready"                            │
│    │                                                                            │
│    ├── [AI ENRICHMENT — runs first, blocks tests until done]                  │
│    │     step 1: schema-dump Job   ──► pg_dump --schema-only                  │
│    │     step 2: ai-generate Job   ──► call LLM → seed.sql + test.py          │
│    │     step 3: ai-seed Job       ──► psql seed.sql → 10 products, reviews  │
│    │     step 4: ai-tests Job      ──► python test.py                         │
│    │                                                                            │
│    └── [TEST SUITE — starts only after AI enrichment Succeeded or Failed]     │
│          step 1: suite-checkpoint-save     ──► pg_dump → ConfigMap            │
│          step 2: smoke-tests               ──► /healthz + /api/products       │
│          step 3: suite-restore-regression  ──► TRUNCATE + psql replay         │
│          step 4: regression-tests          ──► tests/regression.py            │
│          step 5: suite-restore-e2e         ──► TRUNCATE + psql replay         │
│          step 6: e2e-tests (Playwright)    ──► tests/e2e.py                   │
│                                                                                 │
│  PHASE: Terminating                                                             │
│    ├── Delete all namespace resources                                          │
│    ├── Delete namespace                                                        │
│    └── GitHub Deployment: inactive                                             │
└────────────────────────────┬────────────────────────────────────────────────────┘
                             │
          ┌──────────────────┼──────────────────────┐
          │                  │                       │
          ▼                  ▼                       ▼
    PR merged /        TTL expired             @preview
    PR closed          (default 48h)           retest-ai
          │                  │                       │
          └──────────────────┘                       │
                   │                                 │
    cleanup.yaml   │                         AI-only rerun cycle
    kubectl delete Preview ◄────────────┐   (skips smoke/regression/e2e)
    finalizer teardown                   │
    GitHub Deployment: inactive          │
                                         └─ spec.aiEnrichment.rerunRequested=true
```

### Namespace isolation per PR

```
cluster
├── preview-operator-system/          ← operator + extension
│     └── preview-operator pod
├── github-runner/                     ← self-hosted Actions runner + Kaniko jobs
├── observability/                     ← Jaeger + OTel Collector + Instrumentation
│
├── preview-pr-1/                      ┐
│     ├── svc-backend  (app.py:8080)   │  isolated namespace
│     ├── svc-frontend (frontend:3000) │  one per open PR
│     ├── postgres                     │
│     ├── Ingress (pr-1.preview.*)     │
│     └── Jobs (test/AI/restore…)      ┘
│
├── preview-pr-2/                      ┐
│     └── (same structure)             │  PR #2 is completely independent
│                                      ┘
└── preview-pr-N/ …
```

---

## 2. Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Docker | 24+ | https://docs.docker.com/get-docker/ |
| Kind | 0.25+ | `go install sigs.k8s.io/kind@latest` |
| kubectl | 1.28+ | https://kubernetes.io/docs/tasks/tools/ |
| Helm | 3.14+ | https://helm.sh/docs/intro/install/ |
| gh CLI | 2.0+ | https://cli.github.com/ |

---

## 3. Cluster Installation

### Step 0 — Add Helm repositories

Run once before any install step.

```bash
helm repo add jetstack       https://charts.jetstack.io
helm repo add ingress-nginx  https://kubernetes.github.io/ingress-nginx
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm repo update
```

### Step 1 — Create the Kind cluster

```bash
kind create cluster --name testing
kubectl get nodes
# NAME                    STATUS   ROLES           AGE   VERSION
# testing-control-plane   Ready    control-plane   …     v1.35.0
```

### Step 2 — Install cert-manager

```bash
helm install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --version v1.20.2 \
  --set crds.enabled=true \
  --wait

kubectl -n cert-manager rollout status deployment/cert-manager --timeout=120s
kubectl -n cert-manager rollout status deployment/cert-manager-webhook --timeout=120s
```

### Step 3 — Install ingress-nginx

> Do **not** pin a version — older releases are removed from the repo index over time.

**Important:** disable admission webhooks. In Kind, the webhook certificate is self-signed and not trusted by the API server, which causes any Ingress creation to fail with `x509: certificate signed by unknown authority`.

```bash
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --create-namespace \
  --set controller.admissionWebhooks.enabled=false \
  --wait

kubectl -n ingress-nginx rollout status deployment/ingress-nginx-controller --timeout=120s
```

If already installed without this flag:

```bash
helm upgrade ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --set controller.admissionWebhooks.enabled=false \
  --wait

kubectl delete validatingwebhookconfiguration ingress-nginx-admission --ignore-not-found
```

> **WSL2:** preview URLs are reachable at `http://pr-<N>.preview.localtest.me:8080` via port-forward (see [Accessing the Preview](#accessing-the-preview)).

### Step 4 — Install the Preview Operator

The chart is published as an OCI artifact on GHCR (public, no login required).

```bash
helm install preview-operator \
  oci://ghcr.io/ihsenalaya/charts/preview-operator \
  --version 0.13.8 \
  --namespace preview-operator-system \
  --create-namespace \
  --wait

kubectl -n preview-operator-system rollout status deployment/preview-operator --timeout=120s
kubectl get crd previews.platform.company.io
```

#### Upgrading the operator

```bash
# Always apply the CRD first — Helm does NOT update CRDs automatically
helm show crds oci://ghcr.io/ihsenalaya/charts/preview-operator --version 0.13.8 \
  | tail -n +3 \
  | kubectl apply -f -

helm upgrade preview-operator \
  oci://ghcr.io/ihsenalaya/charts/preview-operator \
  --version 0.13.8 \
  --namespace preview-operator-system

kubectl -n preview-operator-system rollout status deployment/preview-operator --timeout=120s
```

> `tail -n +3` strips the two-line Helm OCI pull header that `helm show crds` prepends.

### Step 5 — Install OpenTelemetry Operator

```bash
helm install opentelemetry-operator open-telemetry/opentelemetry-operator \
  --namespace opentelemetry-operator-system \
  --create-namespace \
  --set admissionWebhooks.certManager.enabled=true \
  --set manager.collectorImage.repository=otel/opentelemetry-collector-contrib \
  --wait

kubectl -n opentelemetry-operator-system rollout status deployment/opentelemetry-operator --timeout=120s
```

### Step 6 — Deploy Jaeger and OTel Collector

```bash
kubectl apply -f https://raw.githubusercontent.com/ihsenalaya/idp-preview/main/jaeger.yaml
kubectl -n observability rollout status deployment/jaeger --timeout=120s

kubectl apply -f https://raw.githubusercontent.com/ihsenalaya/idp-preview/main/otel.yaml
kubectl -n observability rollout status deployment/otel-collector --timeout=120s

kubectl get otelcol -n observability
kubectl get instrumentation -n observability
```

### Step 7 — Deploy the self-hosted GitHub Actions runner

#### 7.1 Generate a runner registration token

> Tokens expire after **1 hour**. Regenerate whenever the runner pod restarts.

```bash
gh api -X POST repos/<OWNER>/<REPO>/actions/runners/registration-token --jq '.token'
```

#### 7.2 Apply runner.yaml

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
kubectl -n github-runner rollout status deployment/github-runner --timeout=120s
kubectl logs -n github-runner deployment/github-runner --tail=5
# Expected last line: "Listening for Jobs"
```

> **Note:** `myoung34/github-runner:latest` is ~1 GB. The first pull can take several minutes inside Kind.

#### 7.3 Set the GitHub Actions secret

```bash
gh secret set PREVIEW_GITHUB_TOKEN \
  --repo <OWNER>/<REPO> \
  --body "<YOUR_GITHUB_PAT>"
```

Minimum token permissions:

| Permission | Level |
|---|---|
| `write:packages` | Required — Kaniko pushes to GHCR |
| `Contents` | read |
| `Pull requests` | read |
| `Issues` | write |
| `Deployments` | write |

#### 7.4 Create the operator secret

```bash
kubectl create secret generic preview-github-token \
  --namespace preview-operator-system \
  --from-literal=token="<YOUR_GITHUB_PAT>"
```

#### 7.5 Configure AI enrichment (optional)

**GitHub Models (free tier)**

```bash
kubectl create secret generic ai-api-key \
  --namespace preview-operator-system \
  --from-literal=api-key="<YOUR_GITHUB_TOKEN>"

kubectl set env deployment/preview-operator \
  AI_API_URL=https://models.inference.ai.azure.com \
  -n preview-operator-system
```

**OpenAI**

```bash
kubectl create secret generic ai-api-key \
  --namespace preview-operator-system \
  --from-literal=api-key="sk-..."
# No AI_API_URL override needed — the operator default is https://api.openai.com/v1
```

#### Renew runner token (when token expires)

```bash
NEW_TOKEN=$(gh api -X POST repos/<OWNER>/<REPO>/actions/runners/registration-token --jq '.token')
kubectl set env deployment/github-runner -n github-runner RUNNER_TOKEN="$NEW_TOKEN"
kubectl rollout restart deployment/github-runner -n github-runner
kubectl logs -n github-runner deployment/github-runner --tail=5
# Expected: "Listening for Jobs"
```

---

## 4. The Preview Custom Resource

### Complete annotated example

```yaml
apiVersion: platform.company.io/v1alpha1
kind: Preview
metadata:
  name: pr-42
spec:

  # ── Identity ───────────────────────────────────────────────────────────────
  branch: feature/my-feature
  prNumber: 42
  image: ghcr.io/ihsenalaya/idp-preview:sha-abc   # ignored when services[] is set
  ttl: 48h                                          # default 48h — supports: 1h 24h 72h etc.
  resourceTier: medium                              # small | medium | large

  # ── Multi-service (frontend + backend) ────────────────────────────────────
  services:
    - name: backend
      image: ghcr.io/ihsenalaya/idp-preview:sha-abc
      port: 8080
      pathPrefix: /api          # ingress routes /api/* → svc-backend:8080
    - name: frontend
      image: ghcr.io/ihsenalaya/idp-preview:sha-abc
      port: 3000
      pathPrefix: /             # ingress routes /* → svc-frontend:3000
      env:
        - name: APP_MODE
          value: frontend       # switches entrypoint to frontend.py
        - name: PREVIEW_PR
          value: "42"
        - name: PREVIEW_BRANCH
          value: feature/my-feature

  # ── Approval gate (optional) ───────────────────────────────────────────────
  requiresApproval: false
  # approvedBy: platform-team  # unblocks when requiresApproval=true

  # ── Database ───────────────────────────────────────────────────────────────
  database:
    enabled: true
    databaseName: appdb
    # migration:
    #   enabled: true           # runs an Alembic Job (optional)
    # seed:
    #   enabled: true           # runs a static seed Job (optional)

  # ── Telemetry ──────────────────────────────────────────────────────────────
  telemetry:
    enabled: true
    serviceName: idp-preview-pr-42
    autoInstrumentation:
      language: python
      instrumentationRef: observability/python

  # ── Test Suite ─────────────────────────────────────────────────────────────
  testSuite:
    enabled: true
    smoke: {}                   # built-in — no config needed
    regression:
      enabled: true             # runs /app/tests/regression.py
    e2e:
      enabled: true             # runs /app/tests/e2e.py (Playwright/Chromium)

  # ── AI Enrichment ──────────────────────────────────────────────────────────
  aiEnrichment:
    enabled: true
    apiSecretRef:
      name: ai-api-key
      key: api-key
    githubTokenSecretRef:
      name: preview-github-token
      namespace: preview-operator-system
      key: token
    model: gpt-4o-mini          # gpt-4o-mini (fast + cheap) | gpt-4o (better quality)
    seed:
      enabled: true             # generates + runs seed.sql
    tests:
      enabled: true             # generates + runs test.py
    # rerunRequested: true      # set by @preview retest-ai — triggers AI-only rerun

  # ── GitHub integration ─────────────────────────────────────────────────────
  github:
    enabled: true
    owner: ihsenalaya
    repo: idp-preview
    deploymentId: 123456789     # returned by github.rest.repos.createDeployment()
    environment: pr-42
    commentOnReady: true
    tokenSecretRef:
      name: preview-github-token
      namespace: preview-operator-system
      key: token
```

### Environment variables injected automatically into every service pod

| Variable | Value |
|---|---|
| `DATABASE_URL` | `postgresql://preview_42:<pw>@postgres:5432/appdb` |
| `POSTGRES_USER` | `preview_42` |
| `POSTGRES_PASSWORD` | auto-generated |
| `POSTGRES_DB` | `appdb` |
| `PREVIEW_BRANCH` | `feature/my-feature` |
| `PREVIEW_PR` | `42` |
| `OTEL_SERVICE_NAME` | `idp-preview-pr-42` |
| `OTEL_RESOURCE_ATTRIBUTES` | `preview.name=pr-42,preview.pr_number=42,…` |

### Resource tiers

| Tier | CPU request | CPU limit | Memory request | Memory limit |
|------|-------------|-----------|----------------|--------------|
| `small` | 50m | 200m | 64Mi | 256Mi |
| `medium` | 100m | 500m | 128Mi | 512Mi |
| `large` | 250m | 1000m | 256Mi | 1Gi |

### Lifecycle phases

```
Pending       → requiresApproval=true, waiting for approvedBy to be set
Provisioning  → namespace, PostgreSQL, services, ingress being created
Running       → all resources ready, URL reachable, AI + tests executing
Terminating   → PR closed / TTL expired, finalizer tearing down namespace
Failed        → reconcile error — diagnostics + pod logs captured in status
```

---

## 5. Controller Deep Dive

### Reconcile loop — step by step

The controller uses **controller-runtime** and follows the standard Kubernetes reconciler pattern. Every event (CR create/update, owned resource change, requeue timer) triggers a reconcile call. The function is fully **idempotent** — re-running it at any step produces the same result.

```
Reconcile(ctx, req)
     │
     ├── 1. Fetch Preview CR  (return nil if NotFound)
     │
     ├── 2. Deletion?  ──► handleDeletion()
     │         └── remove namespace, owned resources, then remove finalizer
     │
     ├── 3. Add finalizer if missing  (guarantees teardown runs on delete)
     │
     ├── 4. TTL expired?  ──► patch status Expired + r.Delete(preview)
     │
     ├── 5. Approval gate?  ──► return RequeueAfter=30s  (phase=Pending)
     │
     ├── 6. reconcileNamespace()     ──► create preview-pr-<N>
     │
     ├── 7. reconcileResourceQuota() ──► apply tier limits
     │
     ├── 8. reconcileDatabase()      ──► postgres Deployment + Service + Secret
     │         ├── wait DB ready (RequeueAfter=5s if not)
     │         ├── reconcileMigration() (optional Job)
     │         └── reconcileSeed()     (optional Job)
     │
     ├── 9. reconcileServices()      ──► one Deployment + Service per spec.services[]
     │
     ├── 10. reconcileIngress()      ──► nginx Ingress, path rules from pathPrefix
     │
     ├── 11. reconcileTelemetry()    ──► inject OTel annotation on pods
     │
     ├── 12. reconcileGitHub()       ──► Deployment status + PR comment (idempotent)
     │
     ├── 13. [phase = Running]
     │
     ├── 14. reconcileAIEnrichment() ──► (if enabled)
     │         └── see §7 for full detail
     │
     └── 15. reconcileTestSuite()    ──► (if enabled AND AI done or disabled)
               └── see §6 for full detail
```

### All Jobs created by the controller

The controller never runs long operations inline — it delegates every side-effectful operation to a **Kubernetes Job**, then re-enters the reconcile loop to check completion.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Job name                  │ Image         │ What it does                   │
├─────────────────────────────────────────────────────────────────────────────┤
│  postgres-migrate          │ app image     │ Alembic migration (optional)   │
│  postgres-seed             │ app image     │ static SQL seed (optional)     │
│                             │               │                                │
│  ── AI Enrichment ──────────┼───────────────┼──────────────────────────────│
│  ai-schema-dump            │ postgres:15   │ pg_dump --schema-only          │
│  ai-generate               │ python:3.11   │ call LLM → seed.sql + test.py  │
│  ai-seed                   │ postgres:15   │ psql seed.sql → inserts data   │
│  ai-tests                  │ python:3.11   │ pip install + python test.py   │
│                             │               │                                │
│  ── Test Suite ─────────────┼───────────────┼──────────────────────────────│
│  suite-checkpoint-save     │ postgres:15   │ pg_dump --data-only → ConfigMap│
│  smoke-tests               │ python:3.11   │ embedded smoke script          │
│  suite-restore-regression  │ postgres:15   │ TRUNCATE + psql replay         │
│  regression-tests          │ app image     │ tests/regression.py            │
│  suite-restore-e2e         │ postgres:15   │ TRUNCATE + psql replay         │
│  e2e-tests                 │ playwright    │ tests/e2e.py + Chromium        │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Status as the source of truth

The controller tracks all progress in `status` — persisted in etcd. If the operator pod restarts mid-pipeline, it resumes exactly where it left off by reading the status fields.

```bash
kubectl get preview pr-42 -o jsonpath='{.status}' | jq .
```

```json
{
  "phase": "Running",
  "url": "http://pr-42.preview.localtest.me:8080",
  "namespaceName": "preview-pr-42",
  "readyAt": "2026-05-08T09:00:00Z",
  "expiresAt": "2026-05-10T09:00:00Z",
  "database": {
    "ready": true,
    "host": "postgres",
    "databaseName": "appdb",
    "migration": "Succeeded",
    "seed": "Skipped"
  },
  "aiEnrichment": {
    "phase": "Succeeded",
    "seedStatus": "Succeeded",
    "testsStatus": "Succeeded",
    "completedAt": "2026-05-08T09:05:00Z"
  },
  "tests": {
    "phase": "Succeeded",
    "step": "e2e",
    "smoke":      { "phase": "Succeeded", "passed": 2, "failed": 0 },
    "regression": { "phase": "Succeeded", "passed": 9, "failed": 0 },
    "e2e":        { "phase": "Succeeded", "passed": 6, "failed": 0 }
  },
  "github": {
    "deploymentState": "success",
    "lastNotifiedPhase": "Running",
    "commentId": 987654321,
    "lastEnvironmentUrl": "http://pr-42.preview.localtest.me:8080"
  }
}
```

### Key controller invariants

| Invariant | Why |
|-----------|-----|
| All operations are idempotent | Re-running reconcile after a crash is safe |
| Jobs are looked up by name before creation | Prevents duplicate jobs |
| Status is written after every significant state change | Enables crash recovery |
| AI enrichment must complete before tests start | Tests need seeded data |
| `status.tests.step` is persisted in etcd | Pipeline resumes at exact step after restart |
| CRD schema must match Go types exactly | API server silently strips unknown fields — a mismatch causes infinite loops |

### Inspecting the pipeline

```bash
# Quick overview
kubectl get preview
# NAME    PHASE     BRANCH            TIER     URL                                    EXPIRES                AGE
# pr-42   Running   feature/my-feat   medium   http://pr-42.preview.localtest.me…    2026-05-10T09:00:00Z   2h

# Current pipeline step
kubectl get preview pr-42 -o jsonpath='{.status.tests.step}'

# Watch jobs being created
kubectl get jobs -n preview-pr-42 -w

# Diagnostics on failure
kubectl get preview pr-42 -o jsonpath='{.status.diagnostics}' | jq .
```

---

## 6. Test Suite Orchestration

### Why sequential, isolated, checkpoint-based

A classic shared staging environment has two fatal problems:

- **Cross-PR pollution** — two PRs running simultaneously share the database; test data from PR #28 corrupts the assertions of PR #29.
- **Unstable data** — staging accumulates data from previous runs; a test that expects 10 products may find 247.

The Preview controller solves both by giving each PR its own namespace + database, and by taking a **checkpoint** of the database immediately after the AI seed — then restoring to that checkpoint before every test suite, and again before every individual E2E test.

### Full pipeline chronology

```
                     ┌─────────────────────────────────────────────────────┐
                     │  Database state after AI seed                        │
                     │  10 products, 3 categories, reviews, orders          │
                     └───────────────┬─────────────────────────────────────┘
                                     │
                    ┌────────────────▼─────────────────────────────────────┐
                    │  Job: suite-checkpoint-save                           │
                    │  pg_dump --data-only → ConfigMap "db-checkpoint-      │
                    │  after-seed" in namespace preview-pr-<N>             │
                    └────────────────┬─────────────────────────────────────┘
                                     │
                    ┌────────────────▼─────────────────────────────────────┐
                    │  Job: smoke-tests                                     │
                    │  Image: python:3.11  (embedded smoke script)          │
                    │  APP_URL=http://svc-backend:8080                      │
                    │  Tests:                                               │
                    │    PASS smoke /healthz: 200                          │
                    │    PASS smoke /api/products: 200                     │
                    └────────────────┬─────────────────────────────────────┘
                                     │
                    ┌────────────────▼─────────────────────────────────────┐
                    │  Job: suite-restore-regression                        │
                    │  TRUNCATE all tables + psql replay from ConfigMap     │
                    │  → DB back to post-seed state                         │
                    └────────────────┬─────────────────────────────────────┘
                                     │
                    ┌────────────────▼─────────────────────────────────────┐
                    │  Job: regression-tests                                │
                    │  Image: app image                                     │
                    │  APP_URL=http://svc-backend:8080                      │
                    │  FRONTEND_URL=http://svc-frontend:3000                │
                    │  Script: /app/tests/regression.py                    │
                    │  Tests: 9 HTTP endpoint assertions                    │
                    └────────────────┬─────────────────────────────────────┘
                                     │
                    ┌────────────────▼─────────────────────────────────────┐
                    │  Job: suite-restore-e2e                               │
                    │  TRUNCATE + psql replay                               │
                    │  → DB back to post-seed state                         │
                    └────────────────┬─────────────────────────────────────┘
                                     │
                    ┌────────────────▼─────────────────────────────────────┐
                    │  Job: e2e-tests                                       │
                    │  Image: mcr.microsoft.com/playwright/python:v1.44.0  │
                    │  APP_URL=http://svc-frontend:3000                     │
                    │  FRONTEND_URL=http://svc-frontend:3000                │
                    │  CHECKPOINT_API=http://preview-extension:8090/…     │
                    │                                                       │
                    │  test_catalog_page_loads    ← reset_db() first       │
                    │  test_preview_badge_shown   ← reset_db() first       │
                    │  test_product_detail_panel  ← reset_db() first       │
                    │  test_related_section       ← reset_db() first       │
                    │  test_discount_filter       ← reset_db() first       │
                    │  test_close_detail          ← reset_db() first       │
                    └───────────────────────────────────────────────────────┘
```

### Two levels of database isolation

```
Level 1: between suites
  suite-restore-regression  ──► full TRUNCATE + replay before regression
  suite-restore-e2e         ──► full TRUNCATE + replay before E2E
  Reason: regression tests can create/delete products, change stock, create
          orders — any of that would break E2E assertions.

Level 2: between each E2E test
  reset_db() in tests/e2e.py ──► POST CHECKPOINT_API/restore before each test
  Reason: Playwright tests click, fill forms, navigate — a test that opens a
          detail panel changes page state for the next test.
```

### How reset_db() works in detail

```
e2e pod
  │
  ├── reset_db()  →  POST http://preview-extension/api/previews/pr-42/
  │                       checkpoints/after-seed/restore
  │
  │   Extension patches CR:
  │     spec.database.checkpointRestore = "after-seed"
  │
  │   Controller reconciles:
  │     ├── creates restore Job (TRUNCATE + psql replay from ConfigMap)
  │     ├── waits for Job completion
  │     └── clears spec.database.checkpointRestore
  │
  │   Extension returns HTTP 200
  │
  └── Playwright test starts  (DB is now identical to post-seed state)
```

### Controller — how it tracks test progress

The controller stores the current pipeline step in `status.tests.step`. Each reconcile call reads this field and creates the next job:

```
Reconcile() → reads status.tests.step
  ""                   → set step="saving", create pg_dump job
  "saving"             → pg_dump job complete? → set step="smoke"
  "smoke"              → smoke job complete?   → set step="restore-regression"
  "restore-regression" → restore complete?     → set step="regression"
  "regression"         → regression complete?  → set step="restore-e2e"
  "restore-e2e"        → restore complete?     → set step="e2e"
  "e2e"                → e2e complete?         → set tests.phase="Succeeded"
                          job still running    → RequeueAfter=10s
```

If a job is running, the controller returns `RequeueAfter=10s` and exits — it does not block the goroutine. The next reconcile checks job status again. This loop continues until the job finishes or fails.

### Reading test results

```bash
# Summary
kubectl get preview pr-42 -o jsonpath='{.status.tests}' | jq .

# Per-suite
kubectl get preview pr-42 -o jsonpath='{.status.tests.smoke}'
kubectl get preview pr-42 -o jsonpath='{.status.tests.regression}'
kubectl get preview pr-42 -o jsonpath='{.status.tests.e2e}'

# Live logs during execution
kubectl logs -n preview-pr-42 job/smoke-tests -f
kubectl logs -n preview-pr-42 job/regression-tests -f
kubectl logs -n preview-pr-42 job/e2e-tests -f
```

### PR comment produced automatically

```
## Preview Test Suite Results

**Overall: ✅ Succeeded**

| Suite      | Status       | Passed | Failed |
|------------|--------------|--------|--------|
| Smoke      | ✅ Succeeded | 2      | 0      |
| Regression | ✅ Succeeded | 9      | 0      |
| E2E        | ✅ Succeeded | 6      | 0      |
```

### What each test validates

| Suite | Script | Target | Validates |
|-------|--------|--------|-----------|
| Smoke | embedded in operator | `svc-backend:8080` | Deployment is healthy — `/healthz` 200, `/api/products` 200 |
| Regression | `tests/regression.py` | `svc-backend:8080` | All existing endpoints return correct status + response structure on a real DB |
| E2E | `tests/e2e.py` | `svc-frontend:3000` | Full user flows: browse catalogue, open product detail, related products, discount filter, close panel |

---

## 7. AI Enrichment Orchestration

### Why before tests

The AI seed job inserts realistic product data — names, descriptions, prices, discounts, reviews. The regression and E2E tests depend on this data being present. The controller therefore **blocks the test suite until AI enrichment is Succeeded or Failed** (in which case tests run on an empty or partially seeded DB, which is still better than running before the seed).

```go
// controller logic — tests.go
if aiEnrichmentEnabled(preview) {
    aiPhase := preview.Status.AIEnrichment.Phase
    if aiPhase != "Succeeded" && aiPhase != "Failed" {
        return ctrl.Result{RequeueAfter: 10 * time.Second}, nil
    }
}
// only reaches here when AI is done
reconcileTestSuite(...)
```

### Full AI enrichment pipeline

```
Preview reaches Running phase
           │
           ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Job: ai-schema-dump                                                 │
│  Image: postgres:15                                                  │
│  pg_dump --schema-only → stored in ConfigMap "ai-schema"            │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
           ┌────────────────────▼─────────────────────────────────────┐
           │  Controller: fetch PR diff via GitHub API                 │
           │  GET /repos/{owner}/{repo}/pulls/{prNumber}/files        │
           └────────────────────┬─────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────┐
│  Job: ai-generate                                                    │
│  Image: python:3.11                                                  │
│                                                                      │
│  Prompt includes:                                                    │
│    - DB schema (from ConfigMap)                                      │
│    - PR diff (lines changed)                                         │
│    - system prompt (from operator config or @preview set-prompt)   │
│                                                                      │
│  LLM produces:                                                       │
│    seed.sql  → INSERT INTO categories…; INSERT INTO products…;      │
│               At least 10 products across 3 categories,             │
│               2 reviews per product (varied 1–5 ★ ratings)          │
│    test.py   → Integration tests targeting the modified code paths  │
│                (same PASS/FAIL format as regression.py)              │
│                                                                      │
│  Both files written to ConfigMap "ai-artifacts"                     │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
           ┌────────────────────▼─────────────────────────────────────┐
           │  Job: ai-seed                                             │
           │  Image: postgres:15                                       │
           │  psql seed.sql → inserts products, categories, reviews   │
           └────────────────────┬─────────────────────────────────────┘
                                │
           ┌────────────────────▼─────────────────────────────────────┐
           │  Job: ai-tests                                            │
           │  Image: python:3.11                                       │
           │  pip install requests && python test.py                   │
           │  APP_URL=http://svc-backend:8080                          │
           └────────────────────┬─────────────────────────────────────┘
                                │
                    status.aiEnrichment.phase = Succeeded / Failed
                    Results posted to PR comment
                                │
                                ▼
                    Test suite unblocked (§6)
```

### Enable in CR

```yaml
spec:
  aiEnrichment:
    enabled: true
    apiSecretRef:
      name: ai-api-key
      key: api-key
    model: gpt-4o-mini       # optional, default gpt-4o-mini
    seed:
      enabled: true          # optional, default true
    tests:
      enabled: true          # optional, default true
```

### AI provider options

| Provider | API URL | Secret |
|----------|---------|--------|
| OpenAI (default) | `https://api.openai.com/v1` | `sk-…` PAT |
| GitHub Models (free) | `https://models.inference.ai.azure.com` | GitHub PAT |
| Azure OpenAI | `https://<resource>.openai.azure.com/openai` | Azure API key |

For any non-OpenAI provider, set `AI_API_URL`:

```bash
kubectl set env deployment/preview-operator \
  AI_API_URL=https://models.inference.ai.azure.com \
  -n preview-operator-system
```

### Trigger an AI-only rerun

Use this when you change the AI prompt, the operator image, or want fresh data without rerunning the full workflow:

```bash
# Via Copilot Extension
@preview retest-ai pr-42

# Via kubectl
kubectl patch preview pr-42 --type=merge \
  -p='{"spec":{"aiEnrichment":{"rerunRequested":true}}}'
```

The controller:
1. Deletes the `ai-artifacts` ConfigMap
2. Re-runs the 4-step AI pipeline (schema-dump → generate → seed → tests)
3. Skips smoke / regression / E2E for this cycle
4. Posts updated results to the PR

### Per-environment prompt override

```bash
@preview set-prompt pr-42 "Generate products for a luxury watchmaker. Include Swiss brands, price range €500–€10000, at least 3 watch complications."
@preview retest-ai pr-42
```

### AI test format

The AI uses `tests/example_test.py` as a template — 18 integration tests covering the full API surface. Generated `test.py` files follow the same `PASS/FAIL` line format so the controller can parse results consistently.

---

## 8. GitHub Integration

The operator calls the GitHub API directly from its reconciliation loop — no external webhook, no polling service.

### Phase → GitHub state mapping

```
┌──────────────────┬──────────────────────┬─────────────────────────────────────┐
│ Preview phase   │ GitHub Deployment    │ PR comment                          │
├──────────────────┼──────────────────────┼─────────────────────────────────────┤
│ Pending          │ queued               │ —                                   │
│ Provisioning     │ in_progress          │ 🔄 Provisioning en cours…           │
│ Running          │ success + URL        │ ## Preview Preview Ready           │
│                  │                      │ URL + DB evidence + test results    │
│ Failed           │ failure              │ ## Preview Preview Failed          │
│                  │                      │ diagnostics + pod logs              │
│ Terminating      │ inactive             │ — (posted by cleanup.yaml)          │
└──────────────────┴──────────────────────┴─────────────────────────────────────┘
```

### Idempotence

Before every GitHub API call, the controller checks `status.github.deploymentState`, `lastNotifiedPhase`, and `commentId`. If the state was already written → zero API call, even across 100 reconcile loops. The PR comment is updated in-place (same `commentId`) rather than creating a new comment each time.

```bash
kubectl get preview pr-42 -o jsonpath='{.status.github}' | jq .
kubectl get preview pr-42 -o jsonpath='{.status.github.lastError}'
```

### Accessing the preview

```bash
# Port-forward ingress (required for Kind)
kubectl port-forward -n ingress-nginx svc/ingress-nginx-controller 8080:80

# Preview URL printed in the PR comment:
http://pr-<NUMBER>.preview.localtest.me:8080

# Jaeger traces
kubectl port-forward -n observability svc/jaeger 16686:16686
# Open http://localhost:16686 → service: idp-preview-pr-42
```

> **WSL2:** run the port-forward inside WSL2. Windows browsers reach `localhost:8080` via WSL2 localhost forwarding.

---

## 9. Copilot Extension

Manage preview environments from GitHub Copilot Chat in VS Code — no `kubectl` needed.

### Available commands

| Command | Description |
|---|---|
| `@preview list` | List all active environments |
| `@preview status pr-42` | Phase, URL, DB state, TTL remaining |
| `@preview logs pr-42` | Last 40 lines from the app pod |
| `@preview extend pr-42 24h` | Extend TTL |
| `@preview wake pr-42` | Restart a scaled-down environment |
| `@preview reset-db pr-42` | Delete + re-run migration and seed |
| `@preview run-sql pr-42 <sql>` | Execute arbitrary SQL on the preview DB |
| `@preview retest-ai pr-42` | Trigger AI-only rerun |
| `@preview set-prompt pr-42 <text>` | Set custom AI instructions |
| `@preview show-prompt pr-42` | Show current AI prompt |
| `@preview help` | Show all commands |

### `run-sql` examples

```
# Inspect
@preview run-sql pr-42 SELECT COUNT(*) FROM products;
@preview run-sql pr-42 SELECT p.name, AVG(r.rating) FROM products p LEFT JOIN reviews r ON r.product_id = p.id GROUP BY p.name;

# Modify schema
@preview run-sql pr-42 ALTER TABLE products ADD COLUMN featured BOOLEAN DEFAULT false;

# Insert test data
@preview run-sql pr-42 INSERT INTO products (name, price, stock) VALUES ('Test', 9.99, 10);

# Reset
@preview run-sql pr-42 TRUNCATE orders RESTART IDENTITY CASCADE;
```

### Deploy the extension

```bash
kubectl apply -f config/extension/rbac.yaml
kubectl apply -f config/extension/deployment.yaml
kubectl -n preview-operator-system rollout status deployment/preview-extension --timeout=60s

# Expose for local Kind
kubectl port-forward -n preview-operator-system svc/preview-extension 8090:8090 &
ngrok http 8090
# Copy the HTTPS URL → paste as webhook URL in your GitHub App settings
```

---

## 10. Application Reference

### Services

| Service | File | Port | Ingress path | Role |
|---------|------|------|--------------|------|
| `backend` | `app.py` | `8080` | `/api` | REST API + DB init |
| `frontend` | `frontend.py` | `3000` | `/` | SPA + `/api` proxy to backend |

Both built from the **same Docker image**. The entrypoint is selected via `APP_MODE`:

```bash
docker run -e DATABASE_URL=... image              # → app.py (backend)
docker run -e APP_MODE=frontend -e ... image      # → frontend.py (frontend)
```

The frontend proxies `/api/*` requests to the backend via a Flask route — so `fetch('/api/products')` in the browser works correctly inside the cluster without touching the ingress.

### Database schema

```sql
categories (id SERIAL, name TEXT, slug TEXT)
products   (id SERIAL, name TEXT, description TEXT, category_id INT,
            price NUMERIC, stock INT, discount_pct NUMERIC, created_at TIMESTAMP)
reviews    (id SERIAL, product_id INT, author TEXT, rating INT CHECK(1..5),
            comment TEXT, created_at TIMESTAMP)
orders     (id SERIAL, product_id INT, quantity INT, status TEXT, created_at TIMESTAMP)
```

The backend calls `init_db()` on startup (`CREATE TABLE IF NOT EXISTS`) — restarts are safe.

### Backend REST API (`app.py`)

| Route | Method | Returns |
|-------|--------|---------|
| `/healthz` | GET | `ok` |
| `/api/products` | GET | last 50 products with ratings |
| `/api/products` | POST | create product → 201 |
| `/api/products/<id>` | GET | product + reviews → 200 / 404 |
| `/api/products/<id>` | DELETE | 204 / 404 |
| `/api/products/discounted?min_discount=N` | GET | `{"count":N,"products":[…]}` |
| `/api/products/<id>/related` | GET | `{"count":N,"products":[…]}` |
| `/api/products/<id>/reviews` | GET/POST | reviews |
| `/api/categories` | GET/POST | categories |
| `/api/orders` | GET/POST | orders (409 if insufficient stock) |
| `/api/stats` | GET | totals, avg rating, out-of-stock |
| `/api/seeded-data` | GET | full DB dump for AI enrichment UI |

### Frontend features (`frontend.py`)

| Feature | `data-testid` attribute | Used by |
|---------|------------------------|---------|
| Product grid | `product-grid` | E2E |
| Product card | `product-card` | E2E |
| Discount badge | `product-discount` | E2E |
| Detail side panel | `product-detail` | E2E |
| Detail name | `detail-name` | E2E |
| Detail price | `detail-price` | E2E |
| Related products section | `related-section` | E2E |
| Close button | `close-detail` | E2E |
| Overlay background | `detail-overlay` | E2E |
| Discount filter input | `discount-input` | E2E |
| Discount filter apply | `discount-apply` | E2E |
| Preview badge | `preview-badge` | E2E |

### File map

| File | Role |
|------|------|
| `app.py` | Backend — REST API, DB init |
| `frontend.py` | Frontend — SPA, `/api` proxy |
| `Dockerfile` | Single image, `APP_MODE=frontend` switches entrypoint |
| `tests/regression.py` | 9 endpoint regression tests |
| `tests/e2e.py` | 6 Playwright E2E tests |
| `tests/example_test.py` | 18-test template used by AI to generate `test.py` |
| `.github/workflows/preview.yaml` | CI: build → deploy Preview CR |
| `.github/workflows/cleanup.yaml` | CI: delete Preview CR on PR close |

---

## 11. Troubleshooting

### Runner token expired

Symptom: runner pod is running but shows `Listening for Jobs` then reconnects every few minutes, or jobs never start.

```bash
NEW_TOKEN=$(gh api -X POST repos/<OWNER>/<REPO>/actions/runners/registration-token --jq '.token')
kubectl set env deployment/github-runner -n github-runner RUNNER_TOKEN="$NEW_TOKEN"
kubectl rollout restart deployment/github-runner -n github-runner
kubectl logs -n github-runner deployment/github-runner --tail=5
# Expected: "Listening for Jobs"
```

### Kaniko job hangs on image push

Symptom: workflow times out at `kubectl wait job/kaniko-…`, pod logs show only `Pushing image to ghcr.io/…`.

Cause: `PREVIEW_GITHUB_TOKEN` secret missing or lacks `write:packages`.

```bash
gh secret set PREVIEW_GITHUB_TOKEN --repo <OWNER>/<REPO> --body "<PAT>"
git commit --allow-empty -m "ci: retrigger" && git push
```

### Infinite reconcile loop every 2 seconds

Cause: the CRD schema is missing a field that the controller writes to `status` — the API server silently strips it on every write, so the field never persists, causing the controller to keep trying.

Fix: always apply the CRD **before** helm upgrade.

```bash
helm show crds oci://ghcr.io/ihsenalaya/charts/preview-operator --version 0.13.8 \
  | tail -n +3 | kubectl apply -f -
helm upgrade preview-operator oci://ghcr.io/ihsenalaya/charts/preview-operator \
  --version 0.13.8 --namespace preview-operator-system
```

### Preview stuck in Provisioning

```bash
kubectl describe preview pr-<N>
kubectl get events -n preview-pr-<N> --sort-by='.lastTimestamp'
```

### Preview Failed — x509 webhook error

Symptom: `failed calling webhook "validate.nginx.ingress.kubernetes.io": x509: certificate signed by unknown authority`

```bash
kubectl delete validatingwebhookconfiguration ingress-nginx-admission --ignore-not-found
helm upgrade ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --set controller.admissionWebhooks.enabled=false --wait
kubectl delete preview pr-<N> --ignore-not-found
git commit --allow-empty -m "ci: retrigger" && git push
```

### Preview Failed — read diagnostics

```bash
kubectl get preview pr-<N> -o jsonpath='{.status.diagnostics}' | jq .
# .podLogs      → last 30 lines of the crashed app container
# .lastEvents   → recent Warning events from the namespace
# .debugCommands → kubectl commands for further investigation
```

### No traces in Jaeger

```bash
kubectl get pod -n preview-pr-<N> -l app=preview-preview \
  -o jsonpath='{.items[0].metadata.annotations}' | grep instrumentation
# Expected: "instrumentation.opentelemetry.io/inject-python": "observability/python"
```

### Helm chart version not found

```bash
helm repo update
# Then omit --version to use the latest available release
```

---

## Installed components

| Component | Namespace | Version | Notes |
|-----------|-----------|---------|-------|
| cert-manager | `cert-manager` | v1.20.2 | |
| ingress-nginx | `ingress-nginx` | latest | `admissionWebhooks.enabled=false` required |
| Preview Operator | `preview-operator-system` | **0.13.8** | Multi-service, sequential test pipeline, AI enrichment, checkpoint restore |
| OpenTelemetry Operator | `opentelemetry-operator-system` | latest | |
| Jaeger (all-in-one) | `observability` | 1.67.0 | |
| OTel Collector + Instrumentation | `observability` | 0.149.0 | |
| GitHub Runner | `github-runner` | `myoung34/github-runner:latest` | `EPHEMERAL=false` |
| Preview Extension | `preview-operator-system` | **0.13.8** | Copilot commands + checkpoint API |
