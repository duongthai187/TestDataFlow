# Phase 0 – Microservice Ecommerce Foundation Implementation Plan

## 1. Objectives
- Xây dựng hệ thống microservice ecommerce tối thiểu (MVP) phản ánh đúng các vấn đề trong usecase: phân mảnh dữ liệu, TTL oversell, schema drift, latency trong reconciliation.
- Đảm bảo mỗi service có skeleton FastAPI, database riêng, event publishing via Kafka, và observability cơ bản.
- Chuẩn bị dữ liệu/simulator để tái tạo các sự cố trước khi bước sang giai đoạn AI/ML/Data/Agent Ops.

## 2. Environment & Tooling
| Stack | Purpose |
| --- | --- |
| Python 3.11 + FastAPI | Service implementation |
| Poetry or Hatch | Dependency management |
| Docker Compose | Local orchestration (reuse existing compose) |
| Alembic / Liquibase | DB migration management |
| pytest + httpx | Service/unit tests |
| Kafka + Debezium | Event backbone & CDC |
| Prometheus + Grafana + Loki | Observability baseline |

## 3. Delivery Waves & Milestones
| Wave | Duration | Focus | Deliverables |
| --- | --- | --- | --- |
| W0 – Platform Bootstrapping | Week 1 | Repo scaffolding, CI, base compose | root project layout, Makefile, GitHub Actions pipeline |
| W1 – Core Services | Week 2-3 | Customer, Catalog, Pricing, Cart | FastAPI services with DB migrations, OpenAPI specs |
| W2 – Transactional Backbone | Week 4-5 | Order, Payment, Inventory | Service contracts, transactional logic, Kafka events |
| W3 – Fulfillment & Support | Week 6 | Fulfillment, Support, Notification | Integration with MinIO, attachments, messaging |
| W4 – Cross-Cutting & Issues Simulation | Week 7 | Fraud, Recommendation stub, Observability, Incident scripts | CDC connectors, synthetic data, chaos scripts |

## 4. Repository & Mono-Repo Structure
```
/ services/
  customer-service/
  catalog-service/
  pricing-service/
  cart-service/
  order-service/
  payment-service/
  inventory-service/
  fulfillment-service/
  support-service/
  notification-service/
  fraud-service/
  recommendation-service/
/tests/
/scripts/
  seed/
  chaos/
/docker/
  compose/
  configs/
/docs/design/...
```
- Shared libraries: `services/common/` for logging, tracing, Kafka producers, auth.
- Each service: `app/main.py`, `app/api`, `app/models`, `app/db`, `tests/`.
- Use `.env` per service loaded via Pydantic Settings.

## 5. Core Implementation Tasks (Detailed)
### 5.1 Wave 0 – Bootstrapping
- T-01: Initialize mono-repo with Poetry workspace, lints (`ruff`, `black`, `mypy` baseline).
- T-02: Define shared FastAPI starter (logging middleware, tracing, error handling).
- T-03: Configure GitHub Actions pipeline (lint, unit tests, docker build, generate OpenAPI docs artifact).
- T-04: Extend docker-compose with per-service placeholders (images build context, environment variables) using existing infrastructure containers.

### 5.2 Wave 1 – Core Domain Services
- Customer-service:
  - Implement CRUD APIs, segmentation endpoints, Redis cache.
  - Expose FastAPI docs (`/docs`), instrument metrics.
- Catalog-service:
  - CouchDB integration, GraphQL endpoint (Strawberry or Ariadne) for storefront queries.
  - Media upload stub to MinIO.
- Pricing-service:
  - Rule evaluation engine scaffolding, currency updater stub.
  - Kafka event publishing on rule changes.
- Cart-service:
  - Redis caching, MySQL persistence, integrate pricing snapshot.
  - Publish `cart.item.added` events.
- Shared tasks: implement Pydantic models, register Avro schema definitions for emitted events.

### 5.3 Wave 2 – Transactional Backbone
- Order-service:
  - Order creation flow, idempotency, event emission, status transitions.
  - Integration with cart (consume `cart.checkedout`).
- Payment-service:
  - Simulate PSP integration (mock connector), ledger tables, outbox pattern.
  - Publish `payment.authorized` / `payment.failed`.
- Inventory-service:
  - Cassandra schema, reservation endpoint w/ TTL, CDC hook.
- Kafka & Debezium configuration for MySQL/PostgreSQL change streams.
- Implement saga orchestration (order -> payment -> inventory) with compensation logic to replicate oversell issue (delayed confirmation).

### 5.4 Wave 3 – Fulfillment & Support Layer
- Fulfillment-service:
  - Shipment creation, tracking API, MinIO label storage.
  - Webhook for carrier updates (mock).
- Support-service:
  - Ticket creation, attachments (MinIO), timeline aggregator (calls order/payment/fulfillment).
- Notification-service:
  - Template management, provider mock (log to console), preference enforcement.
- Implement asynchronous email/SMS simulation; ensure events consumed for support/notification interplay.

### 5.5 Wave 4 – Advanced & Issue Simulators
- Fraud-service skeleton consuming order/payment events, scoring stub (random/deterministic for scenarios).
- Recommendation-service stub: expose `/recommendations` returning placeholder; log requests for later MLOps integration.
- Observability: instrument all services with Prometheus metrics, Loki logging, distributed tracing (OpenTelemetry with OTLP exporter).
- Chaos scripts in `/scripts/chaos/`:
  - `simulate_replica_lag.py`: throttle MySQL replica.
  - `introduce_schema_drift.py`: add field to CouchDB doc, skip schema update.
  - `reservation_ttl.sh`: reduce Cassandra TTL, hold payment to cause oversell.
  - `delay_fulfillment_logs.py`: hold MinIO uploads.

## 6. Data Seeding & Scenarios
- `/scripts/seed/` modules per service (Faker-based) to populate baseline data.
- Scenario pipeline `scripts/run_scenario.py` supporting CLI args:
  - `--scenario oversell`
  - `--scenario reconciliation`
  - `--scenario schema-drift`
- Use `pytest` fixtures to ensure reproducibility.
- Output metrics to Prometheus pushgateway for dashboards verifying issues.

## 7. Testing Strategy
- Unit tests per service (pytest, coverage target 70%+).
- Contract tests: use `schemathesis` for OpenAPI, `avro` schema compatibility using local registry stub.
- Integration tests: run docker-compose subset per service pair (e.g., order + payment + inventory) using `pytest-docker`.
- End-to-end smoke test: orchestrate checkout flow via `scripts/e2e_checkout.py` hitting APIs and verifying events/logs.

## 8. Documentation & DevEx
- Maintain service-specific README with endpoints, environment variables, run instructions.
- Auto-generate OpenAPI docs -> publish to `docs/api/<service>.yaml` via CI.
- Keep architecture diagrams up-to-date (Mermaid sequence diagrams) under `docs/design/diagrams/`.
- Developer onboarding guide: prerequisites, make commands (`make up`, `make seed`, `make test`).

## 9. Dependencies & Blocking Issues
- MySQL/PostgreSQL/Cassandra initialization scripts required before service start.
- Need Avro Schema Registry only after Phase 1? For microservice base we can stub or include real registry (prefers include to generate issues). For now, configure to highlight missing compatibility (simulate failure to align with use case).
- Ensure network configuration consistent with docker-compose (datanet network).

## 10. Success Criteria
- Ability to reproduce each problem scenario within local environment (observed via metrics/logs).
- All services expose operational endpoints (`/health`, `/metrics`).
- Checkout workflow functional from API perspective (cart -> order -> payment -> inventory -> fulfillment) with events recorded.
- Synthetic data generators produce multi-region load enabling downstream analytics testers later.

## 11. Next Steps After Phase 0
- Proceed to Phase 1 DataOps foundation (Schema Registry, Airflow, Great Expectations) as documented in `docs/design/platform/phase-1-dataops-foundation.md`.
- Expand recommendation/fraud models leveraging MLOps plan only after baseline microservice system validated.
