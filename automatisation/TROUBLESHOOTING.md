# Troubleshooting — pièges rencontrés en provisioning

Ce document liste les vrais pièges rencontrés lors du provisioning d'un cluster
neuf via `automatisation/`. Pour chacun : symptôme, cause, fix.

---

## 1. Azure OpenAI restauré d'un soft-delete → DNS NXDOMAIN

### Symptôme

L'AI enrichment de `preview-operator` échoue avec :

```
Post "https://preview-openai-idp.openai.azure.com/openai/deployments/gpt-4o-mini/chat/completions":
  dial tcp: lookup preview-openai-idp.openai.azure.com on 10.0.0.10:53: no such host
```

Et `nslookup preview-openai-idp.openai.azure.com 8.8.8.8` retourne `NXDOMAIN`
— **même depuis l'extérieur du cluster**. Côté `az` :

```bash
az cognitiveservices account show -n preview-openai-idp -g idp-preview-rg \
  --query '{state:properties.provisioningState, endpoint:properties.endpoint}'
# {"state": "Succeeded", "endpoint": "https://preview-openai-idp.openai.azure.com/"}
```

Azure considère la ressource opérationnelle, mais son enregistrement DNS A
public **n'a jamais été (re)publié**.

### Cause

Quand un compte Cognitive Services / Azure OpenAI est supprimé puis restauré
via `az cognitiveservices account recover`, **le DNS public n'est pas
toujours re-publié**. C'est un bug Azure connu : la ressource a tous ses
métadonnées correctes mais la zone DNS publique
(`<name>.openai.azure.com`) garde l'état "supprimé" et retourne NXDOMAIN.

Un simple `az cognitiveservices account update` ne resynchronise pas le DNS.

### Fix

**Purger puis recréer** la ressource. Le nouveau record A est propagé en ~1
minute.

```bash
NAME=preview-openai-idp
RG=idp-preview-rg
LOC=eastus

# 1. delete (soft-delete state)
az cognitiveservices account delete -n "$NAME" -g "$RG"

# 2. purge — supprime définitivement l'entrée soft-deleted (libère le nom)
az cognitiveservices account purge -n "$NAME" --resource-group "$RG" --location "$LOC"

# 3. recreate avec le même nom (et donc même endpoint)
az cognitiveservices account create -n "$NAME" -g "$RG" -l "$LOC" \
  --kind OpenAI --sku S0 --custom-domain "$NAME" --yes

# 4. redéployer le modèle
az cognitiveservices account deployment create \
  -n "$NAME" -g "$RG" --deployment-name gpt-4o-mini \
  --model-name gpt-4o-mini --model-version "2024-07-18" --model-format OpenAI \
  --sku-name "GlobalStandard" --sku-capacity 30

# 5. récupérer la nouvelle clé et la pousser dans le Key Vault
AOAI_KEY=$(az cognitiveservices account keys list -n "$NAME" -g "$RG" --query key1 -o tsv | tr -d '\r\n')
az keyvault secret set --vault-name idp-preview-kv --name azure-openai-key --value "$AOAI_KEY"

# 6. forcer ESO à re-synchroniser + bounce les pods pour purger leur cache DNS
kubectl annotate externalsecret -A --all force-sync="$(date +%s)" --overwrite
kubectl rollout restart deployment/preview-operator -n preview-operator-system
for d in preview-troubleshooter-agent preview-diff-analyzer test-strategist-agent; do
  kubectl rollout restart deployment/$d -n kagent-system
done
```

Vérifier que la résolution DNS marche **depuis l'intérieur du cluster** :

```bash
kubectl run -n default --rm -i --restart=Never --image=tutum/dnsutils dnstest \
  -- dig +short preview-openai-idp.openai.azure.com
# doit retourner un CNAME → trafficmanager → A (ex. 20.232.91.78)
```

### Comment éviter le piège

- **Ne jamais `az cognitiveservices account recover`** pour un compte
  utilisé en production. Toujours purger + recréer si le compte a été
  supprimé.
- Si on doit absolument restaurer, vérifier le DNS public **avant** de
  bouncer le cluster :
  ```bash
  nslookup <name>.openai.azure.com 8.8.8.8
  ```

---

## 2. kagent troubleshooter "Failed" alors que l'agent a complété

### Symptôme

```bash
kubectl get preview pr-42 -o jsonpath='{.status.kagent.phase}'
# Failed

kubectl logs -n preview-operator-system deployment/preview-operator | grep kagent
# ERROR kagent analysis failed   error="agent returned failed state"
```

Mais les logs du pod `preview-troubleshooter-agent` montrent un run terminé
proprement (`Runner closed.`).

### Cause

L'agent kagent **appelle Azure OpenAI** pour produire son analyse. Si l'API
OpenAI échoue (DNS NXDOMAIN, throttling, quota dépassé, clé invalide),
l'agent **réussit techniquement** sa session A2A mais retourne un `state:
failed` dans le résultat — et le preview-operator interprète ça comme
`status.kagent.phase=Failed`.

Les logs du pod montrent typiquement :

```
openai._base_client - INFO - Retrying request to /chat/completions in 0.4s
openai._base_client - INFO - Retrying request to /chat/completions in 0.9s
```

Les retries s'épuisent → l'agent renvoie le state failed.

### Fix

C'est un symptôme du problème **§1 OpenAI DNS** ou d'un autre problème de
provider AI (quota, clé). Procédure :

1. Vérifier que l'AI enrichment du Preview marche
   (`status.aiEnrichment.phase = Succeeded`). Si l'AI échoue avec une
   erreur DNS, **fixer §1 d'abord**, kagent suit naturellement.
2. Si l'AI marche mais kagent échoue, vérifier le `ModelConfig` kagent :
   ```bash
   kubectl get modelconfig default-model-config -n kagent-system -o yaml
   ```
   Confirmer que `apiKeySecret`, `apiKeySecretKey`, `azureEndpoint` et
   `azureDeployment` correspondent à la ressource Azure OpenAI.
3. Vérifier le secret `kagent-openai` :
   ```bash
   kubectl -n kagent-system get secret kagent-openai \
     -o jsonpath='{.data.OPENAI_API_KEY}' | base64 -d | wc -c
   # doit retourner 84 (taille standard d'une clé Azure OpenAI)
   ```
4. Bouncer les agents :
   ```bash
   for d in preview-troubleshooter-agent preview-diff-analyzer test-strategist-agent; do
     kubectl rollout restart deployment/$d -n kagent-system
   done
   ```
5. Re-trigger kagent en supprimant et recréant le Preview (le
   troubleshooter ne se relance pas tant que les tests ne re-échouent
   pas — cooldown 5 min).

### Comment éviter le piège

- Provisionner Azure OpenAI **avant** de bootstrap Argo CD. Si la clé
  n'est pas dans le Key Vault à l'instant du bootstrap, ESO ne pourra
  pas matérialiser `kagent-openai` → tous les agents démarreront avec
  une config OpenAI invalide.
- Tester l'endpoint depuis un pod du cluster **avant** de lancer un
  Preview :
  ```bash
  AOAI_KEY=$(kubectl -n kagent-system get secret kagent-openai \
    -o jsonpath='{.data.OPENAI_API_KEY}' | base64 -d)
  kubectl run aoai-test -n default --rm -i --restart=Never \
    --image=curlimages/curl:latest --command -- \
    curl -sS -m 30 -w "HTTP=%{http_code}\n" \
      -H "api-key: $AOAI_KEY" -H "Content-Type: application/json" \
      "https://preview-openai-idp.openai.azure.com/openai/deployments/gpt-4o-mini/chat/completions?api-version=2024-10-21" \
      -d '{"messages":[{"role":"user","content":"hi"}],"max_tokens":5}'
  # Attendu : HTTP=200
  ```

---

## 3. Compte MSA invité ne peut pas s'attribuer un rôle RBAC sur le Key Vault

### Symptôme

```bash
az role assignment create --role "Key Vault Secrets Officer" \
  --assignee-object-id $(az ad signed-in-user show --query id -o tsv) \
  --assignee-principal-type User \
  --scope $(az keyvault show --name idp-preview-kv --query id -o tsv)
# ERROR: Operation returned an invalid status 'Bad Request'
```

Ou avec `--assignee` :

```
ERROR: Cannot find user or service principal in graph database for '...'.
```

### Cause

Si le compte signé est un **Microsoft Account** (MSA, `@outlook.com`,
`@hotmail.com`) **invité** dans le tenant Azure AD (UPN avec `#EXT#`),
Microsoft Graph ne le résout pas pour `az role assignment create` même
quand on fournit explicitement l'object-id. Le CLI échoue avec "Bad
Request" / "Cannot find user".

Ce n'est PAS un problème de droits : le compte est Owner de la
souscription. C'est un bug de résolution Graph du CLI sur les guests MSA.

### Fix

Passer par l'**API REST directement** — elle n'a pas cette validation
Graph :

```bash
SUB=$(az account show --query id -o tsv)
USER_OID=$(az ad signed-in-user show --query id -o tsv)
KV_ID=$(az keyvault show --name idp-preview-kv --query id -o tsv)

# Role IDs des rôles built-in Key Vault :
#   Key Vault Secrets Officer (lecture + écriture) : b86a8fe4-44ce-4948-aee5-eccb2c155cd7
#   Key Vault Secrets User    (lecture seule)      : 4633458b-17de-408a-b874-0445c86b69e6
ROLE_DEF_ID="/subscriptions/$SUB/providers/Microsoft.Authorization/roleDefinitions/b86a8fe4-44ce-4948-aee5-eccb2c155cd7"

az rest --method PUT \
  --uri "https://management.azure.com${KV_ID}/providers/Microsoft.Authorization/roleAssignments/$(uuidgen)?api-version=2022-04-01" \
  --body "{\"properties\":{\"roleDefinitionId\":\"${ROLE_DEF_ID}\",\"principalId\":\"${USER_OID}\",\"principalType\":\"User\"}}"
```

Alternative : le portail Azure gère mieux les guests MSA. IAM → Add role
assignment → sélectionner l'utilisateur fonctionne directement.

### Comment éviter le piège

Pour un déploiement multi-utilisateurs ou CI, créer un **Service
Principal** avec `az ad sp create-for-rbac` et utiliser celui-là pour
toutes les opérations Key Vault. Les SP sont toujours résolvables.

---

## 4. WSL : `az aks get-credentials` écrit dans `C:\Users\...\.kube\config`, pas dans `$HOME/.kube/config`

### Symptôme

```bash
az aks get-credentials --resource-group idp-preview-rg --name idp-preview-test
# WARNING: Merged "idp-preview-test" as current context in C:\Users\Ihsen\.kube\config

kubectl get nodes
# error: no context exists with the name: "idp-preview-test"
```

### Cause

Sur WSL, `az` est typiquement le binaire **Windows** (`/mnt/c/Program
Files/Microsoft SDKs/Azure/CLI2/wbin/az`). Il écrit son kubeconfig dans
le profil Windows (`C:\Users\<user>\.kube\config`). Mais `kubectl` (WSL)
lit `/home/<user>/.kube/config`. Les deux fichiers sont distincts.

### Fix

Utiliser la pipeline qui fusionne dans le bon fichier (déjà documentée
dans `idp-preview/README.md` §3 Step 1) :

```bash
az aks get-credentials \
  --resource-group idp-preview-rg \
  --name idp-preview-test \
  --file - 2>/dev/null \
  | KUBECONFIG="$HOME/.kube/config":/dev/stdin kubectl config view --merge --flatten \
  > /tmp/merged-kube && mv /tmp/merged-kube "$HOME/.kube/config"

kubectl config use-context idp-preview-test
```

Le `--file -` envoie le kubeconfig sur stdout, qu'on merge avec celui
existant en WSL via `kubectl config view --merge`.

### Comment éviter le piège

Préférer le binaire `az` Linux (installé via `apt` ou `pip`) sur WSL :
plus de conflit de chemin.

---

## 5. FQDN AKS périmé dans le kubeconfig après recréation rapide du cluster

### Symptôme

Après `terraform destroy && terraform apply` sur le même nom de cluster :

```bash
kubectl get nodes
# Unable to connect to the server: dial tcp: lookup idp-preview-test-d0fkhgbc.hcp.eastus.azmk8s.io: no such host
```

Le FQDN dans le kubeconfig (`-d0fkhgbc`) n'est pas le bon (le vrai est
maintenant `-ojw043um` par exemple).

### Cause

Azure assigne un **nouveau** suffixe DNS à chaque création AKS. Le
kubeconfig précédent garde l'ancien FQDN, et `--overwrite-existing`
n'écrase pas systématiquement la section `clusters` correctement.

### Fix

Supprimer explicitement les anciennes entrées avant de re-fetcher :

```bash
kubectl config delete-context idp-preview-test
kubectl config delete-cluster idp-preview-test
kubectl config delete-user clusterUser_idp-preview-rg_idp-preview-test

# Puis re-fetch (avec la pipeline WSL du §4)
az aks get-credentials --resource-group idp-preview-rg --name idp-preview-test --file - \
  | KUBECONFIG="$HOME/.kube/config":/dev/stdin kubectl config view --merge --flatten \
  > /tmp/merged && mv /tmp/merged "$HOME/.kube/config"
```

---

## 6. Cluster AKS trop petit — pods Pending "Insufficient CPU"

### Symptôme

Un `Preview` créé ne devient jamais Running. Les pods `svc-backend` ou
`postgres` restent en Pending :

```
FailedScheduling: 0/N nodes are available: N Insufficient cpu.
```

Pourtant `kubectl top nodes` montre une utilisation CPU réelle faible
(15-30 %).

### Cause

Kubernetes schedule sur les **CPU requests**, pas l'usage réel.
La pile complète idp-preview (kagent + microcks + istio +
ingress-nginx + kube-system AKS) consomme **~5660m de requests**. Sur
3×D2s_v3 (allocatable ~5100m après réserve AKS), on est déjà
au-dessus avant même de schedule un Preview.

### Fix

Le sizing **par défaut** dans `terraform/variables.tf` est
`Standard_D4s_v3` × 3 = 12 vCPU. **Ne pas descendre en dessous** pour la
pile complète. Sizing minimal :

| Composants | CPU requests | Recommandé |
|---|---:|---|
| AKS overhead (kube-system) | ~2200m | non-réductible |
| kagent + agents (13) | ~1700m | non-réductible si troubleshooter activé |
| microcks (4 pods) | ~950m | non-réductible si contract testing activé |
| istio (control + gateway) | ~600m | non-réductible si Istio activé |
| 1 Preview moyen | ~500m | varie selon `resourceTier` |
| **TOTAL minimal** | **~6000m** | **2×D4s_v3 ou 4×D2s_v3** |

Pour 5+ Previews simultanés : **3×D4s_v3** (la valeur par défaut de
`variables.tf`).

### Diagnostic rapide

```bash
kubectl get pods -A -o json | python3 -c '
import sys, json
from collections import defaultdict
ns = defaultdict(int)
for p in json.load(sys.stdin)["items"]:
    if p["status"].get("phase") not in ("Running", "Pending"): continue
    for c in p["spec"].get("containers", []):
        v = c.get("resources", {}).get("requests", {}).get("cpu", "0m")
        ns[p["metadata"]["namespace"]] += int(v[:-1]) if v.endswith("m") else int(float(v)*1000) if v else 0
for n, v in sorted(ns.items(), key=lambda x: -x[1]):
    print(f"{n:<28} {v:>5}m")
'
```

---

## 7. DNS wildcard `*.preview.<zone>` non repointé après recréation cluster

### Symptôme

Après création d'un nouveau cluster, le `Preview` est Running, mais
`curl http://pr-N.preview.<zone>` retourne un timeout ou affiche
l'ancien cluster.

### Cause

L'IP publique de `istio-ingressgateway` change à chaque création de
cluster. Le record DNS A pour `*.preview.<zone>` pointe encore sur
l'ancien LoadBalancer.

### Fix

Documenté dans `automatisation/README.md` §5.4. Récupérer l'IP du
nouveau gateway et repointer :

```bash
NEW_IP=$(kubectl -n istio-system get svc istio-ingressgateway \
  -o jsonpath='{.status.loadBalancer.ingress[0].ip}')

az network dns record-set a delete \
  --resource-group <DNS_RG> --zone-name <ZONE> --name '*.preview' --yes

az network dns record-set a add-record \
  --resource-group <DNS_RG> --zone-name <ZONE> \
  --record-set-name '*.preview' --ipv4-address "$NEW_IP" --ttl 300
```

Pour tester avant la propagation DNS, utiliser le `Host` header :

```bash
curl -H "Host: pr-42.preview.<zone>" "http://$NEW_IP/"
```

---

## 8. Argo CD repo-server : `failed to list refs ... context deadline exceeded`

### Symptôme

Plusieurs Applications affichent `SYNC=Unknown` ou `OutOfSync`, et
`kubectl get application <name> -n argocd -o yaml` montre :

```
ComparisonError: failed to generate manifest for source 1 of 1:
  rpc error: failed to list refs: Get "https://github.com/..../info/refs":
  context deadline exceeded
```

### Cause

Sur un cluster AKS frais, la sortie réseau via le LoadBalancer est
parfois lente pendant les premières minutes (NAT pas chaud, DNS
warm-up). Le timeout par défaut du `argocd-repo-server` (60 s) peut
être trop court.

### Fix

Augmenter les timeouts :

```bash
kubectl set env deployment/argocd-repo-server -n argocd \
  ARGOCD_EXEC_TIMEOUT=3m \
  ARGOCD_GIT_REQUEST_TIMEOUT=3m \
  ARGOCD_REPO_SERVER_LISTEN_TIMEOUT=180 \
  --overwrite

kubectl -n argocd rollout status deploy/argocd-repo-server

# Forcer une nouvelle comparaison sur chaque Application
for app in $(kubectl get application -n argocd -o name); do
  kubectl annotate "$app" -n argocd argocd.argoproj.io/refresh=hard --overwrite
done
```

---

## Quick-fix script

Tous ces fixes regroupés (à lancer après un `terraform apply` neuf) :

```bash
#!/usr/bin/env bash
set -euo pipefail
RG=idp-preview-rg
KV=idp-preview-kv
CLUSTER=idp-preview-test

# 1. kubeconfig WSL-safe
az aks get-credentials -g "$RG" -n "$CLUSTER" --file - \
  | KUBECONFIG="$HOME/.kube/config":/dev/stdin kubectl config view --merge --flatten \
  > /tmp/merged && mv /tmp/merged "$HOME/.kube/config"
kubectl config use-context "$CLUSTER"

# 2. Argo CD repo-server timeouts (post-bootstrap)
kubectl set env deployment/argocd-repo-server -n argocd \
  ARGOCD_EXEC_TIMEOUT=3m ARGOCD_GIT_REQUEST_TIMEOUT=3m \
  ARGOCD_REPO_SERVER_LISTEN_TIMEOUT=180 --overwrite

# 3. Vérifier que l'endpoint Azure OpenAI résout
nslookup preview-openai-idp.openai.azure.com 8.8.8.8 | tail -3
# Si NXDOMAIN → voir §1 (purge + recreate)
```
