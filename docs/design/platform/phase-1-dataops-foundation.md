# Phase 1 – DataOps Foundation Blueprint

## 1. Goals
- Thiết lập các thành phần nền tảng để kiểm soát schema, chất lượng dữ liệu và điều phối pipeline cho hệ thống ecommerce.
- Giảm thiểu sự cố schema drift, reconcile chậm, thiếu giám sát chất lượng dữ liệu.
- Chuẩn bị hạ tầng cho các giai đoạn MLOps/AgentOps tiếp theo.

## 2. Components Overview
| Component | Role | Image/Version | Dependencies |
| --- | --- | --- | --- |
| Confluent Schema Registry | Quản lý Avro/JSON schema, enforce compatibility | `confluentinc/cp-schema-registry:7.7.x` | Kafka |
| Apache Airflow | Orchestrate batch/stream jobs, data quality checks | `apache/airflow:2.9` | Postgres (metadata), Redis (celery backend optional) |
| Great Expectations Runner | Data quality validation service | Custom Docker (`great_expectations`) | MinIO (artifact store), Airflow |
| Data Contract Repo | Git-based repository (mono repo) | n/a | CI/CD |
| CI Validation | GitHub Actions workflow | n/a | Schema Registry, GE |

## 3. Architecture Diagram
```text
┌───────────────┐        ┌───────────────────────┐
│  Microservices │  CDC   │      Kafka Topics      │
│ (Order, etc.) ├───────►│  (Avro/JSON schemas)   │
└───────────────┘        └────────┬───────────────┘
                                   │
                            ┌──────▼─────────┐
                            │ Schema Registry│◄──────┐
                            └──────┬─────────┘       │
                                   │                 │
                           Validate schemas          │
                                   │                 │
┌────────────┐    DAG trigger    ┌─▼──────────────┐  │
│   Airflow  ├──────────────────►│ Great Expectations│
└────┬───────┘                   └─┬──────────────┘
     │                             │
     │ DAG scheduling              │ Validations
     │                             │
┌────▼────────┐          ┌─────────▼────────┐
│ Spark/Flink │◄────────►│  MinIO / Iceberg │
└─────────────┘          └─────────────────┘
```

## 4. Deployment Plan
### 4.1 Schema Registry Service
```yaml
  schema-registry:
    image: confluentinc/cp-schema-registry:7.7.0
    hostname: schema-registry
    container_name: schema-registry
    depends_on:
      - kafka
    ports:
      - "8081:8081"
    environment:
      SCHEMA_REGISTRY_HOST_NAME: schema-registry
      SCHEMA_REGISTRY_KAFKASTORE_BOOTSTRAP_SERVERS: PLAINTEXT://kafka:9092
      SCHEMA_REGISTRY_LISTENERS: http://0.0.0.0:8081
```
- Topic naming: `<domain>.<event>.v1`.
- Compatibility: set `BACKWARD_TRANSITIVE` by default.
- Access control: future integration với API key/gateway.

### 4.2 Airflow Stack (Compose excerpt)
```yaml
  airflow-postgres:
    image: postgres:15
    environment:
      POSTGRES_USER: airflow
      POSTGRES_PASSWORD: airflow
      POSTGRES_DB: airflow
    volumes:
      - airflow_db:/var/lib/postgresql/data
    networks: [datanet]

  airflow:
    image: apache/airflow:2.9.3
    environment:
      AIRFLOW__CORE__EXECUTOR: LocalExecutor
      AIRFLOW__CORE__FERNET_KEY: "auto-generate"
      AIRFLOW__DATABASE__SQL_ALCHEMY_CONN: postgresql+psycopg2://airflow:airflow@airflow-postgres:5432/airflow
      AIRFLOW__WEBSERVER__BASE_URL: http://airflow:8080
    command: webserver
    ports:
      - "8089:8080"
    volumes:
      - ./airflow/dags:/opt/airflow/dags
      - ./airflow/logs:/opt/airflow/logs
      - ./airflow/config:/opt/airflow/config
    depends_on: [airflow-postgres]
    networks: [datanet]

  airflow-scheduler:
    image: apache/airflow:2.9.3
    command: scheduler
    environment:
      (same as webserver)
    volumes:
      - ./airflow/dags:/opt/airflow/dags
      - ./airflow/logs:/opt/airflow/logs
      - ./airflow/config:/opt/airflow/config
    depends_on: [airflow, airflow-postgres]
    networks: [datanet]
```
- Optional: add Redis + Celery Worker for higher throughput.
- Integrations: DAGs call Spark, Flink via REST/CLI containers; run GE validations via DockerOperator.

### 4.3 Great Expectations Runner
- Container with Python + Great Expectations CLI, mount `./data-quality/expectations`.
- Provide API (FastAPI) or CLI triggered by Airflow via DockerOperator.
- Store validation results in MinIO bucket `ge-results/`, register metadata to DataHub.

### 4.4 GitOps & CI
- Repo structure:
```
airflow/dags/
  cdc_healthcheck.py
  reconcile_job.py
  ge_validation.py
schema-contracts/
  order_created_v1.avsc
.github/workflows/
  dataops.yml
```
- CI steps: lint DAGs → run GE tests against sample data → validate Avro schema via Schema Registry API → block merge if fail.

## 5. Use Case Mapping
| Pain | DataOps Intervention |
| --- | --- |
| Schema drift gây Flink fail | Schema Registry + CI ensures backward compatibility; Airflow DAG polls connectors and notifies when compatibility broken. |
| Reconcile chậm | Airflow orchestrates nightly Spark job, monitors success; GE validates ledger output; alerts via Prometheus/Alertmanager. |
| Oversell TTL | Airflow DAG checks Cassandra reservation TTL distribution; GE ensures inventory snapshot consistency. |
| Fulfillment visibility | Airflow triggers incremental ingest from MinIO to Iceberg; schema validated before downstream use. |

## 6. Backlog & Deliverables
| ID | Task | Owner | Priority |
| --- | --- | --- | --- |
| DATA-01 | Add Schema Registry service to docker-compose | Platform | High |
| DATA-02 | Initialize schema contract repo + baseline Avro schemas | Data Eng | High |
| DATA-03 | Deploy Airflow (webserver + scheduler + metastore) | Platform | High |
| DATA-04 | Author DAG `cdc_healthcheck` monitoring Debezium connectors | Data Eng | High |
| DATA-05 | Containerize Great Expectations runner + expectation suites | Data Quality | High |
| DATA-06 | Configure CI workflow enforcing schema + GE checks | DevOps | High |
| DATA-07 | Integrate Airflow DAG with Prometheus alerting (success/failure) | Platform | Medium |
| DATA-08 | Document onboarding playbook for data contracts | Data Gov | Medium |

## 7. Risks & Mitigations
- **Resource overhead**: ensure Docker host capacity; scale down Airflow workers initially.
- **Complexity**: provide templates/examples for DAGs and GE suites; training sessions.
- **Governance adoption**: socialize data contract process; integrate with sprint rituals.

## 8. Next Steps
1. Merge compose updates + directories (`airflow/`, `schema-contracts/`, `data-quality/`).
2. Create sample DAG & GE suite for orders/payout pipeline.
3. Hook Airflow into existing monitoring (Prometheus exporter for Airflow). 
4. Plan Phase 2 (Feast + MLflow) after DataOps baseline stable.
