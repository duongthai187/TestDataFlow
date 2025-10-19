# TestDataFlow Microservices Platform

![CI](https://github.com/duongthai187/TestDataFlow/actions/workflows/ci.yml/badge.svg)
![Support Synthetic Probe](https://github.com/duongthai187/TestDataFlow/actions/workflows/support-synthetic-probe.yml/badge.svg)

This repository hosts the ecommerce microservices platform scaffolding (Wave 0) for the DataFlow program. It provides a FastAPI-based mono-repo with shared tooling, development automation, and Docker Compose integration to run all stub services and core infrastructure locally.

## Prerequisites
- Python 3.11
- Poetry 1.8+
- Docker & Docker Compose

## Getting Started
1. **Install dependencies**
   ```bash
   poetry install --no-root --with dev
   ```
2. **Set up pre-commit (optional but recommended)**
   ```bash
   poetry run pre-commit install
   ```
3. **Run quality checks**
   ```bash
   make fmt-check
   make lint
   make test
   ```
4. **Run the services (stub mode)**
   ```bash
   docker compose up --build customer-service catalog-service
   ```
   Replace the service list with the ones you need; all services expose a `/health` endpoint. Use `docker compose ps --format "table {{.Name}}\t{{.State}}\t{{.Health}}"` to confirm every dependency is `healthy`—Compose waits on healthchecks before starting downstream containers.

## Repository Layout
```
services/
  common/          # Shared libraries (config, logging, instrumentation)
  <service>/       # Service-specific FastAPI applications
  Dockerfile       # Shared Dockerfile used by all service containers
.github/workflows/ # CI pipeline definition
Makefile           # Helper commands for development
pyproject.toml     # Poetry configuration
```

## Available Make Targets
- `make install`: install project dependencies (production set)
- `make install-dev`: install dependencies including dev tooling
- `make fmt`: auto-format sources with Black and Ruff
- `make fmt-check`: verify formatting
- `make lint`: run `mypy` and `ruff`
- `make test`: execute pytest suite across all services
- `make run-service SERVICE=<name>`: run a specific service via Uvicorn (e.g. `SERVICE=customer_service`)
- `make support-probe ARGS="..."`: run the synthetic support timeline probe (e.g. `ARGS="--base-url http://localhost:8109"`)
- `make support-offload ARGS="..."`: execute the support attachment offload tool (use `ARGS="--dry-run"` to audit)

## Environment Configuration
Copy `.env.example` to `.env` and adjust values when overriding defaults. Settings are prefixed with `SERVICE_` and automatically loaded by each service.

## Next Steps
Wave 1 will replace the stub health endpoints with real service logic for the core transactional services (customer, catalog, pricing, cart) and connect them to the persistence layer and Kafka events.
