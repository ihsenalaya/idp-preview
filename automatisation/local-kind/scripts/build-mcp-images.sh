#!/usr/bin/env bash
# =============================================================================
# Build + chargement des images MCP de kagent dans kind.
#
# Les images ghcr.io/ihsenalaya/{github,jaeger}-mcp-server sont PRIVEES (403 au
# pull sans token read:packages). On les builde depuis le repo et on les injecte
# dans kind, taguees avec le NOM UPSTREAM exact pour que les manifests
# k8s/kagent/ les trouvent localement (avec imagePullPolicy IfNotPresent — voir
# le patch applique en fin de script).
#
# Usage : ./automatisation/local-kind/scripts/build-mcp-images.sh
# =============================================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IDP_REPO="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
CLUSTER_NAME="idp-preview-local"

GITHUB_MCP_IMAGE="ghcr.io/ihsenalaya/github-mcp-server:latest"
JAEGER_MCP_IMAGE="ghcr.io/ihsenalaya/jaeger-mcp-server:latest"

build_load() {
  local image="$1" ctx="$2"
  echo "==> Build ${image} (ctx: ${ctx})"
  docker build -t "${image}" "${ctx}"
  echo "==> kind load ${image}"
  kind load docker-image "${image}" --name "${CLUSTER_NAME}"
}

build_load "${GITHUB_MCP_IMAGE}" "${IDP_REPO}/github-mcp"
build_load "${JAEGER_MCP_IMAGE}" "${IDP_REPO}/jaeger-mcp"

# Les manifests upstream utilisent imagePullPolicy Always (tag :latest) -> kube
# tenterait un pull GHCR (403). On force IfNotPresent pour utiliser l'image kind.
echo "==> Patch imagePullPolicy=IfNotPresent + suppression imagePullSecrets"
for d in github-mcp-server jaeger-mcp-server; do
  if kubectl get deploy "$d" -n kagent-system >/dev/null 2>&1; then
    kubectl patch deploy "$d" -n kagent-system --type=json -p='[
      {"op":"replace","path":"/spec/template/spec/containers/0/imagePullPolicy","value":"IfNotPresent"}
    ]' 2>/dev/null || true
    kubectl patch deploy "$d" -n kagent-system --type=json -p='[
      {"op":"remove","path":"/spec/template/spec/imagePullSecrets"}
    ]' 2>/dev/null || true
    kubectl rollout restart deploy "$d" -n kagent-system 2>/dev/null || true
  fi
done

# Pas de ghcr-pull-secret (sinon un token sans read:packages casse meme le pull
# anonyme des images publiques). On le retire s'il existe.
kubectl delete secret ghcr-pull-secret -n kagent-system --ignore-not-found 2>/dev/null || true

echo "==> Images MCP pretes dans kind."
