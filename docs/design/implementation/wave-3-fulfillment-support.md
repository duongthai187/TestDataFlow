# Wave 3 – Fulfillment, Support & Notification Implementation Plan

## 1. Objectives
- Hoàn thiện lớp hậu cần và dịch vụ khách hàng: fulfillment-service, support-service, notification-service.
- Đảm bảo hệ thống có thể tái tạo vấn đề visibility delay (MinIO uploads), integrate với transactional backbone (Wave 2).
- Thiết lập các workflow gửi thông báo, lưu trữ attachment, timeline aggregation.

## 2. Scope & Deliverables
| Service | Deliverables |
| --- | --- |
| fulfillment-service | Shipment creation APIs, carrier webhook mock, MinIO label storage, events `fulfillment.shipment.created`, `fulfillment.shipment.updated`. |
| support-service | Ticket management API, attachments (MinIO), timeline aggregator (order/payment/fulfillment), events `support.case.opened`, `support.case.closed`. |
| notification-service | Template management, channel abstraction (email/SMS mock), preference handling, events `notification.sent`, `notification.failed`, `notification.preference.updated`. |
| Integrations | Connect to transactional services, update metrics/dashboards, trigger scenarios for delayed visibility. |

## 3. Implementation Breakdown
### 3.1 Fulfillment Service
- **Data Model (MySQL)**: tables `shipments`, `fulfillment_tasks`, `return_requests` (per blueprint) with Alembic migrations.
- **API**:
  - `POST /fulfillment/shipments` (creates shipment from order, generates tracking number).
  - `GET /fulfillment/shipments/{id}`.
  - `POST /fulfillment/shipments/{id}/status` (update status from carrier).
  - `POST /fulfillment/returns` (initiate return).
  - `GET /fulfillment/track/{trackingNumber}` (reads from Redis cache; fallback to DB).
- **Integrations**:
  - Consume `order.status.changed` (when `FULFILLED_READY`) to auto-initiate shipment.
  - Publish events `fulfillment.shipment.created` and `fulfillment.shipment.updated`.
  - Store label/packing slip to MinIO `fulfillment/shipments/<id>/` (simulate with dummy PDF).
  - Carrier webhook mock at `/fulfillment/carriers/{carrier}/callback` generating updates.
- **Visibility Delay Scenario**: script to delay MinIO upload to trigger support visibility problem.

### 3.2 Support Service
- **Data Model (PostgreSQL)**: `support_tickets`, `support_conversations`, `support_attachments` (reference blueprint). Use Alembic migrations.
- **API**:
  - `POST /support/cases` (create ticket, optional order reference).
  - `GET /support/cases/{id}` (with optional `includeTimeline` query to embed aggregated data from Trino or direct service calls during Wave 3).
  - `POST /support/cases/{id}/messages` (append conversation entry).
  - `POST /support/cases/{id}/close` (close ticket).
  - `POST /support/cases/{id}/timeline/refresh` (explicitly refresh aggregated timeline and clear cache).
- **Attachments**: upload endpoint storing file to MinIO `support/cases/<id>/attachments/` (placeholder file storage with metadata in DB).
- **Timeline Aggregation**:
  - For MVP, call order-service, payment-service, fulfillment-service synchronously (later replaced by Trino view). Handle timeouts gracefully.
  - Cache timeline results in Redis to reduce load (TTL 5 minutes). Configure via `SERVICE_REDIS_URL`, `SERVICE_ORDER_SERVICE_URL`, `SERVICE_PAYMENT_SERVICE_URL`, `SERVICE_FULFILLMENT_SERVICE_URL`.
- **Events**: publish `support.case.opened.v1`, `support.case.updated.v1`, `support.case.closed.v1`.
- **Integration**: consume `fulfillment.shipment.updated` to append timeline notes automatically.

### 3.3 Notification Service
- **Data Model (PostgreSQL)**: `notification_templates`, `notification_preferences`, `notification_jobs`.
- **Template Engine**: Jinja2 rendering with localization support (minimal). Provide default templates for order updates, shipping, support updates.
- **Channels**: implement provider abstraction with mock email/SMS; log messages to console + store result to DB.
- **API**:
  - `POST /notifications/send` (single send).
  - `POST /notifications/batch` (batch send; queue background tasks).
  - `GET/PUT /notifications/preferences/{customerId}`.
- **Events**: consume `order.status.changed`, `fulfillment.shipment.updated`, `support.case.updated`; send notifications respecting preferences.
  - Emit `notification.sent.v1`, `notification.failed.v1`.
- **Rate Limiting**: simple token bucket per channel via Redis keys.
- **Observability**: metrics `notification_send_latency_seconds`, `notification_delivery_rate`.

## 4. Cross-Service Workflows
- **Order → Fulfillment → Support**: On order ready for fulfillment, create shipment, send customer notification, update support timeline.
- **Return & Refund**: Return request triggers notification and updates support case.
- **Abandoned Visibility**: script to delay `fulfillment.shipment.updated`, verifying support timeline stops updating (use case reproduction).
- **Preference Enforcement**: ensure notification-service checks `notification_preferences`; create scenario where preference opt-out prevents email send.

## 5. Data & Scenario Scripts
- `scripts/seed/wave3_seed.py`: add sample shipments, support tickets, notification templates.
- `scripts/scenarios/fulfillment_delay.py`: pause MinIO upload/time-lag shipments.
- `scripts/scenarios/notification_spike.py`: generate high volume notifications to test rate limiting.

## 6. Testing & Quality Gates
- Unit tests per service for business logic (shipment status transitions, support timeline aggregator, template rendering).
- Integration tests using dockerized dependencies (MinIO, Redis, Postgres/MySQL) with pytest fixtures.
- Contract tests for events (Avro schema) and API (OpenAPI).
- End-to-end test orchestrating order -> fulfillment -> notification -> support timeline verifying all interactions.

## 7. Timeline
| Week | Activities |
| --- | --- |
| Week 6 (early) | Fulfillment service implementation + tests |
| Week 6 (mid) | Support service + timeline aggregator |
| Week 6 (late) | Notification service + integration with events |
| Week 6 (end) | Scenario scripts, documentation, dashboards update |

## 8. Observability & Dashboards
- Extend Grafana: `Fulfillment SLA`, `Support Response Time`, `Notification Delivery` dashboards.
- Prometheus exporters: track queue lengths, error rates; add Alertmanager rules (delayed shipments, high notification failure rate).
- Loki logging pipeline: structured logs with `service`, `order_id`, `ticket_id`, `notification_id`.
- Support timeline endpoint now enriches responses with external order/payment/shipment data when `includeTimeline=true`, backed by Redis cache.

## 9. Risks & Mitigations
- **MinIO availability**: implement retry/backoff when storing attachments/labels; log fallback if storage fails (simulate in scenario).
- **Timeline aggregator latency**: fallback to cached data or degrade gracefully with partial timeline.
- **Notification overload**: implement rate limiting and queue (Redis lists or Celery) to handle bursts.
- **Security/PII**: ensure attachments and notifications avoid leaking sensitive data; enforce access checks.

## 10. Exit Criteria
- Fulfillment, support, notification services running with core functionality and integrated with transactional backbone.
- Scenario scripts reproduce visibility delay and notification rate-limit scenarios.
- Dashboards display metrics for these services; alerts configured.
- Documentation updated (service READMEs, API specs, runbooks for ops).

## 11. Next Steps
- Move to Wave 4 (observability, chaos, optimization) after validating these services.
- Prepare for follow-up tasks like returns automation, advanced notification channels, support agent tools.
