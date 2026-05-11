# Talk Proposal — KCD Provence 2025

---

## Title

**Preview Environments à la Demande : Operator Kubernetes, IA et Tests Automatisés sur Chaque PR**

*(English title for international abstract submission:)*
*"Preview Environments on Demand: Kubernetes Operator, AI-Generated Data, and Contract Tests on Every Pull Request"*

---

## Elevator Pitch *(~55 words)*

Chaque pull request mérite un vrai environnement — sa propre base de données, sa propre URL, ses propres tests. Nous avons construit un opérateur Kubernetes qui provisionne tout ça en 90 secondes : isolation réseau, image build in-cluster, seed SQL généré par IA depuis le diff Git, tests de contrat Microcks, et un agent kagent qui explique les échecs directement dans le PR.

---

## Abstract *(~300 words)*

Les environnements de preview sont l'un des outils les plus rentables d'une plateforme développeur moderne — ils permettent de cliquer avant de merger, de détecter les régressions avant la production, et de donner à la QA un environnement réaliste isolé par branche. Le problème : les construire correctement est surprenamment difficile. Il faut gérer le build d'image, le provisionnement d'une base de données, le routage, l'orchestration des tests, le nettoyage automatique — le tout de façon isolée pour chaque PR simultanée.

Ce talk présente `preview-operator`, un opérateur Kubernetes production-grade construit avec kubebuilder, qui automatise tout ce pipeline. Quand un développeur ouvre une PR, un workflow GitHub Actions crée une Custom Resource `Preview`. L'opérateur la réconcilie : il provisionne un namespace dédié avec NetworkPolicy et Pod Security Standards, build l'image avec Kaniko sur des runners self-hosted AKS, provisionne un PostgreSQL éphémère avec des credentials uniques par PR, génère du SQL de seed et des tests d'intégration via un LLM à partir du diff Git réel, exécute 8 étapes de tests séquentielles (smoke, contrat Microcks, régression, E2E Playwright) avec isolation de base de données entre chaque suite, et publie les résultats structurés en commentaire de PR — incluant une analyse de cause racine par un agent kagent si un test échoue.

Le talk couvre aussi l'aspect économique : resource tiers, TTL auto-expiry, et un AI Test Strategist (deuxième agent kagent) qui analyse le diff pour décider quels suites lancer — et skip les autres.

**C'est un talk de praticien avec démo live.** Vrai cluster AKS, vraies PRs, vraies pannes — et un opérateur qui les gère.

---

## Architecture du Système

### Vue d'ensemble — du `git push` au commentaire de PR

```
Developer
  git push → gh pr create
        │
        │  pull_request: opened / synchronize
        ▼
┌──────────────────────────────────────────────────────────────────┐
│  GitHub Actions   (.github/workflows/preview.yaml)               │
│  runs-on: [self-hosted, aks]  ← runner pod dans le cluster AKS  │
│                                                                  │
│  1. Kaniko Job  ──► build image depuis HEAD ──► push GHCR        │
│  2. generate_preview_manifest.py                                 │
│       git diff base...head → classifie chaque fichier           │
│       (backend / frontend / database-migration / api-contract)   │
│       écrit Preview CR avec changeContext + diffPatch (64 KiB)  │
│  3. kubectl apply preview-pr-<N>.yaml                           │
└──────────────────────────────────┬───────────────────────────────┘
                                   │ CR écrit dans etcd
                                   ▼
┌──────────────────────────────────────────────────────────────────┐
│  preview-operator  (controller-runtime, reconcile loop)          │
│                                                                  │
│  PHASE: Provisioning                                             │
│    ├── Namespace preview-pr-<N>                                  │
│    │     ├── NetworkPolicy (ingress: inter-pod + ingress-nginx)  │
│    │     │   (egress: ouvert — AI calls, GHCR, GitHub API)       │
│    │     └── PSS labels: enforce:baseline  warn:restricted       │
│    ├── ResourceQuota  (tier: small / medium / large)             │
│    ├── PostgreSQL éphémère  (credentials uniques par PR)         │
│    ├── Job: postgres-migrate  (Alembic, optionnel)               │
│    ├── Job: postgres-seed     (SQL statique, optionnel)          │
│    ├── Deployments: svc-backend:8080 + svc-frontend:3000         │
│    └── Exposition: VirtualService Istio ou Ingress nginx         │
│                    (auto-détecté au démarrage)                    │
│                                                                  │
│  PHASE: Running                                                  │
│    ├── Commentaire PR: "🔄 Preview en cours…" → "## Preview Ready"│
│    │                                                              │
│    ├── [AI ENRICHMENT — bloque les tests tant que non terminé]   │
│    │   Job 1: ai-schema-dump  ──► pg_dump --schema-only          │
│    │   Inline:  controller appelle LLM (diff + schéma + prompt)  │
│    │            LLM répond: { seed.sql, test.py }                 │
│    │            stocké dans ConfigMap "ai-enrichment"            │
│    │   Job 2: ai-seed  ──► psql seed.sql → 10 produits, reviews  │
│    │   Job 3: ai-tests ──► python test.py (tests ciblés sur diff) │
│    │                                                              │
│    ├── [TEST STRATEGY — mode: Auto]                              │
│    │   Crée un stub TestPlan (phase=Pending)                     │
│    │   Crée un Job éphémère (curlimages/curl, TTL=300s)          │
│    │     → POST A2A JSON-RPC → test-strategist-agent (kagent)    │
│    │   Agent lit changeContext.changedFiles + diffPatch           │
│    │   Répond: mustRun=[smoke,regression] canSkip=[contract,e2e]  │
│    │   Contrôleur accepte si confidence ≥ 70 (sinon: FullSuite)  │
│    │                                                              │
│    └── [TEST SUITE — 8 étapes séquentielles]                    │
│        1. suite-checkpoint-save ──► pg_dump → ConfigMap          │
│        2. smoke-tests           ──► /healthz + /api/products     │
│        3. microcks-import       ──► upload openapi.yaml          │
│        4. microcks-contract     ──► OPEN_API_SCHEMA validation   │
│        5. suite-restore-reg.    ──► TRUNCATE + replay dump       │
│        6. regression-tests      ──► tests/regression.py (9 cas) │
│        7. suite-restore-e2e     ──► TRUNCATE + replay dump       │
│        8. e2e-tests             ──► Playwright (6 tests)         │
│                                     reset_db() avant chaque test │
│                                                                  │
│   Si échec → triggerKagentAnalysis()                             │
│     Job curl → POST A2A → preview-troubleshooter-agent           │
│     Agent lit: logs pods, events K8s, CR status, job output      │
│     → Commentaire PR structuré: cause racine + fix suggéré       │
│                                                                  │
│  PHASE: Terminating  (PR fermée ou TTL expiré)                   │
│    ├── delete namespace (et tout ce qu'il contient)              │
│    └── GitHub Deployment: inactive                               │
└──────────────────────────────────────────────────────────────────┘
```

---

## Session Details

| Champ | Valeur |
|---|---|
| **Format** | Talk + démo live |
| **Durée** | 35 min + 5 min Q&A |
| **Niveau** | Intermédiaire (familiarité Kubernetes assumée) |
| **Langue** | Français *(slides en anglais)* |
| **Track** | Platform Engineering / Developer Experience |

---

## Les 5 Problèmes que ce Projet Résout

### 1 — La base de données partagée de staging pollue les tests

En staging classique, PR #28 et PR #29 partagent la même base. Les données insérées par PR #28 cassent les assertions de PR #29. La régression passe ici, échoue là, selon l'ordre d'exécution.

**Solution :** chaque PR a son propre PostgreSQL éphémère dans son propre namespace. Le contrôleur génère un `Secret postgres-credentials` avec un user unique (`preview_42`), un mot de passe 64 caractères crypto-aléatoire, et injecte le tout dans chaque pod. Le Secret est créé une seule fois et jamais écrasé.

Deux niveaux d'isolation de base de données :
- **Entre suites** : un Job `suite-restore-regression` fait un `TRUNCATE` complet + replay du dump avant chaque suite de tests.
- **Entre chaque test E2E** : la fonction `reset_db()` dans `tests/e2e.py` appelle l'Extension via HTTP pour déclencher une restauration du checkpoint — chaque test Playwright démarre sur une DB identique.

### 2 — Les données de test de staging ne correspondent pas à la PR

Un seed statique ne couvre pas les nouveaux champs, les nouvelles routes, les nouvelles contraintes. Un test qui reçoit `{"id": 1, "name": "Produit A"}` ne teste pas le nouveau champ `discount_pct` ajouté dans la PR.

**Solution : AI Enrichment.** L'opérateur :
1. Dump le schéma PostgreSQL réel (`pg_dump --schema-only`).
2. Récupère le diff Git de la PR via l'API GitHub.
3. Envoie schéma + diff + system prompt au LLM (Azure OpenAI gpt-4o-mini).
4. Le LLM retourne un JSON structuré `{ "seed_sql": "...", "test_script": "..." }`.
5. Un Job `ai-seed` exécute `psql -f seed.sql` — 10 produits, 3 catégories, reviews, orders, cohérents avec les changements du diff.
6. Un Job `ai-tests` exécute `python test.py` — des tests d'intégration ciblés sur les chemins de code modifiés.

Le LLM ne touche jamais PostgreSQL directement. Il génère du SQL et du Python. L'exécution reste dans le cluster, dans un Job avec les credentials de la base de la PR.

### 3 — On ne sait jamais si l'API est cassée avant la prod

Les tests de régression vérifient les comportements existants mais pas la conformité du contrat API. Un renommage de champ, un mauvais code HTTP, un champ requis manquant peuvent passer tous les tests et casser un consommateur en production.

**Solution : Microcks Contract Testing.** Le contrôleur crée un Job `microcks-import` qui récupère `api/openapi.yaml` depuis HEAD de la branche, l'uploade dans Microcks (OPEN_API_SCHEMA runner), puis un Job `microcks-contract-tests` qui envoie de vraies requêtes HTTP à `svc-backend:8080` et valide chaque réponse contre la spec. Aucun import manuel. La spec testée est toujours celle de la PR.

### 4 — On ne sait pas pourquoi les tests ont échoué

Le développeur reçoit "E2E: 3 failed" dans son PR. Il doit `kubectl logs job/e2e-tests`, lire les événements K8s, comprendre si c'est son code ou l'infra. Sur une preview éphémère, les logs peuvent déjà être gone.

**Solution : kagent AI Failure Analysis.** Dès qu'une suite de tests passe en `Failed`, l'opérateur crée un Job éphémère qui appelle le `preview-troubleshooter-agent` via le protocole A2A (JSON-RPC 2.0). L'agent (read-only, sans accès aux Secrets) lit les logs, les events Kubernetes, le statut du CR, et publie un commentaire PR structuré :

```markdown
**Risk level:** HIGH
**Evidence:** e2e-tests Job exit code 1
  Pod logs: TimeoutError — `data-testid="product-grid"` never appeared
  Events: svc-frontend pod 0/1 Ready for last 2m
**Root cause:** La readiness probe du frontend passe mais le bundle React
  ne s'est pas chargé — le trafic est routé avant que le frontend soit chaud.
**Suggested fix:** Ajouter un startupProbe avec initialDelaySeconds=30
  sur svc-frontend, ou augmenter le timeout E2E.
**Reproduce:** kubectl logs -n preview-pr-42 job/e2e-tests
```

### 5 — On lance toujours tous les tests même quand c'est inutile

Une PR qui corrige un typo dans un README déclenche smoke + contrat + régression + E2E. Une PR qui touche uniquement le CSS déclenche les tests de migration de base de données.

**Solution : AI Test Strategist.** Avant de lancer un seul Job de test, l'opérateur crée un `TestPlan` stub (CRD) et déclenche un second agent kagent — le `test-strategist-agent`. L'agent reçoit `changeContext.changedFiles`, `detectedImpacts`, et le `diffPatch` brut. Il répond avec `mustRun` / `canSkip` + une rationale + un score de confiance :

```yaml
mustRun: [smoke, regression]
canSkip:
  - suite: migration, reason: "No migration files changed."
  - suite: contract,  reason: "No API contract changes."
  - suite: e2e,       reason: "No frontend or user-journey files changed."
confidence: 82
```

Si le score est en dessous du seuil (défaut 70), l'opérateur tombe en `FullSuite`. Si l'agent timeout, fallback configurable : `Full | Skip | Error`. Les suites `canSkip` sont marquées `Skipped` dans le statut et n'occupent aucun CPU.

---

## Aspect Économique

La question "combien ça coûte?" est au cœur de tout projet de plateforme.

| Levier | Mécanisme | Impact |
|--------|-----------|--------|
| **Resource tiers** | `small` (100m/128Mi) · `medium` · `large` (2000m/2Gi) | Chaque PR consomme selon ses besoins réels, pas un slot staging fixe |
| **TTL auto-expiry** | Défaut 48h — `r.Delete(preview)` quand expiré | Zéro environnement zombie. La cleanup est déclenchée par le contrôleur, pas par un humain |
| **Test Strategist** | Suites `canSkip` → 0 Job schedulé | Une PR CSS ne lance pas Playwright + Chromium (économie de ~1 CPU·min) |
| **Approval gate** | `spec.requiresApproval: true` forcé par webhook sur `large` | Bloque le provisionnement des environnements coûteux jusqu'à approbation humaine |
| **gpt-4o-mini** | ~$0,15 / M tokens input | Un enrichissement complet (schéma + diff + seed + tests) coûte <$0,01 |
| **ConfigMap pour les checkpoints** | pg_dump → ConfigMap (max 950 Ko) | Snapshots base de données sans coût de stockage externe (PVC, S3) |
| **Self-hosted runners AKS** | Kaniko in-cluster | Zéro minutes GitHub Actions consommées pour les builds |
| **Namespace → delete** | Un `kubectl delete preview pr-42` supprime tout | PostgreSQL, Deployments, Jobs, Secrets, Ingress — tout dans le namespace |

Un environnement `medium` avec DB + AI + tests complets consomme environ **2.5 CPU·min** et **1 Go RAM pendant ~90 secondes**. Sur AKS avec des nœuds Standard_D4s_v3 (4 vCPU / 16 Go), on peut faire tourner ~8 PRs en parallèle sur un seul nœud.

---

## Learning Outcomes

Les participants repartent avec :

1. **Une implémentation concrète du pattern Operator** appliquée à un problème de plateforme réel — finalizers, status conditions, idempotence, generation-reset, RequeueAfter. Pas un hello-world.

2. **Le design de la boucle AI Enrichment** : comment envoyer schéma + diff à un LLM, valider le JSON retourné (`seed_sql` + `test_script`), détecter si le LLM a mis du SQL dans le Python (auto-retry avec prompt de correction), et stocker le tout dans un ConfigMap pour l'exécuter dans deux Jobs séparés.

3. **L'orchestration de tests séquentiels dans un opérateur** : comment `status.tests.step` persiste l'état dans etcd, comment chaque reconcile crée le prochain Job et retourne `RequeueAfter=5s`, et comment le pipeline survit au redémarrage du pod opérateur en milieu d'exécution.

4. **Le design de l'isolation de base de données à deux niveaux** : namespace séparé par PR, puis checkpoint pg_dump → ConfigMap → TRUNCATE + replay entre chaque suite et avant chaque test E2E via l'API Extension.

5. **L'intégration de deux agents kagent avec des rôles complémentaires** : un agent pré-tests (décide quoi lancer), un agent post-échec (explique pourquoi ça a planté) — les deux via une architecture où le contrôleur ne fait aucun appel HTTP, il crée seulement un Job éphémère `curlimages/curl`.

6. **Les leviers économiques concrets** : tiers de ressources, TTL, test strategist, approval gate, et pourquoi gpt-4o-mini + ConfigMap rend l'IA enrichissement viable à <$0,01 par PR.

---

## Démo Live *(~12 minutes)*

```
Setup: 2 PRs ouvertes en parallèle sur le cluster AKS live

Acte 1 — Pipeline nominal (PR #29 — nouveau endpoint top-rated)
  1. git push → workflow → Kaniko build + kubectl apply Preview CR     (~45s)
  2. Operator: namespace + NetworkPolicy + PSS + PostgreSQL             (~5s)
  3. AI Enrichment: schema-dump → LLM → seed.sql + test.py            (~15s)
     kubectl get cm ai-enrichment -n preview-pr-29 -o yaml            (live)
  4. Test Strategist: TestPlan → mustRun=[smoke,regression] skip e2e  (~5s)
     kubectl get testplan -n preview-pr-29 -o yaml                    (live)
  5. Tests: smoke → contract → regression (e2e skipped)               (~25s)
  6. Commentaire PR: URL + tableau résultats + stratégie kagent        (~2s)
  ──────────────────────────────────────────────────────────────────
  Total: ~97 secondes

Acte 2 — Échec de contrat (PR #30 — renommage de champ dans app.py)
  1. Même pipeline, mais openapi.yaml non mis à jour
  2. Microcks contract: FAIL — field "id" missing (found "order_id")
  3. kagent déclenché automatiquement
  4. Commentaire PR: root cause + ligne exacte à corriger + commandes
     kubectl logs -n preview-pr-30 job/microcks-contract-tests        (live)

Acte 3 — PR docs-only (README fix)
  1. Test Strategist: mustRun=[smoke] canSkip=[migration,contract,
     regression,e2e]  confidence=95
  2. 1 seul Job lancé. Le reste: Skipped.
  ──────────────────────────────────────────────────────────────────
  Économie: ~2 CPU·min + ~90s de feedback time
```

---

## Plan du Talk *(35 min)*

| Temps | Section |
|---|---|
| 0–3 min | Le problème : pourquoi le staging partagé est cassé par design |
| 3–7 min | Architecture : CRD Preview, boucle de réconciliation, phases |
| 7–11 min | **Démo Acte 1** — pipeline nominal, 90 secondes |
| 11–16 min | Deep dive : AI Enrichment — LLM → ConfigMap → Job (pas de kubectl exec, pas d'accès direct à la DB) |
| 16–21 min | Deep dive : orchestration des tests — status.tests.step, checkpoint pg_dump, isolation à deux niveaux |
| 21–25 min | **Démo Acte 2 & 3** — contrat cassé + PR docs-only |
| 25–29 min | kagent : deux agents, deux rôles — Test Strategist + Troubleshooter (protocole A2A, Job éphémère, read-only) |
| 29–32 min | Aspect économique : tiers, TTL, test skip, approval gate |
| 32–35 min | Limites connues, ce qu'on ferait différemment, ressources |

---

## Pourquoi ce Talk, Pourquoi Maintenant

Platform engineering est passé de "nice to have" à discipline à part entière. Mais beaucoup de plateformes se limitent encore à Argo CD + un staging partagé. Ce talk montre ce que ça donne quand on prend le problème plus loin : isolation complète, données contextualisées, tests de contrat, et IA pour diagnostiquer — sans vendor lock-in, avec du code open-source.

La partie "AI en infrastructure" est aussi souvent mal faite : LLM bolté sans gestion d'erreur, sans validation de sortie, sans fallback. Ce talk montre une intégration prudente : output validé, retry automatique, AI enrichment non-bloquant pour les tests, agent kagent sans accès aux Secrets.

KCD Provence : l'audience est exactement celle qui build ou évalue ce genre de plateformes — SREs, platform engineers, seniors dev en mode "on veut améliorer notre DX".

---

## Bio du Speaker

**Ihsen Alaya** — Platform Engineer & Kubernetes Practitioner

Ingénieur plateforme avec une expérience dans la conception et l'exploitation de plateformes de delivery sur Kubernetes (AKS). Focus sur le développement d'opérateurs, les pipelines GitOps, et l'expérience développeur.

A construit `preview-operator` et `idp-preview` comme implémentation de référence open-source des patterns présentés dans ce talk. Actif dans la communauté cloud-native française.

*Premier talk KCD — speaker expérimenté en sessions internes et workshops techniques.*

---

## Prérequis Techniques pour le Public

- Familiarité de base avec Kubernetes (Pods, Deployments, namespaces)
- Connaissance générale du pattern Operator (pas de kubebuilder requis)
- Aucune connaissance préalable de kagent, Microcks, ou Kaniko

---

## Limites Connues (à aborder dans le talk)

| Limite | Impact | Contournement actuel |
|--------|--------|---------------------|
| ConfigMap max 1 Mo | Checkpoints de grandes bases de données impossibles | pg_dump compressé, tables sélectives |
| FQDN egress sur Azure CNI + Cilium hybrid | `toFQDNs` non disponible sans full Cilium CNI | Azure Firewall pour l'egress sortant |
| PAT GitHub long-lived | Surface d'attaque si PAT compromis | Migration vers GitHub App planifiée |
| gpt-4o-mini hallucine du SQL parfois | ai-seed Job échoue | Détection automatique + retry avec prompt de correction |
| Playwright/Chromium ~1 Go RAM | Coûteux si E2E sur chaque PR | Test Strategist skip E2E quand pas de changement frontend |

---

## Matériel de Support

| Ressource | Lien |
|---|---|
| Opérateur (source) | `github.com/ihsenalaya/preview-operator` |
| Application démo | `github.com/ihsenalaya/idp-preview` |
| Helm chart | `oci://ghcr.io/ihsenalaya/charts/preview-operator` |
| OpenAPI spec | `api/openapi.yaml` dans ce repo |
| Script de démo KCD | `docs/kubecon-demo-script.md` dans ce repo |

Les slides seront soumis avant l'événement. La démo tourne sur un cluster AKS live. Une alternative Kind est disponible si la connectivité est indisponible le jour J.

---

## Tags / Keywords

`platform-engineering` · `kubernetes-operator` · `kubebuilder` · `developer-experience` · `preview-environments` · `ai-enrichment` · `llm-in-infrastructure` · `microcks` · `contract-testing` · `kagent` · `a2a-protocol` · `kaniko` · `aks` · `networkpolicy` · `postgresql` · `gitops` · `ephemeral-environments`
