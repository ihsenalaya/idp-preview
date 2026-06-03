#!/usr/bin/env bash
# =============================================================================
# Etape 2 — Cree les namespaces + les Secrets Kubernetes depuis .env.
#
# Remplace External Secrets + Azure Key Vault de la version prod. Les secrets
# sont crees directement (kubectl apply), de maniere idempotente, AVANT le
# bootstrap ArgoCD pour qu'ils soient disponibles des le demarrage des pods.
#
# Equivalences avec la prod (gitops/manifests/external-secrets/) :
#   preview-operator-system/preview-github-token (token)  <- GITHUB_TOKEN
#   preview-operator-system/ai-api-key           (api-key)<- GITHUB_MODELS_TOKEN
#   kagent-system/preview-github-token           (token)  <- GITHUB_TOKEN
#   kagent-system/kagent-openai           (OPENAI_API_KEY) <- GITHUB_MODELS_TOKEN
#   kagent-system/ghcr-pull-secret      (dockerconfigjson)  <- GITHUB_TOKEN
#   github-runner/runner-token                   (token)  <- GITHUB_TOKEN
#
# Les images (preview-operator, *-mcp-server) sont PUBLIQUES sur GHCR : aucun
# build local. ghcr-pull-secret n'est requis que parce que les manifests
# upstream k8s/kagent le referencent ; il evite des warnings d'event.
# =============================================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ ! -f "${ROOT_DIR}/.env" ]]; then
  echo "ERREUR: ${ROOT_DIR}/.env introuvable. Copier .env.example en .env." >&2
  exit 1
fi
# shellcheck disable=SC1091
set -a; source "${ROOT_DIR}/.env"; set +a

: "${GITHUB_TOKEN:?GITHUB_TOKEN manquant dans .env}"
: "${GITHUB_MODELS_TOKEN:?GITHUB_MODELS_TOKEN manquant dans .env}"

ensure_ns() {
  kubectl create namespace "$1" --dry-run=client -o yaml | kubectl apply -f -
}

# apply_secret <ns> <name> <key1=val1> [<key2=val2> ...]
apply_secret() {
  local ns="$1" name="$2"; shift 2
  local args=()
  for kv in "$@"; do args+=(--from-literal="${kv}"); done
  kubectl create secret generic "${name}" -n "${ns}" \
    "${args[@]}" --dry-run=client -o yaml | kubectl apply -f -
}

echo "==> Namespaces..."
for ns in preview-operator-system kagent-system github-runner; do ensure_ns "${ns}"; done

echo "==> Secrets preview-operator-system..."
apply_secret preview-operator-system preview-github-token "token=${GITHUB_TOKEN}"
apply_secret preview-operator-system ai-api-key           "api-key=${GITHUB_MODELS_TOKEN}"

echo "==> Secrets kagent-system..."
apply_secret kagent-system preview-github-token "token=${GITHUB_TOKEN}"
apply_secret kagent-system kagent-openai        "OPENAI_API_KEY=${GITHUB_MODELS_TOKEN}"

echo "==> Secret ghcr-pull-secret (kagent-system)..."
kubectl create secret docker-registry ghcr-pull-secret -n kagent-system \
  --docker-server=ghcr.io \
  --docker-username="${GITHUB_USER:-ihsenalaya}" \
  --docker-password="${GITHUB_TOKEN}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "==> Secret github-runner..."
apply_secret github-runner runner-token "token=${GITHUB_TOKEN}"

echo "==> Secrets crees/mis a jour."
