# Terraform — cluster AKS de test idp-preview

Recree automatiquement le cluster AKS de **test** (`idp-preview-test`) avec la
configuration exacte attendue par la couche GitOps : OIDC issuer + workload
identity actives, et le federated credential pour External Secrets Operator.

## Perimetre

Ce Terraform gere **uniquement** :

- le cluster AKS de test ;
- le federated credential ESO (lie le ServiceAccount `external-secrets` a la
  managed identity `idp-eso-identity`).

Ressources **partagees** avec la prod, referencees en data sources et **non**
gerees ici : le resource group `idp-preview-rg`, le Key Vault `idp-preview-kv`,
la managed identity `idp-eso-identity` et son role `Key Vault Secrets User`.

## Pre-requis

- Terraform >= 1.5, Azure CLI authentifie (`az login`).
- La managed identity `idp-eso-identity` doit exister (creee une seule fois —
  voir `../gitops/SECRETS.md`).

## Utilisation

```bash
cd automatisation/terraform
terraform init
terraform plan
terraform apply
```

Puis deployer la plateforme via GitOps :

```bash
# 1. Recuperer le kubeconfig (commande exacte dans les outputs Terraform)
az aks get-credentials --resource-group idp-preview-rg \
  --name idp-preview-test --overwrite-existing

# 2. Bootstrap Argo CD + App-of-Apps
bash ../gitops/bootstrap.sh

# 3. Synchroniser les Applications (UI Argo CD ou `argocd app sync`)
```

## Suppression

```bash
terraform destroy
```

Supprime le cluster de test et son federated credential ; les ressources
partagees (RG, Key Vault, identite) restent intactes.

## Variables principales

| Variable | Defaut | Description |
|---|---|---|
| `cluster_name` | `idp-preview-test` | Nom du cluster |
| `node_count` | `3` | Nombre de noeuds |
| `node_vm_size` | `Standard_D4s_v3` | Taille des VMs |
| `kubernetes_version` | `null` | `null` => version par defaut d'AKS |
| `resource_group_name` | `idp-preview-rg` | RG partage |

## Etat Terraform

L'etat est local (`terraform.tfstate`) et **ignore par Git**. Pour un usage
partage/CI, configurer un backend distant (ex. `azurerm` backend sur un
Storage Account).
