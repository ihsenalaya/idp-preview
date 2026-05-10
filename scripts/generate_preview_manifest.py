#!/usr/bin/env python3
"""
generate_preview_manifest.py — Generate the complete Preview CR manifest with
changeContext (diff classification) and testStrategy (mode=Auto).

Outputs a valid Kubernetes YAML manifest ready to pipe to `kubectl apply -f -`.

Usage:
  python3 scripts/generate_preview_manifest.py \
    --pr-number 28 \
    --branch feat/my-feature \
    --image ghcr.io/owner/repo:sha \
    --base-sha <BASE_SHA> \
    --head-sha <HEAD_SHA> \
    --repo owner/repo \
    --repo-owner owner \
    --repo-name repo \
    --deployment-id 12345 \
    --github-token-secret preview-github-token \
    [--max-patch-bytes 65536]
"""

import argparse
import subprocess
import sys
import json


# ─── File classification ──────────────────────────────────────────────────────

def classify_file(path: str) -> str:
    p = path.lower()
    if any(x in p for x in ["migrations/", "versions/", "alembic/"]):
        return "database-migration"
    if any(p.endswith(x) or x in p for x in ["openapi.yaml", "openapi.json", ".proto", "swagger.yaml", "swagger.json"]):
        return "api-contract"
    if any(x in p or p.endswith(x) for x in ["templates/", "static/", "frontend/", ".css", ".js", ".html", ".jsx", ".tsx", ".vue"]):
        return "frontend"
    if any(x in p or p.endswith(x.lstrip(".")) for x in ["docs/", ".md", ".rst", "README", "LICENSE", "CHANGELOG"]):
        return "docs"
    if any(p.endswith(x) for x in [".py", ".go", ".java", ".rb", ".rs", ".ts"]):
        return "backend"
    return "other"


def get_changed_files(base_sha: str, head_sha: str):
    result = subprocess.run(
        ["git", "diff", "--numstat", f"{base_sha}...{head_sha}"],
        capture_output=True, text=True,
    )
    files = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            add = int(parts[0]) if parts[0] != "-" else 0
            delete = int(parts[1]) if parts[1] != "-" else 0
            files.append((parts[2], add, delete))
    return files


def get_diff_patch(base_sha: str, head_sha: str, max_bytes: int) -> str:
    result = subprocess.run(
        ["git", "diff", f"{base_sha}...{head_sha}"],
        capture_output=True, text=True,
    )
    patch = result.stdout
    encoded = patch.encode("utf-8", errors="replace")
    if len(encoded) > max_bytes:
        patch = encoded[:max_bytes].decode("utf-8", errors="replace") + "\n... (diff truncated)\n"
    return patch


def yaml_literal_block(text: str, indent: int) -> str:
    """Render a string as a YAML literal block scalar (|) with given indent."""
    pad = " " * indent
    lines = ["|"]
    for line in text.splitlines():
        # Escape nothing — literal block scalars preserve content verbatim.
        lines.append(pad + line)
    # Ensure trailing newline inside the block
    if text and not text.endswith("\n"):
        lines.append(pad)
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pr-number", required=True, type=int)
    p.add_argument("--branch", required=True)
    p.add_argument("--image", required=True)
    p.add_argument("--base-sha", required=True)
    p.add_argument("--head-sha", required=True)
    p.add_argument("--repo", required=True, help="owner/repo slug")
    p.add_argument("--repo-owner", required=True)
    p.add_argument("--repo-name", required=True)
    p.add_argument("--deployment-id", required=True)
    p.add_argument("--github-token-secret", default="preview-github-token")
    p.add_argument("--max-patch-bytes", type=int, default=65536)
    p.add_argument("--confidence-threshold", type=int, default=70)
    p.add_argument("--agent-timeout-seconds", type=int, default=120)
    args = p.parse_args()

    changed = get_changed_files(args.base_sha, args.head_sha)
    total_add = sum(a for _, a, _ in changed)
    total_del = sum(d for _, _, d in changed)
    classified = [(path, classify_file(path)) for path, _, _ in changed]
    types_set = {t for _, t in classified}

    database    = "database-migration" in types_set
    api_contract = "api-contract" in types_set
    frontend    = "frontend" in types_set
    backend     = "backend" in types_set

    patch = get_diff_patch(args.base_sha, args.head_sha, args.max_patch_bytes)

    # Build changed files YAML lines
    changed_files_lines = []
    for path, ftype in classified:
        changed_files_lines.append(f"      - path: {json.dumps(path)}")
        changed_files_lines.append(f"        type: {ftype}")
    changed_files_yaml = "\n".join(changed_files_lines) if changed_files_lines else "      []"

    # Build diffPatch block (literal block scalar, indented 6 spaces under changeContext)
    diff_patch_yaml = ""
    if patch.strip():
        lines = ["      diffPatch: |"]
        for line in patch.splitlines():
            lines.append("        " + line)
        diff_patch_yaml = "\n".join(lines)

    manifest = f"""\
apiVersion: platform.company.io/v1alpha1
kind: Preview
metadata:
  name: pr-{args.pr_number}
spec:
  branch: {args.branch}
  prNumber: {args.pr_number}
  image: {args.image}
  resourceTier: medium
  ttl: 48h
  services:
    - name: backend
      image: {args.image}
      port: 8080
      pathPrefix: /api
    - name: frontend
      image: {args.image}
      port: 3000
      pathPrefix: /
      env:
        - name: APP_MODE
          value: frontend
        - name: PREVIEW_PR
          value: "{args.pr_number}"
        - name: PREVIEW_BRANCH
          value: {args.branch}
  database:
    enabled: true
    databaseName: appdb
  telemetry:
    enabled: true
    serviceName: idp-testing
    autoInstrumentation:
      language: python
      instrumentationRef: observability/python
  testSuite:
    enabled: true
    smoke: {{}}
    contractTesting:
      enabled: true
      microcksURL: http://microcks.microcks.svc.cluster.local:8080
      apiName: Preview Catalog API
      apiVersion: "1.0.0"
      specURL: https://raw.githubusercontent.com/{args.repo}/{args.branch}/api/openapi.yaml
    regression:
      enabled: true
    e2e:
      enabled: true
  aiEnrichment:
    enabled: true
    apiSecretRef:
      name: ai-api-key
      key: api-key
    model: gpt-4o-mini
  kagent:
    enabled: true
    namespace: kagent-system
    agentName: preview-troubleshooter-agent
  github:
    enabled: true
    owner: {args.repo_owner}
    repo: {args.repo_name}
    deploymentId: {args.deployment_id}
    environment: pr-{args.pr_number}
    commentOnReady: true
    tokenSecretRef:
      name: {args.github_token_secret}
      namespace: preview-operator-system
      key: token
  changeContext:
    diffRef:
      provider: github
      repository: {args.repo}
      pullRequestNumber: {args.pr_number}
      baseSHA: {args.base_sha}
      headSHA: {args.head_sha}
    summary:
      changedFilesCount: {len(changed)}
      additions: {total_add}
      deletions: {total_del}
    changedFiles:
{changed_files_yaml}
    detectedImpacts:
      database: {str(database).lower()}
      apiContract: {str(api_contract).lower()}
      backend: {str(backend).lower()}
      frontend: {str(frontend).lower()}
{diff_patch_yaml}
  testStrategy:
    mode: Auto
    confidenceThreshold: {args.confidence_threshold}
    agentTimeoutSeconds: {args.agent_timeout_seconds}
    fallbackOnAgentTimeout: Full
"""

    sys.stdout.write(manifest)


if __name__ == "__main__":
    main()
