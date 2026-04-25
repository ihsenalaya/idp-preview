# idp-testing

Demo application for validating the Cellenza preview environment workflow.  
Each pull request gets an isolated Kubernetes environment with its own PostgreSQL database, a public URL, and automatic GitHub Deployment status. Traces are collected by OpenTelemetry and visible in Jaeger.

---

## Architecture

```
PR opened / updated
       │
       ▼
GitHub Actions (self-hosted runner inside the cluster)
       │
       ├─ Kaniko  ──► builds image in-cluster ──► pushes to GHCR
       │
       ├─ kubectl apply Cellenza CR  ──► Cellenza Operator
       │                                      │
       │                     ┌────────────────┼──────────────────┐
       │                Namespace         PostgreSQL           OTel annotation
       │                Deployment         (sidecar)         (auto-instrumentation)
       │                Service                                    │
       │                Ingress  ──► pr-<N>.preview.localtest.me   │
       │                                                           ▼
       │                                                    Jaeger (traces)
       └─ Operator posts GitHub Deployment status + PR comment
```

PR closed → cleanup workflow deletes the Cellenza CR → operator finalizer tears down all resources.

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Docker | 24+ | https://docs.docker.com/get-docker/ |
| Kind | 0.25+ | `go install sigs.k8s.io/kind@latest` or [releases](https://github.com/kubernetes-sigs/kind/releases) |
| kubectl | 1.28+ | https://kubernetes.io/docs/tasks/tools/ |
| Helm | 3.14+ | https://helm.sh/docs/intro/install/ |
| gh CLI | 2.0+ | https://cli.github.com/ |

---

## Step 1 — Create the Kind cluster

```bash
kind create cluster --name testing
```

Verify:

```bash
kubectl get nodes
# NAME                    STATUS   ROLES           AGE   VERSION
# testing-control-plane   Ready    control-plane   ...   v1.35.0
```

---

## Step 2 — Install cert-manager

Required by the Cellenza Operator webhook and the OpenTelemetry Operator.

```bash
helm repo add cert-manager https://charts.jetstack.io
helm repo update

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
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update

helm install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --create-namespace \
  --version 4.15.1

kubectl -n ingress-nginx rollout status deployment/ingress-nginx-controller --timeout=120s
```

---

## Step 4 — Install the Cellenza Operator

The chart is published via OCI to GHCR. No `helm repo add` needed.

```bash
helm install cellenza-operator \
  oci://ghcr.io/ihsenalaya/charts/cellenza-operator \
  --version 0.6.2 \
  --namespace cellenza-operator-system \
  --create-namespace

kubectl -n cellenza-operator-system rollout status deployment/cellenza-operator --timeout=120s
```

Verify the CRD is installed:

```bash
kubectl get crd cellenzas.platform.company.io
```

---

## Step 5 — Install OpenTelemetry Operator

Required to inject Python auto-instrumentation into preview pods.

```bash
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm repo update

helm install opentelemetry-operator open-telemetry/opentelemetry-operator \
  --namespace opentelemetry-operator-system \
  --create-namespace \
  --version 0.110.0 \
  --set admissionWebhooks.certManager.enabled=true \
  --set manager.collectorImage.repository=otel/opentelemetry-collector-contrib

kubectl -n opentelemetry-operator-system rollout status deployment/opentelemetry-operator --timeout=120s
```

---

## Step 6 — Deploy Jaeger and configure the OTel Collector

A single command deploys Jaeger (all-in-one, in-memory) and configures the OpenTelemetry Collector + Python auto-instrumentation:

```bash
# Jaeger all-in-one
kubectl apply -f https://raw.githubusercontent.com/ihsenalaya/idp-testing/main/jaeger.yaml

kubectl -n observability rollout status deployment/jaeger --timeout=120s

# OTel Collector + Python Instrumentation CR
kubectl apply -f https://raw.githubusercontent.com/ihsenalaya/cellenza-operator/main/demo-app/otel.yaml

kubectl -n observability rollout status deployment/otel-collector --timeout=120s
```

Verify:

```bash
kubectl get otelcol -n observability
kubectl get instrumentation -n observability
```

Expected output:

```
NAME   MODE         VERSION   READY
otel   deployment   0.148.0   1/1

NAME     ENDPOINT                                                        SAMPLER
python   http://otel-collector.observability.svc.cluster.local:4318      parentbased_traceidratio
```

---

## Step 7 — Deploy the self-hosted GitHub Actions runner

The runner runs inside the cluster so it has direct access to the Kubernetes API.  
Its service account has `cluster-admin` rights to create Jobs, Secrets, and Cellenza resources.

### 7.1 Generate a runner registration token

> Tokens expire after **1 hour**. If the runner pod restarts, repeat this step.

```bash
gh api -X POST repos/<YOUR_OWNER>/<YOUR_REPO>/actions/runners/registration-token --jq '.token'
```

### 7.2 Create `runner.yaml`

Replace `<YOUR_OWNER>`, `<YOUR_REPO>`, and `<TOKEN>` with the values from the previous step.

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

### 7.3 Apply and verify

```bash
kubectl apply -f runner.yaml
kubectl -n github-runner rollout status deployment/github-runner --timeout=60s
kubectl logs -n github-runner deployment/github-runner --tail=5
# Expected last line: "Listening for Jobs"
```

Verify the runner appears as **online** in GitHub:

```bash
gh api repos/<YOUR_OWNER>/<YOUR_REPO>/actions/runners \
  --jq '.runners[] | {name, status, labels: [.labels[].name]}'
```

---

## Step 8 — Fork or configure this repository

The GitHub Actions workflows are already in `.github/workflows/`:

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `preview.yaml` | PR opened / updated | Build image, deploy preview, post GitHub Deployment |
| `cleanup.yaml` | PR closed | Delete Cellenza CR, mark deployment as inactive |

The workflows use only `secrets.GITHUB_TOKEN` — no additional secrets are needed.

---

## Step 9 — Open a pull request

Create a branch with any change in the application code (not in `.github/workflows/`):

```bash
git checkout -b my-feature
echo "# test" >> app.py
git add app.py
git commit -m "test: trigger preview"
git push origin my-feature
gh pr create --title "test: trigger preview" --body "Testing the preview flow"
```

The `Preview Environment` workflow starts automatically on the self-hosted runner.

> **Important:** Do not modify `.github/workflows/` files in your PR branch — GitHub will not
> trigger the workflow on self-hosted runners when the workflow files themselves are changed.

---

## Accessing the preview

### Port-forward ingress (required for Kind)

```bash
kubectl port-forward -n ingress-nginx svc/ingress-nginx-controller 8080:80
```

Leave this running in a terminal. The preview URL is printed in the PR comment:

```
http://pr-<NUMBER>.preview.localtest.me:8080
```

`localtest.me` resolves to `127.0.0.1` automatically — no DNS configuration needed.

> **WSL2:** Run the port-forward inside WSL2. Windows browsers reach `localhost:8080` through
> the WSL2 localhost forwarding (enabled by default in WSL2 ≥ 2.0).

### Jaeger UI

```bash
kubectl port-forward -n observability svc/jaeger 16686:16686
```

Open [http://localhost:16686](http://localhost:16686). Select service **`idp-testing`** to see traces from the Flask app.

---

## Troubleshooting

### Workflow does not trigger

The runner pod may have restarted and its token expired. Regenerate and redeploy:

```bash
NEW_TOKEN=$(gh api -X POST repos/<OWNER>/<REPO>/actions/runners/registration-token --jq '.token')
kubectl set env deployment/github-runner -n github-runner RUNNER_TOKEN="$NEW_TOKEN"
kubectl rollout restart deployment/github-runner -n github-runner
kubectl logs -n github-runner deployment/github-runner --tail=5
```

### No traces in Jaeger

Verify the OTel annotation was injected on the preview pod:

```bash
kubectl get pod -n preview-pr-<NUMBER> -l app=pr-<NUMBER> \
  -o jsonpath='{.items[0].metadata.annotations}' | grep instrumentation
```

Expected: `instrumentation.opentelemetry.io/inject-python: observability/python`

If missing, check that `spec.telemetry.enabled: true` is in the Cellenza resource:

```bash
kubectl get cellenza pr-<NUMBER> -o yaml | grep -A8 telemetry
```

### Cellenza stuck in Pending

```bash
kubectl describe cellenza pr-<NUMBER>
kubectl get events -n preview-pr-<NUMBER> --sort-by='.lastTimestamp'
```

### Preview pod CrashLoopBackOff

```bash
kubectl logs -n preview-pr-<NUMBER> -l app=pr-<NUMBER>
```

---

## Application

The application is the **Cellenza Demo App** — a Flask guestbook backed by PostgreSQL:

| Route | Description |
|-------|-------------|
| `GET /` | PostgreSQL status, environment variables, message board |
| `POST /add` | Insert a message into the database |
| `GET /healthz` | Returns `ok` — used by Kubernetes liveness/readiness probes |

The operator injects the following environment variables automatically:

| Variable | Source |
|----------|--------|
| `DATABASE_URL` | Built from the PostgreSQL Secret |
| `POSTGRES_DB` | From the database spec |
| `POSTGRES_USER` | From the database Secret |
| `PREVIEW_BRANCH` | `spec.branch` |
| `PREVIEW_PR` | `spec.prNumber` |

---

## Summary of installed components

| Component | Namespace | Install | Version |
|-----------|-----------|---------|---------|
| cert-manager | `cert-manager` | Helm `cert-manager/cert-manager` | v1.20.2 |
| ingress-nginx | `ingress-nginx` | Helm `ingress-nginx/ingress-nginx` | 4.15.1 |
| Cellenza Operator | `cellenza-operator-system` | Helm OCI `ghcr.io/ihsenalaya/charts/cellenza-operator` | 0.6.2 |
| OpenTelemetry Operator | `opentelemetry-operator-system` | Helm `open-telemetry/opentelemetry-operator` | 0.110.0 |
| Jaeger (all-in-one) | `observability` | `kubectl apply -f jaeger.yaml` | 1.67 |
| OTel Collector + Instrumentation | `observability` | `kubectl apply -f otel.yaml` | 0.148.0 |
| GitHub Runner | `github-runner` | `kubectl apply -f runner.yaml` | `myoung34/github-runner:latest` |
