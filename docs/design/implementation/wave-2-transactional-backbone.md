# Wave 2 – Transactional Backbone Implementation Plan

## 1. Objectives
- Hoàn thiện chuỗi giao dịch chính: order → payment → inventory với event-driven saga và cơ chế bù trừ.
- Thiết lập CDC (Debezium) cho MySQL/PostgreSQL, đảm bảo sự cố trong usecase có thể tái tạo (reconciliation delay, oversell TTL).
- Mở rộng monitoring và test coverage cho transaction flows.

## 2. Scope & Deliverables
| Service / Component | Deliverables |
| --- | --- |
| order-service | Order creation, status transitions, saga orchestrator, outbox pattern, events `order.created`, `order.status.changed`. |
| payment-service | PSP integration mock, ledger tables, transactional outbox, events `payment.authorized`, `payment.failed`, `payment.refunded`. |
| inventory-service | Cassandra reservation logic, stock adjustments, TTL enforcement, events `inventory.reserved`, `inventory.adjusted`. |
| saga coordinator | State machine orchestrating order/payment/inventory with compensating actions. |
| CDC layer | Debezium connectors (MySQL orders, PostgreSQL payments) + topic setup. |
| Testing | End-to-end checkout tests, failure scenarios (PSP timeout, inventory shortage). |

## 3. Implementation Breakdown
### 3.1 Order Service Enhancements
- **Data Model**: Extend existing MySQL schema with `order_status_history`, `order_outbox` (for event reliability).
- **API**:
  - `POST /orders` (accepts `cartId`, `paymentMethod`, `shippingAddress`).
  - `GET /orders/{id}` (include line items, status timeline).
  - `POST /orders/{id}/cancel` (compensation path).
- **Saga Orchestration**:
  - Use transactional workflow orchestrator (custom module or library like `dramatiq`/`celery` with saga pattern).
  - Steps: validate cart → reserve inventory → authorize payment → confirm order.
  - Compensation: on failure, release inventory, cancel payment, update status.
- **Events**: Outbox table with `status` (`PENDING`, `SENT`); background process flush to Kafka.
- **Testing**: make use of `pytest` with `pytest-asyncio`; simulate concurrency.

### 3.2 Payment Service Enhancements
- **PSP Mock**: implement module simulating PSP responses (success, failure, timeout). Support async callbacks.
- **Ledger**:
  - Tables `payments`, `payment_attempts`, `refunds`, `payment_outbox`.
  - Enforce idempotency via PSP event IDs.
- **API**:
  - `POST /payments` to create intent.
  - `POST /payments/{id}/confirm` (calls PSP, updates status).
  - `POST /payments/{id}/refund`.
- **Events**: `payment.authorized.v1`, `payment.failed.v1`, `payment.refunded.v1` with Avro schema.
- **Monitoring**: metrics `payment_attempt_latency_seconds`, `payment_failure_rate`.
- **Testing**: unit tests for state transitions, integration tests with PSP mock.

### 3.3 Inventory Service Enhancements
- **Reservation Logic**: Cassandra table `reservation` with TTL (default 10 mins). Use lightweight transactions or idempotent updates to avoid duplicate holds.
- **API**:
  - `POST /inventory/reserve` (accepts array of sku/qty, optional warehouse preference).
  - `POST /inventory/release` (on cancel).
  - `POST /inventory/adjust` (used by fulfillment returns).
- **Event Consumers**: listen to `order.status.changed` (to release holds on cancel) and `payment.authorized` (to confirm reservation).
- **Events**: `inventory.reserved.v1`, `inventory.released.v1`, `inventory.adjusted.v1`.
- **Testing**: load tests for high concurrency (simulate 1k reservations in 1 minute). Validate TTL expiry causing oversell scenario for future resolution.

### 3.4 CDC & Event Infrastructure
- **Debezium Config**:
  - MySQL connector capturing `orders`, `order_items`, `order_outbox`.
  - PostgreSQL connector for `payments`, `payment_outbox`.
  - Register connectors via REST API (docker compose service `connect`).
- **Schema Registry**: ensure Avro schema definitions exist; enforce compatibility `BACKWARD` to replicate schema drift issue when broken.
- **Monitoring**: add connectors to Prometheus scraping; Grafana dashboards for lag.

### 3.5 Saga & Event Storming
- Document sequence diagram (Mermaid) for checkout saga.
- Provide event storming board (Miro/diagram) mapping commands→events→policies.
- Add compensation policies for each failure case.

## 4. Testing & Scenarios
- **Checkout Success**: script `scripts/e2e_checkout_success.py` verifying order flows and data stored correctly.
- **PSP Timeout**: simulate PSP delay > 30s causing payment failure, ensure saga rolls back inventory and order status `CANCELLED`.
- **Oversell**: reduce reservation TTL to 2 minutes, hold payment confirmation to reproduce oversell event; record metrics.
- **Reconciliation Lag**: purposely delay CDC connector to mimic 5-min replication lag; observe finance dashboard stale data.
- **Schema Drift**: modify payment event schema (simulate new field) without updating registry to highlight failure.

## 5. Timeline
| Week | Activities |
| --- | --- |
| Week 4 (early) | Implement order-service saga + outbox; tests. |
| Week 4 (mid) | Payment service PSP integration + events. |
| Week 4 (late) | Inventory service reservation logic + events. |
| Week 5 (early) | CDC connectors setup + monitoring. |
| Week 5 (mid) | Integrate services end-to-end; run scenario scripts. |
| Week 5 (late) | Documentation, diagrams, backlog grooming for issues observed. |

## 6. Risks & Mitigation
- **Saga complexity**: start with orchestrator in order-service; plan refactor to event choreography later.
- **Data consistency**: use outbox pattern to avoid dual-write issues; integration tests verifying eventual consistency.
- **CDC performance**: tune connector snapshot modes; limit to necessary tables (include outbox to propagate events when service down).
- **Testing flakiness**: isolate integration tests, use deterministic seeds for PSP responses.

## 7. Exit Criteria
- Checkout saga working for success, failure, compensation paths.
- Debezium connectors streaming order/payment changes to Kafka topics (observed via console consumer).
- Metrics dashboards show transaction flow (order count, payment latency, inventory holds).
- Scenario scripts demonstrate oversell, reconciliation lag, schema drift ready for Wave 3/4 remediation.

## 8. Next Steps
- Prepare for Wave 3 (Fulfillment, Support, Notification) once transactional backbone stabilized.
- Start defining BI dashboards (Trino queries) using data from CDC for analytics validation.
