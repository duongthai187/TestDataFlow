# Notification Service Blueprint

## 1. Domain Scope
- Quản lý gửi thông báo đa kênh (email, SMS, push, in-app) cho sự kiện ecommerce.
- Điều phối template, localization, throttling, preference management.
- Đảm bảo delivery reliable, observability đầy đủ và tuân thủ opt-in/opt-out.

## 2. Data Model (PostgreSQL + Redis + ClickHouse)
- PostgreSQL tables:
  ```sql
  CREATE TABLE notification_templates (
    template_id UUID PRIMARY KEY,
    channel VARCHAR(16) NOT NULL,
    locale VARCHAR(10) NOT NULL,
    name VARCHAR(64) NOT NULL,
    version SMALLINT NOT NULL,
    subject TEXT,
    body_markdown TEXT,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
  );

  CREATE TABLE notification_preferences (
    customer_id BIGINT NOT NULL,
    channel VARCHAR(16) NOT NULL,
    opt_in BOOLEAN NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (customer_id, channel)
  );
  ```
- Redis: queue for rate limiting tokens per channel (`notif_rate::{channel}`) + template cache.
- ClickHouse: store delivery logs (`notification_events`) để analytics (fast query).

## 3. API Endpoints (FastAPI)
```python
@router.post("/notifications/send", response_model=NotificationResponse)
async def send_notification(payload: NotificationSendRequest):
    ...

@router.post("/notifications/batch", response_model=BatchResponse)
async def send_batch(payload: NotificationBatchRequest):
    ...

@router.get("/notifications/preferences/{customer_id}", response_model=PreferenceResponse)
async def get_preferences(customer_id: int):
    ...

@router.put("/notifications/preferences/{customer_id}", response_model=PreferenceResponse)
async def update_preferences(customer_id: int, payload: PreferenceUpdate):
    ...
```
- Webhook endpoints để nhận delivery receipts từ ESP/SMS provider.
- Background workers (Celery/Kafka consumers) xử lý queue `notification.send.request`.

## 4. Event Contracts
- Incoming events:
  - `order.status.changed.v1`: gửi email/SMS update.
  - `fulfillment.shipment.updated.v1`: push tracking notification.
  - `marketing.campaign.created.v1`: trigger batch sends (respect preferences).
- Outgoing events:
  - `notification.sent.v1`: contains `notification_id`, `channel`, `status`.
  - `notification.failed.v1`: with `error_code`, `provider_message`.
  - `notification.preference.updated.v1`: sync với customer-service.
- Event payloads không chứa PII raw (mask email/số điện thoại). Sử dụng token reference.

## 5. Integrations
- Email provider (SendGrid/Mailgun), SMS aggregator (Twilio), push notification service (FCM/APNs).
- Template rendering sử dụng Jinja2; static assets (images) lưu trên CDN.
- Preference sync với customer-service, marketing automation.
- Analytics pipeline: Spark job đọc ClickHouse, tạo dashboard churn vs notification engagement.

## 6. Observability
- Metrics: `notification_send_latency_seconds`, `notification_delivery_rate`, `notification_bounce_total`.
- Logging: include `notification_id`, `channel`, `provider_status`; mask recipient.
- Tracing: trace send pipeline -> provider call -> receipt handling.
- Alerting: high bounce rate, provider API errors > threshold, rate limit nearing quota.

## 7. Testing
- Unit: template rendering context, preference enforcement, rate limit.
- Integration: fake providers (WireMock), verify webhook signature.
- Contract: Avro schema for events, AsyncAPI for provider webhooks.
- Load: simulate marketing burst (500k notifications) ensure queue scaling.

## 8. Backlog
| Task | Description | Priority |
| --- | --- | --- |
| NTF-01 | Implement unified provider adapter with failover | High |
| NTF-02 | Build template versioning + localization UI workflow | High |
| NTF-03 | Integrate ClickHouse delivery analytics with Grafana | Medium |
| NTF-04 | Add in-app notification channel via WebSocket | Medium |
| NTF-05 | Support WhatsApp/OTT messaging providers | Low |

## 9. Risks
- **Provider outages**: implement multi-provider fallback, queue backlog handling.
- **Compliance**: enforce opt-out, include unsubscribe tokens, respect quiet hours.
- **Performance**: ensure rate-limiting and backpressure to avoid provider throttling.
