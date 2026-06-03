#!/usr/bin/env bash
# =============================================================================
# Etape 1 — Cree le cluster kind local (idp-preview-local).
# Idempotent : ne recree pas le cluster s'il existe deja.
# =============================================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
CLUSTER_NAME="idp-preview-local"

if kind get clusters 2>/dev/null | grep -qx "${CLUSTER_NAME}"; then
  echo "==> Cluster kind '${CLUSTER_NAME}' deja present — rien a faire."
else
  echo "==> Creation du cluster kind '${CLUSTER_NAME}'..."
  kind create cluster --config "${ROOT_DIR}/kind-config.yaml"
fi

kubectl cluster-info --context "kind-${CLUSTER_NAME}"
echo "==> Cluster pret. Contexte kubectl : kind-${CLUSTER_NAME}"
