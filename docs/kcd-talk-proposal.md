# Talk Proposal — KCD Provence 2025

---

## Title

**From PR to Preview in 90 Seconds: Building AI-Powered Ephemeral Environments with a Kubernetes Operator**

---

## Elevator Pitch *(~50 words — shown in the schedule)*

Every pull request deserves a live environment — **isolated by NetworkPolicy, secured with Pod Security Standards, and seeded by AI**. We built a Kubernetes operator that provisions namespaces, enforces network isolation, builds images in-cluster, seeds a database from an LLM-generated diff, runs contract tests, and posts a URL back to the PR — all from a single `git push`.

---

## Abstract *(~280 words)*

Preview environments are one of the highest-leverage tools in a modern engineering platform: they let reviewers click before they merge, catch regressions before they reach production, and give QA a realistic target that mirrors the real stack. The problem is that building them well is surprisingly hard — you need image builds, database provisioning, ingress routing, test orchestration, and cleanup, all automated and isolated per branch.

This talk walks through the design and implementation of `preview-operator`, a production-grade Kubernetes operator built with kubebuilder that does exactly that. When a developer opens a pull request, a GitHub Actions workflow creates a `Preview` custom resource. The operator reconciles it: it provisions a dedicated namespace with NetworkPolicy (baseline Pod Security Standards enforced), builds the application image with Kaniko on self-hosted AKS runners, seeds a PostgreSQL database using AI-generated SQL produced by an LLM from the actual git diff, runs Microcks contract tests against the OpenAPI spec, and posts a structured status comment back to the PR — including links, test results, and an AI failure analysis when something goes wrong.

Attendees will see the full reconciliation loop in action, understand the design tradeoffs (operator vs. Argo Workflows vs. shell scripts), and learn how to integrate AI enrichment safely into a Kubernetes controller without turning it into a black box.

**This is a case study with a live demo.** Real cluster, real PRs, real failures — and a controller that handles them.

---

## Architecture Overview

Each `Preview` CR triggers a reconciliation loop that creates a fully isolated, self-contained environment:

```
┌─ GitHub PR ───────────────────────────────────────────────────────────────┐
│  git push → Actions workflow → kubectl apply Preview CR                   │
└───────────────────────────────────────────────────────────────────────────┘
                                      │
                          preview-operator reconciles
                                      │
             ┌────────────────────────▼────────────────────────┐
             │            Namespace: preview-pr-<N>             │
             │                                                   │
             │  ┌─────────────────────────────────────────────┐ │
             │  │  NetworkPolicy (auto-provisioned)            │ │
             │  │                                              │ │
             │  │  Ingress rules:                              │ │
             │  │    • inter-pod within namespace (app ↔ db)  │ │
             │  │    • ingress-nginx controller only           │ │
             │  │                                              │ │
             │  │  Egress rules:                               │ │
             │  │    • open (AI calls, GHCR pulls, GitHub API) │ │
             │  │                                              │ │
             │  │  Pod Security Standards:                     │ │
             │  │    enforce: baseline  (blocks privileged)    │ │
             │  │    warn:    restricted (flags best gaps)     │ │
             │  └─────────────────────────────────────────────┘ │
             │                                                   │
             │  Kaniko Job → GHCR  →  App Deployment            │
             │  PostgreSQL StatefulSet                           │
             │  AI Seed Job  (LLM diff → SQL → psql)            │
             │  Microcks contract tests  (OpenAPI spec)          │
             │  Regression + E2E tests                           │
             │  Ingress / VirtualService (Istio auto-detected)   │
             └───────────────────────────────────────────────────┘
                                      │
                          PR comment: URL + test table + AI analysis
```

**NetworkPolicy is not optional** — it is reconciled before any workload is created, and the operator refuses to proceed to the build phase until the policy is in place. This ensures every preview environment is isolated from day zero: a broken app in `preview-pr-42` cannot reach pods in `preview-pr-43` or in `production`.

---

## Session Details

| Field | Value |
|---|---|
| **Format** | Talk + live demo |
| **Duration** | 35 minutes + 5 min Q&A |
| **Level** | Intermediate (some Kubernetes familiarity assumed) |
| **Language** | French *(English slides)* |
| **Track** | Platform Engineering / Developer Experience |

---

## Learning Outcomes

Attendees leave with:

1. **A mental model of the operator pattern** applied to a real platform engineering problem — not a toy example, but a production controller with finalizers, status conditions, and idempotent reconciliation.

2. **Network isolation by default with NetworkPolicy** — how to auto-provision per-namespace NetworkPolicies that enforce ingress isolation (inter-pod + ingress-nginx only) and open egress, and why this must happen *before* any workload lands, not as an afterthought.

3. **Pod Security Standards in practice** — how `enforce: baseline` + `warn: restricted` on the namespace prevents privilege escalation without breaking legitimate workloads, and what the label-based approach looks like in a reconciler.

4. **A safe approach to LLM integration** in infrastructure tooling — prompt design, structured output, retry logic, and failure handling so the AI enrichment never blocks the reconciliation loop.

5. **Practical answers** to questions like: *how do you isolate preview namespaces without cluster-admin?*, *when should you use an operator vs. Argo Workflows?*, *how do you clean up reliably without leaving dangling resources?*

6. **A running codebase** they can fork and run in their own cluster today (`github.com/ihsenalaya/preview-operator`, Apache 2.0).

---

## Demo Scenario *(live, ~10 minutes)*

```
1. git push to feature branch → GitHub Actions creates Preview CR
2. Operator provisions namespace + NetworkPolicy + PSS labels         (~5s)
3. Kaniko builds image on self-hosted AKS runner + pushes to GHCR    (~45s)
4. Operator provisions PostgreSQL + runs AI-generated seed Job        (~20s)
5. Microcks contract tests run against OpenAPI spec                   (~15s)
6. Regression + E2E tests run                                         (~10s)
7. PR comment posted: URL, test table, AI analysis if failure         (~2s)
─────────────────────────────────────────────────────────────────────
Total: ~90 seconds from push to live preview
```

Then: intentionally break the OpenAPI contract → show kagent posting an AI failure analysis comment to the PR with the exact line to fix.

---

## Outline *(35 min)*

| Time | Section |
|---|---|
| 0–3 min | The problem: why "just use Argo" isn't always the answer |
| 3–8 min | Architecture overview: CRD, reconciliation phases, components |
| 8–18 min | **Live demo** — full PR-to-preview pipeline |
| 18–24 min | Deep dive: AI enrichment loop (LLM → ConfigMap → Job) |
| 24–29 min | Security by default: NetworkPolicy rules, PSS labels, RBAC — and why order matters |
| 29–33 min | Lessons learned: what broke in production, what we'd do differently |
| 33–35 min | Resources + Q&A setup |

---

## Why This Talk, Why Now

Platform engineering has graduated from "nice to have" to a first-class discipline — and preview environments are one of the most visible wins a platform team can deliver. Meanwhile, AI integration in infrastructure tooling is happening fast and often badly: LLMs bolted on without structure, failure handling, or clear ownership.

This talk shows both done right, on real infrastructure, by a practitioner — not a vendor demo.

KCD audiences skew exactly toward the people who would build or operate something like this: SREs, platform engineers, and senior developers who are evaluating whether to build, buy, or fork. This talk gives them the building blocks.

---

## Speaker Bio

**Ihsen Alaya** — Platform Engineer & Cloud Native Practitioner

Platform engineer with experience designing and operating Kubernetes-based delivery platforms on Azure (AKS). Contributor to internal developer platforms at multiple companies, with a focus on operator development, GitOps pipelines, and developer experience tooling.

Built `preview-operator` as an open-source reference implementation for the platform patterns described in this talk. Active in the French cloud-native community.

*First-time KCD speaker — experienced internal speaker and workshop facilitator.*

---

## Technical Prerequisites for Attendees

- Basic familiarity with Kubernetes (Pods, Deployments, namespaces)
- Awareness of the operator pattern (no deep knowledge required)
- No prior kubebuilder or controller-runtime knowledge needed

---

## Supporting Materials

| Resource | Link |
|---|---|
| Operator source code | `github.com/ihsenalaya/preview-operator` |
| Demo application | `github.com/ihsenalaya/idp-preview` |
| Helm chart | `oci://ghcr.io/ihsenalaya/charts/preview-operator` |
| Architecture diagram | `docs/kubecon-demo-script.md` in this repo |
| OpenAPI contract | `api/openapi.yaml` in this repo |

Slides will be submitted before the event. The demo runs on a live AKS cluster; a Kind-based fallback is available if connectivity is unavailable on the day.

---

## Diversity & Inclusion Notes

- First-time KCD speaker, French-speaking community member
- Talk delivered in French to maximize accessibility for local attendees
- Slides in English to allow broader reuse and sharing after the event
- Open-source code available before the talk so attendees can explore independently

---

## Tags / Keywords

`platform-engineering` · `kubernetes-operator` · `kubebuilder` · `developer-experience` · `preview-environments` · `ai-enrichment` · `microcks` · `contract-testing` · `kaniko` · `aks` · `networkpolicy` · `gitops`
