#!/usr/bin/env bash
# =============================================================================
# Supprime entierement le cluster kind local.
# =============================================================================
set -euo pipefail
CLUSTER_NAME="idp-preview-local"
echo "==> Suppression du cluster kind '${CLUSTER_NAME}'..."
kind delete cluster --name "${CLUSTER_NAME}"
echo "==> Supprime."
