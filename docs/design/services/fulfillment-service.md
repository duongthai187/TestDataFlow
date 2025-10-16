# Fulfillment Service Blueprint

## 1. Domain Scope
- Điều phối quy trình fulfillment: picking, packing, shipping, returns.
- Kết nối với 3PL, last-mile carriers, warehouse management hệ thống.
- Cung cấp tracking realtime cho order-service và customer portal.

## 2. Data Model (MySQL + Redis + MinIO)
- MySQL tables:
  ```sql
  CREATE TABLE shipments (
    shipment_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    order_id BIGINT NOT NULL,
    fulfillment_center_id BIGINT NOT NULL,
    carrier_code VARCHAR(32) NOT NULL,
    service_level VARCHAR(32) NOT NULL,
    status VARCHAR(24) NOT NULL,
    tracking_number VARCHAR(64),
    shipped_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ,
    estimated_delivery TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
  );

  CREATE TABLE fulfillment_tasks (
    task_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    shipment_id BIGINT NOT NULL REFERENCES shipments(shipment_id),
    task_type VARCHAR(24) NOT NULL,
    status VARCHAR(16) NOT NULL,
    assigned_to VARCHAR(64),
    deadline TIMESTAMPTZ,
    payload JSON,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
  );

  CREATE TABLE return_requests (
    return_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    order_id BIGINT NOT NULL,
    authorization_code VARCHAR(32) UNIQUE,
    status VARCHAR(16) NOT NULL,
    reason TEXT,
    requested_at TIMESTAMPTZ NOT NULL,
    processed_at TIMESTAMPTZ
  );
  ```
- Redis: cache shipment tracking info (`shipment::{tracking_number}` TTL 15 phút) để giảm load 3PL API.
- MinIO: lưu label PDF, packing slip, proof-of-delivery images.

## 3. API Endpoints (FastAPI)
```python
@router.post("/fulfillment/shipments", response_model=ShipmentResponse)
async def create_shipment(payload: ShipmentCreate):
    ...

@router.get("/fulfillment/shipments/{shipment_id}", response_model=ShipmentResponse)
async def get_shipment(shipment_id: int):
    ...

@router.post("/fulfillment/shipments/{shipment_id}/status", response_model=ShipmentResponse)
async def update_status(shipment_id: int, payload: ShipmentStatusUpdate):
    ...

@router.post("/fulfillment/returns", response_model=ReturnResponse)
async def create_return(payload: ReturnCreate):
    ...

@router.get("/fulfillment/track/{tracking_number}", response_model=TrackingResponse)
async def track_shipment(tracking_number: str):
    ...
```
- Webhook endpoint `/fulfillment/carriers/{carrier}/callback` nhận updates từ 3PL/carrier.
- Background workers polling carriers không hỗ trợ webhook.

## 4. Event Contracts
- Outgoing:
  - `fulfillment.shipment.created.v1`: `order_id`, `shipment_id`, `carrier`, `eta`.
  - `fulfillment.shipment.updated.v1`: `status`, `tracking_number`, `event_time`.
  - `fulfillment.return.requested.v1`: cho support-service, warehouse.
  - `fulfillment.return.completed.v1`: cho finance (refund) và inventory.
- Incoming:
  - `order.fulfillment_ready.v1`: từ order-service khi đơn sẵn sàng pick.
  - `inventory.stock.reserved.v1`: ensure stock allocated.
  - `payment.refunded.v1`: sync return workflow.

## 5. Integrations
- Warehouse management (WMS) API: send picking tasks, receive completion events.
- Carrier APIs (DHL, FedEx, local VN post): create labels, track statuses.
- Notification service: push tracking updates tới khách hàng qua email/SMS.
- Data lake: Spark job ingest shipment logs vào Iceberg `fulfillment_events`.

## 6. Observability
- Metrics: `shipment_creation_latency_seconds`, `carrier_callback_errors_total`, `return_processing_time_seconds`.
- Logging: include `shipment_id`, `carrier_code`, `status_transition`.
- Tracing: cross-service trace with order-service (link by `order_id`).
- Alert: escalate nếu `shipment.status=DELAYED` > threshold.

## 7. Testing
- Unit: status transition guardrails, SLA calculation, label generation.
- Integration: carrier sandbox API, WMS simulator, Redis cache invalidation.
- Contract: AsyncAPI for carrier callbacks, Avro for events.
- Resilience: test retry logic khi carrier API 429/500, circuit breaker fallback.

## 8. Backlog
| Task | Description | Priority |
| --- | --- | --- |
| FFM-01 | Build carrier integration abstraction + sandbox mocks | High |
| FFM-02 | Implement return workflow with RMA approval | High |
| FFM-03 | Add shipment ETA prediction (Flink + ML model) | Medium |
| FFM-04 | Provide warehouse dashboard (Grafana + Prometheus metrics) | Medium |
| FFM-05 | Automate label archival lifecycle in MinIO | Low |

## 9. Risks
- **Carrier SLA variance**: monitor, implement multi-carrier fallback.
- **Return fraud**: integrate với fraud-service cross-check.
- **Operational overload**: queue tasks, auto-scale workers, implement manual override portal.
