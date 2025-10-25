POETRY?=poetry
PYTHON?=python3
SERVICE?=
ARGS?=

.PHONY: install install-dev fmt fmt-check lint test run-service support-probe support-offload support-generate notification-probe notification-chaos-provider notification-chaos-redis chaos-replication-lag chaos-schema-drift chaos-ttl-oversell chaos-fulfillment-delay

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

support-generate:
	$(POETRY) run python scripts/synthetic/generate_support_cases.py $(ARGS)

notification-probe:
	$(POETRY) run python scripts/synthetic/notification_probe.py $(ARGS)

notification-chaos-provider:
	$(POETRY) run python scripts/chaos/notification_provider_failure.py $(ARGS)

notification-chaos-redis:
	$(POETRY) run python scripts/chaos/notification_redis_outage.py $(ARGS)

chaos-replication-lag:
	$(POETRY) run python scripts/chaos/simulate_replication_lag.py $(ARGS)

chaos-schema-drift:
	$(POETRY) run python scripts/chaos/simulate_schema_drift.py $(ARGS)

chaos-ttl-oversell:
	$(POETRY) run python scripts/chaos/simulate_ttl_oversell.py $(ARGS)

chaos-fulfillment-delay:
	$(POETRY) run python scripts/chaos/simulate_fulfillment_delay.py $(ARGS)
