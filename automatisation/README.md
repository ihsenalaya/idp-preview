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

### Étape 4 — Synchronisation automatique

L'App-of-Apps crée 16 Applications enfants, toutes en **sync automatique**
(`automated` + `selfHeal` + `prune`). Argo CD déploie et reconcilie tout seul,
dans l'ordre des waves (voir §4) — rien à lancer manuellement.

```bash
# Accès à l'UI Argo CD pour suivre l'avancement
kubectl -n argocd port-forward svc/argocd-server 8080:443
# https://localhost:8080  (user: admin)

# Forcer une synchro immédiate (optionnel) :
argocd app sync -l argocd.argoproj.io/instance=idp-preview-root
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

## 5. Bascule vers un nouveau cluster

Procédure générique pour migrer la plateforme d'un cluster existant vers un
nouveau (montée de version Kubernetes, changement de région, recréation
propre…). Le principe : on **monte le nouveau cluster en parallèle**, on le
valide, on bascule le trafic, puis on décommissionne l'ancien.

### 5.1 — Provisionner le nouveau cluster

Choisir un **nom distinct** pour ne pas écraser l'ancien :

```bash
cd automatisation/terraform
terraform apply -var 'cluster_name=idp-preview-v2'
# (ou modifier cluster_name dans terraform.tfvars)
```

Terraform crée le nouveau cluster **et** son federated credential ESO (chaque
cluster a son propre OIDC issuer — c'est géré automatiquement).

### 5.2 — Déployer la plateforme dessus

Rejouer les **étapes 2 à 4** sur le nouveau cluster : `get-credentials`,
`bootstrap.sh`, puis synchronisation des waves.

### 5.3 — Basculer le contexte kubectl

```bash
az aks get-credentials --resource-group idp-preview-rg \
  --name idp-preview-v2 --overwrite-existing
kubectl config use-context idp-preview-v2
kubectl config get-contexts          # vérifier le contexte actif (*)
```

### 5.4 — Repointer le DNS wildcard

Le nouvel ingress gateway Istio a une **nouvelle IP publique**. Récupérer l'IP
et mettre à jour l'enregistrement DNS `*.preview.<domaine>` :

```bash
NEW_IP=$(kubectl -n istio-system get svc istio-ingressgateway \
  -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo "Nouvelle IP : $NEW_IP"

az network dns record-set a delete \
  --resource-group <DNS_RG> --zone-name <ZONE> --name '*.preview' --yes
az network dns record-set a add-record \
  --resource-group <DNS_RG> --zone-name <ZONE> \
  --record-set-name '*.preview' --ipv4-address "$NEW_IP" --ttl 300
```

Tant que le DNS n'est pas propagé, tester via port-forward :
`kubectl -n <preview-ns> port-forward svc/svc-frontend 3000:3000`.

### 5.5 — Basculer le pipeline CI

Le runner GitHub Actions tourne **dans le cluster**. Une fois le nouveau
cluster déployé, son runner (label `test1`) se ré-enregistre et prend le
relais : les previews suivantes se déploient sur le nouveau cluster. Vérifier :

```bash
gh api repos/<owner>/<repo>/actions/runners \
  --jq '.runners[] | {name,status,labels:[.labels[].name]}'
```

### 5.6 — Vérifier puis décommissionner l'ancien

```bash
kubectl get applications -n argocd      # 17 Applications Healthy
# ouvrir/mettre à jour une PR pour valider un Preview de bout en bout
```

Une fois la bascule validée, supprimer l'ancien cluster (voir §6) — en pointant
Terraform sur l'**ancien** `cluster_name`, ou via `az aks delete`.

---

## 6. Suppression

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
