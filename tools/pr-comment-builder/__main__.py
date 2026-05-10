#!/usr/bin/env python3
"""PR comment builder — generates idempotent Markdown PR comment for idp-preview.

Usage:
    python -m tools.pr-comment-builder \
        --change-context path/to/change_context.yaml \
        --report-dir test-reports/ \
        --preview-url https://pr-42.preview.example.com \
        --namespace preview-pr-42 \
        --pr 42 \
        --output pr-comment.md
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

MARKER = "<!-- idp-preview-pr-comment -->"


def load_yaml(path: str) -> dict:
    if yaml is None:
        raise RuntimeError("pyyaml not installed — run: pip install pyyaml")
    with open(path) as f:
        return yaml.safe_load(f) or {}


def load_report(report_dir: str) -> dict:
    report_path = os.path.join(report_dir, "pytest-report.json")
    if not os.path.exists(report_path):
        return {}
    with open(report_path) as f:
        return json.load(f)


def _status_icon(passed: int, failed: int, total: int) -> str:
    if total == 0:
        return "⚪"
    if failed == 0:
        return "✅"
    if failed == total:
        return "❌"
    return "⚠️"


def build_comment(
    change_context: dict,
    report: dict,
    preview_url: str,
    namespace: str,
    pr: str,
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # --- Section 1: What Changed ---
    detected = change_context.get("detectedImpacts", [])
    changed_files = change_context.get("changedFiles", [])
    impact_lines = "\n".join(f"- `{i}`" for i in detected) if detected else "- No impact areas detected"
    file_lines = "\n".join(f"- `{f}`" for f in changed_files[:10]) if changed_files else "- (no file list)"
    if len(changed_files) > 10:
        file_lines += f"\n- … and {len(changed_files) - 10} more"

    # --- Section 2: Why Tests Ran ---
    test_selection = change_context.get("testSelection", {})
    selected_suites = test_selection.get("suites", detected or ["unit", "regression"])
    reason = test_selection.get("reason", "Change context analysis triggered relevant test suites")
    suite_lines = "\n".join(f"- `{s}`" for s in selected_suites)

    # --- Section 3: Test Results ---
    summary = report.get("summary", {})
    total = summary.get("total", 0)
    passed = summary.get("passed", 0)
    failed = summary.get("failed", 0)
    skipped = summary.get("skipped", 0)
    duration = round(report.get("duration", 0), 1)
    icon = _status_icon(passed, failed, total)

    failed_tests: list[dict[str, Any]] = [
        t for t in report.get("tests", []) if t.get("outcome") == "failed"
    ]
    failed_block = ""
    if failed_tests:
        rows = []
        for t in failed_tests[:5]:
            name = t.get("nodeid", "unknown")
            call = t.get("call", {})
            longrepr = call.get("longrepr", "") if isinstance(call, dict) else ""
            first_line = longrepr.split("\n")[0][:120] if longrepr else "see logs"
            rows.append(f"| `{name}` | {first_line} |")
        failed_block = "\n**Failed tests:**\n\n| Test | Error |\n|------|-------|\n" + "\n".join(rows)
        if len(failed_tests) > 5:
            failed_block += f"\n\n_…and {len(failed_tests) - 5} more failures_"

    # --- Section 4: Preview Environment ---
    env_url = preview_url or f"(no preview URL — namespace: {namespace})"

    # --- Section 5: Next Steps ---
    next_steps = []
    if failed > 0:
        kagent_marker = any(
            "kagent_demo" in str(t.get("markers", "")) or "kagent_demo" in t.get("nodeid", "")
            for t in failed_tests
        )
        if kagent_marker:
            next_steps.append("kagent AI analysis triggered — check the `kagent` namespace for the analysis report")
        next_steps.append(f"Fix {failed} failing test(s) and push a new commit")
    if "database_migration" in detected or "migration" in str(selected_suites):
        next_steps.append("Verify database migration was applied cleanly in the preview environment")
    if "api_contract" in detected:
        next_steps.append("Run Microcks contract tests to validate the API schema change")
    if not next_steps:
        next_steps.append("All tests passed — ready for review")

    next_steps_block = "\n".join(f"- {s}" for s in next_steps)

    comment = f"""{MARKER}

## idp-preview — PR #{pr}

> Generated at {now} · Namespace `{namespace}`

---

### 1 · What Changed

**Detected impact areas:**
{impact_lines}

**Changed files:**
{file_lines}

---

### 2 · Why These Tests Ran

{reason}

**Selected suites:**
{suite_lines}

---

### 3 · Test Results {icon}

| Metric | Value |
|--------|-------|
| Total  | {total} |
| Passed | {passed} |
| Failed | {failed} |
| Skipped | {skipped} |
| Duration | {duration}s |
{failed_block}

---

### 4 · Preview Environment

**URL:** {env_url}

```
kubectl get pods -n {namespace}
kubectl logs -n {namespace} -l app=backend --tail=50
```

---

### 5 · Next Steps

{next_steps_block}

---
<sub>Built by <a href="https://github.com/ihsenalaya/idp-preview">idp-preview</a> operator · <a href="https://github.com/ihsenalaya/idp-preview/blob/main/tools/pr-comment-builder/__main__.py">comment builder source</a></sub>
"""
    return comment


def is_idempotent_update(existing: str, new_comment: str) -> bool:
    return MARKER in existing


def main() -> None:
    parser = argparse.ArgumentParser(description="Build idempotent PR comment for idp-preview")
    parser.add_argument("--change-context", default="", help="Path to changeContext YAML file")
    parser.add_argument("--report-dir", default="test-reports", help="Directory with pytest-report.json")
    parser.add_argument("--preview-url", default="", help="Preview environment URL")
    parser.add_argument("--namespace", default="preview", help="Kubernetes namespace")
    parser.add_argument("--pr", default="?", help="Pull request number")
    parser.add_argument("--output", default="pr-comment.md", help="Output markdown file")
    parser.add_argument("--check-idempotent", default="", help="Path to existing comment to check")
    args = parser.parse_args()

    change_context: dict = {}
    if args.change_context and os.path.exists(args.change_context):
        try:
            change_context = load_yaml(args.change_context)
        except Exception as e:
            print(f"Warning: could not load change context: {e}", file=sys.stderr)

    report = load_report(args.report_dir)

    comment = build_comment(
        change_context=change_context,
        report=report,
        preview_url=args.preview_url,
        namespace=args.namespace,
        pr=args.pr,
    )

    if args.check_idempotent and os.path.exists(args.check_idempotent):
        with open(args.check_idempotent) as f:
            existing = f.read()
        if is_idempotent_update(existing, comment):
            print(f"Idempotent update — replacing existing comment in {args.output}")

    with open(args.output, "w") as f:
        f.write(comment)

    print(f"PR comment written to {args.output} ({len(comment)} bytes)")


if __name__ == "__main__":
    main()
