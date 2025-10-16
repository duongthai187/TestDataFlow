# Wave 0 – Platform Bootstrapping Plan

## 1. Objectives
- Thiết lập khung làm việc chuẩn cho toàn bộ microservice mono-repo: cấu trúc dự án, tooling, CI/CD, docker compose.
- Đảm bảo developer có thể chạy `docker compose up` để boot tất cả services (stub) + infrastructure (Kafka, DBs) và chạy test/lint cơ bản.
- Chuẩn bị nền tảng cho các wave tiếp theo (Wave 1+).

## 2. Scope
- Repo scaffolding (directory tree, shared libraries, config).
- Python tooling (Poetry workspace/Hatch), lint/format/test harness.
- Docker Compose extension: add service build contexts, env templates, network.
- CI/CD pipeline initial (GitHub Actions) covering lint + unit tests + build.
- Developer onboarding documentation (`README`, make commands).

## 3. Deliverables
| Deliverable | Description |
| --- | --- |
| Repository skeleton | `services/<service>` directories with minimal FastAPI app.
| Shared libs | `services/common` for config, logging, tracing, Kafka clients.
| Tooling | `pyproject.toml` (workspace), `Makefile`, `.pre-commit-config.yaml`.
| Docker | Updated `docker-compose.yml` to include service build contexts (placeholder containers). |
| CI pipeline | `.github/workflows/ci.yml` with lint/test/build steps. |
| Documentation | root `README.md`, developer onboarding doc. |

## 4. Task Breakdown
| ID | Task | Details | Owner | Duration |
| --- | --- | --- | --- | --- |
| W0-01 | Repo Initialization | Create root structure, commit baseline | Platform | 1d |
| W0-02 | Configure Poetry workspace | Set up `pyproject.toml`, dependency groups (prod/dev/test) | Platform | 0.5d |
| W0-03 | Scaffold FastAPI template | `services/common/` + cookiecutter style to generate service skeleton | Platform | 1d |
| W0-04 | Create skeleton services | For customer, catalog, pricing, cart, order, payment, inventory, fulfillment, support, notification, fraud, recommendation (basic `/health` endpoint) | Backend | 1d (automated) |
| W0-05 | Update docker-compose | Add build sections pointing to each service, environment `.env.example` | Platform | 1d |
| W0-06 | Setup CI | GitHub Actions: lint (`ruff`), format (`black --check`), type (`mypy`), tests (`pytest`) | DevOps | 1d |
| W0-07 | Pre-commit hooks | Configure `pre-commit` with `ruff`, `black`, `isort` | Platform | 0.5d |
| W0-08 | Documentation | Write README (run instructions, directory layout, make targets) | DevRel | 0.5d |
| W0-09 | Observability bootstrap | Add `/metrics` endpoint via Prometheus FastAPI plugin, standard logging format | Backend | 1d |

## 5. Detailed Steps
### 5.1 Repository Structure
```
services/
  common/
    __init__.py
    config.py
    logging.py
    kafka.py
    tracing.py
  customer-service/
    app/main.py
    app/api/routes.py
    app/dependencies.py
    app/db.py
    tests/
  ... (other services)
pyproject.toml
poetry.lock
Makefile
.pre-commit-config.yaml
docker-compose.yml
.env.example
```
- Each service includes `routers.health`, `routers.info` for stub endpoints.
- Database stubs (SQLAlchemy for SQL services, `cassandra-driver` placeholder, `couchdb` client).

### 5.2 Poetry Workspace
- `pyproject.toml` example:
```toml
[tool.poetry]
name = "ecommerce-platform"
version = "0.1.0"
description = "Monorepo for microservice ecommerce"
package-mode = false

[tool.poetry.dependencies]
python = "^3.11"
fastapi = "^0.115"
udf = "..."

[tool.poetry.group.dev.dependencies]
pytest = "^8.3"
black = "^24.8"
ruff = "^0.5"
mypy = "^1.11"
pre-commit = "^3.7"
```
- Configure path dependencies for each service or use Poetry plugins like `poetry-multiproject`.

### 5.3 Service Skeleton (Example `app/main.py`)
```python
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from services.common.config import settings
from services.common.logging import configure_logging
from .api import health

configure_logging()
app = FastAPI(title="Customer Service")
app.include_router(health.router)

@app.on_event("startup") async def startup_event():
    Instrumentator().instrument(app).expose(app)

@app.get("/health", tags=["health"]) async def healthcheck():
    return {"status": "ok"}
```
- Use `Instrumentator` for `/metrics`.
- Add middleware for request logging & correlation ID.

### 5.4 Docker Compose Updates
- For each service (example customer-service):
```yaml
  customer-service:
    build:
      context: ./services/customer-service
      dockerfile: Dockerfile
    environment:
      SERVICE_NAME: customer-service
      DATABASE_URL: postgresql://app:app123@postgres:5432/appdb
    ports:
      - "8101:8000"
    depends_on:
      - postgres
    networks: [datanet]
```
- Template `Dockerfile` per service using multi-stage build (Poetry install -> slim image).
- Provide `.env.example` with shared config (Kafka host, DB credentials).

### 5.5 CI/CD Pipeline (`.github/workflows/ci.yml`)
```yaml
name: CI
on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install Poetry
        run: pip install poetry
      - name: Install deps
        run: poetry install
      - name: Lint
        run: poetry run ruff check .
      - name: Format check
        run: poetry run black --check .
      - name: Type check
        run: poetry run mypy services
      - name: Tests
        run: poetry run pytest
```

### 5.6 Documentation & Makefile
- Makefile commands:
```
install:
	poetry install

lint:
	poetry run ruff check .

format:
	poetry run black .

run:
	docker compose up --build

seed:
	poetry run python scripts/seed/base_seed.py
```
- README sections: architecture overview, prerequisites, quick start, service endpoints.

## 6. Dependencies & Risks
- Need consistent Python version across services (3.11). Ensure dev environment ready.
- Build times: consider caching Poetry install in Docker (use `poetry export` + pip install for runtime image).
- Dev experience: ensure `pre-commit` easy to install via `poetry run pre-commit install`.

## 7. Acceptance Criteria
- Running `docker compose up --build` launches all stub services with `/health` returning 200.
- `poetry run pytest` passes (placeholder tests verifying health endpoint).
- CI pipeline green; blocking on PR merges.
- Developer docs guide new engineer to run, test, and extend a service within 30 mins.

## 8. Next Steps
- Move to Wave 1 once Wave 0 deliverables completed: implement full functionality for customer, catalog, pricing, and cart services.
- Begin populating Debezium/Schema Registry config for Wave 1 depending on requirements.
