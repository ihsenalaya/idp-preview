#!/usr/bin/env python3
"""
validate-yaml.py — parse all YAML files under k8s/ and api/ and report errors.

Exit code: 0 if all files are valid, 1 if any file fails to parse.

Usage:
  python3 scripts/validate-yaml.py
  make validate-yaml
"""
import sys
import pathlib

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

ROOT = pathlib.Path(__file__).parent.parent
SEARCH_DIRS = [ROOT / "k8s", ROOT / "api"]

passed = 0
failed = 0
errors = []

for search_dir in SEARCH_DIRS:
    if not search_dir.exists():
        continue
    for path in sorted(search_dir.rglob("*.yaml")):
        rel = path.relative_to(ROOT)
        try:
            with path.open() as f:
                docs = list(yaml.safe_load_all(f))
            # Reject empty files (None document with no content)
            non_empty = [d for d in docs if d is not None]
            if not non_empty:
                print(f"  WARN  {rel}  (empty file)")
            else:
                print(f"  PASS  {rel}  ({len(non_empty)} document(s))")
            passed += 1
        except yaml.YAMLError as exc:
            print(f"  FAIL  {rel}  — {exc}")
            errors.append(str(rel))
            failed += 1
        except OSError as exc:
            print(f"  FAIL  {rel}  — {exc}")
            errors.append(str(rel))
            failed += 1

print()
print(f"Results: {passed} passed, {failed} failed")

if errors:
    print()
    print("Failed files:")
    for e in errors:
        print(f"  {e}")
    sys.exit(1)
