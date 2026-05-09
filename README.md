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
│    ├── Expose               VirtualService (Istio) or Nginx Ingress (auto-detected)│
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
│          step 3: microcks-import           ──► upload openapi.yaml (non-blocking)│
│          step 4: microcks-contract-tests   ──► OPEN_API_SCHEMA validation     │
│          step 5: suite-restore-regression  ──► TRUNCATE + psql replay         │
│          step 6: regression-tests          ──► tests/regression.py            │
│          step 7: suite-restore-e2e         ──► TRUNCATE + psql replay         │
│          step 8: e2e-tests (Playwright)    ──► tests/e2e.py                   │
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
│     ├── VirtualService/Ingress        │  pr-1.preview.ihsenalaya.xyz
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
helm repo add microcks       https://microcks.io/helm
helm repo update
```

### Step 1 — Create the AKS cluster

```bash
# Créer le resource group et le cluster AKS (ajuster --location si besoin)
az group create --name <YOUR_RG> --location francecentral

az aks create \
  --resource-group <YOUR_RG> \
  --name <YOUR_CLUSTER> \
  --node-count 2 \
  --node-vm-size Standard_D4s_v3 \
  --generate-ssh-keys

# Récupérer les credentials
az aks get-credentials --resource-group <YOUR_RG> --name <YOUR_CLUSTER>
```

> **WSL/Windows :** `az aks get-credentials` écrit dans `C:\Users\<USER>\.kube\config`, pas dans `~/.kube/config`.
> Fusionner manuellement vers WSL :
> ```bash
> KUBECONFIG=/mnt/c/Users/<USER>/.kube/config \
>   kubectl config view --minify --context <YOUR_CLUSTER> --raw \
>   > ~/.kube/<YOUR_CLUSTER>.yaml
> export KUBECONFIG=~/.kube/<YOUR_CLUSTER>.yaml
> # Ajouter à ~/.bashrc pour persistance
> ```

```bash
kubectl get nodes
# NAME                                STATUS   ROLES   AGE   VERSION
# aks-nodepool1-XXXXXXXX-vmss000000   Ready    agent   …     v1.32.x
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

### Step 3 — Install ingress-nginx (fallback without Istio)

> Skip this step if you are using Istio (Step 3b). The operator auto-detects which is available.

**Important:** disable admission webhooks in Kind clusters (webhook cert is self-signed):

```bash
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --create-namespace \
  --set controller.admissionWebhooks.enabled=false \
  --wait

kubectl -n ingress-nginx rollout status deployment/ingress-nginx-controller --timeout=120s
```

### Step 3b — Install Istio (recommended for production / AKS)

Istio provides public URLs without port-forwarding via a shared wildcard DNS entry.

```bash
# Download istioctl
# ⚠️  /usr/local/bin nécessite sudo sur WSL — utiliser ~/bin à la place
mkdir -p ~/bin
curl -sL "https://github.com/istio/istio/releases/download/1.23.0/istioctl-1.23.0-linux-amd64.tar.gz" \
  | tar -xz -C ~/bin
export PATH="$HOME/bin:$PATH"   # ajouter à ~/.bashrc pour persistance

# Install Istio with ingress gateway
istioctl install --set profile=minimal \
  --set components.ingressGateways[0].enabled=true \
  --set components.ingressGateways[0].name=istio-ingressgateway \
  -y

# Attendre l'attribution de l'IP externe (AKS peut prendre 2-3 min)
kubectl get svc istio-ingressgateway -n istio-system --watch
# Arrêter quand EXTERNAL-IP n'est plus <pending>

ISTIO_IP=$(kubectl get svc istio-ingressgateway -n istio-system \
  -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo "Istio IP: $ISTIO_IP"   # vérifier que la valeur n'est pas vide

# Create wildcard DNS record in Azure DNS
az network dns record-set a add-record \
  --zone-name <YOUR_ZONE>   \
  --resource-group <YOUR_RG> \
  --record-set-name "*.preview" \
  --ipv4-address "$ISTIO_IP" \
  --ttl 300

# Create the shared gateway (one per cluster)
kubectl apply -f - <<EOF
apiVersion: networking.istio.io/v1beta1
kind: Gateway
metadata:
  name: preview-gateway
  namespace: istio-system
spec:
  selector:
    istio: ingressgateway
  servers:
    - port:
        number: 80
        name: http
        protocol: HTTP
      hosts:
        - "*.preview.<YOUR_ZONE>"
EOF
```

Then install the operator with `--set previewDomain=preview.<YOUR_ZONE>` (Step 4).

### Step 4 — Install the Preview Operator

Sur AKS, l'image est tirée depuis GHCR — pas besoin de `docker build` ni de `kind load`.

```bash
# Récupérer le chart depuis GHCR (version publiée)
helm install preview-operator oci://ghcr.io/ihsenalaya/preview-operator/helm/preview-operator \
  --version 1.0.21 \
  --namespace preview-operator-system \
  --create-namespace \
  --set image.tag=1.0.21 \
  --set previewDomain=preview.<YOUR_ZONE>

# OU depuis le chart local (si vous avez cloné le repo preview-operator)
# Appliquer d'abord le CRD (Helm ne met pas à jour les CRDs sur helm upgrade)
kubectl apply -f charts/preview-operator/crds/platform.company.io_previews.yaml

helm install preview-operator ./charts/preview-operator \
  --namespace preview-operator-system \
  --create-namespace \
  --set image.tag=1.0.21 \
  --set previewDomain=preview.<YOUR_ZONE>

kubectl -n preview-operator-system rollout status deployment/preview-operator --timeout=120s
kubectl get crd previews.platform.company.io
```

> **`ai.apiURL` :** ne pas mettre l'URL complète du déploiement — mettre uniquement l'endpoint de base.
> L'opérateur ajoute lui-même `/openai/deployments/<model>/chat/completions`.
> L'URL correcte est définie via la variable d'environnement `AI_API_URL` (voir Step 7.5).

#### Upgrading the operator

```bash
# Appliquer le CRD mis à jour (Helm ne met pas à jour les CRDs automatiquement)
kubectl apply -f charts/preview-operator/crds/platform.company.io_previews.yaml

helm upgrade preview-operator oci://ghcr.io/ihsenalaya/preview-operator/helm/preview-operator \
  --version <NEW_VERSION> \
  --namespace preview-operator-system \
  --reuse-values \
  --set image.tag=<NEW_VERSION>

kubectl -n preview-operator-system rollout status deployment/preview-operator --timeout=120s
```

### Step 4b — Install Microcks

Microcks provides in-cluster OpenAPI contract testing.

```bash
# Sur AKS — utiliser l'IP du LoadBalancer Istio ou un NodePort
# L'opérateur communique avec Microcks en intra-cluster : pas d'ingress requis
helm install microcks microcks/microcks \
  --namespace microcks \
  --create-namespace \
  --set "microcks.url=microcks.microcks.svc.cluster.local" \
  --set "microcks.generateCert=false" \
  --set "keycloak.url=keycloak.microcks.svc.cluster.local" \
  --set "keycloak.generateCert=false"

kubectl -n microcks rollout status deployment/microcks --timeout=180s
```

> **Importer le contrat OpenAPI avant le premier test.** Sans import, Microcks renvoie `HTTP 500`
> sur `/api/tests` même si la spec est accessible via `specURL`.
> Le manifest preview déclenche l'import automatiquement via un Job `microcks-import` —
> mais seulement si `spec.testSuite.contractTesting.specURL` est accessible depuis le cluster
> (URL publique, pas `localhost`).

The operator creates test jobs that call Microcks at `http://microcks.microcks.svc.cluster.local:8080` — no ingress needed for in-cluster communication.

### Step 4c — Install kagent

kagent orchestrates AI agents inside Kubernetes. Install CRDs first, then the main chart.

```bash
# CRDs must be installed before the main chart
helm install kagent-crds oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds \
  --namespace kagent-system \
  --create-namespace

helm install kagent oci://ghcr.io/kagent-dev/kagent/helm/kagent \
  --namespace kagent-system

kubectl -n kagent-system rollout status deployment/kagent-controller --timeout=120s
```

#### Create the Azure OpenAI secret for kagent

```bash
# Create an Azure OpenAI resource (if not already done)
az cognitiveservices account create \
  --name "preview-openai" \
  --resource-group "<YOUR_RG>" \
  --kind "OpenAI" \
  --sku "S0" \
  --location "eastus"

az cognitiveservices account deployment create \
  --name "preview-openai" \
  --resource-group "<YOUR_RG>" \
  --deployment-name "gpt-4o-mini" \
  --model-name "gpt-4o-mini" \
  --model-version "2024-07-18" \
  --model-format "OpenAI" \
  --sku-name "GlobalStandard" \
  --sku-capacity 30

# ⚠️  WSL/Windows : az CLI ajoute un \r en fin de valeur — toujours utiliser tr -d '\r\n'
AOAI_KEY=$(az cognitiveservices account keys list \
  --name "preview-openai" --resource-group "<YOUR_RG>" \
  --query "key1" -o tsv | tr -d '\r\n')

AOAI_ENDPOINT=$(az cognitiveservices account show \
  --name "preview-openai" --resource-group "<YOUR_RG>" \
  --query "properties.endpoint" -o tsv | tr -d '\r\n')

# Secret for kagent agents
kubectl create secret generic kagent-openai \
  --namespace kagent-system \
  --from-literal=OPENAI_API_KEY="$AOAI_KEY"

# Secret for the operator AI enrichment
kubectl create secret generic azure-openai-credentials \
  --namespace preview-operator-system \
  --from-literal=api-key="$AOAI_KEY"

# Pull secret for private GHCR images (jaeger-mcp-server)
GH_TOKEN=$(cat ~/.config/gh/hosts.yml | grep oauth_token | awk '{print $2}')
kubectl create secret docker-registry ghcr-pull-secret \
  --namespace kagent-system \
  --docker-server=ghcr.io \
  --docker-username="<YOUR_GITHUB_USERNAME>" \
  --docker-password="$GH_TOKEN"
```

#### Configure kagent ModelConfig for Azure OpenAI

```bash
# Récupérer l'endpoint exact depuis Azure (ne pas deviner le suffixe -<ID>)
AOAI_ENDPOINT=$(az cognitiveservices account show \
  --name "preview-openai" --resource-group "<YOUR_RG>" \
  --query "properties.endpoint" -o tsv | tr -d '\r\n')

kubectl patch modelconfig default-model-config -n kagent-system --type=merge -p "{
  \"spec\": {
    \"provider\": \"AzureOpenAI\",
    \"model\": \"gpt-4o-mini\",
    \"apiKeySecret\": \"kagent-openai\",
    \"apiKeySecretKey\": \"OPENAI_API_KEY\",
    \"azureOpenAI\": {
      \"azureEndpoint\": \"$AOAI_ENDPOINT\",
      \"azureDeployment\": \"gpt-4o-mini\",
      \"apiVersion\": \"2024-10-21\"
    }
  }
}"
```

#### Deploy the preview troubleshooter agent

```bash
kubectl apply -f k8s/kagent/rbac-readonly.yaml
kubectl apply -f k8s/kagent/jaeger-mcp-server.yaml
kubectl apply -f k8s/kagent/preview-troubleshooter-agent.yaml

# Attendre que jaeger-mcp-server soit Running avant de vérifier l'agent
kubectl rollout status deployment/jaeger-mcp-server -n kagent-system --timeout=120s

# L'agent doit être READY=True ACCEPTED=True — si ACCEPTED=False, jaeger-mcp-server n'est pas encore prêt
kubectl get agent preview-troubleshooter-agent -n kagent-system
```

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

The runner uses a **long-lived GitHub PAT** (`ACCESS_TOKEN`) rather than a one-time registration token. The `myoung34/github-runner` image automatically exchanges the PAT for a fresh registration token on every pod start — no manual renewal needed.

> **Clusters multiples :** chaque cluster doit avoir un nom de runner et des labels distincts
> pour éviter que GitHub envoie les jobs au mauvais cluster.
> Modifier `RUNNER_NAME` et `LABELS` dans `runner.yaml` avant d'appliquer :
> ```yaml
> - name: RUNNER_NAME
>   value: aks-runner-<ENV>        # ex: aks-runner-prod, aks-runner-test1
> - name: LABELS
>   value: self-hosted,aks,<ENV>   # ex: self-hosted,aks,test1
> ```
> Et adapter `runs-on` dans le workflow : `runs-on: [self-hosted, aks, <ENV>]`

> **Token type :** utiliser un PAT (`ghp_...` ou `github_pat_...`) — les tokens OAuth (`gho_...`)
> ne fonctionnent pas pour l'enregistrement du runner et échouent avec "Token is not valid".

#### 7.1 Create the runner PAT secret

The PAT must have `repo` scope (for registration) and `write:packages` (for Kaniko to push to GHCR).

```bash
kubectl create namespace github-runner --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic runner-token \
  --namespace github-runner \
  --from-literal=token="<YOUR_GITHUB_PAT>"
```

#### 7.2 Apply runner.yaml

`runner.yaml` is already configured in this repo. Apply it directly:

```bash
kubectl apply -f runner.yaml
kubectl -n github-runner rollout status deployment/github-runner --timeout=120s
kubectl logs -n github-runner deployment/github-runner --tail=5
# Expected last line: "Listening for Jobs"
```

The relevant configuration inside `runner.yaml`:

```yaml
env:
  - name: REPO_URL
    value: https://github.com/ihsenalaya/idp-preview
  - name: ACCESS_TOKEN          # long-lived PAT — auto-renews registration on restart
    valueFrom:
      secretKeyRef:
        name: runner-token
        key: token
  - name: RUNNER_NAME
    value: aks-runner
  - name: LABELS
    value: self-hosted,aks      # matches runs-on: [self-hosted, aks] in preview.yaml
  - name: EPHEMERAL
    value: "false"
```

> **No docker socket needed.** The workflow uses Kaniko (in-cluster image build), not Docker-in-Docker.

#### 7.3 Set the GitHub Actions secret

```bash
gh secret set PREVIEW_GITHUB_TOKEN \
  --repo <OWNER>/<REPO> \
  --body "<YOUR_GITHUB_PAT>"
```

Minimum PAT permissions:

| Permission | Level | Purpose |
|---|---|---|
| `write:packages` | Required | Kaniko pushes to GHCR |
| `repo` (Contents) | read | Kaniko clones repo, spec import fetches openapi.yaml |
| `Pull requests` | write | Operator posts PR comments |
| `Issues` | write | |
| `Deployments` | write | Operator creates GitHub Deployments |

#### 7.4 Create the operator GitHub token secret

```bash
kubectl create secret generic preview-github-token \
  --namespace preview-operator-system \
  --from-literal=token="<YOUR_GITHUB_PAT>"
```

#### 7.5 Configure AI enrichment

**Azure OpenAI (used in this setup)**

```bash
# ⚠️  WSL/Windows : toujours utiliser tr -d '\r\n' sur les sorties az CLI
AOAI_KEY=$(az cognitiveservices account keys list \
  --name "preview-openai" --resource-group "<YOUR_RG>" \
  --query "key1" -o tsv | tr -d '\r\n')

kubectl create secret generic ai-api-key \
  --namespace preview-operator-system \
  --from-literal=api-key="$AOAI_KEY"

# Configurer l'URL de base Azure OpenAI (endpoint sans le path /deployments/...)
AOAI_ENDPOINT=$(az cognitiveservices account show \
  --name "preview-openai" --resource-group "<YOUR_RG>" \
  --query "properties.endpoint" -o tsv | tr -d '\r\n')

kubectl set env deployment/preview-operator \
  AI_API_URL="$AOAI_ENDPOINT" \
  -n preview-operator-system
```

**OpenAI**

```bash
kubectl create secret generic ai-api-key \
  --namespace preview-operator-system \
  --from-literal=api-key="sk-..."
```

**GitHub Models (free tier)**

```bash
kubectl create secret generic ai-api-key \
  --namespace preview-operator-system \
  --from-literal=api-key="<YOUR_GITHUB_TOKEN>"

kubectl set env deployment/preview-operator \
  AI_API_URL=https://models.inference.ai.azure.com \
  -n preview-operator-system
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

  # ── Contract Testing (Microcks OPEN_API_SCHEMA) ───────────────────────────
  contractTesting:
    enabled: true
    specURL: https://raw.githubusercontent.com/ihsenalaya/idp-preview/main/api/openapi.yaml
    importUsername: manager     # Microcks user with manager role (default: manager)
    # importPassword defaults to microcks123; override via MICROCKS_PASSWORD env

  # ── kagent — AI failure analysis ───────────────────────────────────────────
  kagent:
    enabled: true
    agentName: preview-troubleshooter-agent
    agentNamespace: kagent-system

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
     ├── 10. reconcileExposure()     ──► VirtualService (Istio) or Nginx Ingress (auto-detected)
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
               ├── saving → smoke → import-spec → contract
               ├── restore-regression → regression
               ├── restore-e2e → e2e
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
│  microcks-import           │ python:3.11   │ upload openapi.yaml to Microcks│
│  microcks-contract-tests   │ python:3.11   │ OPEN_API_SCHEMA validation     │
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
  "url": "http://pr-42.preview.ihsenalaya.xyz",
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
    "lastEnvironmentUrl": "http://pr-42.preview.ihsenalaya.xyz"
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
# pr-42   Running   feature/my-feat   medium   http://pr-42.preview.ihsenalaya.xyz   2026-05-10T09:00:00Z   2h

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
                    │  Job: microcks-import  (non-blocking)                 │
                    │  Image: python:3.11                                   │
                    │  Fetches openapi.yaml from SPEC_URL (GitHub raw)     │
                    │  Uploads to Microcks /api/artifact/upload            │
                    │  Uses Keycloak password grant (manager role)         │
                    │  Failure does NOT stop the pipeline                  │
                    └────────────────┬─────────────────────────────────────┘
                                     │
                    ┌────────────────▼─────────────────────────────────────┐
                    │  Job: microcks-contract-tests                         │
                    │  Image: python:3.11                                   │
                    │  Runner: OPEN_API_SCHEMA                             │
                    │  BACKEND_URL=http://svc-backend.preview-pr-<N>       │
                    │            .svc.cluster.local:8080  (full FQDN)     │
                    │  Validates every 2xx response against openapi.yaml   │
                    │  Results posted to PR comment                        │
                    │  On failure → kagent triggered for AI analysis       │
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
  "saving"             → pg_dump job complete?    → set step="smoke"
  "smoke"              → smoke job complete?      → set step="import-spec"
  "import-spec"        → import job done/failed?  → set step="contract"
  "contract"           → contract job complete?   → set step="restore-regression"
  "restore-regression" → restore complete?        → set step="regression"
  "regression"         → regression complete?     → set step="restore-e2e"
  "restore-e2e"        → restore complete?        → set step="e2e"
  "e2e"                → e2e complete?            → set tests.phase="Succeeded"
                          job still running       → RequeueAfter=10s
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

**With Istio (AKS / production)** — no port-forward needed:

```bash
# URL is printed in the PR comment and in status:
http://pr-<N>.preview.ihsenalaya.xyz

kubectl get preview pr-<N> -o jsonpath='{.status.url}'
```

**With ingress-nginx (Kind / local)** — port-forward required:

```bash
kubectl port-forward -n ingress-nginx svc/ingress-nginx-controller 8080:80
# Then: http://pr-<N>.preview.localtest.me:8080
```

**Jaeger traces:**

```bash
kubectl port-forward -n observability svc/jaeger 16686:16686
# Open http://localhost:16686 → service: idp-preview-pr-42
```

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
helm show crds oci://ghcr.io/ihsenalaya/charts/preview-operator --version 1.0.21 \
  | tail -n +3 | kubectl apply -f -
helm upgrade preview-operator oci://ghcr.io/ihsenalaya/charts/preview-operator \
  --version 1.0.21 --namespace preview-operator-system
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
| Istio | `istio-system` | 1.23.0 | Ingress gateway, VirtualService routing, `*.preview.ihsenalaya.xyz` |
| Preview Operator | `preview-operator-system` | **1.0.21** | Multi-service, sequential test pipeline, AI enrichment, contract testing, kagent, Istio support |
| OpenTelemetry Operator | `opentelemetry-operator-system` | latest | |
| Jaeger (all-in-one) | `observability` | 1.67.0 | |
| OTel Collector + Instrumentation | `observability` | 0.149.0 | |
| GitHub Runner | `github-runner` | `myoung34/github-runner:latest` | `EPHEMERAL=false` |
| Preview Extension | `preview-operator-system` | **1.0.21** | Copilot commands + checkpoint API |
| Microcks | `microcks` | latest | OPEN_API_SCHEMA contract testing |
| kagent | `kagent-system` | latest | AI troubleshooter — read-only cluster analysis |

---

## 12. Contract testing and AI-powered failure analysis

> **Platform narrative:**
> "Every pull request gets an isolated Kubernetes preview environment,
> AI-generated test data, API contract validation with Microcks, automated
> regression/E2E tests, and kagent-powered failure explanation posted directly
> as a GitHub PR comment."

### Stack versions

| Component | Version | Role |
|-----------|---------|------|
| preview-operator | **1.0.21** | Provisions and orchestrates preview environments |
| idp-preview (this app) | latest | Sample Flask REST API + frontend |
| Microcks | 1.14.0 | OpenAPI contract testing (OPEN_API_SCHEMA runner) |
| kagent | 0.9.2 | AI agent framework (Azure OpenAI gpt-4o-mini) |
| CRD | `previews.platform.company.io/v1alpha1` | Preview CR |

### Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  Developer — git push + gh pr create                                │
└────────────────────────────┬────────────────────────────────────────┘
                             │ pull_request: opened / synchronize
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  GitHub Actions (.github/workflows/preview.yaml)                    │
│  Kaniko build → push image → apply Preview CR                      │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Preview Operator 1.0.21                                            │
│                                                                     │
│  Namespace preview-pr-<N>                                          │
│   ├── PostgreSQL + backend (app:8080) + frontend (3000)            │
│   ├── AI enrichment: schema-dump → generate → seed → ai-tests     │
│   └── Test suite:                                                  │
│         smoke → microcks-import → contract → regression → E2E      │
│                       │                │                           │
│         ┌─────────────┘               │                           │
│         │  openapi.yaml uploaded       │                           │
│         │  to Microcks                 │                           │
│         ▼                              │                           │
│  ┌──────────────────┐                 │                           │
│  │  Microcks        │◄────────────────┘                           │
│  │  (microcks ns)   │  OPEN_API_SCHEMA runner                     │
│  │  HTTP requests → │  svc-backend.<ns>.svc.cluster.local:8080    │
│  │  svc-backend     │  validates responses vs openapi.yaml         │
│  └──────┬───────────┘                                             │
└─────────│───────────────────────────────────────────────────────────┘
          │
          ├─── PASS ──► PR comment ✅ (contract: N passed)
          │
          └─── FAIL ──► kagent triggered 🤖
                              │
                              ▼
                   ┌──────────────────────────┐
                   │  preview-troubleshooter  │
                   │  -agent (read-only)       │
                   │                          │
                   │  Inspects:               │
                   │  - Preview CR status     │
                   │  - Pod/job logs          │
                   │  - Microcks job output   │
                   │  - K8s events            │
                   └──────────┬───────────────┘
                              │
                              ▼
                   Structured PR comment:
                   Risk level / Evidence /
                   Root cause / Suggested fix /
                   Reproduction commands
```

### What Microcks adds

[Microcks](https://microcks.io) is an open-source API mocking and testing
platform. In the Preview Platform it runs **OPEN_API_SCHEMA** validation:
it sends real HTTP requests to the live backend (`svc-backend:8080`) and
validates every response against `api/openapi.yaml`.

- **Contract = single source of truth.** The OpenAPI file in the repo
  defines what the API must return. Microcks enforces it on every PR.
- **Catches schema drift early.** A field rename, wrong HTTP status code,
  or missing required field is caught before code review — not by a
  downstream consumer in production.
- **Zero infrastructure for the developer.** Microcks runs in-cluster;
  the Job is created and cleaned up automatically by the operator.

### What kagent adds

[kagent](https://kagent.dev) is a Kubernetes AI agent framework. The
`preview-troubleshooter-agent` is a **read-only** agent that:

- Is triggered automatically when any test suite (Microcks, regression, E2E) fails.
- Reads Kubernetes resources, job logs, and events using a Kubernetes MCP
  server — **no kubectl exec, no secret access, no mutations.**
- Produces a structured Markdown GitHub PR comment with:
  - Risk level (HIGH / MEDIUM / LOW / INFO)
  - Evidence collected from the cluster
  - Likely root cause
  - Suggested fix with file and line references
  - kubectl commands to reproduce the failure

### Why kagent complements but does not replace the Preview Operator

| Concern | Preview Operator | kagent |
|---------|-----------------|--------|
| Provision environments | ✅ | ❌ |
| Run test pipelines | ✅ | ❌ |
| Manage lifecycle (TTL, teardown) | ✅ | ❌ |
| Diagnose failures | ❌ | ✅ |
| Explain root cause in plain language | ❌ | ✅ |
| Suggest code fixes | ❌ | ✅ |
| Mutate cluster resources | ✅ (controlled) | ❌ (by design) |

### How it fits the existing pipeline

```
Existing pipeline                       New additions
─────────────────                       ──────────────
1. AI enrichment (seed + tests)
2. smoke-tests
3. [NEW] microcks-import          ←── uploads api/openapi.yaml to Microcks
4. [NEW] microcks-contract-tests  ←── OPEN_API_SCHEMA validation
5. suite-restore-regression
6. regression-tests
7. suite-restore-e2e
8. e2e-tests

On any failure → kagent ←─────────────── preview-troubleshooter-agent
                                          reads logs from all above steps
```

### Manual commands

```bash
# Validate OpenAPI spec locally
pip install pyyaml
make validate-openapi

# Validate all YAML files
make validate-yaml

# Run Microcks contract test manually
export MICROCKS_URL=http://localhost:8080
export BACKEND_URL=http://localhost:8080
make microcks-contract-test

# Apply kagent resources
kubectl apply -f k8s/kagent/namespace.yaml
kubectl apply -f k8s/kagent/rbac-readonly.yaml
kubectl apply -f k8s/kagent/jaeger-mcp-server.yaml
kubectl rollout status deployment/jaeger-mcp-server -n kagent-system --timeout=120s
kubectl apply -f k8s/kagent/preview-troubleshooter-agent.yaml
```

### Required secrets

| Secret | Namespace | Keys | Purpose |
|--------|-----------|------|---------|
| `microcks-credentials` | `preview-pr-<N>` | `client_id`, `client_secret` | Microcks OAuth2 (optional) |
| `azure-openai-credentials` | `kagent-system` | `api-key` | Model provider for kagent |

### Limitations

| Limitation | Detail |
|------------|--------|
| Microcks must be pre-installed | Not installed by the operator chart — deploy separately |
| OpenAPI spec must be imported in Microcks | Upload `api/openapi.yaml` once before first use |
| kagent is read-only | Diagnosis only — cannot auto-fix failures |
| kagent requires a model provider | Azure OpenAI, OpenAI, or any OpenAI-compatible API |
