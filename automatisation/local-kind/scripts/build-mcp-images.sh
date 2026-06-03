#!/usr/bin/env bash
# =============================================================================
# Build + chargement des images MCP custom dans le cluster kind.
#
# Pourquoi : les images ghcr.io/ihsenalaya/{github,jaeger}-mcp-server sont
# PRIVEES sur GHCR (403 au pull sans token read:packages). Pour que n'importe
# qui puisse refaire l'install (repo public), on ne tire PAS ces images : on les
# builde depuis les sources du repo (github-mcp/, jaeger-mcp/) et on les injecte
# dans kind, taguees avec le NOM UPSTREAM exact.
#
# Les Deployments (k8s/kagent/{github,jaeger}-mcp-server.yaml) declarent
# `imagePullPolicy: IfNotPresent` -> kube utilise l'image deja chargee dans kind
# et ne tente aucun pull GHCR. Aucun ghcr-pull-secret ni PAT requis en local.
#
# Appele automatiquement par up.sh (apres la creation du cluster). Peut aussi
# etre relance seul si tu modifies github-mcp/server.py ou jaeger-mcp/server.py :
#   ./automatisation/local-kind/scripts/build-mcp-images.sh
# (puis : kubectl rollout restart deploy/{github,jaeger}-mcp-server -n kagent-system)
# =============================================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IDP_REPO="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
CLUSTER_NAME="${CLUSTER_NAME:-idp-preview-local}"

build_load() {
  local image="$1" ctx="$2"
  echo "==> Build ${image}  (contexte: ${ctx})"
  docker build -t "${image}" "${ctx}"
  echo "==> kind load ${image}  ->  cluster ${CLUSTER_NAME}"
  kind load docker-image "${image}" --name "${CLUSTER_NAME}"
}

build_load "ghcr.io/ihsenalaya/github-mcp-server:latest" "${IDP_REPO}/github-mcp"
build_load "ghcr.io/ihsenalaya/jaeger-mcp-server:latest" "${IDP_REPO}/jaeger-mcp"

echo "==> Images MCP construites et chargees dans kind (imagePullPolicy: IfNotPresent)."
