# PHINS — unified developer / operator entry point
# -----------------------------------------------------------------------------
# This Makefile is the single human-facing entry point for build, test,
# deploy, validate, and restore operations. It replaces the previous
# scatter of ~10 deploy/test shell scripts.
#
# Quick start:
#   make help              show this list
#   make install           install runtime deps
#   make install-dev       install runtime + dev/test deps
#   make smoke             quick end-to-end smoke test against localhost:8000
#   make test              full pytest suite
#   make test-fast         pytest with parallel workers
#   make validate          run all validators (system, external, portal, railway)
#   make serve             run the web portal locally (./scripts/entrypoint.sh)
#   make docker-build      build the multi-stage Docker image
#   make docker-run        run the image locally on :8000
#   make ci-local          replay the GitHub Actions security_scan checks
#   make backup            invoke scripts/backup_platform.sh
#   make restore TARGET=<commit-or-date>  preview a restore (dry-run by default)
#   make restore-apply TARGET=<commit-or-date>  actually run the restore
#   make clean             remove caches and bytecode
#
# Environment overrides:
#   PORT, HOST, DATABASE_URL, USE_SQLITE, USE_DATABASE, PHINS_TEST_MODE
# -----------------------------------------------------------------------------

PYTHON       ?= python3
PIP          ?= $(PYTHON) -m pip
PYTEST       ?= $(PYTHON) -m pytest
DOCKER       ?= docker
IMAGE_NAME   ?= phins-portal
IMAGE_TAG    ?= local
PORT         ?= 8000
HOST         ?= 127.0.0.1
ENTRYPOINT   := ./scripts/entrypoint.sh

# Tracker for the canonical smoke flow.
SMOKE_BASE_URL ?= http://localhost:$(PORT)

.DEFAULT_GOAL := help

.PHONY: help install install-dev install-runtime serve cron db-init smoke \
        test test-fast test-smoke validate validate-system \
        validate-external validate-portal validate-railway \
        docker-build docker-run docker-shell ci-local \
        backup restore restore-apply clean tree

help:
	@awk 'BEGIN {FS = ":.*##"; printf "PHINS Makefile targets:\n"} \
	      /^[a-zA-Z_-]+:.*?##/ { printf "  %-22s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

# -----------------------------------------------------------------------------
# Install
# -----------------------------------------------------------------------------
install: install-runtime ## install runtime deps only (matches production image)

install-runtime: ## install runtime deps only
	$(PIP) install -r requirements.txt

install-dev: ## install runtime + dev/test deps (pytest, mypy, moto)
	$(PIP) install -r requirements-dev.txt

# -----------------------------------------------------------------------------
# Run
# -----------------------------------------------------------------------------
serve: ## run the production web portal locally via entrypoint.sh
	PORT=$(PORT) HOST=$(HOST) $(ENTRYPOINT) serve

cron: ## run the monthly auto-pay batch (one-shot)
	$(ENTRYPOINT) cron

db-init: ## initialize the database (idempotent; refuses prod-style seeding)
	$(ENTRYPOINT) db-init

# -----------------------------------------------------------------------------
# Test
# -----------------------------------------------------------------------------
test: ## full pytest suite
	$(PYTEST) -q

test-fast: ## pytest with parallel workers (requires pytest-xdist)
	$(PYTEST) -q -n auto

test-smoke: ## quick smoke test against $(SMOKE_BASE_URL)
	@bash quick_smoke_test.sh

smoke: test-smoke ## alias for test-smoke

# -----------------------------------------------------------------------------
# Validate (delegates to the existing Python validators; phase 5 will
# consolidate these into a single 'phins validate' CLI)
# -----------------------------------------------------------------------------
validate: validate-system validate-external validate-portal validate-railway ## run all validators

validate-system: ## system invariants validator
	$(PYTHON) validate_system.py

validate-external: ## external integrations probe
	$(PYTHON) validate_external_services.py

validate-portal: ## portal customer-access validator
	$(PYTHON) validate_portal_customer_access.py

validate-railway: ## railway config validator
	$(PYTHON) validate_railway_config.py

# -----------------------------------------------------------------------------
# Docker
# -----------------------------------------------------------------------------
docker-build: ## build the multi-stage image
	$(DOCKER) build -t $(IMAGE_NAME):$(IMAGE_TAG) .

docker-run: ## run the image locally on $(PORT)
	$(DOCKER) run --rm -p $(PORT):$(PORT) -e PORT=$(PORT) $(IMAGE_NAME):$(IMAGE_TAG)

docker-shell: ## drop into /bin/sh inside the image (debugging)
	$(DOCKER) run --rm -it --entrypoint $(ENTRYPOINT) $(IMAGE_NAME):$(IMAGE_TAG) shell

# -----------------------------------------------------------------------------
# CI replay (best-effort local simulation of .github/workflows/security_scan.yml)
# -----------------------------------------------------------------------------
ci-local: ## replay the security_scan job locally (best-effort)
	@command -v bandit  >/dev/null || $(PIP) install bandit
	@command -v safety  >/dev/null || $(PIP) install safety
	@command -v pip-audit >/dev/null || $(PIP) install pip-audit
	bandit -r . --exclude "./.git,./node_modules,./__pycache__,./tests,./.venv" || true
	safety check -r requirements.txt --full-report || true
	pip-audit -r requirements.txt || true

# -----------------------------------------------------------------------------
# Backup / restore
# -----------------------------------------------------------------------------
backup: ## produce a full platform snapshot under backups/<UTC-timestamp>/
	bash scripts/backup_platform.sh

restore: ## preview a restore (dry-run). Usage: make restore TARGET=<commit-or-date>
	./preview_restore.sh $(TARGET)

restore-apply: ## actually run a restore. Usage: make restore-apply TARGET=<commit-or-date>
	./restore_platform.sh $(TARGET)

# -----------------------------------------------------------------------------
# Housekeeping
# -----------------------------------------------------------------------------
clean: ## remove pycache, pytest cache, mypy cache, coverage
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -prune -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -prune -exec rm -rf {} +
	rm -rf .coverage coverage htmlcov

tree: ## print the high-value paths section of AGENTS.md
	@sed -n '/^## 2) High-Value Paths/,/^## 3) Hard Rules/p' AGENTS.md
