.PHONY: help validate-openapi validate-yaml microcks-contract-test lint-shell py-compile

MICROCKS_URL        ?= http://localhost:8080
BACKEND_URL         ?= http://localhost:8080
API_NAME            ?= Preview Catalog API
API_VERSION         ?= 1.0.0
TEST_RUNNER         ?= OPEN_API_SCHEMA

help:
	@echo ""
	@echo "  Preview Platform — available make targets"
	@echo ""
	@echo "  validate-openapi       Validate api/openapi.yaml against OpenAPI 3.0.3 spec"
	@echo "  validate-yaml          Validate all YAML files in k8s/ and api/"
	@echo "  microcks-contract-test Run Microcks contract test against BACKEND_URL"
	@echo "  lint-shell             Run shellcheck on all shell scripts"
	@echo "  py-compile             Syntax-check all Python files"
	@echo ""
	@echo "  Env vars for microcks-contract-test:"
	@echo "    MICROCKS_URL (default: $(MICROCKS_URL))"
	@echo "    BACKEND_URL  (default: $(BACKEND_URL))"
	@echo "    MICROCKS_CLIENT_ID / MICROCKS_CLIENT_SECRET (optional)"
	@echo ""

validate-openapi:
	@echo "→ Validating api/openapi.yaml …"
	@python3 scripts/validate-openapi.py api/openapi.yaml

validate-yaml:
	@echo "→ Validating YAML files …"
	@python3 scripts/validate-yaml.py

microcks-contract-test:
	@echo "→ Running Microcks contract test …"
	@MICROCKS_URL="$(MICROCKS_URL)" \
	 BACKEND_URL="$(BACKEND_URL)" \
	 API_NAME="$(API_NAME)" \
	 API_VERSION="$(API_VERSION)" \
	 TEST_RUNNER="$(TEST_RUNNER)" \
	 bash scripts/run-microcks-contract-test.sh

lint-shell:
	@echo "→ Running shellcheck …"
	@if command -v shellcheck >/dev/null 2>&1; then \
	  shellcheck scripts/run-microcks-contract-test.sh; \
	  echo "  shellcheck passed."; \
	else \
	  echo "  shellcheck not installed — skipping."; \
	fi

py-compile:
	@echo "→ Syntax-checking Python files …"
	@python3 -m py_compile app.py && echo "  PASS app.py"
	@python3 -m py_compile frontend.py && echo "  PASS frontend.py"
	@python3 -m py_compile tests/regression.py && echo "  PASS tests/regression.py"
	@python3 -m py_compile tests/e2e.py && echo "  PASS tests/e2e.py"
	@python3 -m py_compile tests/example_test.py && echo "  PASS tests/example_test.py"
	@python3 -m py_compile scripts/validate-yaml.py && echo "  PASS scripts/validate-yaml.py"
	@python3 -m py_compile scripts/validate-openapi.py && echo "  PASS scripts/validate-openapi.py"
