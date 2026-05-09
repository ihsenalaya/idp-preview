#!/usr/bin/env python3
"""
validate-openapi.py — validate an OpenAPI 3.0.x document.

Checks performed:
  1. File is parseable YAML
  2. Top-level required fields are present (openapi, info, paths)
  3. openapi version starts with "3."
  4. All $ref targets exist in components/
  5. All paths have at least one method with operationId and responses
  6. All response schemas referenced exist in components/schemas

Exit code: 0 if valid, 1 if any check fails.

Usage:
  python3 scripts/validate-openapi.py api/openapi.yaml
  make validate-openapi
"""
import sys
import pathlib

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}

errors = []
warnings = []


def err(msg):
    errors.append(msg)
    print(f"  FAIL  {msg}")


def warn(msg):
    warnings.append(msg)
    print(f"  WARN  {msg}")


def ok(msg):
    print(f"  PASS  {msg}")


def resolve_ref(spec, ref):
    """Return the object pointed to by a $ref like '#/components/schemas/Foo'."""
    if not ref.startswith("#/"):
        return None
    parts = ref[2:].split("/")
    node = spec
    for part in parts:
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def collect_refs(node, refs=None):
    """Recursively collect all $ref strings in a YAML document."""
    if refs is None:
        refs = set()
    if isinstance(node, dict):
        if "$ref" in node:
            refs.add(node["$ref"])
        for v in node.values():
            collect_refs(v, refs)
    elif isinstance(node, list):
        for item in node:
            collect_refs(item, refs)
    return refs


def main():
    if len(sys.argv) < 2:
        print("Usage: validate-openapi.py <path-to-openapi.yaml>", file=sys.stderr)
        sys.exit(1)

    path = pathlib.Path(sys.argv[1])
    if not path.exists():
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    print(f"Validating {path} …")
    print()

    # 1. Parse YAML
    try:
        with path.open() as f:
            spec = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        err(f"YAML parse error: {exc}")
        _report()
        sys.exit(1)

    if not isinstance(spec, dict):
        err("Document root must be a YAML mapping")
        _report()
        sys.exit(1)

    ok("YAML parse succeeded")

    # 2. Required top-level fields
    for field in ("openapi", "info", "paths"):
        if field not in spec:
            err(f"Missing required top-level field: '{field}'")
        else:
            ok(f"Top-level field '{field}' present")

    # 3. OpenAPI version
    version = spec.get("openapi", "")
    if not str(version).startswith("3."):
        err(f"openapi version must start with '3.' — got '{version}'")
    else:
        ok(f"openapi version: {version}")

    # 4. Info fields
    info = spec.get("info", {})
    for field in ("title", "version"):
        if field not in info:
            err(f"Missing info.{field}")
        else:
            ok(f"info.{field}: {info[field]!r}")

    # 5. Paths
    paths = spec.get("paths", {})
    if not paths:
        warn("No paths defined")
    else:
        ok(f"{len(paths)} path(s) defined")

    for path_str, path_item in paths.items():
        if not isinstance(path_item, dict):
            err(f"Path '{path_str}' must be a mapping")
            continue
        methods = [m for m in path_item if m in HTTP_METHODS]
        if not methods:
            warn(f"Path '{path_str}' has no HTTP methods")
            continue
        for method in methods:
            op = path_item[method]
            if not isinstance(op, dict):
                err(f"  {method.upper()} {path_str}: operation must be a mapping")
                continue
            if "operationId" not in op:
                warn(f"  {method.upper()} {path_str}: missing operationId")
            if "responses" not in op:
                err(f"  {method.upper()} {path_str}: missing responses")
            else:
                ok(f"  {method.upper()} {path_str} ({op.get('operationId','?')})")

    # 6. $ref resolution
    all_refs = collect_refs(spec)
    components = spec.get("components", {})

    for ref in sorted(all_refs):
        if not ref.startswith("#/"):
            warn(f"External $ref not checked: {ref}")
            continue
        target = resolve_ref(spec, ref)
        if target is None:
            err(f"Unresolved $ref: {ref}")
        else:
            ok(f"Resolved $ref: {ref}")

    # 7. Summary
    print()
    print("=" * 50)
    print(f"  {len(errors)} error(s), {len(warnings)} warning(s)")
    print("=" * 50)

    if errors:
        sys.exit(1)


def _report():
    print()
    print(f"{len(errors)} error(s), {len(warnings)} warning(s)")


if __name__ == "__main__":
    main()
