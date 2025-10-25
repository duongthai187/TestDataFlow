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
  - Alertmanager rules for SLO breaches (checkout failure > threshold, replica lag > 5m, high notification failure). Route severity high/critical tới Slack `#data-ops` qua biến môi trường `ALERTMANAGER_SLACK_WEBHOOK_URL`; email integration sẽ bổ sung sau.
  - Support service alert pack: timeline p95 latency, collection failures, attachment backlog growth; align with Grafana playbooks and maintenance automation.

- **Synthetic checks**:
  - Build lightweight probes for support-service timeline (create ticket → measure latency) and attach to CI/cron for early detection.
  - Compose stack cấu hình healthcheck chuẩn (`restart: unless-stopped`, `depends_on.condition: service_healthy`) cho toàn bộ dịch vụ lõi; microservice đều trả về `/health` nhằm đồng bộ với synthetic probe và giảm lỗi khởi động chéo.

### 3.2 Chaos & Scenario Automation
- Scripts under `scripts/chaos/`:
  - `notification_provider_failure.py`: create sample notifications and force `/fail` to validate alert `NotificationFailureRateHigh` and failure dashboards.
  - `notification_redis_outage.py`: stop/start Redis around synthetic sends to trigger `notification_rate_limit_errors_total` and validate rate limiter alerting.
  - `simulate_replication_lag.py`: pause Debezium connectors, insert MySQL rows while CDC halted, resume connectors, and report binlog delta to validate replication lag alerting.
  - `simulate_schema_drift.py`: alter MySQL OLTP tables (add/drop unexpected column) to mimic producer schema drift and trigger Debezium/consumer failures.
  - `simulate_ttl_oversell.py`: adjust Cassandra reservation TTL to provoke rapid expiry/oversell and validate inventory alerts.
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

_Progress_
- ✅ `scripts/synthetic/generate_support_cases.py` tạo ticket support + tin nhắn follow-up; gọi thông qua `make support-generate`.

### 3.4 CI/CD Integrations
- Extend GitHub Actions pipeline:
  - Run smoke tests (bring up subset via Docker Compose in pipeline).
  - Execute contract tests for kafka events using schema registry mock.
  - Run scenario script (lightweight) to ensure no regression.
- Publish test reports, coverage, and OpenAPI docs as artifacts.
- Add badge to README for build status, coverage.

### 3.5 Runbooks & Documentation
- Create runbooks under `docs/runbooks/` for each scenario (reconciliation lag, oversell, schema drift, fulfillment delay).
  - ✅ `docs/runbooks/fulfillment-delay.md` mô tả detection/remediation cho backlog artefact Fulfillment (MinIO hold).
  - ✅ `docs/runbooks/replication-lag.md` mô tả tình huống Debezium/Kafka Connect replication lag.
  - ✅ `docs/runbooks/schema-drift.md` mô tả xử lý schema drift MySQL/Debezium.
  - ✅ `docs/runbooks/ttl-oversell.md` mô tả xử lý Cassandra TTL oversell.
  - ✅ `docs/runbooks/reconciliation-delay.md` mô tả xử lý Finance reconciliation chậm (tạm thời, bổ sung automation sau).
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
