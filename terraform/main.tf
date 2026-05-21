# =============================================================================
# Cluster AKS de test idp-preview — recreation automatique.
#
# Provisionne uniquement le cluster de TEST et son federated credential ESO.
# Le resource group, le Key Vault et la managed identity `idp-eso-identity`
# sont PARTAGES avec le cluster de prod : ils sont reference en data sources,
# jamais recrees ici.
#
# Apres `terraform apply` : recuperer les credentials puis lancer le bootstrap
# GitOps (voir terraform/README.md et gitops/bootstrap.sh).
# =============================================================================

# --- Ressources existantes (partagees, non gerees par ce Terraform) ----------
data "azurerm_resource_group" "rg" {
  name = var.resource_group_name
}

data "azurerm_user_assigned_identity" "eso" {
  name                = var.eso_identity_name
  resource_group_name = var.resource_group_name
}

# --- Cluster AKS de test -----------------------------------------------------
resource "azurerm_kubernetes_cluster" "test" {
  name                = var.cluster_name
  location            = data.azurerm_resource_group.rg.location
  resource_group_name = data.azurerm_resource_group.rg.name
  dns_prefix          = var.cluster_name
  kubernetes_version  = var.kubernetes_version
  sku_tier            = "Free"

  # Requis par External Secrets Operator (authentification Azure Workload Identity).
  oidc_issuer_enabled       = true
  workload_identity_enabled = true

  default_node_pool {
    name       = "nodepool1"
    node_count = var.node_count
    vm_size    = var.node_vm_size
  }

  identity {
    type = "SystemAssigned"
  }

  tags = var.tags
}

# --- Federated credential pour External Secrets Operator ---------------------
# Lie le ServiceAccount du controleur ESO de CE cluster a la managed identity
# `idp-eso-identity` (qui a deja le role "Key Vault Secrets User" sur le vault).
resource "azurerm_federated_identity_credential" "eso" {
  name                = "eso-external-secrets-${var.cluster_name}"
  resource_group_name = var.resource_group_name
  parent_id           = data.azurerm_user_assigned_identity.eso.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = azurerm_kubernetes_cluster.test.oidc_issuer_url
  subject             = var.eso_service_account_subject
}
