# Recommendation Service Blueprint

## 1. Domain Scope & Objectives
- Cung cấp personalized recommendations (product-to-product, customer-to-product, content) cho toàn bộ kênh (web, mobile, email).
- Xây dựng nền tảng Recommendation/MLOps có thể reuse cho các bài toán AI khác (fraud, pricing optimization, marketing churn) trong tổ chức.
- Đảm bảo vòng đời ML đầy đủ: dữ liệu → feature engineering → training → evaluation → deployment → monitoring → feedback loop.

## 2. Architecture Overview
- **Online path**: FastAPI inference service + feature service + vector search engine → trả về kết quả < 50ms P95.
- **Offline path**: Spark/Flink pipelines tạo features, huấn luyện model (Kubeflow/Airflow), lưu model vào registry (MLflow/Nexus), deploy qua CI/CD.
- **Common platform**: Shared feature store (Feast), model registry, experiment tracking, ML metadata catalog, monitoring stack (Prometheus + Evidently + Grafana).
- Multi-tenant design: namespaces theo domain (recommendation, fraud, pricing), reusable components (feature store, pipelines, monitoring policies).

## 3. Data Stores & Schemas
### 3.1 Feature Store (Feast + Iceberg/Parquet)
- Offline store: Iceberg tables (`features.reco_user_daily`, `features.reco_item_daily`). Schema example:
  ```sql
  CREATE TABLE features.reco_user_daily (
    event_timestamp TIMESTAMPTZ,
    customer_id BIGINT,
    total_orders_30d INT,
    total_spend_30d NUMERIC(12,2),
    last_category VARCHAR(64),
    preferred_brands ARRAY<VARCHAR>,
    churn_score NUMERIC(5,2)
  );
  ```
- Online store: Redis/KeyDB for low latency feature retrieval (`FS:user::{customer_id}`) + TTL sync jobs.

### 3.2 Event & Interaction Storage
- Kafka topics `behavior.page_view`, `behavior.add_to_cart`, `order.completed` (Avro) → Flink pipeline writes to Iceberg and updates vector store.
- ClickHouse: store aggregated interaction metrics for analytics dashboards.

### 3.3 Vector Store
- Milvus/Qdrant for embedding index `rec_product_embeddings` (fields: `sku`, `vector`, `updated_at`, `metadata`).
- Support approximate nearest neighbor (HNSW/IVF).

### 3.4 Model Registry & Metadata
- MLflow Tracking + Model Registry: store experiments, metrics (NDCG@10, CTR uplift), lineage.
- Metadata store (Kubeflow Metadata / OpenLineage) capture pipeline runs.

## 4. APIs (FastAPI + gRPC)
```python
@router.post("/recommendations", response_model=RecommendationResponse)
async def get_recommendations(payload: RecommendationRequest):
    ...  # orchestrate online feature lookup + embedding service + ranking model

@router.post("/recommendations/bulk", response_model=BulkRecommendationResponse)
async def get_bulk_recommendations(payload: BulkRecommendationRequest):
    ...

@router.post("/feedback", response_model=FeedbackAck)
async def submit_feedback(payload: RecommendationFeedback):
    ...  # capture click/convert signal
```
- gRPC endpoint `RecommendationService/GetRecommendations` cho high throughput.
- Real-time AB testing flag via Config service to choose model version.

## 5. Pipelines & Workflow
### 5.1 Data Ingestion
- Flink job `interaction_stream` joins behavior events with catalog/inventory to build session context; writes to Kafka `reco.features.stream` and Iceberg bronze.
- Debezium CDC from order-service/payment-service enrich purchase history features.

### 5.2 Feature Engineering
- Spark Structured Streaming jobs convert bronze → silver features tables, compute windows (1h/1d/30d), handle late data.
- Great Expectations verify feature quality (null checks, distribution drift) before publishing to Feast.

### 5.3 Model Training & Evaluation
- Kubeflow Pipelines or Airflow DAG orchestrates:
  1. Pull training dataset from Feast offline store.
  2. Train candidate models (matrix factorization, two-tower deep learning, gradient boosted ranking).
  3. Log metrics to MLflow; compare to champion model using automated threshold (NDCG, MAP, CTR uplift, diversity score).
  4. Run bias/fairness checks (via Aequitas or custom) across segments.
  5. If passes gates, package model (ONNX/PyTorch) and push to registry.
- Support offline evaluation with replay simulation (Spark) to estimate conversion uplift.

### 5.4 Deployment & Serving
- CI/CD pipeline (GitHub Actions + Argo CD) automates model promotion: registry tag → build inference image → deploy to Kubernetes with canary strategy.
- Blue/green or shadow deployment using Istio/Linkerd; integrates with `notification-service` for A/B messaging.
- Feature store online sync job updates Redis/KeyDB every 5 minutes; fallback precomputed cache for cold start.

### 5.5 Monitoring & Feedback
- Real-time metrics ingestion (Prometheus + StatsD) for CTR, conversion, latency, feature freshness.
- Evidently AI monitors drift, data quality; alerts via Alertmanager.
- Feedback API writes to Kafka `reco.feedback.v1`; assimilation job updates training labels.
- Experiment service (Optimizely/LaunchDarkly) manages treatment assignments; results stored in ClickHouse.

## 6. Event Contracts
- Incoming events:
  - `behavior.*`, `cart.*`, `order.*`, `catalog.product.updated.v1`, `pricing.updated.v1`.
  - `customer.segment.recalculated.v1` to personalize by segment.
- Outgoing events:
  - `reco.recommendations.served.v1` (payload: `request_id`, `customer_id`, `model_version`, `items[]`).
  - `reco.feedback.received.v1` (click/purchase outcome).
  - `mlops.model.promoted.v1` (used across org to track model lifecycle changes).
- Event schema stored in Schema Registry; include metadata for governance (`data_sensitivity`, `retention_policy`).

## 7. Integrations
- **Catalog Service**: maintain consistent product metadata, variant availability.
- **Pricing Service**: incorporate dynamic price signals into ranking features.
- **Inventory Service**: filter out-of-stock SKUs in real time.
- **Notification Service**: embed recommendations in emails/push campaigns.
- **Analytics/BI**: expose Iceberg tables + Trino views for marketing analysis.
- **Organization-wide MLOps**:
  - Shared model registry & feature store for fraud, pricing, churn models.
  - Centralized model governance board (approval workflows, audit logs).
  - Reusable data contracts and pipeline templates (Airflow DAG libs, Kubeflow components).

## 8. Observability & Governance
- Metrics: `recommendation_latency_seconds`, `ctr_current`, `conversion_uplift`, `feature_freshness_seconds`, `model_drift_score`.
- Tracing: propagate `request_id`, `model_version`, `feature_vector_id` via OpenTelemetry.
- Logging: structured logs with `customer_id` hashed; include `experiment_bucket`.
- Dashboards: Grafana boards for online metrics, MLflow UI for experiments, Evidently dashboards for drift.
- Governance: data catalog (DataHub/Amundsen) registers features, models, datasets. Access policies enforced via OPA.

## 9. Testing & Validation
- Unit: feature transformation functions, ranking business rules, fallback logic.
- Integration: end-to-end pipeline in staging (Feast → model server → API); contract tests for events.
- Shadow testing: replay traffic to candidate models without customer exposure.
- Canary tests: monitor key KPIs (CTR, conversions, add-to-cart) before 100% rollout.
- Chaos tests: simulate feature store outage, vector index stale; ensure graceful degradation (fallback to popular items list).

## 10. MLOps Lifecycle (Org-wide Blueprint)
1. **DataOps**: standardized ingestion via CDC/Flink/Spark, schema contracts, automated quality checks (Great Expectations + DataHub lineage).
2. **FeatureOps**: Feast-managed features with governance, automatic documentation, approval workflows.
3. **ModelOps**: MLflow registry with versioning, automated promotion gates, security scanning of model artifacts.
4. **DeploymentOps**: GitOps pipelines, infrastructure as code (Terraform for K8s/cluster resources), blue/green strategies.
5. **MonitoringOps**: unified telemetry (Prometheus, Grafana, Evidently, Sentry), anomaly detection for drift/perf.
6. **FeedbackOps**: close loop via feedback APIs, label extraction jobs, experiment analytics.
7. **Governance & Compliance**: model cards, audit trails, explainability reports (SHAP/LIME) stored in documentation repository.
8. **Collaboration**: centralized notebooks environment (JupyterHub/Databricks), standard templates, knowledge base.

## 11. Backlog
| Task | Description | Priority |
| --- | --- | --- |
| REC-01 | Stand up Feast feature store (Iceberg offline, Redis online) | High |
| REC-02 | Build interaction ingestion pipeline (Flink → Iceberg) | High |
| REC-03 | Implement two-tower model training pipeline in Kubeflow | High |
| REC-04 | Deploy realtime inference service with canary support | High |
| REC-05 | Integrate Evidently drift monitoring + Alertmanager | Medium |
| REC-06 | Build experiment analytics dashboard (ClickHouse + Superset) | Medium |
| REC-07 | Extend platform templates for cross-domain models | Medium |
| REC-08 | Implement privacy guardrails (opt-out, GDPR compliance) | Medium |
| REC-09 | Add reinforcement learning loop for on-site personalization | Low |

## 12. Risks & Mitigations
- **Feature staleness/cold start**: implement fallback heuristics, capture incremental updates via streaming, precompute for new users.
- **Model drift & bias**: continuous monitoring, automated retraining triggers, fairness audits before promotion.
- **Operational complexity**: invest into platform automation, documented runbooks, on-call rotation.
- **Data privacy**: enforce consent checks (customer preferences), anonymize PII in training datasets, apply differential privacy when required.
- **Cross-service dependency**: define SLAs with catalog/inventory/pricing; implement circuit breakers and caching when upstream slow.
