variable "subscription_id" {
  description = "ID de l'abonnement Azure."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group existant (partage avec le cluster de prod et le Key Vault)."
  type        = string
  default     = "idp-preview-rg"
}

variable "cluster_name" {
  description = "Nom du cluster AKS de test."
  type        = string
  default     = "idp-preview-test"
}

variable "kubernetes_version" {
  description = "Version Kubernetes. null => version par defaut d'AKS."
  type        = string
  default     = null
}

variable "node_count" {
  description = "Nombre de noeuds du node pool."
  type        = number
  default     = 3
}

variable "node_vm_size" {
  description = "Taille des VMs du node pool."
  type        = string
  default     = "Standard_D4s_v3"
}

variable "eso_identity_name" {
  description = "Managed identity existante utilisee par External Secrets Operator."
  type        = string
  default     = "idp-eso-identity"
}

variable "eso_service_account_subject" {
  description = "Sujet du federated credential : le ServiceAccount du controleur ESO."
  type        = string
  default     = "system:serviceaccount:external-secrets:external-secrets"
}

variable "tags" {
  description = "Tags appliques au cluster."
  type        = map(string)
  default = {
    environment = "test"
    project     = "idp-preview"
    managed-by  = "terraform"
  }
}
