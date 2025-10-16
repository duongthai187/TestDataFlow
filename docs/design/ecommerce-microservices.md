# Ecommerce Microservices Architecture & Data Strategy

## 1. Context & Objectives
- Triển khai hệ thống ecommerce đa vùng (Bắc Mỹ, Châu Âu, Đông Nam Á) theo kiến trúc microservice sử dụng backend FastAPI.
- Hệ thống hiện tại phân mảnh dữ liệu mạnh giữa nhiều OLTP SQL và NoSQL như mô tả trong usecase `docs/usecases/tinh-huong-ecommerce-phuc-tap.md`.
- Mục tiêu: mô hình hóa toàn bộ kiến trúc, chỉ rõ các điểm nghẽn, sau đó chuẩn hóa luồng dữ liệu (stream + batch) để hỗ trợ phân tích, vận hành realtime, và tuân thủ governance.

## 2. Microservice Landscape (FastAPI)
| Service | Domain Core | Data Store | Synchronous APIs | Async Events (Kafka) | Ghi chú |
| --- | --- | --- | --- | --- | --- |
| `customer-service` | Hồ sơ khách hàng, loyalty, segmentation flags | PostgreSQL (`customer_profiles`, `customer_segments`) + Redis cache | GET/PUT `/customers`, `/segments` | `customer.updated`, `customer.segment.recalculated` | Đồng bộ với marketing pipeline. |
| `catalog-service` | Catalog sản phẩm, thuộc tính đa ngôn ngữ, media | CouchDB (`products`, `product_translations`), PostgreSQL (`product_taxonomy`), MinIO media | CRUD `/products`, GraphQL `/catalog` | `catalog.product.created`, `catalog.product.updated` | Đồng bộ search, recommendation, storefront. |
| `review-service` | Review người dùng | CouchDB (`reviews`) | POST `/reviews`, GET `/reviews/{sku}` | `review.created` | Chia sẻ cùng CouchDB cluster đa vùng. |
| `pricing-service` | Giá động, khuyến mãi | PostgreSQL (`price_rules`) | GET `/pricing/{sku}`, POST `/campaigns` | `price.rule.updated` | Dữ liệu input từ marketing analytics. |
| `cart-service` | Giỏ hàng realtime | MySQL (`cart_sessions`, `cart_items`) | CRUD `/carts`, `/carts/{id}/items` | `cart.item.added`, `cart.checkedout` | TTL sessions, replicate per region. |
| `order-service` | Đơn hàng, line item, trạng thái fulfillment | MySQL (`orders`, `order_items`, `order_status_history`) | POST `/orders`, GET `/orders/{id}` | `order.created`, `order.status.changed` | Đẩy event cho payment và inventory. |
| `payment-service` | Thanh toán, ledger PSP, hoàn tiền | PostgreSQL (`payments`, `payment_attempts`, `psp_settlement`, `refunds`) | POST `/payments`, GET `/payments/{order_id}` | `payment.authorized`, `payment.failed` | Partition theo ngày để reconcile nhanh. |
| `inventory-service` | Stock, reservation, hold TTL | Cassandra (`stock_level`, `reservation`, `inventory_events`) | POST `/inventory/reserve`, `/inventory/release` | `inventory.reserved`, `inventory.adjusted` | Co-locate với order để giữ latency. |
| `fulfillment-service` | Tracking, shipment, logistics SLA | MySQL (`shipments`, `fulfillment_tasks`), Redis cache, MinIO labels | GET `/fulfillment/shipments`, `/fulfillment/track/{tracking}` | `fulfillment.shipment.created`, `fulfillment.shipment.updated` | Điều phối 3PL, returns, cập nhật tracking realtime. |
| `fraud-service` | Đánh giá rủi ro realtime | PostgreSQL (`fraud_decisions`), Cassandra fingerprints, Redis blacklist | POST `/fraud/evaluate` | `fraud.decision.made`, `fraud.case.escalated` | Tiêu thụ events order + payment, cung cấp scoring. |
| `support-service` | Ticket, lịch sử tương tác 360° | PostgreSQL (`support_tickets`, `support_conversations`), MinIO attachments | GET `/support/cases`, POST `/support/cases` | `support.case.opened`, `support.case.closed` | Kết hợp dữ liệu từ toàn stack cho agent UI. |
| `notification-service` | Thông báo đa kênh, preference | PostgreSQL (`notification_templates`, `notification_preferences`), Redis rate limit, ClickHouse events | POST `/notifications/send`, `/notifications/preferences/{customer}` | `notification.sent`, `notification.failed`, `notification.preference.updated` | Đảm bảo compliance opt-in, multi-provider fallback. |
| `recommendation-service` | Personalized recommendations, ML platform | Feast/Iceberg feature store, Redis online store, Milvus vector DB | POST `/recommendations`, `/feedback` | `reco.recommendations.served`, `reco.feedback.received`, `mlops.model.promoted` | Nền tảng MLOps reuse cho toàn tổ chức, hỗ trợ realtime inference. |

### 2.1 Service Interaction Highlights
- Checkout flow: `cart-service` → emits `cart.checkedout` → `order-service` persist order → `order.created` triggers `payment-service` and `inventory-service`.
- Inventory reservation: `order-service` requests `/inventory/reserve`; Cassandra giữ record hold TTL và emit `inventory.reserved` để cập nhật dashboard.
- Payment reconciliation: `payment-service` ghi ledger và đẩy `payment.authorized`; `fraud-service` join với hành vi gần nhất từ Kafka clickstream.
- Customer 360: `support-service` aggregate qua Trino view, fallback sang API synchronous khi miss cache.

## 3. OLTP Schemas (Fragmented)

### 3.1 MySQL (Order & Cart domain)
```sql
CREATE TABLE orders (
  order_id        BIGINT PRIMARY KEY AUTO_INCREMENT,
  tenant_region   VARCHAR(8) NOT NULL,
  customer_id     BIGINT NOT NULL,
  currency_code   CHAR(3) NOT NULL,
  grand_total     DECIMAL(12,2) NOT NULL,
  status          ENUM('PENDING','CONFIRMED','FULFILLED','CANCELLED','RETURNED') NOT NULL,
  created_at      DATETIME NOT NULL,
  updated_at      DATETIME NOT NULL,
  requested_ship_date DATETIME,
  INDEX idx_orders_customer_created (customer_id, created_at),
  INDEX idx_orders_region_status (tenant_region, status)
) ENGINE=InnoDB;

CREATE TABLE order_items (
  order_item_id  BIGINT PRIMARY KEY AUTO_INCREMENT,
  order_id       BIGINT NOT NULL,
  sku            VARCHAR(64) NOT NULL,
  quantity       INT NOT NULL,
  unit_price     DECIMAL(12,2) NOT NULL,
  discount_amount DECIMAL(12,2) DEFAULT 0,
  fulfillment_status ENUM('PENDING','ALLOCATED','SHIPPED','BACKORDER','CANCELLED') NOT NULL,
  updated_at     DATETIME NOT NULL,
  UNIQUE KEY uk_order_item (order_id, sku),
  CONSTRAINT fk_order_items_order FOREIGN KEY (order_id) REFERENCES orders(order_id)
);

CREATE TABLE cart_sessions (
  cart_id        BIGINT PRIMARY KEY AUTO_INCREMENT,
  customer_id    BIGINT,
  session_token  CHAR(36) NOT NULL,
  created_at     DATETIME NOT NULL,
  expires_at     DATETIME NOT NULL,
  tenant_region  VARCHAR(8) NOT NULL,
  INDEX idx_cart_session_token (session_token)
);

CREATE TABLE cart_items (
  cart_item_id   BIGINT PRIMARY KEY AUTO_INCREMENT,
  cart_id        BIGINT NOT NULL,
  sku            VARCHAR(64) NOT NULL,
  quantity       INT NOT NULL,
  added_at       DATETIME NOT NULL,
  INDEX idx_cart_items_cart (cart_id),
  CONSTRAINT fk_cart_items_session FOREIGN KEY (cart_id) REFERENCES cart_sessions(cart_id) ON DELETE CASCADE
);
```

### 3.2 PostgreSQL (Payment, Customer, Support)
```sql
CREATE TABLE payments (
  payment_id       UUID PRIMARY KEY,
  order_id         BIGINT NOT NULL,
  provider         VARCHAR(32) NOT NULL,
  amount_authorized NUMERIC(12,2) NOT NULL,
  currency_code    CHAR(3) NOT NULL,
  status           VARCHAR(16) NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL,
  updated_at       TIMESTAMPTZ NOT NULL,
  partition_key    DATE NOT NULL DEFAULT CURRENT_DATE,
  UNIQUE (order_id, provider, partition_key)
);

CREATE TABLE payment_attempts (
  attempt_id    UUID PRIMARY KEY,
  payment_id    UUID NOT NULL REFERENCES payments(payment_id),
  attempt_no    INT NOT NULL,
  channel       VARCHAR(16) NOT NULL,
  response_code VARCHAR(8),
  response_payload JSONB,
  created_at    TIMESTAMPTZ NOT NULL
);

CREATE TABLE psp_settlement (
  settlement_id UUID PRIMARY KEY,
  payment_id    UUID NOT NULL REFERENCES payments(payment_id),
  settled_amount NUMERIC(12,2) NOT NULL,
  settled_at    TIMESTAMPTZ NOT NULL,
  provider_batch_id VARCHAR(64) NOT NULL
);

CREATE TABLE customer_profiles (
  customer_id    BIGSERIAL PRIMARY KEY,
  email          CITEXT UNIQUE NOT NULL,
  full_name      VARCHAR(128),
  locale         VARCHAR(8),
  marketing_opt_in BOOLEAN DEFAULT false,
  risk_score     NUMERIC(5,2) DEFAULT 0,
  created_at     TIMESTAMPTZ NOT NULL,
  updated_at     TIMESTAMPTZ NOT NULL
);

CREATE TABLE support_tickets (
  ticket_id      UUID PRIMARY KEY,
  customer_id    BIGINT NOT NULL REFERENCES customer_profiles(customer_id),
  channel        VARCHAR(16) NOT NULL,
  subject        TEXT NOT NULL,
  status         VARCHAR(16) NOT NULL,
  opened_at      TIMESTAMPTZ NOT NULL,
  closed_at      TIMESTAMPTZ
);
```

### 3.3 Cassandra (Inventory)
```sql
CREATE KEYSPACE inventory WITH replication = {
  'class': 'NetworkTopologyStrategy',
  'us-east': 3,
  'eu-west': 3,
  'asia-southeast': 3
};

CREATE TABLE inventory.stock_level (
  sku TEXT,
  warehouse_id TEXT,
  iso_week TEXT,
  available_qty INT,
  reserved_qty INT,
  updated_at TIMESTAMP,
  PRIMARY KEY ((sku, warehouse_id), iso_week)
) WITH CLUSTERING ORDER BY (iso_week DESC);

CREATE TABLE inventory.reservation (
  reservation_id UUID,
  order_id BIGINT,
  sku TEXT,
  warehouse_id TEXT,
  qty INT,
  ttl_expire TIMESTAMP,
  status TEXT,
  PRIMARY KEY (reservation_id)
) WITH default_time_to_live = 3600;
```

### 3.4 CouchDB (Product & Review)
```json
{
  "_id": "product::SKU123",
  "type": "product",
  "sku": "SKU123",
  "status": "ACTIVE",
  "default_locale": "en_US",
  "categories": ["electronics", "mobile"],
  "attributes": {
    "brand": "ACME",
    "model": "X100"
  }
}
```
```json
{
  "_id": "product::SKU123::vi_VN",
  "type": "translation",
  "sku": "SKU123",
  "locale": "vi_VN",
  "title": "Điện thoại ACME X100",
  "description": "Mô tả tiếng Việt",
  "last_synced": "2025-10-16T15:00:00Z"
}
```
```json
{
  "_id": "review::SKU123::98765",
  "type": "review",
  "sku": "SKU123",
  "customer_id": 98765,
  "rating": 4,
  "title": "Tốt",
  "body": "Pin khỏe, màn hình đẹp",
  "created_at": "2025-10-15T11:20:00Z"
}
```

## 4. Problem Scenarios (As-Is)
1. **Cross-region reconciliation**: Orders ghi nhận tại MySQL US, nhưng payment ở PostgreSQL EU → dashboard Finance trễ >4 giờ.
2. **Oversell do TTL**: Cassandra `reservation` TTL hết trước khi payment confirm, kho không kịp refresh → marketing quảng cáo sản phẩm hết hàng.
3. **Schema drift**: Nhóm product thêm field mới vào CouchDB mà không cập nhật analytics pipeline → Flink job thất bại, segmentation stale.
4. **Kafka consumer break**: Marketing consumer bị lỗi schema registry, `product.updated` không xử lý → giá quảng cáo sai lệch.
5. **Fulfillment visibility**: Log shipment lưu file CSV lên MinIO batch 30 phút → support không có update realtime.
6. **Fraud detection delay**: Payment data write sau 5 phút mới replicate → `fraud-service` không có context kịp thời, rủi ro chargeback.

## 5. Target Data Architecture & Remediation
- **CDC Layer**: Debezium connectors cho MySQL (binlog ROW) và PostgreSQL (WAL). Cassandra CDC qua DataStax Agent hoặc commitlog tailer; CouchDB `_changes` feed → Kafka.
- **Event Backbone**: Kafka topics chuẩn hóa, Avro schema quản lý qua Schema Registry. Partition theo `tenant_region` để cân bằng.
- **Lakehouse**: MinIO + Nessie + Iceberg để lưu raw/curated tables (`raw.orders_mysql`, `curated.order_payment`, `inventory.snapshot`).
- **Streaming**:
  - Flink job `fraud_enricher`: join `order.created`, `payment.authorized`, `inventory.reserved`, hành vi clickstream, emit alert <2 phút.
  - Flink job `inventory_global_view`: aggregate per SKU + region, sink Cassandra global table và publish panel feed.
- **Batch**:
  - Spark structured streaming ingest raw to Iceberg bronze.
  - Nightly Spark job reconcile `orders`, `payments`, `shipment_logs` (MinIO) → produce finance ledger in Iceberg silver, sync to Doris/Trino.
- **Serving Layer**: Trino exposes unified views (`vw_customer_360`, `vw_inventory_global`). Support-service caching qua Redis + periodic refresh.
- **Governance**: Great Expectations on Iceberg ingestion, data contracts defined per topic, Nessie branches cho promotion, audit via Atlas/Amundsen (future).

## 6. Task Breakdown (Execution Backlog)

### Phase A – Xây dựng & mô phỏng vấn đề
1. **Schema & Config Consolidation**
   - Chuẩn hóa DDL/JSON cho từng service như trên.
   - Tạo Debezium connector configs (MySQL, PostgreSQL).
   - Document Cassandra keyspaces & TTL policies.
2. **Synthetic Data Generators**
   - Python scripts (Faker) tạo giao dịch multi-region cho cart/order/payment.
   - Cassandra load test (cassandra-stress) để tạo reservation churn.
   - CouchDB bulk loader (python + `_bulk_docs`).
   - Kafka behavior event producer (FastAPI background task or separate worker).
3. **Incident Simulation**
   - Throttle replication MySQL replica → verify reconciliation lag.
   - Force schema change in CouchDB (add field), quan sát failure Flink job.
   - Kafka schema mismatch scenario (deploy incompatible schema version).
   - Delay shipment log upload để support dashboard stale.
4. **Observability Baseline**
   - Prometheus exporters (FastAPI metrics, Debezium, Kafka).
   - Grafana dashboards (checkout latency, replication lag, inventory health).
   - Loki log pipelines tagging service, region, request ID.

### Phase B – Giải pháp & chuẩn hóa luồng dữ liệu
1. **CDC & Lakehouse Foundation**
   - Deploy Debezium connectors → Kafka topics.
   - Configure Iceberg catalog (Nessie) namespaces, retention policies.
   - Implement Spark streaming ingestion (bronze tables).
2. **Streaming Pipelines**
   - Flink fraud detection topology (SQL or DataStream API) with 2-minute window.
   - Flink inventory aggregator writing to Cassandra global + Kafka for marketing.
   - Set up Kafka Connect sink to Elastic/Prometheus for monitoring events.
3. **Batch & Analytics**
   - Spark job for finance reconciliation → Iceberg silver/gold tables.
   - Trino views / materialized views for Support 360 & Marketing segmentation.
   - Doris/BI data mart sync.
4. **Operational Hardening**
   - Schema registry enforcement & contract tests.
   - Automated data quality checks (Great Expectations) per ingestion.
   - Incident playbooks & Alertmanager rules for SLA breaches.
5. **API Enhancements**
   - Update support-service to consume unified data (Trino REST or cached view).
   - Expose inventory global API for marketing, using aggregated Cassandra table.
   - Add fallback & circuit breaker patterns via API Gateway/Service Mesh.

## 7. Next Steps
- Hoàn thiện OpenAPI specs & AsyncAPI schemas cho từng service.
- Viết tài liệu pipeline chi tiết (Flink, Spark) và script seed dữ liệu.
- Chuẩn bị infra IaC (Terraform/K8s manifests) cho multi-region deployment.
- Thiết lập CI/CD: unit + contract tests, CDC pipeline validation, data quality CI.
- Triển khai lộ trình AI/ML/Data/Agent Ops trong `docs/design/platform/ai-ml-agent-ops.md` (Schema Registry, Feast, MLflow, Airflow, LLMOps).

## 8. API & Contract Blueprint
### 8.1 REST (OpenAPI snippets)
- `order-service`
  ```yaml
  /orders:
    post:
      summary: Create order
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/CreateOrderRequest'
      responses:
        '201':
          description: Created
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/OrderResponse'
  ```
  - `CreateOrderRequest` gồm `customerId`, `items[] { sku, qty, price }`, `paymentIntentId`, `channel`.
  - Validation: FastAPI `pydantic` models, enforce idempotency header `X-Idempotency-Key`.

- `inventory-service`
  ```yaml
  /inventory/reserve:
    post:
      summary: Hold stock for order
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                orderId: { type: string }
                warehousePreference: { type: string }
                lines:
                  type: array
                  items:
                    type: object
                    properties:
                      sku: { type: string }
                      qty: { type: integer }
      responses:
        '200': { description: Reservation accepted }
        '409': { description: Not enough stock }
  ```

- `support-service` GET `/support/cases/{ticketId}?includeTimeline=true` trả về timeline tổng hợp (order, payment, shipment) từ Trino view, fallback API call khi Trino unavailable.

### 8.2 AsyncAPI (Kafka topics)
```yaml
asyncapi: '2.6.0'
info:
  title: Ecommerce Event Mesh
  version: '1.0.0'
channels:
  order.created:
    subscribe:
      message:
        $ref: '#/components/messages/OrderCreated'
components:
  messages:
    OrderCreated:
      payload:
        type: object
        properties:
          eventId: { type: string }
          orderId: { type: string }
          tenantRegion: { type: string }
          status: { type: string }
          grandTotal: { type: number, format: float }
          createdAt: { type: string, format: date-time }
```

- Giao thức: Kafka + Avro + Schema Registry; enforce compatibility `BACKWARD_TRANSITIVE`.
- Topic naming convention: `<domain>.<event>.<version>` (vd `order.created.v1`).

## 9. Event Schema Catalogue (Avro)
```json
{
  "type": "record",
  "namespace": "com.ecommerce.order",
  "name": "OrderCreated",
  "fields": [
    { "name": "event_id", "type": "string" },
    { "name": "order_id", "type": "long" },
    { "name": "tenant_region", "type": "string" },
    { "name": "customer_id", "type": "long" },
    { "name": "grand_total", "type": { "type": "bytes", "logicalType": "decimal", "precision": 12, "scale": 2 } },
    { "name": "status", "type": { "type": "enum", "name": "OrderStatus", "symbols": ["PENDING","CONFIRMED","FULFILLED","CANCELLED","RETURNED"] } },
    { "name": "created_at", "type": { "type": "long", "logicalType": "timestamp-millis" } },
    { "name": "items", "type": { "type": "array", "items": { "name": "OrderLine", "type": "record", "fields": [
        { "name": "sku", "type": "string" },
        { "name": "qty", "type": "int" },
        { "name": "unit_price", "type": { "type": "bytes", "logicalType": "decimal", "precision": 12, "scale": 2 } }
    ] } } }
  ]
}
```
- Tương tự định nghĩa `payment.authorized`, `inventory.reserved`, `customer.updated` (include versioning & optional fields with defaults).
- Embed `trace_id` & `correlation_id` trong header dùng Kafka message headers, propagate via OpenTelemetry.

## 10. Synthetic Data & Scenario Simulation
### 10.1 Data Generators
- `scripts/generate_orders.py`: FastAPI client + Faker; tạo 10K orders/region, kèm event push Kafka.
- `scripts/generate_payments.py`: insert vào PostgreSQL, mapping order_id; simulate retries & PSP codes.
- `scripts/generate_inventory.py`: use `cassandra-driver`, seed stock per SKU/warehouse, create reservations with varying TTL.
- `scripts/generate_reviews.py`: bulk load CouchDB `_bulk_docs` 100K documents multi-locale.
- Clickstream: Python Kafka producer publish Avro events `behavior.pageView`, `behavior.addToCart` cho Flink job.

### 10.2 Incident Playbooks
| Scenario | Steps | Metrics/Validation |
| --- | --- | --- |
| Replica lag | Throttle MySQL replica (simulate network) → run reconciliation job | Measure `replication_lag_seconds`, check finance dashboard delay |
| Schema drift | Add `newAttribute` trong CouchDB doc, chưa update schema registry | Flink job fails; alert triggered via Grafana | 
| Kafka incompatibility | Publish incompatible schema version to `product.updated` | Consumer crash, Schema Registry logs; verify contract tests fail in CI |
| Fulfillment delay | Delay MinIO upload 30m | Support dashboard stale; alert `fulfillment_lag_minutes > 10` |
| TTL oversell | Reduce Cassandra TTL to 5m, hold payment 10m | Inventory mismatch, triggered by Great Expectations check |

### 10.3 Tooling
- Containerized scripts invoked via `docker compose run generator --scenario <name>`.
- Use `pytest` fixtures to seed DB before each scenario.
- Observability harness: Prometheus pushgateway for synthetic metrics.

## 11. Implementation Roadmap
### 11.1 Delivery Waves
1. **Wave 0 – Foundations (Week 0-2)**
   - Stand up core FastAPI services skeleton (customer, product, order, payment).
   - Provision databases per service (MySQL cluster, PostgreSQL, Cassandra, CouchDB, Redis).
   - Establish CI/CD baseline (lint, unit tests, docker build).
2. **Wave 1 – Event Backbone & CDC (Week 3-5)**
   - Deploy Kafka, Schema Registry, Debezium connectors.
   - Implement event publishing from services (FastAPI -> Kafka producer).
   - Define Avro schemas & compatibility rules; contract test pipeline.
3. **Wave 2 – Data Lakehouse (Week 6-8)**
   - Setup MinIO, Nessie, Iceberg tables; Spark ingestion jobs.
   - Configure Flink cluster; deploy `fraud_enricher` streaming job.
   - Validate data availability via Trino queries & dashboards.
4. **Wave 3 – Observability & Resilience (Week 9-11)**
   - Integrate Prometheus, Grafana, Loki, Alertmanager; create dashboards.
   - Implement chaos scripts (replica lag, schema drift) & verify alerts.
   - Add API Gateway policies (rate-limit, circuit breaker).
5. **Wave 4 – Optimization & Governance (Week 12+)**
   - Great Expectations checks, lineage catalog; Nessie branching for promotion.
   - Optimize Cassandra global aggregation, marketing segmentation pipeline.
   - Handover runbooks, finalize documentation.

### 11.2 Work Items & Dependencies
| Task ID | Description | Owner | Prereq | Duration |
| --- | --- | --- | --- | --- |
| T-01 | Define OpenAPI/AsyncAPI repo & CI validation | Platform | None | 2d |
| T-05 | Implement Debezium MySQL connector | Data Eng | T-01 | 3d |
| T-07 | Build Spark streaming ingestion -> Iceberg | Data Eng | T-05 | 5d |
| T-09 | Develop Flink fraud job (join order/payment) | Data Eng | T-07 | 5d |
| T-12 | Implement Support 360 API aggregator | Backend | T-07 | 4d |
| T-15 | Setup Great Expectations suite | Data Gov | T-07 | 3d |
| T-17 | Chaos scenario automation | SRE | T-05 | 4d |
| T-20 | Final integration tests & docs | All | T-12,T-15,T-17 | 3d |

### 11.3 Risk Register
- **Latency spikes**: ensure Flink job parallelism auto scales; set backlog alarms.
- **Data contract violation**: enforce CI check gating merges; quick rollback via Schema Registry compatibility.
- **Cross-region outages**: implement active-active Cassandra + MySQL; replicate Iceberg metadata to secondary MinIO.
- **Security compliance**: tokenize sensitive payment data; ensure GDPR compliance by pseudonymizing customer data in analytics tables.

## 12. Reference & Further Work
- FastAPI docs (Context7): `/tiangolo/fastapi` – sử dụng Pydantic models, background tasks cho event emit.
- Apache Flink docs `/apache/flink` chủ đề: stateful stream processing, Kafka connector, table API.
- Apache Iceberg docs `/apache/iceberg` – table format, schema evolution.
- Great Expectations docs `/great-expectations/docs` – data quality suite integration.
- Tiếp tục phát triển sequence diagram (PlantUML/Mermaid) cho checkout, fraud, support 360 flows.

## 13. Detailed Blueprints
- Services: `docs/design/services/order-service.md`, `docs/design/services/inventory-service.md`, `docs/design/services/payment-service.md`, `docs/design/services/support-service.md`, `docs/design/services/customer-service.md`, `docs/design/services/pricing-service.md`, `docs/design/services/fraud-service.md`, `docs/design/services/catalog-service.md`, `docs/design/services/fulfillment-service.md`, `docs/design/services/notification-service.md`, `docs/design/services/recommendation-service.md`, `docs/design/services/cart-service.md`, `docs/design/services/review-service.md`.
- Pipelines: `docs/design/pipelines.md` mô tả CDC, streaming, batch workflows và backlog.
- Platform Ops: `docs/design/platform/ai-ml-agent-ops.md` cùng các phase chi tiết trong thư mục `docs/design/platform/`.
