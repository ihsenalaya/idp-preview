#!/usr/bin/env python3
"""
Fetches the PR changed files, classifies them, and writes
/tmp/preview-manifest.yaml ready for kubectl apply.

Environment variables (all required):
  PR_NUM, REPO, HEAD_SHA, BASE_SHA, HEAD_REF, IMAGE,
  DEPLOYMENT_ID, CTRL_SECRET, OWNER, REPO_NAME, GH_TOKEN
"""
import json
import os
import re
import urllib.request

PR_NUM      = os.environ["PR_NUM"]
REPO        = os.environ["REPO"]
HEAD_SHA    = os.environ["HEAD_SHA"]
BASE_SHA    = os.environ["BASE_SHA"]
HEAD_REF    = os.environ["HEAD_REF"]
IMAGE       = os.environ["IMAGE"]
DEP_ID      = os.environ["DEPLOYMENT_ID"]
CTRL_SECRET = os.environ["CTRL_SECRET"]
OWNER       = os.environ["OWNER"]
REPO_NAME   = os.environ["REPO_NAME"]
GH_TOKEN    = os.environ.get("GH_TOKEN", "")


def classify(path):
    if re.search(r"migrations/versions/", path):
        return "database-migration"
    if re.search(r"api/openapi\.yaml", path):
        return "api-contract"
    if re.search(r"frontend\.py|templates/|static/", path):
        return "frontend"
    if re.search(r"app\.py|tests/", path):
        return "backend"
    if re.search(r"README|\.md$|docs/", path):
        return "docs"
    return "other"


def fetch_changed_files():
    url = f"https://api.github.com/repos/{REPO}/pulls/{PR_NUM}/files?per_page=100"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"token {GH_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"[ctx] WARNING: could not fetch PR files: {e}")
        return []


files = fetch_changed_files()
changed = [{"path": f["filename"], "type": classify(f["filename"])} for f in files]

database     = str(any(c["type"] == "migration" for c in changed)).lower()
api_contract = str(any(c["type"] == "contract"  for c in changed)).lower()
frontend     = str(any(c["type"] == "frontend"  for c in changed)).lower()
backend      = str(any(c["type"] == "backend"   for c in changed)).lower()

print(f"[ctx] {len(changed)} files — db={database} api={api_contract} frontend={frontend} backend={backend}")

# Build changedFiles YAML block (6 spaces indent = top-level field in manifest)
changed_files_block = ""
for c in changed:
    changed_files_block += f"      - path: {c['path']}\n        type: {c['type']}\n"

microcks_url = "http://microcks.microcks.svc.cluster.local:8080"

manifest = (
    "apiVersion: platform.company.io/v1alpha1\n"
    "kind: Preview\n"
    "metadata:\n"
    f"  name: pr-{PR_NUM}\n"
    "spec:\n"
    f"  branch: {HEAD_REF}\n"
    f"  prNumber: {PR_NUM}\n"
    f"  image: {IMAGE}\n"
    "  resourceTier: medium\n"
    "  ttl: 48h\n"
    "  testStrategy:\n"
    "    mode: Auto\n"
    "    confidenceThreshold: 65\n"
    "  changeContext:\n"
    "    diffRef:\n"
    f"      headSHA: {HEAD_SHA}\n"
    f"      baseSHA: {BASE_SHA}\n"
    "    summary:\n"
    f"      changedFilesCount: {len(changed)}\n"
    "    detectedImpacts:\n"
    f"      database: {database}\n"
    f"      apiContract: {api_contract}\n"
    f"      frontend: {frontend}\n"
    f"      backend: {backend}\n"
    "    changedFiles:\n"
    + changed_files_block +
    "  services:\n"
    "    - name: backend\n"
    f"      image: {IMAGE}\n"
    "      port: 8080\n"
    "      pathPrefix: /api\n"
    "    - name: frontend\n"
    f"      image: {IMAGE}\n"
    "      port: 3000\n"
    "      pathPrefix: /\n"
    "      env:\n"
    "        - name: APP_MODE\n"
    "          value: frontend\n"
    "        - name: PREVIEW_PR\n"
    f"          value: \"{PR_NUM}\"\n"
    "        - name: PREVIEW_BRANCH\n"
    f"          value: {HEAD_REF}\n"
    "  database:\n"
    "    enabled: true\n"
    "    databaseName: appdb\n"
    "  telemetry:\n"
    "    enabled: true\n"
    "    serviceName: idp-testing\n"
    "    autoInstrumentation:\n"
    "      language: python\n"
    "      instrumentationRef: observability/python\n"
    "  testSuite:\n"
    "    enabled: true\n"
    "    smoke: {}\n"
    "    migration:\n"
    "      enabled: true\n"
    "    contractTesting:\n"
    "      enabled: true\n"
    f"      microcksURL: {microcks_url}\n"
    "      apiName: Preview Catalog API\n"
    "      apiVersion: \"1.0.0\"\n"
    f"      specURL: https://raw.githubusercontent.com/{REPO}/{HEAD_REF}/api/openapi.yaml\n"
    "    regression:\n"
    "      enabled: true\n"
    "    e2e:\n"
    "      enabled: true\n"
    "  aiEnrichment:\n"
    "    enabled: true\n"
    "    apiSecretRef:\n"
    "      name: ai-api-key\n"
    "      key: api-key\n"
    "    model: gpt-4o-mini\n"
    "  kagent:\n"
    "    enabled: true\n"
    "    namespace: kagent-system\n"
    "    agentName: preview-troubleshooter-agent\n"
    "    testStrategistAgentName: test-strategist-agent\n"
    "  github:\n"
    "    enabled: true\n"
    f"    owner: {OWNER}\n"
    f"    repo: {REPO_NAME}\n"
    f"    deploymentId: {DEP_ID}\n"
    f"    environment: pr-{PR_NUM}\n"
    "    commentOnReady: true\n"
    "    tokenSecretRef:\n"
    f"      name: {CTRL_SECRET}\n"
    "      namespace: preview-operator-system\n"
    "      key: token\n"
)

out = "/tmp/preview-manifest.yaml"
with open(out, "w") as f:
    f.write(manifest)

print(f"[ctx] manifest written to {out}")
