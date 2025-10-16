# Payment Service Blueprint

## 1. Domain Scope
- Xử lý toàn bộ lifecycle thanh toán: tạo intent, thực hiện authorization/capture/refund theo cổng PSP.
- Lưu trữ ledger chi tiết (PostgreSQL) phục vụ reconciliations, audits, chargeback.
- Phát event cho downstream (order-service, finance, fraud-service).

## 2. Data Model (PostgreSQL)
- `payments`, `payment_attempts`, `psp_settlement` như tài liệu tổng.
- `refunds`:
  ```sql
  CREATE TABLE refunds (
    refund_id UUID PRIMARY KEY,
    payment_id UUID NOT NULL REFERENCES payments(payment_id),
    amount NUMERIC(12,2) NOT NULL,
    reason VARCHAR(64),
    status VARCHAR(16) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    processed_at TIMESTAMPTZ
  );
  ```
- `payment_outbox` cho transactional outbox.
- Partition: `payments` partition by range `partition_key` (DATE) per month để tối ưu query lớn.

## 3. API Endpoints
```python
@router.post("/payments", response_model=PaymentResponse)
async def create_payment(payload: PaymentCreate):
    ...

@router.post("/payments/{payment_id}/confirm", response_model=PaymentResponse)
async def confirm_payment(payment_id: UUID, payload: PaymentConfirm):
    ...

@router.post("/payments/{payment_id}/refund", response_model=RefundResponse)
async def refund(payment_id: UUID, payload: RefundCreate):
    ...

@router.get("/payments/{order_id}", response_model=List[PaymentResponse])
async def list_payments(order_id: int):
    ...
```
- Integrate PSP connectors (stripe/adyen simulation). Use background task for asynchronous PSP callback handling.
- Error handling: 402 for payment required, 409 for invalid state transitions.

## 4. Event Contracts
- Outgoing:
  - `payment.authorized.v1` (includes `payment_id`, `order_id`, `amount`, `payment_method`, `risk_score`).
  - `payment.failed.v1` (`failure_reason`, `psp_code`).
  - `payment.refunded.v1`.
- Incoming:
  - `order.created.v1` (optional: to auto-initiate payment if autopay).
  - PSP webhook events (converted to Kafka via connector or HTTP endpoint -> event).
- Ensure idempotency by storing PSP event IDs.

## 5. Integrations
- External PSP API: use httpx AsyncClient with retries + circuit breaker.
- Fraud Service: synchronous scoring (REST `/fraud/evaluate`) before final authorization.
- Finance systems: scheduled export (Spark job) from Iceberg `payments` table.

## 6. Observability
- Metrics: `payment_attempt_duration_seconds`, `payment_authorized_total`, `payment_failure_rate`.
- Logging: mask PAN/token, but include `payment_id`, `order_id`, `psp`.
- Tracing: instrument PSP calls, event publishing.

## 7. Testing
- Unit: status transitions, input validation, idempotency.
- Integration: run PSP simulator container; verify webhook handling.
- Contract: Avro schema compatibility; AsyncAPI tests.
- Load test: concurrency for sales events (simulate 5k req/min).

## 8. Backlog
| Task | Description | Priority |
| --- | --- | --- |
| PAY-01 | Implement PSP connector abstraction + mock simulator | High |
| PAY-02 | Build transactional outbox + Debezium config | High |
| PAY-03 | Integrate fraud scoring before capture | High |
| PAY-04 | Add reconciliation endpoint exporting CSV to MinIO | Medium |
| PAY-05 | Implement retry/compensation for PSP timeouts | Medium |

## 9. Risks
- **PSP SLA breaches**: implement fallback/queuing, escalate to manual review.
- **Security compliance**: store tokens only, ensure PCI-DSS guidelines, encryption at rest.
- **Data drift**: maintain schema mapping between PSP payloads and internal model.
