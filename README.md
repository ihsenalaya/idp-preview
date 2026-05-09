# idp-preview — Preview Platform

Demo application and reference implementation for the **Preview Operator** — a Kubernetes controller that turns every pull request into a fully isolated preview environment, complete with its own PostgreSQL database, ingress URL, full test pipeline, AI-generated seed data, distributed traces, and automated failure analysis via kagent.

---

## Table of Contents

1. [Architecture](#1-architecture)
2. [Prerequisites](#2-prerequisites)
3. [AKS Cluster Installation](#3-aks-cluster-installation)
4. [GitHub Actions Runner Setup](#4-github-actions-runner-setup)
5. [The Preview Custom Resource](#5-the-preview-custom-resource)
6. [Test Suite](#6-test-suite)
7. [Contract Testing with Microcks](#7-contract-testing-with-microcks)
8. [AI Enrichment](#8-ai-enrichment)
9. [kagent — Automated Failure Analysis](#9-kagent--automated-failure-analysis)
10. [Distributed Tracing with Jaeger](#10-distributed-tracing-with-jaeger)
11. [GitHub Integration](#11-github-integration)
12. [Application Reference](#12-application-reference)
13. [Troubleshooting](#13-troubleshooting)

---

## 1. Architecture

```
Pull Request opened
       │
       ▼
GitHub Actions (self-hosted, AKS)
  ├── Kaniko builds & pushes image → ghcr.io
  ├── Imports OpenAPI spec → Microcks
  └── Applies Preview CR
             │
             ▼
    Preview Operator (preview-operator-system)
      ├── Creates namespace preview-pr-<N>
      ├── Deploys backend + frontend services
      ├── Provisions PostgreSQL sidecar
      ├── Creates ingress (pr-<N>.preview.localtest.me)
      └── Orchestrates test pipeline:
            smoke → contract (Microcks) → regression → e2e (Playwright)
                        │
                        ▼ on failure
              kagent (preview-troubleshooter-agent)
                ├── Inspects K8s resources
                ├── Queries Jaeger traces
                └── Posts AI analysis → GitHub PR comment
```

**Key components:**

| Component | Namespace | Role |
|-----------|-----------|------|
| preview-operator | preview-operator-system | Reconciles Preview CRs |
| GitHub Actions runner | github-runner | Runs CI workflows on AKS |
| Microcks | microcks | OpenAPI contract validation |
| Jaeger | observability | Distributed trace storage |
| kagent | kagent-system | AI-powered K8s agent (Google ADK) |
| Jaeger MCP Server | kagent-system | Exposes Jaeger traces as MCP tools |

---

## 2. Prerequisites

- AKS cluster (tested with `preview-cluster`, resource group `kubebuilder`)
- `kubectl` configured against the cluster
- `helm` v3+
- `gh` CLI authenticated
- GHCR package set to **public** (or configure pull secrets)
- Azure OpenAI resource (for AI enrichment and kagent LLM)

---

## 3. AKS Cluster Installation

### 3.1 Preview Operator

```bash
helm upgrade --install preview-operator \
  oci://ghcr.io/ihsenalaya/charts/preview-operator \
  --version 1.0.5 \
  --namespace preview-operator-system \
  --create-namespace
```

Create the GitHub token secret (used by the operator to post PR comments):

```bash
kubectl create secret generic preview-github-token \
  --namespace=preview-operator-system \
  --from-literal=token=<your-github-pat>
```

### 3.2 Microcks

```bash
helm repo add microcks https://microcks.io/helm
helm upgrade --install microcks microcks/microcks \
  --namespace microcks --create-namespace \
  --set microcks.url=microcks.<ingress-ip>.nip.io \
  --set keycloak.url=keycloak.<ingress-ip>.nip.io
```

### 3.3 Jaeger (OpenTelemetry)

```bash
kubectl apply -f otel.yaml       # OpenTelemetry Collector
kubectl apply -f jaeger.yaml     # Jaeger all-in-one
```

### 3.4 kagent

```bash
helm repo add kagent https://kagent-dev.github.io/kagent/helm
helm upgrade --install kagent kagent/kagent \
  --namespace kagent-system --create-namespace \
  --set providers.azure.endpoint=https://<your-aoai>.openai.azure.com \
  --set providers.azure.deployment=gpt-4o-mini \
  --set providers.azure.apiVersion=2024-10-21
```

Create the Azure OpenAI API key secret (strip any trailing whitespace):

```bash
kubectl create secret generic kagent-openai \
  --namespace=kagent-system \
  --from-literal=OPENAI_API_KEY=<your-azure-openai-key>
```

Deploy the preview troubleshooter agent and Jaeger MCP server:

```bash
kubectl apply -f k8s/kagent/
```

---

## 4. GitHub Actions Runner Setup

```bash
# Create runner namespace
kubectl apply -f runner.yaml

# Create GHCR pull secret for the runner
kubectl create secret docker-registry ghcr-pull-secret \
  --namespace=github-runner \
  --docker-server=ghcr.io \
  --docker-username=<github-user> \
  --docker-password=<github-pat>
```

The runner is registered as `self-hosted, aks` and picked up by the `preview.yaml` workflow.

---

## 5. The Preview Custom Resource

The workflow applies a `Preview` CR that drives the entire lifecycle:

```yaml
apiVersion: platform.company.io/v1alpha1
kind: Preview
metadata:
  name: pr-<N>
spec:
  branch: <branch>
  prNumber: <N>
  image: ghcr.io/<repo>:<sha>
  resourceTier: medium
  ttl: 48h
  services:
    - name: backend
      port: 8080
      pathPrefix: /api
    - name: frontend
      port: 3000
      pathPrefix: /
  database:
    enabled: true
    databaseName: appdb
  telemetry:
    enabled: true
    serviceName: idp-testing
    autoInstrumentation:
      language: python
      instrumentationRef: observability/python
  testSuite:
    enabled: true
    smoke: {}
    contractTesting:
      enabled: true
      microcksURL: http://microcks.microcks.svc.cluster.local:8080
      apiName: Preview Catalog API
      apiVersion: "1.0.0"
    regression:
      enabled: true
    e2e:
      enabled: true
  aiEnrichment:
    enabled: true
    apiSecretRef:
      name: ai-api-key
      key: api-key
    model: gpt-4o-mini
  kagent:
    enabled: true
    namespace: kagent-system
    agentName: preview-troubleshooter-agent
  github:
    enabled: true
    owner: <owner>
    repo: <repo>
    deploymentId: <id>
    environment: pr-<N>
    commentOnReady: true
    tokenSecretRef:
      name: preview-github-token
      namespace: preview-operator-system
      key: token
```

---

## 6. Test Suite

The operator runs tests sequentially after the preview environment is ready:

| Suite | Runner | What it tests |
|-------|--------|---------------|
| **Smoke** | requests | `/healthz` + `/api/products` — basic liveness |
| **Contract** | Microcks OPEN_API_SCHEMA | All API endpoints validated against `api/openapi.yaml` |
| **Regression** | requests | Full HTTP API coverage (9 tests) |
| **E2E** | Playwright (Chromium) | Browser UI — product grid, filters, detail panel |

Results are posted as a GitHub PR comment by the operator.

---

## 7. Contract Testing with Microcks

The `api/openapi.yaml` file defines the contract for `Preview Catalog API v1.0.0`.

The workflow **imports this spec into Microcks** at the start of every run so the contract is always up-to-date. Microcks then validates every API endpoint response schema against the spec using `OPEN_API_SCHEMA` runner.

The operator submits the test to Microcks via:
```
POST /api/tests
{
  "serviceId": "Preview Catalog API:1.0.0",
  "testEndpoint": "http://svc-backend:8080",
  "runnerType": "OPEN_API_SCHEMA"
}
```

---

## 8. AI Enrichment

When the preview starts, the operator calls Azure OpenAI to:
1. Analyze the PR diff
2. Generate SQL seed data matching the schema
3. Generate a regression test script for the modified endpoints

The seed data is inserted into PostgreSQL before tests run. Results appear in the operator status and the GitHub PR comment.

Configure via the `ai-api-key` secret in `preview-operator-system`:

```bash
kubectl create secret generic ai-api-key \
  --namespace=preview-operator-system \
  --from-literal=api-key=<azure-openai-key>
```

---

## 9. kagent — Automated Failure Analysis

When any test suite fails, the operator automatically calls the `preview-troubleshooter-agent` via the **A2A JSON-RPC protocol** (kagent v0.9+).

The agent:
1. Inspects pods, jobs, and events in the preview namespace
2. Queries Jaeger for error traces (via the Jaeger MCP server)
3. Synthesizes an analysis with root cause and suggested fix
4. Posts it as a **GitHub PR comment** (`## AI Failure Analysis by kagent`)

### Jaeger MCP Server

A custom Python MCP server (`jaeger-mcp-server`) exposes three tools to the agent:

| Tool | Description |
|------|-------------|
| `jaeger_get_services` | Lists services with traces in Jaeger |
| `jaeger_get_traces` | Gets traces for a service, filterable by `error=true` |
| `jaeger_get_trace` | Full span tree for a specific trace ID |

The server is deployed in `kagent-system` and registered as a `RemoteMCPServer` with SSE transport.

### Agent Flow

```
Operator detects test failure
       │
       ▼
POST http://preview-troubleshooter-agent.kagent-system:8080
     (A2A JSON-RPC, method: message/send)
       │
       ▼
Agent (Google ADK + Azure OpenAI gpt-4o-mini)
  ├── kubectl get pods/jobs/events -n preview-pr-<N>
  ├── kubectl logs <failed-job> -n preview-pr-<N>
  ├── jaeger_get_services
  ├── jaeger_get_traces(service=idp-testing, tags=error=true)
  └── jaeger_get_trace(<trace-id>)
       │
       ▼
GitHub PR comment: "## AI Failure Analysis by kagent"
```

---

## 10. Distributed Tracing with Jaeger

The application is auto-instrumented via OpenTelemetry. Traces are collected by the OTel Collector and stored in Jaeger.

Access Jaeger UI:
```bash
kubectl port-forward -n observability svc/jaeger 16686:16686
# Open http://localhost:16686
```

Service name: `idp-testing`

---

## 11. GitHub Integration

The operator posts three types of GitHub comments:

| Event | Comment |
|-------|---------|
| Preview ready | Environment URL + deployment status |
| Tests complete | Full test suite results (smoke / contract / regression / e2e) |
| Tests failed | kagent AI failure analysis |

GitHub Deployment status is updated to `success` once the environment is ready.

---

## 12. Application Reference

The demo app (`idp-testing`) exposes:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/healthz` | Health check |
| GET | `/api/products` | List products |
| POST | `/api/products` | Create product |
| GET | `/api/products/{id}` | Get product detail |
| DELETE | `/api/products/{id}` | Delete product |
| GET | `/api/products/discounted` | Products with discount ≥ min_discount |
| GET | `/api/products/{id}/related` | Related products (same category) |
| GET | `/api/products/{id}/reviews` | List reviews |
| POST | `/api/products/{id}/reviews` | Create review |
| POST | `/api/orders` | Create order |
| GET | `/api/orders` | List orders |
| GET | `/api/categories` | List categories |
| POST | `/api/categories` | Create category |
| GET | `/api/stats` | Catalog statistics |

Full contract: [`api/openapi.yaml`](api/openapi.yaml)

---

## 13. Troubleshooting

### Preview stuck in Provisioning

```bash
kubectl describe preview pr-<N>
kubectl get events -n preview-pr-<N> --sort-by=.lastTimestamp
```

### Test job failed

```bash
kubectl get jobs -n preview-pr-<N>
kubectl logs job/smoke-tests -n preview-pr-<N>
kubectl logs job/microcks-contract-tests -n preview-pr-<N>
kubectl logs job/regression-tests -n preview-pr-<N>
kubectl logs job/e2e-tests -n preview-pr-<N>
```

### kagent not posting analysis

```bash
# Check agent is reachable
kubectl get pod -n kagent-system -l app.kubernetes.io/name=preview-troubleshooter-agent

# Check API key has no trailing whitespace
kubectl get secret kagent-openai -n kagent-system -o jsonpath='{.data.OPENAI_API_KEY}' | base64 -d | cat -A

# Recreate secret if needed (strip whitespace)
KEY=$(kubectl get secret kagent-openai -n kagent-system -o jsonpath='{.data.OPENAI_API_KEY}' | base64 -d | tr -d '\r\n')
kubectl create secret generic kagent-openai -n kagent-system --from-literal=OPENAI_API_KEY="$KEY" --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart deployment/preview-troubleshooter-agent -n kagent-system
```

### Microcks 0 tests

The workflow imports the OpenAPI spec at the start of each run. If the import fails:

```bash
# Check Microcks has the API registered
curl -s http://microcks.<ip>.nip.io/api/services | jq '.[] | .name'

# Re-run the import manually
kubectl run microcks-import --namespace=microcks --image=python:3.11-slim \
  --restart=Never --rm -i --command -- python3 << 'EOF'
# ... (see workflow step)
EOF
```

### Operator logs

```bash
kubectl logs -n preview-operator-system deployment/preview-operator --tail=100
```
