# Order Service Blueprint

## 1. Domain Scope
- Chịu trách nhiệm tạo và quản lý trạng thái đơn hàng trong toàn bộ lifecycle (PENDING → CONFIRMED → FULFILLED/RETURNED).
- Hợp tác chặt chẽ với `cart-service`, `inventory-service`, `payment-service`, `fulfillment-service`.
- Là nguồn sự thật duy nhất (system of record) cho order header và line items (MySQL).

## 2. Data Model
### 2.1 Tables (MySQL)
- `orders`: như định nghĩa trong tài liệu tổng (`orders`, `order_items`, `order_status_history`).
- `order_status_history` bổ sung:
  ```sql
  CREATE TABLE order_status_history (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    order_id BIGINT NOT NULL,
    from_status ENUM('PENDING','CONFIRMED','FULFILLED','CANCELLED','RETURNED') NOT NULL,
    to_status   ENUM('PENDING','CONFIRMED','FULFILLED','CANCELLED','RETURNED') NOT NULL,
    reason_code VARCHAR(32),
    comment TEXT,
    transitioned_at DATETIME NOT NULL,
    actor VARCHAR(32) NOT NULL,
    CONSTRAINT fk_status_history_order FOREIGN KEY (order_id) REFERENCES orders(order_id)
  );
  ```
- Indexing: composite indexes trên `(tenant_region, created_at)` và `(status, updated_at)` để feed analytics và CDC triggers.

### 2.2 ORM/Pydantic Models
- `OrderCreate`, `OrderItemCreate` (validation `qty > 0`, `unit_price >= 0`).
- `OrderResponse`: include nested items và trạng thái hiện tại.

## 3. API Contract (FastAPI)
```python
@router.post("/orders", response_model=OrderResponse, status_code=201)
async def create_order(payload: OrderCreate, idempotency_key: str = Header(...)):
    ...

@router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(order_id: int):
    ...

@router.post("/orders/{order_id}/status", response_model=OrderResponse)
async def transition_status(order_id: int, payload: OrderStatusUpdate):
    ...
```

- Middleware kiểm tra header `X-Idempotency-Key` (Redis cache) để tránh duplicate submission.
- Background task: publish `order.created` event sau khi commit transaction (sử dụng SQLAlchemy session + `after_commit` hook).
- Error mapping: 409 (conflict), 422 (validation), 404 (not found).

## 4. Event Integration
### 4.1 Outgoing Events
- `order.created.v1`
  - Produced sau transaction commit.
  - Key: `order_id` (Kafka partition bởi tenant region).
- `order.status.changed.v1`
  - Emitted khi transition.
- `order.item.backordered.v1`
  - Khi inventory không đủ.

### 4.2 Incoming Events
- `payment.authorized.v1`: cập nhật status `CONFIRMED`.
- `payment.failed.v1`: transition `CANCELLED` + release inventory.
- `inventory.reservation.failed.v1`: mark order `PENDING_REVIEW` và raise alert.
- Use Kafka consumer group `order-service-events`; handle idempotency qua `event_id` table (PostgreSQL or Redis) → TODO.

## 5. Dependencies & Interactions
- REST calls tới `inventory-service` (`/inventory/reserve`, `/inventory/release`).
- REST call tới `payment-service` để tạo payment intent (fallback khi event bus unavailable).
- gRPC optional cho synchronous risk check (future).

## 6. Observability
- Metrics (Prometheus):
  - `order_created_total{tenant_region}`
  - `order_status_transition_seconds_bucket`
  - `order_create_requests_inflight`
- Tracing: OpenTelemetry instrumentation (trace id propagate vào Kafka headers).
- Logging: Structured JSON (order_id, customer_id, status).

## 7. Testing & QA Checklist
- Unit tests: Pydantic validation, status transitions.
- Integration tests: MySQL + Kafka test container (pytest fixtures).
- Contract tests: ensure AsyncAPI schemas align (using `schemathesis`/custom validator).
- Chaos test: duplicate `order.created` delivery -> ensure idempotent.

## 8. Backlog Tasks
| Task | Description | Priority |
| --- | --- | --- |
| OR-01 | Implement idempotency key storage (Redis) | High |
| OR-02 | Build Kafka producer wrapper with tracing headers | High |
| OR-03 | Add saga timeout logic (cancel if payment not confirmed within X minutes) | Medium |
| OR-04 | Expose `/orders/search` with pagination/filtering (for Support UI) | Medium |
| OR-05 | Implement compensating action for inventory failure | Medium |

## 9. Risks & Mitigations
- **Double spend events**: Use transactional outbox (MySQL table + Debezium) to publish events reliably.
- **Cross-region replication lag**: Provide eventual consistency note to downstream, use `last_updated_at` field.
- **Schema evolution**: version Pydantic models, maintain compatibility.
