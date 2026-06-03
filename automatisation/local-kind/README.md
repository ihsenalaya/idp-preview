# Automatisation locale — IDP Preview Platform sur **kind** + **GitHub Models**

Variante **100 % locale** de la plateforme : un cluster [kind](https://kind.sigs.k8s.io/)
sur ton poste, Argo CD en GitOps, et les **GitHub Models gratuits** comme moteur
IA (au lieu d'Azure OpenAI). Aucune dépendance Azure (ni AKS, ni Key Vault, ni
Azure OpenAI).

```
automatisation/local-kind/
├── kind-config.yaml     →  cluster kind (ports 80/443 mappés sur l'hôte)
├── .env.example         →  tokens GitHub (à copier en .env)
├── scripts/             →  up.sh / down.sh + étapes 01→04
├── gitops/              →  Argo CD App-of-Apps (10 composants)
└── examples/            →  Preview CR de démonstration
```

Le principe : **kind crée le cluster**, **un script crée les secrets**,
**Argo CD déploie la plateforme**. Tout converge en continu vers Git.

---

## 1. Différences avec la version prod (`../README.md`)

| Aspect | Prod (AKS) | Local (kind) |
|--------|-----------|--------------|
| Cluster | AKS (Terraform) | kind (`kind-config.yaml`) |
| Moteur IA | Azure OpenAI (payant) | **GitHub Models (gratuit)** |
| Secrets | Azure Key Vault + External Secrets | **Script + `.env`** (Secrets natifs) |
| Exposition previews | Istio Gateway + LoadBalancer | **ingress-nginx + nip.io** |
| Service mesh | Istio | *(retiré)* |
| Images | GHCR `ghcr.io/ihsenalaya/...` (publiques) | **identiques — tirées directement** (pas de build) |
| Composants | 16 | 10 (Istio ×4 et External-Secrets ×2 retirés) |

**Comment l'IA bascule sur GitHub Models — sans modifier le code :**

- **preview-operator** : son client AI détecte `azure.com` dans l'URL pour
  choisir le mode d'auth. On pointe `ai.apiURL` sur
  `https://models.github.ai/inference` (pas de `azure.com`) → il utilise
  `Authorization: Bearer <token>`, exactement ce qu'attend GitHub Models.
- **kagent** : provider `OpenAI` avec `config.baseUrl =
  https://models.github.ai/inference`.
- Modèles nommés avec le préfixe éditeur : **`openai/gpt-4o-mini`**.
- Token : un PAT GitHub avec le scope **`models:read`**.

---

## 2. Pré-requis

| Outil | Rôle |
|-------|------|
| Docker | moteur de conteneurs (kind tourne dedans) |
| [kind](https://kind.sigs.k8s.io/docs/user/quick-start/#installation) | cluster Kubernetes local |
| kubectl | interaction cluster |
| helm | inspection/templating des charts (utilisé par Argo CD côté serveur) |

> **Aucun build d'image.** Les images `ghcr.io/ihsenalaya/preview-operator`,
> `github-mcp-server` et `jaeger-mcp-server` sont **publiques** sur GHCR et
> tirées directement par Kubernetes. Le chart de l'opérateur est lui aussi
> public (dépôt Git `preview-operator`).

### Le token GitHub Models

1. Crée un PAT : **Settings → Developer settings → Personal access tokens**.
2. Donne-lui au minimum le scope **`models:read`** (fine-grained : permission
   *Models → read*) ; ajoute `repo` si tu veux les commentaires de PR / le runner.
3. Vérifie qu'il marche :

```bash
curl -s https://models.github.ai/inference/chat/completions \
  -H "Authorization: Bearer $GITHUB_MODELS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model":"openai/gpt-4o-mini","messages":[{"role":"user","content":"ping"}]}'
```

---

## 3. Étape 0 — Pousser cette automatisation sur Git (obligatoire)

Argo CD **tire les manifests depuis Git**, pas depuis ton disque. Les fichiers
de `automatisation/local-kind/` (et `jaeger.yaml`, `otel.yaml`, `runner.yaml`)
doivent donc exister sur une **branche** du dépôt que les Applications suivent.

Par défaut, les Applications pointent sur la branche **`local-kind`** du dépôt
`https://github.com/ihsenalaya/idp-preview`. Crée-la et pousse :

```bash
git checkout -b local-kind
git add automatisation/local-kind
git commit -m "Add local kind automation"
git push -u origin local-kind
```

> Pour utiliser un autre dépôt/branche : renseigne `GIT_REPO_URL` / `GIT_REVISION`
> dans `.env` (le root-app les prendra en compte) **et** remplace la valeur
> `targetRevision` dans les Applications enfants :
>
> ```bash
> grep -rl 'targetRevision: local-kind' automatisation/local-kind/gitops/apps \
>   | xargs sed -i 's#targetRevision: local-kind#targetRevision: <ta-branche>#'
> ```

---

## 4. Déploiement

```bash
cd automatisation/local-kind
cp .env.example .env        # puis renseigne GITHUB_TOKEN / GITHUB_MODELS_TOKEN
./scripts/up.sh
```

`up.sh` enchaîne :

| Étape | Script | Action |
|-------|--------|--------|
| 1 | `01-create-cluster.sh` | crée le cluster kind `idp-preview-local` |
| 2 | `02-secrets.sh` | crée namespaces + Secrets depuis `.env` |
| 3 | `03-bootstrap-argocd.sh` | installe Argo CD + l'App-of-Apps racine |

Ensuite Argo CD déploie tout, **wave par wave** :

| Wave | Applications |
|------|--------------|
| **-2** | cert-manager · ingress-nginx · kagent-crds |
| **-1** | opentelemetry-operator |
| **0**  | microcks · kagent |
| **1**  | **preview-operator** · observability · github-runner |
| **2**  | kagent-agents |

Suivre l'avancement :

```bash
kubectl get applications -n argocd -w        # toutes Healthy/Synced attendu
kubectl get pods -A

# UI Argo CD
kubectl -n argocd port-forward svc/argocd-server 8080:443
# https://localhost:8080  (user: admin, mot de passe affiché par l'étape 4)
```

---

## 5. Tester une preview (sans le runner CI)

```bash
kubectl apply -f examples/preview-sample.yaml
kubectl get preview -n preview-operator-system -w
```

Quand la Preview est `Ready`, ouvre :

```
http://pr-42.preview.127.0.0.1.nip.io
```

> `*.127.0.0.1.nip.io` résout toujours vers `127.0.0.1` — aucune config DNS.
> Les ports 80/443 du cluster kind sont mappés sur l'hôte, donc l'Ingress nginx
> répond directement sur `localhost`.

Voir l'enrichissement IA (seed SQL + tests générés par GitHub Models) :

```bash
kubectl describe preview preview-sample -n preview-operator-system
kubectl logs -n preview-operator-system deploy/preview-operator-controller-manager -f
```

---

## 6. Inputs (où changer quoi)

| Input | Fichier | Valeur |
|-------|---------|--------|
| Tokens GitHub | `.env` | `GITHUB_TOKEN`, `GITHUB_MODELS_TOKEN` |
| Dépôt/branche GitOps | `.env` (`GIT_*`) + `gitops/apps/*` (`targetRevision`) | `local-kind` |
| Domaine des previews | `gitops/apps/06-preview-operator.yaml` (`previewDomain`) | `preview.127.0.0.1.nip.io` |
| Endpoint IA opérateur | `gitops/apps/06-preview-operator.yaml` (`ai.apiURL`) | `https://models.github.ai/inference` |
| Endpoint/modèle IA kagent | `gitops/apps/05-kagent.yaml` (`providers.openAI`) | baseUrl + `openai/gpt-4o-mini` |
| Modèle des Preview | `examples/preview-sample.yaml` (`aiEnrichment.model`) | `openai/gpt-4o-mini` |
| Tailles cluster | `kind-config.yaml` | 1 control-plane + 2 workers |

---

## 7. Suppression

```bash
./scripts/down.sh        # kind delete cluster idp-preview-local
```

---

## 8. Limites connues du local

- **Rate limits GitHub Models** : le tier gratuit est fortement limité
  (requêtes/min + tokens/requête). Parfait pour la démo et le dev, pas pour de
  la charge. Si l'enrichissement IA renvoie des `429`, l'opérateur réessaie
  (backoff intégré) — patiente ou réduis la fréquence.
- **kagent + baseUrl** : le ModelConfig `default-model-config` est généré par le
  chart depuis `providers.openAI.config.baseUrl`. **Confirmé** avec le chart
  0.9.2 : il rend bien `spec.openAI.baseUrl: https://models.github.ai/inference`.
  Vérifier après déploiement :
  ```bash
  kubectl get modelconfig default-model-config -n kagent-system \
    -o jsonpath='{.spec.openAI.baseUrl}{"\n"}'
  ```
- **github-runner** : s'enregistre comme runner self-hosted, mais ses jobs CI
  (build/push d'images vers GHCR) supposent un accès GitHub réel. Pour tester
  l'opérateur isolément, crée des `Preview` à la main (§5).
- **microcks** : déployé avec une config locale minimale (Keycloak désactivé) ;
  ajuster `gitops/apps/04-microcks.yaml` selon les besoins.
- **Ressources** : la pile complète (cert-manager, ingress, otel, microcks,
  kagent, opérateur, jaeger, runner) demande un Docker généreux — prévoir
  ~8 Go de RAM et 4 vCPU minimum alloués à Docker.

---

## 9. Documentation liée

- [`../README.md`](../README.md) — version prod AKS (référence)
- [`../gitops/README.md`](../gitops/README.md) — détail de la couche Argo CD prod
- [`../TROUBLESHOOTING.md`](../TROUBLESHOOTING.md) — pièges (certains spécifiques à Azure)
