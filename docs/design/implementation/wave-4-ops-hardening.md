# Wave 4 – Observability, Chaos & Operational Hardening Plan

## 1. Objectives
- Nâng cấp hệ thống microservice đã xây dựng ở Waves 0-3 với đầy đủ observability, chaos engineering, và automation để tái tạo các sự cố mô tả trong usecase.
- Thiết lập baseline monitoring dashboards, alerting, synthetic data generators, và incident playbooks.
- Chuẩn bị nền tảng để chuyển sang Phase 1+ (DataOps/MLOps/AgentOps) với dữ liệu quan sát được rõ ràng.

## 2. Scope & Deliverables
| Area | Deliverables |
| --- | --- |
| Observability | Prometheus metrics integrated across services, Grafana dashboards, Loki log labels, OpenTelemetry tracing setup. |
| Chaos & Scenarios | Scripts to reproduce oversell, schema drift, replica lag, delayed visibility. Integration into CI/nightly run. |
| Synthetic Data | Load generators feeding realistic traffic (orders, carts, payments, shipments). |
| Runbooks | Incident playbooks documenting detection, mitigation, rollback, communication. |
| CI/CD Enhancements | Automated scenario regression tests, artifact publishing (dashboards, docs). |

## 3. Implementation Breakdown
### 3.1 Observability Stack
- **Metrics**:
  - Ensure all services export `/metrics` via Prometheus Instrumentator.
  - Configure Prometheus scrape configs (update compose) for new services.
  - Add custom metrics: checkout saga success/failure counts, reservation TTL expiries, notification failure rate.
- **Dashboards**:
  - `Checkout Flow`: order, payment, inventory metrics, saga percent success.
  - `Fulfillment & Support`: shipment status age, support response time, backlog.
  - `Notifications`: send volume, failure rate, channel latency.
  - `Infra`: DB connection counts, Kafka consumer lag, Debezium lag.
- **Tracing**:
  - Implement OpenTelemetry instrumentation in common library (FastAPI middleware). Export to OTLP receiver (e.g., Jaeger or Grafana Tempo). Include trace IDs in logs/events.
- **Logging**:
  - Standardize structured log format using `structlog` or `loguru`. Add Loki labels `service`, `tenant_region`, `order_id`.
- **Alerting**:
  - Alertmanager rules for SLO breaches (checkout failure > threshold, replica lag > 5m, high notification failure). Provide Slack/email integration stubs.

### 3.2 Chaos & Scenario Automation
- Scripts under `scripts/chaos/`:
  - `simulate_replication_lag.py`: throttle MySQL/Postgres replication.
  - `simulate_schema_drift.py`: add unregistered field to CouchDB/Avro schema.
  - `simulate_ttl_oversell.py`: set Cassandra TTL low, delay payment confirmations.
  - `simulate_fulfillment_delay.py`: hold MinIO uploads.
- Integrate with `pytest` or custom harness to run nightly; capture metrics snapshots.
- Provide `Makefile` target `make chaos SCENARIO=oversell` to run script.

### 3.3 Synthetic Data Generators
- Implement asynchronous generators using `asyncio`/`httpx` to call services.
- Modules:
  - `generate_customer_activity.py`: create sessions, add to cart, checkout.
  - `generate_support_cases.py`: create support tickets triggered by shipments.
  - `generate_notifications.py`: simulate marketing campaigns.
- Use Faker for data; support multi-region distribution.
- Optionally integrate with Locust/K6 for load tests.

### 3.4 CI/CD Integrations
- Extend GitHub Actions pipeline:
  - Run smoke tests (bring up subset via Docker Compose in pipeline).
  - Execute contract tests for kafka events using schema registry mock.
  - Run scenario script (lightweight) to ensure no regression.
- Publish test reports, coverage, and OpenAPI docs as artifacts.
- Add badge to README for build status, coverage.

### 3.5 Runbooks & Documentation
- Create runbooks under `docs/runbooks/` for each scenario (reconciliation lag, oversell, schema drift, fulfillment delay).
- Document detection steps (Grafana panels, Prometheus queries) and remediation actions.
- Provide onboarding doc for SRE/Support teams.

## 4. Timeline
| Week | Activities |
| --- | --- |
| Week 7 (early) | Instrumentation updates, metrics/dashboards |
| Week 7 (mid) | Chaos scripts + nightly jobs |
| Week 7 (late) | Synthetic data generators + scenario automation |
| Week 8 (early) | Runbooks, CI/CD integration |
| Week 8 (late) | Final verification, sign-off to proceed to Phase 1 |

## 5. Risks & Mitigations
- **Observability overload**: ensure dashboards curated, avoid overwhelming metrics; prioritize key KPIs.
- **Chaos unpredictability**: run in controlled environment (non-prod) with reset scripts.
- **Data generator resource usage**: throttle load to avoid overwhelming local environment; default to moderate concurrency.
- **Maintenance burden**: document scripts and line owners; integrate into routine QA cycle.

## 6. Exit Criteria
- Dashboards/alerts validated; SLO breaches visible.
- All scenario scripts reproducible and documented; automation verifies success/failure states.
- CI pipeline includes regression checks; artifacts accessible.
- Runbooks published and referenced in design docs.
- Stakeholders sign off on readiness to proceed with DataOps/MLOps phases.

## 7. Next Steps
- Once Wave 4 complete, start Phase 1 DataOps foundation (Schema Registry, Airflow, GE) as per platform plan.
- Optionally explore packaging microservice stack for deployment (Kubernetes manifests) prior to Phase 1.
