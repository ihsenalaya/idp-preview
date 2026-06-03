#!/usr/bin/env bash
# =============================================================================
# Etape 3 — Installe ArgoCD puis applique l'App-of-Apps racine.
#
# A partir de la, ArgoCD deploie toute la plateforme locale (voir
# gitops/apps/). Aucun secret n'est manipule ici (cf. 02-secrets.sh).
#
# Les valeurs GIT_REPO_URL / GIT_REVISION du .env sont injectees dans le
# root-app applique localement. Les Applications enfants, elles, sont tirees
# du Git : leurs champs repoURL/targetRevision doivent deja pointer sur la
# bonne branche dans le depot (voir README.md, etape 0).
# =============================================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
GITOPS_DIR="${ROOT_DIR}/gitops"
ARGOCD_VERSION="${ARGOCD_VERSION:-v3.2.0}"
ARGOCD_NAMESPACE="argocd"

# shellcheck disable=SC1091
[[ -f "${ROOT_DIR}/.env" ]] && { set -a; source "${ROOT_DIR}/.env"; set +a; }
GIT_REPO_URL="${GIT_REPO_URL:-https://github.com/ihsenalaya/idp-preview}"
GIT_REVISION="${GIT_REVISION:-local-kind}"

echo "==> Cluster cible : $(kubectl config current-context)"
echo "==> Argo CD ${ARGOCD_VERSION} | repo=${GIT_REPO_URL} rev=${GIT_REVISION}"

# 1. Namespace + installation ArgoCD
kubectl create namespace "${ARGOCD_NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -
echo "==> Installation d'Argo CD..."
kubectl apply -n "${ARGOCD_NAMESPACE}" \
  -f "https://raw.githubusercontent.com/argoproj/argo-cd/${ARGOCD_VERSION}/manifests/install.yaml"
kubectl -n "${ARGOCD_NAMESPACE}" rollout status deploy/argocd-server     --timeout=300s
kubectl -n "${ARGOCD_NAMESPACE}" rollout status deploy/argocd-repo-server --timeout=300s

# 2. AppProject + depot Helm OCI public (kagent)
echo "==> AppProject + depot OCI public kagent..."
kubectl apply -f "${GITOPS_DIR}/argocd-config/argocd-project.yaml"
kubectl apply -f "${GITOPS_DIR}/argocd-config/repo-kagent-oci.yaml"

# 3. App-of-Apps racine (repo/revision injectes depuis .env)
echo "==> Deploiement de l'App-of-Apps racine..."
sed -e "s#__GIT_REPO_URL__#${GIT_REPO_URL}#g" \
    -e "s#__GIT_REVISION__#${GIT_REVISION}#g" \
    "${GITOPS_DIR}/argocd-config/root-app.yaml" | kubectl apply -f -

# 4. Mot de passe admin initial
echo ""
echo "==> Argo CD installe."
echo -n "    Mot de passe admin initial : "
kubectl -n "${ARGOCD_NAMESPACE}" get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' 2>/dev/null | base64 -d || echo "(secret deja supprime)"
echo ""
echo "    UI : kubectl -n ${ARGOCD_NAMESPACE} port-forward svc/argocd-server 8080:443"
echo "         puis https://localhost:8080  (user: admin)"
