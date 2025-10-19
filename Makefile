POETRY?=poetry
PYTHON?=python3
SERVICE?=
ARGS?=

.PHONY: install install-dev fmt fmt-check lint test run-service support-probe support-offload

install:
	$(POETRY) install --no-root

install-dev:
	$(POETRY) install --no-root --with dev

fmt:
	$(POETRY) run black services
	$(POETRY) run ruff check services --fix

fmt-check:
	$(POETRY) run black services --check
	$(POETRY) run ruff check services

lint:
	$(POETRY) run mypy services
	$(POETRY) run ruff check services

test:
	$(POETRY) run pytest

run-service:
ifndef SERVICE
	$(error SERVICE must be provided, e.g. make run-service SERVICE=customer_service)
endif
	$(POETRY) run uvicorn services.$(SERVICE).app.main:app --host 0.0.0.0 --port 8000

support-probe:
	$(POETRY) run python scripts/synthetic/support_timeline_probe.py $(ARGS)

support-offload:
	$(POETRY) run python scripts/maintenance/offload_support_attachments.py $(ARGS)
