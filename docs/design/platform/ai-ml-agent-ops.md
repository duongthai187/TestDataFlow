# AI/ML/Data/Agent Ops Master Plan

## 1. Context & Objectives
- Hệ thống ecommerce hiện tại đang chịu các vấn đề trong usecase `docs/usecases/tinh-huong-ecommerce-phuc-tap.md`: phân mảnh dữ liệu, reconcile chậm, oversell, schema drift, thiếu realtime visibility, rủi ro fraud.
- Mục tiêu của AI/ML/Data/Agent Ops: xây dựng nền tảng end-to-end giúp giải quyết các vấn đề trên, đồng thời tạo năng lực tăng doanh thu/lợi nhuận qua personalization, dynamic pricing, churn prevention, operational automation.
- Phạm vi gồm DataOps, MLOps (bao gồm recommendation/fraud/pricing), LLMOps/AgentOps (support, observability automation) và governance.

## 2. Hiện Trạng Stack (docker-compose.yml)
| Layer | Thành phần hiện tại | Nhận xét |
| --- | --- | --- |
| Messaging | Apache Kafka (KRaft), Debezium Connect | Foundation tốt cho CDC/event mesh nhưng thiếu Schema Registry, thiếu quản lý connectors. |
| Storage | MySQL, PostgreSQL, Cassandra, CouchDB, MinIO, Nessie, Iceberg, Doris | Đáp ứng đa mô hình nhưng chưa có metadata catalog, quality guardrails. |
| Compute | Spark (batch), Flink (stream), Trino (ad-hoc) | Đủ cho pipeline core nhưng thiếu workflow orchestrator và feature store. |
| Monitoring | Prometheus, Grafana, Loki, Alertmanager, exporters | Nhà xưởng observability tốt, cần mở rộng cho ML/LLM metrics + data quality. |
| Dev/ML Tooling | (Missing) | Chưa có MLflow, Feast, Kubeflow/Airflow, DataHub, feature store, model registry. |

## 3. Target Platform Architecture
### 3.1 DataOps Plane
- **Schema & Metadata**: triển khai **Confluent Schema Registry** (hoặc Apicurio) + **DataHub** (metadata catalog) để theo dõi lineage giữa Kafka, Iceberg, OLTP.
- **Quality**: deploy **Great Expectations** service + Data Quality runner (Docker) tích hợp Spark/Flink. Lưu kết quả vào DataHub và Prometheus.
- **Workflow Orchestration**: sử dụng **Apache Airflow** (hoặc Dagster) để điều phối batch pipelines, Debezium config drift detection, data seeding.
- **Data Contracts & Testing**: GitOps repo cho contracts; CI sử dụng **dbt tests** + **Soda Core** cho light checks.

### 3.2 Feature & Model Ops
- **Feature Store**: **Feast** (offline store Iceberg via Nessie, online store Redis/KeyDB). Containers: `feast-core`, `feast-online`.
- **Model Registry & Experiment Tracking**: **MLflow Tracking Server** + `mlflow` UI, backed by PostgreSQL + MinIO artifact store.
- **Training Orchestration**: **Kubeflow Pipelines** (kf-serving) hoặc **Ray Train/Serve**. Với docker-compose PoC: dùng **KServe** difficult → adopt **Ray cluster** (Ray head/worker) cho training/inference, future port to K8s.
- **Model Serving**: 
  - Real-time microservices (FastAPI) embed **Ray Serve** or **Seldon Core** in future.
  - Batch inference via Spark integrated with MLflow model.
- **CI/CD**: tăng cường GitHub Actions pipelines: unit tests, data contract tests, model evaluation step, canary deploy via feature flag.

### 3.3 LLMOps & AgentOps
- **Vector DB**: add **Milvus/Qdrant** for embeddings (align recommendation blueprint).
- **LLM Serving**: 
  - Self-hosted open source (Llama.cpp / vLLM) container for internal inference.
  - Integrate with managed API fallback (OpenAI/Azure) via gateway.
- **Agent Orchestration**: adopt **LangChain** (or **LlamaIndex**) service layer for building support agent, observability copilot, anomaly triage bots.
- **RAG Pipeline**: ingest docs (usecases, runbooks, dashboards) to vector store. Build ingestion job via Airflow.
- **Evaluation & Monitoring**: use **Trulens** or **LangSmith** for agent eval, log to Prometheus + Loki.

### 3.4 Governance & Security
- Implement **OPA/Gatekeeper** for policy-as-code (data access, model promotion).
- **Secrets Management**: incorporate **HashiCorp Vault** (optional) or at minimum Docker secrets.
- **Compliance**: maintain model cards stored in Git + DataHub; track data residency per dataset.

## 4. Proposed Additions (Services/Frameworks)
| Component | Purpose | Deployment Notes |
| --- | --- | --- |
| Schema Registry | Avro/JSON schema governance | Use `confluentinc/cp-schema-registry`, connect to Kafka. |
| Airflow | Pipeline orchestration | `apache/airflow` docker compose, integrate with Spark/Flink via Rest API. |
| Great Expectations | Data quality service | Run as container + S3(MinIO) store for expectation suites. |
| DataHub | Metadata catalog & lineage | Deploy `datahub-gms`, `datahub-frontend`, `datahub-actions`. |
| Feast | Feature store | Connect to Iceberg offline via Trino/Parquet; online store Redis (existing). |
| MLflow | Experiment tracking & registry | Backend store PostgreSQL, artifact store MinIO bucket. |
| Ray Cluster | Distributed training/inference | Compose services `ray-head`, `ray-worker`. |
| Milvus/Qdrant | Vector search for recsys/RAG | Connect to recommendation service, support agent. |
| vLLM | LLM inference | Provide `vllm` container; route through API gateway. |
| LangChain Server | Agent runtime | Deploy FastAPI-based orchestrator using LangChain or LlamaIndex + Celery. |
| Evidently AI | Drift monitoring | Container to compute metrics, push to Prometheus/Grafana. |
| OpenTelemetry Collector | Unified telemetry pipeline | Export traces/metrics/logs to Prom/Grafana/Loki; integrate ML services. |

## 5. Use Case Alignment
| Use Case Pain | AI/ML/Data/Agent Ops giải pháp |
| --- | --- |
| Cross-region reconciliation chậm | Airflow + Spark job orchestrated via MLflow ensures scheduled reconciliation; DataHub lineage + Great Expectations catches delays; Evidently monitors drift in finance metrics. |
| Oversell TTL | Feature store + Flink streaming pipeline publish real-time availability features; Airflow ensures TTL audits; Agent monitors inventory anomalies. |
| Schema drift | Schema Registry with compatibility rules; DataHub data contracts; Airflow job auto-validate connectors; alerts via Alertmanager. |
| Fulfillment visibility | Real-time feature pipeline + Ray Serve for ETA prediction; Notification agent pushes updates; Observability agent queries Grafana via API. |
| Fraud risk | MLflow/Kubeflow pipeline for fraud models, Ray Serve for inference; agent monitors chargeback patterns. |
| Revenue uplift | Feast + recommendation platform (already designed) integrated with ML Ops; pricing optimization models share infrastructure; marketing AI agent uses LangChain & Qdrant to tailor campaigns. |

## 6. Roadmap & Break Tasks
### Phase 1 – Foundations (Weeks 1-4)
1. Stand up Schema Registry + Airflow + Great Expectations.
2. Deploy DataHub (ingest metadata from MySQL, PostgreSQL, Kafka, Iceberg).
3. Integrate CI pipeline to run data quality + contract tests pre-deploy.
  - Chi tiết triển khai: `docs/design/platform/phase-1-dataops-foundation.md`.

### Phase 2 – MLOps Core (Weeks 5-8)
1. Deploy MLflow Tracking + Feast (offline Iceberg, online Redis).
2. Provision Ray cluster; migrate recommendation training pipeline to MLflow-managed flow.
3. Implement model promotion workflow (MLflow → GitOps → deploy to Ray Serve/ FastAPI).
  - Chi tiết triển khai: `docs/design/platform/phase-2-mlops-core.md`.

### Phase 3 – Agent & LLMOps (Weeks 9-12)
1. Deploy Qdrant + LangChain Orchestrator + vLLM (PoC with support knowledge base).
2. Build RAG ingestion Airflow DAG (docs, dashboards, runbooks).
3. Implement agent monitoring (Trulens/Evidently) + integrate with Alertmanager.
  - Chi tiết triển khai: `docs/design/platform/phase-3-llm-agent-ops.md`.

### Phase 4 – Enterprise Hardening (Weeks 13+)
1. Introduce OPA policy checks, Vault secrets, audit trails in DataHub.
2. Extend platform to pricing/fraud ML use cases; add experiment analytics dashboards (ClickHouse).
3. Build self-service portal (Backstage or DataHub UI) for data/ML productization.
  - Chi tiết triển khai: `docs/design/platform/phase-4-enterprise-hardening.md`.

## 7. Operations & Observability Enhancements
- Extend Prometheus with ML/LLM exporters; integrate MLflow metrics → Prometheus via pushgateway.
- Create Grafana boards: model performance, feature freshness, agent success, latency.
- Loki pipelines tag `service=mlflow`, `service=feast`, `service=agent` for debugging.
- Implement SLOs: inference latency P95, model drift thresholds, data pipeline SLA (Airflow DAG success rates).

## 8. Governance Checklist
- Every dataset/model registered in DataHub with owner, SLA, retention, sensitivity.
- Model cards stored in Git + DataHub; include fairness, explainability (SHAP) artifacts.
- Approvals required (Git PR + OPA rule) before pushing model to production stages.
- Audit logs emitted to Loki; periodic compliance review via Airflow job.

## 9. Next Actions
1. Cập nhật docker-compose để thêm Schema Registry, Airflow, MLflow, Feast, Qdrant, Ray cluster (PoC scope).
2. Viết tài liệu vận hành cho từng dịch vụ mới (ports, credentials, persistent volumes).
3. Chuẩn bị scripts seed metadata vào DataHub, expectation suites cho Great Expectations.
4. Thiết lập CI pipeline (GitHub Actions) chạy data & model checks trước khi merge vào `main`.
