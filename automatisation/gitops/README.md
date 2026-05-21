# GitOps — IDP Preview Platform (Argo CD)

Cette couche GitOps reproduit **toute** la plateforme IDP Preview de maniere
declarative. Argo CD est la seule source de verite : tout composant decrit ici
est installe et reconcilie automatiquement.

## Architecture

```
bootstrap.sh
  └─ installe Argo CD + applique root-app (App-of-Apps)
       └─ root-app  ──synchronise──▶  automatisation/gitops/apps/*.yaml  (14 Applications)
                                          │
   wave -2 : external-secrets · cert-manager · kagent-crds · istio-base
   wave -1 : external-secrets-config · ingress-nginx · istiod · otel-operator
   wave  0 : istio-ingressgateway · microcks · kagent
   wave  1 : preview-operator · observability · github-runner
   wave  2 : kagent-agents · istio-preview-gateway
```

Les `sync-wave` garantissent l'ordre : CRDs et cert-manager d'abord, secrets
ensuite, puis les operateurs, puis les workloads, enfin les ressources custom.

## Composants geres

| Application | Source | Type |
|---|---|---|
| external-secrets | charts.external-secrets.io 2.5.0 | Helm |
| cert-manager | charts.jetstack.io v1.20.2 | Helm |
| ingress-nginx | kubernetes.github.io/ingress-nginx 4.15.1 | Helm |
| istio-base / istiod / istio-ingressgateway | istio-release 1.23.0 | Helm |
| opentelemetry-operator | open-telemetry 0.113.1 | Helm |
| microcks | microcks.io/helm 1.14.0 | Helm |
| kagent-crds / kagent | ghcr.io/kagent-dev (OCI) 0.9.2 | Helm |
| preview-operator | ghcr.io/ihsenalaya/charts (OCI prive) 1.0.47 | Helm |
| external-secrets-config | `automatisation/gitops/manifests/external-secrets/` | manifests |
| observability | `jaeger.yaml` + `otel.yaml` | manifests |
| github-runner | `runner.yaml` | manifests |
| kagent-agents | `k8s/kagent/` | manifests |
| istio-preview-gateway | `automatisation/gitops/manifests/istio/` | manifests |

Les secrets sont fournis par Azure Key Vault via External Secrets — voir
[SECRETS.md](SECRETS.md).

## Mise en route

```bash
# 1. Pre-requis Azure (Key Vault, identite, federation) — une seule fois.
#    Deja provisionne ; pour un cluster neuf voir SECRETS.md.

# 2. Bootstrap : installe Argo CD et l'App-of-Apps.
./automatisation/gitops/bootstrap.sh

# 3. Acces a l'UI Argo CD
kubectl -n argocd port-forward svc/argocd-server 8080:443
# https://localhost:8080  (user: admin, mot de passe affiche par bootstrap.sh)
```

## Modele de synchronisation

Toutes les Applications sont en **sync automatique** avec **self-heal** et
**prune** (`automated: { prune: true, selfHeal: true }`) :

- **root-app** : cree et met a jour les objets `Application` enfants.
- **Applications enfants** : Argo CD reconcilie en continu. Toute derive par
  rapport au Git est corrigee automatiquement (self-heal) et une ressource
  retiree du Git est elaguee (prune).

Consequence : le cluster **converge en permanence** vers l'etat decrit dans Git
— pas de derive ni de composant casse qui passe inapercu.

Forcer une synchronisation immediate (sinon Argo CD reconcilie de lui-meme dans
les ~3 min) :

```bash
argocd app sync -l argocd.argoproj.io/instance=idp-preview-root
```

Pour suspendre temporairement l'auto-sync d'un composant (ex. debug), retirer
le bloc `automated:` de son fichier `automatisation/gitops/apps/NN-*.yaml`.

## Adoption d'un cluster existant

Ce cluster a deja ete configure manuellement (Helm + kubectl). Argo CD **adopte**
les ressources existantes :

- Apps **Helm** (versions et valeurs identiques a l'existant) : le diff est nul
  ou trivial — sync sans risque.
- **Istio** : installe a l'origine via `istioctl`. Les charts Helm produisent
  des labels/annotations differents → diff important sur `istio-base`, `istiod`,
  `istio-ingressgateway`. **Revoir le diff dans l'UI avant de synchroniser** ;
  l'ingress gateway route les previews actives `*.preview.ihsenalaya.xyz`.
- **Secrets** : voir la section migration dans [SECRETS.md](SECRETS.md).

## Apres le merge de la PR

Le champ `targetRevision` pointe sur la branche `feat/argocd-gitops` pour
permettre la validation avant merge. Une fois la PR fusionnee, le remplacer
par `main` dans :

- `automatisation/gitops/argocd-config/root-app.yaml`
- `automatisation/gitops/apps/11-observability.yaml`, `12-github-runner.yaml`,
  `13-kagent-agents.yaml`, `14-istio-gateway.yaml`, `15-external-secrets-config.yaml`

```bash
grep -rl 'feat/argocd-gitops' automatisation/gitops/ | xargs sed -i 's#feat/argocd-gitops#main#'
```

## Structure

```
automatisation/gitops/
├── bootstrap.sh                  # installe Argo CD + root-app
├── README.md / SECRETS.md
├── argocd-config/
│   ├── argocd-project.yaml       # AppProject idp-preview
│   ├── repo-kagent-oci.yaml      # depot Helm OCI public kagent
│   └── root-app.yaml             # App-of-Apps racine
├── apps/                         # 00..15 — une Application par composant
└── manifests/
    ├── external-secrets/         # ClusterSecretStore + ExternalSecrets + namespaces
    └── istio/                    # Gateway preview-gateway
```
