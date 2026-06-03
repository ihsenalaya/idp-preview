#!/usr/bin/env bash
# =============================================================================
# Deploiement complet de la plateforme locale, de bout en bout.
#   1. cree le cluster kind
#   2. cree les secrets depuis .env
#   3. bootstrappe ArgoCD (qui deploie tout le reste)
#
# Les images (operateur + serveurs MCP) sont PUBLIQUES sur GHCR : tirees
# directement par Kubernetes, aucun build local.
#
# Pre-requis : docker, kind, kubectl, helm, et un fichier .env rempli.
# =============================================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bash "${SCRIPT_DIR}/01-create-cluster.sh"
bash "${SCRIPT_DIR}/02-secrets.sh"
bash "${SCRIPT_DIR}/03-bootstrap-argocd.sh"

cat <<'EOF'

==> Plateforme en cours de deploiement par ArgoCD.
    Suivre :   kubectl get applications -n argocd -w
    Pods    :   kubectl get pods -A

    Une preview PR sera exposee sur :
       http://pr-<N>.preview.127.0.0.1.nip.io
EOF
