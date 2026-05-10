.PHONY: help validate-openapi validate-yaml microcks-contract-test lint-shell py-compile \
        test-unit test-regression test-migration test-contract test-e2e test-all \
        seed pr-comment

MICROCKS_URL        ?= http://localhost:8080
BACKEND_URL         ?= http://localhost:8080
API_NAME            ?= Preview Catalog API
API_VERSION         ?= 1.0.0
TEST_RUNNER         ?= OPEN_API_SCHEMA
REPORT_DIR          ?= test-reports
PREVIEW_URL         ?=
NAMESPACE           ?= preview
PR                  ?= 0

help:
	@echo ""
	@echo "  Preview Platform — available make targets"
	@echo ""
	@echo "  Test targets:"
	@echo "    test-unit          Run unit tests (no DB/API required)"
	@echo "    test-regression    Run regression tests (requires DATABASE_URL + running API)"
	@echo "    test-migration     Run migration tests (requires DATABASE_URL)"
	@echo "    test-contract      Run contract/schemathesis tests"
	@echo "    test-e2e           Run Playwright E2E tests (requires FRONTEND_URL)"
	@echo "    test-all           Run all test suites"
	@echo ""
	@echo "  Other targets:"
	@echo "    seed               Seed the database with default data"
	@echo "    pr-comment         Build PR comment markdown"
	@echo "    validate-openapi   Validate api/openapi.yaml"
	@echo "    validate-yaml      Validate all YAML files"
	@echo "    microcks-contract-test  Run Microcks contract test"
	@echo "    lint-shell         Run shellcheck"
	@echo "    py-compile         Syntax-check Python files"
	@echo ""
	@echo "  Env vars: DATABASE_URL, PREVIEW_URL, NAMESPACE, PR, REPORT_DIR"
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

test-unit:
	@echo "→ Running unit tests …"
	@mkdir -p $(REPORT_DIR)
	@python3 -m pytest tests/unit/ -m "not requires_db and not requires_api" \
	  --json-report --json-report-file=$(REPORT_DIR)/pytest-report.json -v

test-regression:
	@echo "→ Running regression tests (requires DATABASE_URL + API) …"
	@mkdir -p $(REPORT_DIR)
	@python3 -m pytest tests/regression/ \
	  --json-report --json-report-file=$(REPORT_DIR)/pytest-report.json -v

test-migration:
	@echo "→ Running migration tests (requires DATABASE_URL) …"
	@mkdir -p $(REPORT_DIR)
	@python3 -m pytest tests/migration/ -m requires_db \
	  --json-report --json-report-file=$(REPORT_DIR)/pytest-report.json -v

test-contract:
	@echo "→ Running contract/schemathesis tests …"
	@mkdir -p $(REPORT_DIR)
	@python3 -m pytest tests/contract/ \
	  --json-report --json-report-file=$(REPORT_DIR)/pytest-report.json -v

test-e2e:
	@echo "→ Running E2E tests (requires FRONTEND_URL) …"
	@mkdir -p $(REPORT_DIR)
	@python3 -m pytest tests/e2e.py \
	  --json-report --json-report-file=$(REPORT_DIR)/pytest-report.json -v

test-all:
	@echo "→ Running all test suites …"
	@mkdir -p $(REPORT_DIR)
	@python3 -m pytest tests/ \
	  --json-report --json-report-file=$(REPORT_DIR)/pytest-report.json -v

seed:
	@echo "→ Seeding database …"
	@if [ -z "$$DATABASE_URL" ]; then echo "DATABASE_URL not set"; exit 1; fi
	@psql "$$DATABASE_URL" -f seeds/default/seed.sql

pr-comment:
	@echo "→ Building PR comment …"
	@mkdir -p $(REPORT_DIR)
	@python3 -m tools.pr-comment-builder \
	  --change-context $(CHANGE_CONTEXT_FILE) \
	  --report-dir $(REPORT_DIR) \
	  --preview-url "$(PREVIEW_URL)" \
	  --namespace "$(NAMESPACE)" \
	  --pr "$(PR)" \
	  --output pr-comment.md
	@echo "  Written to pr-comment.md"
