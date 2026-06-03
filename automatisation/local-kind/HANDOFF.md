# HANDOFF — reprise du travail (local kind + GitHub Models)

> Document de passation pour **reprendre sur une machine plus puissante**.
> Lis-le en entier avant de continuer. Cible : finir la démo complète
> (plateforme + preview + **tests** + **kagent**) avec les **GitHub Models gratuits**.

## 0. Contexte & objectif

Décliner la plateforme IDP Preview (prod = AKS + Azure Key Vault + Azure OpenAI)
en **100 % local** : cluster **kind**, **ArgoCD** GitOps, secrets locaux, et
**GitHub Models** (gratuit) comme moteur IA — à la place d'Azure OpenAI.

Tout est dans `automatisation/local-kind/` (ne touche pas à `automatisation/`
prod, intacte).

## 1. État au moment du handoff

### ✅ Validé et fonctionnel (sur une machine 7 GiB, profil **lean**)
- **GitHub Models** : appel direct OK (`pong`) sur `https://models.github.ai/inference`,
  modèle `openai/gpt-4o-mini`, token fine-grained avec permission **Models: read**.
- **kind + ArgoCD + cert-manager + ingress-nginx + preview-operator** : 3/3 Synced/Healthy.
- **Runner self-hosted in-cluster** : enregistré, labels `self-hosted, aks, test1`.
- **Flux PR → workflow → preview COMPLET** (le vrai pipeline, sans intervention) :
  - PR #49 (modif `templates/catalog.html`) → workflow `Preview Environment`
    sur le runner → **Kaniko** build+push `ghcr.io/ihsenalaya/idp-preview:<sha>`
    → Preview multi-service (backend 8080 `/api` + frontend 3000 `/` + PostgreSQL).
  - **AI enrichment** : seed SQL **généré par GitHub Models** et appliqué à PostgreSQL
    (`/api/products` renvoie de vrais produits). Jobs `ai-schema-dump`, `ai-seed`,
    `ai-tests` = Completed.
  - UI accessible : `http://pr-49.preview.127.0.0.1.nip.io` (HTTP 200).
  - L'opérateur a commenté la PR : **« Preview Ready » + URL**.
- **Tests** : ont démarré via **FallbackPolicy** (`testplan pr-49-fullsuite` Ready,
  confidence 100 ; `testrun` Running). smoke/regression/e2e lancés ;
  **contract échoue** (Microcks non déployé en lean).

### ⚠️ Pas terminé (à finir sur la machine puissante)
- **kagent** : déployé mais sa pile **complète** (postgresql, grafana-mcp,
  querydoc, kmcp, tools, controller) **+ la preview** → **OOM sur 7 GiB**
  (control-plane tué 2×). Voir §4.
- **Images MCP privées** : `ghcr.io/ihsenalaya/github-mcp-server:latest` et
  `jaeger-mcp-server:latest` sont **PRIVÉES** → `403` au pull. Le token n'a pas
  `read:packages`. **Workaround validé** : builder en local depuis
  `idp-preview/github-mcp/` et `idp-preview/jaeger-mcp/`, `kind load`, puis
  patcher le déploiement (image locale + `imagePullPolicy: IfNotPresent`, retirer
  `imagePullSecrets`). L'image `local/github-mcp-server:dev` a déjà été buildée+chargée.
- **Microcks** non déployé (lean) → contract tests KO. À ajouter sur machine ≥16 Go.
- **test-strategist** (kagent) : non confirmé (fallback a pris le relais).
- **diff-analyzer** (kagent) : non confirmé (dépend de github-mcp-server).

## 2. LE point bloquant : la RAM

Machine actuelle = **WSL2 plafonné à 7,1 GiB**. La pile complète (16 composants)
OOM le control-plane kind. **Le vrai fix sur la nouvelle machine** :

```ini
# C:\Users\<toi>\.wslconfig
[wsl2]
memory=16GB      # ou plus ; nécessite un hôte Windows >= 24 Go
processors=6
```
Puis `wsl --shutdown` et relancer. Vérifier dans WSL : `free -h` (doit montrer ~16G).

Avec ≥16 Go : déployer la **parité complète** (les 10 apps + Microcks + kagent),
plus besoin du profil lean.

## 3. Reprise pas à pas (machine puissante)

```bash
# Pré-requis : docker, kind, kubectl, helm, gh (connecté en tant que ihsenalaya)

cd idp-preview/automatisation/local-kind
cp .env.example .env        # PUIS éditer .env (cf. §5 tokens)
./scripts/up.sh             # cluster + secrets + ArgoCD bootstrap

# Déployer toutes les apps (root-app) — nécessite la branche local-kind poussée (faite, cf. §6)
# Le root-app pointe sur GIT_REVISION du .env (= local-kind).
kubectl get applications -n argocd -w     # attendre Healthy

# Déclencher le flux preview comme en prod : ouvrir/mettre à jour une PR
# (le runner in-cluster build + crée le Preview). Voir .github/workflows/preview.yaml
```

### Pour kagent (sur ≥16 Go)
- Apps `03-kagent-crds`, `05-kagent`, `09-kagent-agents` (déjà dans `gitops/apps/`).
- `05-kagent.yaml` configure déjà GitHub Models (provider OpenAI + `config.baseUrl`
  = `https://models.github.ai/inference`). **Confirmé** : le chart 0.9.2 rend bien
  `default-model-config` avec `spec.openAI.baseUrl`.
- **Images MCP** : comme privées, builder en local + `kind load` + patcher
  (cf. §1 ⚠️), OU obtenir un token `read:packages` et garder `ghcr-pull-secret`.
- Si RAM serrée, alléger : `ui.replicas: 0` (fait dans la version testée) ;
  envisager de désactiver grafana-mcp / querydoc / kmcp si possible.

### Pour les tests complets
- Déployer **Microcks** (app `04-microcks.yaml`) pour les contract tests.
- testStrategy mode `Auto` : si kagent (test-strategist) répond avant
  `agentTimeoutSeconds`, il choisit les suites ; sinon **FallbackPolicy = Full**.

## 4. Pourquoi l'OOM (technique)

- Control-plane kind = conteneur Docker ; sous pression mémoire il sort en
  `Exited (128)` → API injoignable. **Récup** : `docker start
  idp-preview-local-control-plane` puis attendre ~20 s.
- kagent 0.9.2 déploie BEAUCOUP (postgresql + grafana-mcp + querydoc + kmcp +
  tools + controller + ui). ~1 Go+. Incompatible avec une preview (postgres +
  2 apps + jobs) sur 7 Go.

## 5. Tokens (IMPORTANT — sécurité)

- **NE PAS coller un PAT dans le chat** : GitHub le révoque en ~2 min (détection
  de fuite). Mets-le **directement dans `.env`** (gitignoré) ou dans l'UI GitHub.
- `GITHUB_TOKEN` (push/PR/runner) : réutilisé depuis `gh`
  (`/home/ihsen/.config/gh/hosts.yml` → `oauth_token`). Scopes : `repo, workflow,
  read:org, gist`. **Pas** `read:packages` (d'où le 403 sur images privées).
- `GITHUB_MODELS_TOKEN` : fine-grained PAT, **Account permission → Models: Read**.
  Créer sur https://github.com/settings/personal-access-tokens/new. Tester :
  `curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer <T>" https://api.github.com/user` → 200.
- Secret Actions repo **`PREVIEW_GITHUB_TOKEN`** : déjà configuré (push GHCR via
  Kaniko). Le package `idp-preview` (image app) doit être pullable par le cluster
  (public, ou pull secret).

## 6. Git / branche

- Toute l'automatisation est sur la branche **`local-kind`** (poussée).
- Les apps ArgoCD pointent sur `targetRevision: local-kind` ; le runner et les
  manifests bruts (`k8s/kagent`, `jaeger.yaml`, `otel.yaml`, `runner.yaml`)
  existent aussi sur `main`.
- La PR de démo #49 est sur la branche `feat/catalog-banner-demo`.
- `.env` n'est **jamais** committé (`.gitignore`).

## 7. Détails utiles déjà découverts

- L'opérateur **auto-détecte** l'absence d'Istio → expose les previews en
  **Ingress nginx** (`pr-<N>.preview.127.0.0.1.nip.io`).
- Bug opérateur (single-service) : Ingress backend port `80` vs Service `8080`
  → 503. Le **multi-service** (généré par `scripts/generate_preview_manifest.py`)
  n'a pas ce bug (utilise `svc.Port`).
- App du repo : Flask, backend `app.py` (8080, `/healthz`, API produits/catégories),
  frontend `frontend.py` (3000, sert l'UI, proxy `/api` → `BACKEND_URL`).
- Readiness opérateur : `GET /healthz` sur le port → l'image doit répondre 200.
