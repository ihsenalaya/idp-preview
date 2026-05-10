#!/usr/bin/env python3
"""
generate_preview_manifest.py — Classify the PR diff and emit changeContext + testStrategy
fields to stdout as YAML, for injection into the Preview CR.

Usage:
  python3 scripts/generate_preview_manifest.py \
    --base-sha <BASE_SHA> \
    --head-sha <HEAD_SHA> \
    --pr-number <N> \
    --repo <owner/repo> \
    [--max-patch-bytes 65536]

Output (stdout):
  changeContext:
    diffRef:
      provider: github
      repository: owner/repo
      pullRequestNumber: <N>
      baseSHA: <BASE>
      headSHA: <HEAD>
    summary:
      changedFilesCount: N
      additions: N
      deletions: N
    changedFiles:
      - path: app.py
        type: backend
    detectedImpacts:
      database: false
      apiContract: false
      backend: true
      frontend: false
    diffPatch: |
      <raw unified diff, up to --max-patch-bytes>
  testStrategy:
    mode: Auto
    confidenceThreshold: 70
    agentTimeoutSeconds: 120
    fallbackOnAgentTimeout: Full
"""

import argparse
import subprocess
import sys


# ─── File classification rules ────────────────────────────────────────────────

MIGRATION_PATTERNS = ["migrations/", "versions/", "alembic/"]
API_CONTRACT_PATTERNS = ["openapi.yaml", "openapi.json", ".proto", "swagger.yaml", "swagger.json"]
FRONTEND_PATTERNS = ["templates/", "static/", "frontend/", ".css", ".js", ".html", ".jsx", ".tsx", ".vue"]
DOCS_PATTERNS = ["docs/", ".md", ".rst", ".txt", "README", "LICENSE", "CHANGELOG"]
CONFIG_PATTERNS = [".yaml", ".yml", ".json", ".toml", ".ini", ".env", "Dockerfile", "Makefile", ".github/", "k8s/", "charts/", "config/"]


def classify_file(path: str) -> str:
    p = path.lower()

    for pat in MIGRATION_PATTERNS:
        if pat in p:
            return "database-migration"

    for pat in API_CONTRACT_PATTERNS:
        if p.endswith(pat.lstrip(".")) or pat.lstrip(".") in p:
            return "api-contract"

    for pat in FRONTEND_PATTERNS:
        if pat in p or p.endswith(pat):
            return "frontend"

    for pat in DOCS_PATTERNS:
        if pat.lower() in p or p.endswith(pat.lstrip(".")):
            return "docs"

    # Backend: Python/Go/Java source not already classified
    if any(p.endswith(ext) for ext in [".py", ".go", ".java", ".rb", ".rs", ".ts"]):
        return "backend"

    for pat in CONFIG_PATTERNS:
        if pat in p or p.endswith(pat.lstrip(".")):
            return "other"

    return "other"


def get_changed_files(base_sha: str, head_sha: str):
    """Return list of (path, additions, deletions) for files changed between base and head."""
    result = subprocess.run(
        ["git", "diff", "--numstat", f"{base_sha}...{head_sha}"],
        capture_output=True, text=True, check=True,
    )
    files = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            add = int(parts[0]) if parts[0] != "-" else 0
            delete = int(parts[1]) if parts[1] != "-" else 0
            path = parts[2]
            files.append((path, add, delete))
    return files


def get_diff_patch(base_sha: str, head_sha: str, max_bytes: int) -> str:
    """Return the raw unified diff, truncated to max_bytes."""
    result = subprocess.run(
        ["git", "diff", f"{base_sha}...{head_sha}"],
        capture_output=True, text=True,
    )
    patch = result.stdout
    if len(patch.encode()) > max_bytes:
        patch = patch.encode()[:max_bytes].decode(errors="replace")
        patch += "\n... (diff truncated)\n"
    return patch


def indent(text: str, spaces: int) -> str:
    pad = " " * spaces
    return "\n".join(pad + line for line in text.splitlines())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--pr-number", required=True, type=int)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--max-patch-bytes", type=int, default=65536)
    parser.add_argument("--confidence-threshold", type=int, default=70)
    parser.add_argument("--agent-timeout-seconds", type=int, default=120)
    args = parser.parse_args()

    changed = get_changed_files(args.base_sha, args.head_sha)

    total_add = sum(a for _, a, _ in changed)
    total_del = sum(d for _, _, d in changed)

    classified = [(path, classify_file(path)) for path, _, _ in changed]

    types = {t for _, t in classified}
    database = "database-migration" in types
    api_contract = "api-contract" in types
    frontend = "frontend" in types
    backend = "backend" in types

    patch = get_diff_patch(args.base_sha, args.head_sha, args.max_patch_bytes)

    # ─── Emit YAML ────────────────────────────────────────────────────────────
    lines = []
    lines.append("changeContext:")
    lines.append("  diffRef:")
    lines.append("    provider: github")
    lines.append(f"    repository: {args.repo}")
    lines.append(f"    pullRequestNumber: {args.pr_number}")
    lines.append(f"    baseSHA: {args.base_sha}")
    lines.append(f"    headSHA: {args.head_sha}")
    lines.append("  summary:")
    lines.append(f"    changedFilesCount: {len(changed)}")
    lines.append(f"    additions: {total_add}")
    lines.append(f"    deletions: {total_del}")
    lines.append("  changedFiles:")
    for path, ftype in classified:
        lines.append(f"    - path: {path}")
        lines.append(f"      type: {ftype}")
    lines.append("  detectedImpacts:")
    lines.append(f"    database: {str(database).lower()}")
    lines.append(f"    apiContract: {str(api_contract).lower()}")
    lines.append(f"    backend: {str(backend).lower()}")
    lines.append(f"    frontend: {str(frontend).lower()}")
    if patch.strip():
        lines.append("  diffPatch: |")
        for pline in patch.splitlines():
            # Escape special YAML chars in the literal block scalar
            lines.append("    " + pline)
    lines.append("testStrategy:")
    lines.append("  mode: Auto")
    lines.append(f"  confidenceThreshold: {args.confidence_threshold}")
    lines.append(f"  agentTimeoutSeconds: {args.agent_timeout_seconds}")
    lines.append("  fallbackOnAgentTimeout: Full")

    print("\n".join(lines))


if __name__ == "__main__":
    main()
