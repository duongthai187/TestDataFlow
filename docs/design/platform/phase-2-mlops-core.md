# Phase 2 – MLOps Core Blueprint

## 1. Goals
- Thiết lập hạ tầng chuẩn cho quản lý vòng đời model (training, registry, serving) và chia sẻ feature giữa các use case (recommendation, fraud, pricing).
- Tích hợp ML pipeline với DataOps (Phase 1) để đảm bảo dữ liệu đầu vào đáng tin cậy.
- Chuẩn hóa quy trình model promotion, canary deployment, monitoring.

## 2. Component Overview
| Component | Role | Image/Version | Dependencies |
| --- | --- | --- | --- |
| MLflow Tracking Server | Experiment tracking, model registry | `ghcr.io/mlflow/mlflow:2.14.1` | PostgreSQL (backend), MinIO (artifact) |
| Feast | Feature store (offline/online) | `feastdev/feast-core:0.44`, `feastdev/feast-serving:0.44` | Redis, Iceberg/Nessie, Kafka |
| Ray Cluster | Distributed training & serving | `rayproject/ray:2.10.0` | MinIO (datasets), GPU optional |
| Model Build Service | CI pipeline (GitHub Actions) | n/a | MLflow, Feast |
| Promotion Controller | Automate registry → deploy | Airflow DAG / GitOps | Ray Serve, FastAPI microservices |
| Monitoring Stack | Model metrics, drift | Prometheus, Evidently, Grafana | MLflow, Ray logs |

## 3. Architecture Snapshot
```text
              ┌───────────────┐
              │  Feature Store │◄─────────────┐
              │   (Feast)     │              │
              └─────┬─────────┘              │ offline sync
                    │                        │
            ┌───────▼───────┐        ┌───────▼─────────┐
            │ MLflow Tracking│◄──────►│  Ray Training   │
            │ + Registry     │ log    │ (Ray Jobs)      │
            └───┬───────────┘        └─────┬───────────┘
                │ model versions            │ deployed models
                │                           │
        ┌───────▼────────┐          ┌───────▼─────────┐
        │ GitHub Actions │─────────►│ Ray Serve / API │
        │  (Model Build) │          │ (FastAPI apps)  │
        └───────┬────────┘          └────────┬────────┘
                │ deploy manifests           │
                ▼                            ▼
          GitOps Repo                   Monitoring Stack
```

## 4. Deployment Plan
### 4.1 MLflow Tracking Server
```yaml
  mlflow-postgres:
    image: postgres:15
    environment:
      POSTGRES_USER: mlflow
      POSTGRES_PASSWORD: mlflow
      POSTGRES_DB: mlflow
    volumes:
      - mlflow_db:/var/lib/postgresql/data
    networks: [datanet]

  mlflow:
    image: ghcr.io/mlflow/mlflow:2.14.1
    command: mlflow server --backend-store-uri postgresql+psycopg2://mlflow:mlflow@mlflow-postgres:5432/mlflow --default-artifact-root s3://mlflow-artifacts --host 0.0.0.0 --port 5000
    environment:
      MLFLOW_S3_ENDPOINT_URL: http://minio:9000
      AWS_ACCESS_KEY_ID: admin
      AWS_SECRET_ACCESS_KEY: admin12345
    ports:
      - "5000:5000"
    depends_on: [mlflow-postgres, minio]
    networks: [datanet]
```
- Create MinIO bucket `mlflow-artifacts`.
- Configure authentication (future: OIDC proxy).

### 4.2 Feast Feature Store
- Offline store via Iceberg catalog (Trino connector) or direct Parquet on MinIO.
- Compose services:
```yaml
  feast-redis:
    image: redis:7
    ports:
      - "6379:6379"
    networks: [datanet]

  feast-core:
    image: feastdev/feast-core:0.44
    environment:
      FEAST_SERVER_PORT: 6565
      FEAST_TELEMETRY: "false"
    ports:
      - "6565:6565"
    networks: [datanet]

  feast-online:
    image: feastdev/feast-serving:0.44
    environment:
      FEAST_SERVING_PORT: 7070
      FEAST_REDIS_CONNECTION_STRING: feast-redis:6379
    ports:
      - "7070:7070"
    depends_on: [feast-redis]
    networks: [datanet]
```
- Feast configuration stored under `feast/feature_repo/`; use Feast CLI container for apply (`feast apply`).
- Offline store config example:
```yaml
project: ecommerce
registry: s3://feast-registry/registry.db
provider: trino
offline_store:
  type: trino
  catalog: nessie
  schema: features
online_store:
  type: redis
  connection_string: feast-redis:6379
```

### 4.3 Ray Cluster
```yaml
  ray-head:
    image: rayproject/ray:2.10.0
    command: ray start --head --dashboard-host 0.0.0.0 --dashboard-port=8265 --port=6379
    ports:
      - "8265:8265"  # dashboard
      - "10001:10001"  # client
    volumes:
      - ./ray/scripts:/opt/ray/scripts
    networks: [datanet]

  ray-worker:
    image: rayproject/ray:2.10.0
    command: ray start --address ray-head:6379
    depends_on: [ray-head]
    networks: [datanet]
```
- Provide container env for ML dependencies (PyTorch, XGBoost, LightGBM). Build custom image if necessary.
- Access MinIO dataset via `AWS_*` env (same credentials as MLflow).
- Ray Serve apps packaged with FastAPI microservices (e.g., recommendation-service) or run as separate deployment.

### 4.4 CI/CD Workflow
- GitHub Actions pipeline `mlops.yml`:
  1. Checkout repo, install dependencies.
  2. Run unit tests for feature transforms (`pytest`).
  3. Launch training script via Ray (local cluster or container) using sample dataset.
  4. Log results to MLflow (DEV stage).
  5. If metrics pass thresholds, push model to MLflow with stage `Staging`.
  6. Generate deployment manifest (Ray Serve config or FastAPI artifact) and create PR in GitOps repo.

### 4.5 Promotion Flow
- Airflow DAG `model_promotion.py` runs daily:
  - Query MLflow for models in `Staging` with metrics above target & drift below threshold.
  - Trigger canary deployment: update Ray Serve config (50/50 traffic split).
  - Monitor metrics via Prometheus; if success after window -> set stage to `Production`, else rollback.
- Record change in DataHub: MLflow plugin emits lineage update linking dataset → feature → model → consumer service.

### 4.6 Monitoring Enhancements
- Export Ray metrics (`ray.metrics_export_port`), configure Prometheus scrape.
- MLflow metrics to Prometheus via custom exporter or Airflow job writing to Pushgateway.
- Evidently drift jobs reading inference logs from Kafka `reco.recommendations.served.v1`, writing results to Prometheus.

## 5. Use Case Coverage
| Scenario | MLOps Intervention |
| --- | --- |
| Recommendation refinement | Shared features from Feast + Ray training ensures fresh models; canary deployment via Ray Serve reduces risk. |
| Fraud detection | Same infrastructure logs experiments, shares features (transaction history), enables rapid retraining when drift flagged. |
| Dynamic pricing | Feast hosts pricing signals; Ray orchestrates gradient boosted models; MLflow tracks experiments for auditing. |
| Operational analytics | MLflow & DataHub provide traceable lineage for compliance; models can be rolled back quickly via registry. |

## 6. Integration with Phase 1
- Airflow orchestrates Feast materializations and MLflow promotion DAGs.
- Great Expectations runs before Feast ingestion to ensure feature quality.
- Schema Registry ensures event schemas feeding Feast stay compatible.
- DataHub ingests MLflow metadata using `datahub-ingestion` job (Airflow schedule).

## 7. Backlog & Ownership
| ID | Task | Owner | Priority |
| --- | --- | --- | --- |
| MLOPS-01 | Add MLflow services + configure MinIO bucket | Platform | High |
| MLOPS-02 | Stand up Feast (core + online) and bootstrap feature repo | Data Eng | High |
| MLOPS-03 | Deploy Ray head/worker + custom image for ML deps | ML Eng | High |
| MLOPS-04 | Build CI workflow logging experiments to MLflow | DevOps | High |
| MLOPS-05 | Create Airflow DAG for Feast materialization (daily/hourly) | Data Eng | High |
| MLOPS-06 | Implement model promotion DAG + canary logic | ML Ops | Medium |
| MLOPS-07 | Configure Prometheus scraping for Ray, MLflow metrics | Observability | Medium |
| MLOPS-08 | Integrate DataHub ingestion for MLflow metadata | Data Gov | Medium |

## 8. Risks & Mitigations
- **Resource usage**: Ray workloads may require GPU or large memory; plan autoscaling and resource quotas.
- **Operational complexity**: provide templates for feature definitions, training scripts, Ray Serve config. Establish code owners.
- **Model governance**: enforce approval gates in MLflow (manual sign-off) before Production stage. Log human approvals via Airflow tasks.

## 9. Next Steps
1. Update docker-compose with MLflow, Feast, Ray services and supporting volumes.
2. Scaffold `feast/feature_repo/` with initial entities/features (customer profile, product interactions).
3. Write reference training pipeline (recommendation two-tower) integrating Ray + MLflow + Feast.
4. Define monitoring dashboards (Grafana) for model performance and Ray cluster health.
5. Align security plan: secrets management (Vault or Docker secrets), role-based access to MLflow/Feast.
