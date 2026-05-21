output "cluster_name" {
  description = "Nom du cluster AKS cree."
  value       = azurerm_kubernetes_cluster.test.name
}

output "oidc_issuer_url" {
  description = "URL de l'OIDC issuer (utilisee par le federated credential ESO)."
  value       = azurerm_kubernetes_cluster.test.oidc_issuer_url
}

output "eso_federated_credential" {
  description = "Nom du federated credential ESO cree."
  value       = azurerm_federated_identity_credential.eso.name
}

output "get_credentials_command" {
  description = "Commande pour recuperer le kubeconfig du cluster."
  value       = "az aks get-credentials --resource-group ${var.resource_group_name} --name ${azurerm_kubernetes_cluster.test.name} --overwrite-existing"
}

output "next_steps" {
  description = "Etapes suivantes pour deployer la plateforme via GitOps."
  value       = <<-EOT
    1. az aks get-credentials --resource-group ${var.resource_group_name} --name ${azurerm_kubernetes_cluster.test.name} --overwrite-existing
    2. bash ../gitops/bootstrap.sh
    3. Synchroniser les Applications dans l'UI Argo CD (ou `argocd app sync`).
  EOT
}
