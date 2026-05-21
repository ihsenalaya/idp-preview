# Automatisation — IDP Preview Platform

Ce dossier contient **toute l'automatisation** de la plateforme : provisioning
de l'infrastructure (Terraform) et déploiement applicatif (Argo CD GitOps).

```
automatisation/
├── terraform/   →  provisionne le cluster AKS (+ federated credential ESO)
└── gitops/      →  Argo CD App-of-Apps : déploie les 16 composants
```

Le principe : **Terraform crée le cluster**, **Argo CD déploie la plateforme
dessus**. Aucune étape manuelle de `helm install` / `kubectl apply`.

---

## 1. Pré-requis

### Outils

| Outil | Version | Rôle |
|-------|---------|------|
| Azure CLI | 2.50+ | `az login` effectué |
| Terraform | ≥ 1.5 | Provisioning du cluster |
| kubectl | 1.28+ | Interaction cluster |
| Helm | 3.14+ | Pré-installation des CRDs (via bootstrap.sh) |

### Infrastructure Azure partagée (one-time, déjà en place)

Ces ressources sont **partagées** entre tous les clusters et ne sont **pas**
gérées par ce Terraform (créées une seule fois — voir `gitops/SECRETS.md`) :

| Ressource | Nom | Rôle |
|-----------|-----|------|
| Resource group | `idp-preview-rg` | Conteneur de toutes les ressources |
| Key Vault | `idp-preview-kv` | Secrets `github-pat`, `azure-openai-key` |
| Managed identity | `idp-eso-identity` | Identité d'External Secrets (rôle `Key Vault Secrets User`) |

---

## 2. Déploiement pas à pas

### Étape 1 — Provisionner le cluster (Terraform)

```bash
cd automatisation/terraform
terraform init      # télécharge le provider azurerm
terraform plan      # vérifie le plan
terraform apply     # crée le cluster AKS + le federated credential ESO
```

Terraform crée : le cluster AKS (OIDC issuer + workload identity activés) et le
`federated credential` qui autorise External Secrets à lire le Key Vault.

### Étape 2 — Récupérer le kubeconfig

```bash
az aks get-credentials --resource-group idp-preview-rg \
  --name idp-preview-test --overwrite-existing
```

> La commande exacte est affichée dans les outputs Terraform (`get_credentials_command`).

### Étape 3 — Bootstrap Argo CD

```bash
bash automatisation/gitops/bootstrap.sh
```

Ce script : installe Argo CD, pré-installe les CRDs External Secrets en
server-side, applique le projet Argo CD et déploie l'**App-of-Apps racine**.
Il affiche le mot de passe admin Argo CD à la fin.

### Étape 4 — Synchroniser les Applications

L'App-of-Apps crée 16 Applications enfants, en **sync manuel** par défaut.
Les synchroniser **dans l'ordre des waves** (voir §4) :

```bash
# Accès à l'UI Argo CD
kubectl -n argocd port-forward svc/argocd-server 8080:443
# https://localhost:8080  (user: admin)

# ou en CLI, wave par wave :
argocd app sync cert-manager external-secrets kagent-crds istio-base   # wave -2
argocd app sync ingress-nginx istiod opentelemetry-operator external-secrets-config  # wave -1
argocd app sync istio-ingressgateway microcks kagent                   # wave 0
argocd app sync preview-operator observability github-runner           # wave 1
argocd app sync kagent-agents istio-preview-gateway                    # wave 2
```

### Étape 5 — Vérifier

```bash
kubectl get applications -n argocd      # toutes Healthy attendu
kubectl get pods -A                     # tous les pods Running
```

---

## 3. Les inputs

### 3.1 — Inputs Terraform (`terraform/`)

Renseignés dans `terraform/terraform.tfvars` ou via `-var` ; défauts dans
`terraform/variables.tf`.

| Variable | Défaut | Description |
|----------|--------|-------------|
| `subscription_id` | *(requis)* | ID de l'abonnement Azure |
| `resource_group_name` | `idp-preview-rg` | RG existant (partagé) |
| `cluster_name` | `idp-preview-test` | Nom du cluster AKS |
| `kubernetes_version` | `null` | `null` ⇒ version par défaut d'AKS |
| `node_count` | `3` | Nombre de nœuds |
| `node_vm_size` | `Standard_D4s_v3` | Taille des VMs |
| `eso_identity_name` | `idp-eso-identity` | Managed identity ESO existante |
| `eso_service_account_subject` | `system:serviceaccount:external-secrets:external-secrets` | Sujet du federated credential |
| `tags` | `{environment,project,managed-by}` | Tags du cluster |

### 3.2 — Inputs Argo CD / Helm (`gitops/`)

Valeurs à adapter selon l'environnement, dans les fichiers indiqués :

| Input | Fichier | Valeur actuelle |
|-------|---------|-----------------|
| Branche Git suivie | `gitops/argocd-config/root-app.yaml` + apps `11`-`15` (`targetRevision`) | `feat/argocd-gitops` → `main` après merge |
| Domaine des previews | `gitops/apps/10-preview-operator.yaml` (`previewDomain`) | `preview.ihsenalaya.xyz` |
| Endpoint Azure OpenAI | `gitops/apps/10-preview-operator.yaml` (`ai.apiURL`) | `https://preview-openai-idp.openai.azure.com/...` |
| Client-id de l'identité ESO | `gitops/apps/00-external-secrets.yaml` (`azure.workload.identity/client-id`) | `48c913e5-dba9-4978-b18f-39454949c32f` |
| URL du Key Vault | `gitops/manifests/external-secrets/cluster-secret-store.yaml` (`vaultUrl`) | `https://idp-preview-kv.vault.azure.net` |
| Versions des charts | chaque `gitops/apps/NN-*.yaml` (`targetRevision`) | cf. `gitops/README.md` |

### 3.3 — Inputs secrets (Azure Key Vault)

Les secrets ne sont **jamais** dans Git : ils sont lus depuis le Key Vault
`idp-preview-kv` par External Secrets Operator. Deux entrées à provisionner :

| Secret Key Vault | Contenu | Utilisé par |
|------------------|---------|-------------|
| `github-pat` | PAT GitHub (`repo`, `write:packages`) | runner, opérateur, pull GHCR, repo Argo CD |
| `azure-openai-key` | Clé API Azure OpenAI | enrichissement IA, kagent |

Détail complet et procédure de rotation : [`gitops/SECRETS.md`](gitops/SECRETS.md).

---

## 4. Les sync waves

Argo CD déploie **wave par wave** (annotation `argocd.argoproj.io/sync-wave`),
en attendant que chaque wave soit `Healthy` avant la suivante :

| Wave | Applications | Rôle |
|------|--------------|------|
| **-2** | kagent-crds · istio-base · cert-manager · external-secrets | CRDs + cert-manager |
| **-1** | ingress-nginx · istiod · opentelemetry-operator · external-secrets-config | Opérateurs + secrets ESO |
| **0** | istio-ingressgateway · microcks · kagent | Services |
| **1** | preview-operator · observability · github-runner | Workloads |
| **2** | kagent-agents · istio-preview-gateway | Ressources custom |

Ordre garanti : **CRDs → cert-manager → opérateurs → services → workloads →
ressources custom**.

---

## 5. Suppression

```bash
cd automatisation/terraform
terraform destroy        # supprime le cluster + son federated credential
```

Les ressources partagées (RG, Key Vault, identité) restent intactes.

---

## Documentation détaillée

- [`terraform/README.md`](terraform/README.md) — détail du provisioning
- [`gitops/README.md`](gitops/README.md) — détail de la couche Argo CD
- [`gitops/SECRETS.md`](gitops/SECRETS.md) — Key Vault, ESO, Workload Identity
