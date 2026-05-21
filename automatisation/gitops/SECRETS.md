# Gestion des secrets — Azure Key Vault + External Secrets

Aucun secret n'est stocke dans Git. La source de verite est **Azure Key Vault**.
**External Secrets Operator (ESO)** materialise les `Secret` Kubernetes a partir
du vault, en s'authentifiant via **Azure Workload Identity** (sans aucun secret
d'amorcage).

```
Azure Key Vault (idp-preview-kv)
  ├── github-pat            PAT GitHub (repo, write:packages, deployments, PR)
  └── azure-openai-key      Cle API Azure OpenAI
            │
            │  Workload Identity  (idp-eso-identity  ──federated──▶  SA external-secrets)
            ▼
External Secrets Operator  ──génère──▶  Secrets K8s natifs
            │
            ├── preview-operator-system/preview-github-token, ai-api-key, azure-openai-credentials
            ├── kagent-system/preview-github-token, kagent-openai, ghcr-pull-secret
            ├── github-runner/runner-token
            └── argocd/repo-ihsenalaya-charts   (credential depot Helm OCI prive)
```

## Ressources Azure (deja provisionnees)

| Ressource | Nom | Detail |
|---|---|---|
| Key Vault | `idp-preview-kv` | RG `idp-preview-rg`, RBAC authorization activee |
| Secret KV | `github-pat` | PAT GitHub |
| Secret KV | `azure-openai-key` | Cle Azure OpenAI |
| Managed Identity | `idp-eso-identity` | client-id `48c913e5-dba9-4978-b18f-39454949c32f` |
| Role assignment | `Key Vault Secrets User` | identite ESO, scope = le vault |
| Federated credential | `eso-external-secrets` | sujet `system:serviceaccount:external-secrets:external-secrets` |

> Le **client-id** est un identifiant, pas un secret : il est volontairement
> committe dans `automatisation/gitops/apps/00-external-secrets.yaml`.

## Reproduire la configuration Azure (cluster neuf)

```bash
RG=idp-preview-rg
LOCATION=eastus
CLUSTER=idp-preview-cluster
KV=idp-preview-kv

# 1. Key Vault (RBAC)
az keyvault create --name "$KV" --resource-group "$RG" --location "$LOCATION" \
  --enable-rbac-authorization true --sku standard
az role assignment create --role "Key Vault Secrets Officer" \
  --assignee-object-id "$(az ad signed-in-user show --query id -o tsv)" \
  --assignee-principal-type User \
  --scope "$(az keyvault show --name "$KV" --query id -o tsv)"

# 2. Chargement des secrets
az keyvault secret set --vault-name "$KV" --name github-pat       --value "<PAT_GITHUB>"
az keyvault secret set --vault-name "$KV" --name azure-openai-key --value "<CLE_AZURE_OPENAI>"

# 3. OIDC issuer + workload identity sur l'AKS
az aks update --resource-group "$RG" --name "$CLUSTER" \
  --enable-oidc-issuer --enable-workload-identity
OIDC_URL=$(az aks show -g "$RG" -n "$CLUSTER" --query oidcIssuerProfile.issuerUrl -o tsv)

# 4. Managed identity pour ESO
az identity create --name idp-eso-identity --resource-group "$RG" --location "$LOCATION"
ESO_CLIENT_ID=$(az identity show -n idp-eso-identity -g "$RG" --query clientId -o tsv)
ESO_PRINCIPAL=$(az identity show -n idp-eso-identity -g "$RG" --query principalId -o tsv)

# 5. Role sur le vault
az role assignment create --role "Key Vault Secrets User" \
  --assignee-object-id "$ESO_PRINCIPAL" --assignee-principal-type ServicePrincipal \
  --scope "$(az keyvault show --name "$KV" --query id -o tsv)"

# 6. Federated credential : identite <-> ServiceAccount du controleur ESO
az identity federated-credential create --name eso-external-secrets \
  --identity-name idp-eso-identity --resource-group "$RG" \
  --issuer "$OIDC_URL" \
  --subject "system:serviceaccount:external-secrets:external-secrets" \
  --audiences "api://AzureADTokenExchange"

# 7. Reporter $ESO_CLIENT_ID dans automatisation/gitops/apps/00-external-secrets.yaml
#    (serviceAccount.annotations."azure.workload.identity/client-id")
```

## Rotation d'un secret

Mettre a jour la valeur dans Key Vault — ESO la repropage automatiquement dans
le cluster (au plus tard apres `refreshInterval`, soit 1 h) :

```bash
az keyvault secret set --vault-name idp-preview-kv --name github-pat --value "<NOUVEAU_PAT>"
# rafraichissement immediat optionnel :
kubectl annotate externalsecret -A --all force-sync="$(date +%s)" --overwrite
```

## Migration depuis les secrets crees a la main

Le cluster contenait deja ces `Secret` crees manuellement. ESO v2.5 les a
**adoptes** automatiquement lors du premier sync de `external-secrets-config`
(les valeurs etant identiques, aucune coupure de service). Aucune action
manuelle n'a ete necessaire.

Si une adoption echoue (conflit de propriete), supprimer le secret concerne et
laisser ESO le recreer :

```bash
kubectl delete secret <nom> -n <namespace>   # ESO le regenere depuis Key Vault
```

## Secrets hors perimetre

Ces secrets restent generes dans le cluster (cert-manager / charts Helm) et
n'ont pas a etre dans Key Vault :

- `preview-operator-webhook-cert` (cert-manager)
- `microcks-keycloak-admin`, `microcks-mongodb-connection`, `microcks-microcks-grpc-secret` (chart Microcks)
- secrets par-agent generes par le controleur kagent
