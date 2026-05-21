#!/usr/bin/env bash
# =============================================================================
# Bootstrap GitOps — IDP Preview Platform
# -----------------------------------------------------------------------------
# Installe Argo CD puis applique l'App-of-Apps racine. A partir de la, Argo CD
# deploie toute la plateforme (voir automatisation/gitops/apps/).
#
# Aucun secret n'est manipule par ce script : les secrets de la plateforme sont
# tires d'Azure Key Vault par External Secrets Operator (workload identity).
# Le pre-requis Azure (Key Vault + managed identity + federated credential) est
# decrit dans automatisation/gitops/SECRETS.md.
#
# Pre-requis : kubectl pointe sur le bon cluster, droits cluster-admin.
# Usage : ./automatisation/gitops/bootstrap.sh
# =============================================================================
set -euo pipefail

ARGOCD_VERSION="${ARGOCD_VERSION:-v3.2.0}"
ARGOCD_NAMESPACE="argocd"
ESO_CHART_VERSION="${ESO_CHART_VERSION:-2.5.0}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Cluster cible : $(kubectl config current-context)"
echo "==> Argo CD : ${ARGOCD_VERSION}"

# 1. Namespace Argo CD
kubectl create namespace "${ARGOCD_NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -

# 2. Installation d'Argo CD
echo "==> Installation d'Argo CD..."
kubectl apply -n "${ARGOCD_NAMESPACE}" \
  -f "https://raw.githubusercontent.com/argoproj/argo-cd/${ARGOCD_VERSION}/manifests/install.yaml"
kubectl -n "${ARGOCD_NAMESPACE}" rollout status deploy/argocd-server --timeout=300s
kubectl -n "${ARGOCD_NAMESPACE}" rollout status deploy/argocd-repo-server --timeout=300s

# 3. AppProject + depot Helm OCI public (kagent)
echo "==> Application du projet et du depot OCI public..."
kubectl apply -f "${SCRIPT_DIR}/argocd-config/argocd-project.yaml"
kubectl apply -f "${SCRIPT_DIR}/argocd-config/repo-kagent-oci.yaml"

# 3b. CRDs External Secrets (server-side)
# Les CRDs ESO (~335 Ko) depassent la limite d'annotation de l'apply
# client-side d'Argo CD. On les installe ici en server-side ; l'Application
# external-secrets utilise installCRDs=false.
echo "==> Pre-installation des CRDs External Secrets (server-side)..."
helm repo add external-secrets https://charts.external-secrets.io >/dev/null 2>&1 || true
helm repo update external-secrets >/dev/null 2>&1
helm template external-secrets external-secrets/external-secrets \
  --version "${ESO_CHART_VERSION}" --include-crds --set installCRDs=true \
  --namespace external-secrets \
  | python3 -c 'import sys,yaml; yaml.safe_dump_all((d for d in yaml.safe_load_all(sys.stdin) if d and d.get("kind")=="CustomResourceDefinition"), sys.stdout)' \
  | kubectl apply --server-side --force-conflicts -f -

# 4. App-of-Apps racine
echo "==> Deploiement de l'App-of-Apps racine..."
kubectl apply -f "${SCRIPT_DIR}/argocd-config/root-app.yaml"

# 5. Mot de passe admin initial
echo ""
echo "==> Argo CD installe."
echo "    Mot de passe admin initial :"
kubectl -n "${ARGOCD_NAMESPACE}" get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' 2>/dev/null | base64 -d || echo "(secret deja supprime)"
echo ""
echo "    Acces UI : kubectl -n ${ARGOCD_NAMESPACE} port-forward svc/argocd-server 8080:443"
echo "               puis https://localhost:8080  (user: admin)"
echo ""
echo "==> Les Applications enfants sont en sync MANUEL. Verifiez le diff dans"
echo "    l'UI Argo CD avant de synchroniser. Voir automatisation/gitops/README.md."
