# Data Pipelines Blueprint

## 1. Overview
- Kết hợp streaming & batch để đồng bộ dữ liệu phân mảnh từ các OLTP stores sang Lakehouse (Iceberg) và downstream services.
- Thành phần chính: Debezium, Kafka, Flink, Spark, Trino, Great Expectations, Nessie.

## 2. CDC Layer
### 2.1 Debezium Connectors
- **MySQL Connector** (`order-mysql-connector.json`):
  ```json
  {
    "name": "orders-mysql-connector",
    "config": {
      "connector.class": "io.debezium.connector.mysql.MySqlConnector",
      "database.hostname": "mysql",
      "database.port": "3306",
      "database.user": "debezium",
      "database.password": "debezium",
      "database.server.id": "184054",
      "database.server.name": "mysql-oltp",
      "database.include.list": "ecommerce",
      "table.include.list": "ecommerce.orders,ecommerce.order_items",
      "database.history.kafka.bootstrap.servers": "kafka:9092",
      "database.history.kafka.topic": "schema-changes.mysql",
      "include.schema.changes": "false",
      "snapshot.mode": "when_needed",
      "tombstones.on.delete": "false",
      "heartbeat.interval.ms": "5000",
      "include.query": "false"
    }
  }
  ```
- **PostgreSQL Connector** (`payment-postgres-connector.json`): WAL logical decoding, slot per region.
- **Cassandra Connector**: DataStax CDC for Apache Cassandra (runs agent, push events to Kafka topic `cassandra.inventory.events`).
- **CouchDB CDC**: custom worker reads `_changes` feed, publishes to Kafka (since official connector limited).

### 2.2 Outbox Pattern
- Services (order, inventory) write to outbox table/collection; Debezium captures and publishes to domain topics ensuring transactional consistency.
- Outbox schema example (MySQL):
  ```sql
  CREATE TABLE outbox_events (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    aggregate_type VARCHAR(64) NOT NULL,
    aggregate_id VARCHAR(64) NOT NULL,
    type VARCHAR(128) NOT NULL,
    payload JSON NOT NULL,
    created_at DATETIME NOT NULL,
    published BOOLEAN NOT NULL DEFAULT FALSE
  );
  ```

## 3. Streaming Pipelines (Flink)
### 3.1 Fraud Enricher Job
- Source: Kafka (`order.created`, `payment.authorized`, `behavior.addToCart`).
- Pattern: keyed by `customer_id`, tumbling window 2 phút.
- Steps:
  1. Enrich order with payment + behavior metrics.
  2. Apply rules/ML model (PMML or custom) for risk scoring.
  3. Emit `fraud.alert` to Kafka & push to Redis feature store.
- Implementation: Flink Table API (SQL) or DataStream; leverage state TTL; side output for anomalies.

### 3.2 Inventory Global Aggregation
- Sources: `inventory.events`, `order.status.changed`.
- Compute per SKU global availability, update Cassandra global table (`inventory_global`), publish to `inventory.global.update`.
- Use Async I/O sink to Cassandra; ensure idempotent writes via upsert query.

### 3.3 Schema Drift Monitoring
- Flink job consuming Debezium schema change topics → compare with contract repo; raise alerts when unexpected fields appear.

## 4. Batch & Lakehouse (Spark)
### 4.1 Structured Streaming Ingestion
- Job `bronze_ingest.py`: read from Kafka topics (raw Debezium events), parse payload, write to Iceberg Bronze tables partitioned by date + region.
- Use checkpoint in HDFS/MinIO; ensure exactly-once semantics via Iceberg integration.

### 4.2 Silver Transformations
- Nightly job join orders + payments + shipment logs → create `iceberg.silver.finance_ledger`.
- Another job dedupe reservations & compute daily inventory snapshot.

### 4.3 Gold Layer / BI
- Create aggregated tables for marketing segmentation, support dashboards.
- Publish to Doris or accessible via Trino views.

## 5. Data Quality & Governance
- Great Expectations suite runs on Bronze & Silver tables.
  - Expectations: non-null keys, numeric ranges, referential consistency (order-payment).
  - Failures push alerts to Slack via Airflow/Prefect.
- Schema Registry compatibility checks enforced via CI pipeline.
- Nessie branching strategy: dev → staging → prod branches for Iceberg metadata; controlled promotions.

## 6. Orchestration & Scheduling
- Use Prefect/Apache Airflow for batch job orchestration.
- DAG Example: `daily_finance_recon` (trigger 02:00 local), tasks: snapshot → reconcile → GE validation → publish.
- Streaming jobs managed via Kubernetes operators (Flink K8s Operator, Spark Operator) with Helm charts.

## 7. Observability for Pipelines
- Metrics (Prometheus):
  - Flink: `flink_taskmanager_job_latency`, `flink_job_restarts_total`.
  - Spark: `spark_streaming_input_rate`, `spark_streaming_batch_duration`.
  - Debezium: `debezium_connector_total_events_seen`, `max_lag_in_seconds`.
- Logs: routed to Loki with labels `app`, `job`, `pipeline`.
- Alerts: pipeline lag > 5 min, GE validation failure, job restart loops.

## 8. Implementation Tasks
| ID | Description | Owner | Duration |
| --- | --- | --- | --- |
| PIPE-01 | Provision Kafka topics & ACLs | Platform | 2d |
| PIPE-02 | Deploy Debezium connectors (MySQL, Postgres) | Data Eng | 3d |
| PIPE-03 | Implement Cassandra CDC pipeline | Data Eng | 4d |
| PIPE-04 | Build Flink Fraud Enricher | Data Eng | 5d |
| PIPE-05 | Build Inventory Aggregator | Data Eng | 5d |
| PIPE-06 | Create Spark Bronze ingestion job | Data Eng | 4d |
| PIPE-07 | Implement Silver finance reconciliation job | Data Eng | 3d |
| PIPE-08 | Integrate Great Expectations suite | Data Gov | 3d |
| PIPE-09 | Setup pipeline observability dashboards | SRE | 2d |

## 9. Risks & Mitigations
- **Connector lag**: implement auto-scaling, alert thresholds.
- **Schema evolution**: rely on Avro compatibility + automated contract tests before deploy.
- **Job failure**: design restart policies, checkpointing.
- **Cost**: evaluate resource requirements, use autoscaling where possible.
