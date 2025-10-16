# Fraud Service Blueprint

## 1. Domain Scope
- Phát hiện và ngăn chặn giao dịch gian lận cho thanh toán, chính sách hoàn tiền, loyalty abuse.
- Cung cấp scoring realtime cho payment-service và order-service.
- Thu thập sự kiện đa nguồn (orders, payments, device fingerprint) để huấn luyện mô hình ML.

## 2. Data Model (PostgreSQL + Cassandra + Feature Store)
- PostgreSQL (`fraud_decisions`, `fraud_rules`, `case_reviews`).
  ```sql
  CREATE TABLE fraud_decisions (
    decision_id UUID PRIMARY KEY,
    transaction_id UUID NOT NULL,
    order_id VARCHAR(64),
    payment_id UUID,
    customer_id BIGINT,
    risk_score NUMERIC(5,2) NOT NULL,
    decision VARCHAR(16) NOT NULL,
    reason_codes TEXT[],
    triggered_rules TEXT[],
    model_version VARCHAR(32),
    decided_at TIMESTAMPTZ NOT NULL,
    review_required BOOLEAN DEFAULT false
  );
  ```
- Cassandra cluster lưu session fingerprint (`fingerprint_events` partition by device_id, clustering by event_time).
- Feature store (Iceberg on Nessie) cho ML features: bảng `fraud_features_daily`, `fraud_training_labels`.
- Redis: cache danh sách đen (IP, card token, email) với TTL linh hoạt.

## 3. API Endpoints (FastAPI)
```python
@router.post("/fraud/evaluate", response_model=FraudDecision)
async def evaluate_transaction(payload: FraudEvaluationRequest):
    ...

@router.post("/fraud/cases/{decision_id}/escalate", response_model=FraudCaseResponse)
async def escalate_case(decision_id: UUID, payload: CaseEscalation):
    ...

@router.get("/fraud/blacklist", response_model=BlacklistPage)
async def list_blacklist(filter: BlacklistFilter = Depends()):
    ...

@router.post("/fraud/blacklist", response_model=BlacklistEntry)
async def upsert_blacklist(payload: BlacklistUpsert):
    ...
```
- Support gRPC streaming endpoint cho high throughput evaluation từ payment-service.
- Webhook cho manual review tool để cập nhật kết quả.

## 4. Scoring Pipeline
- Realtime scoring: ingest payload → enrich từ Redis blacklist + Cassandra fingerprint → apply rule engine → call ML model via TorchServe.
- Batch retraining: daily Spark job đọc Iceberg features, re-train model, deploy qua MLOps pipeline.
- Store feature drift metrics trong Prometheus.

## 5. Event Contracts
- Incoming events:
  - `payment.authorized.v1`, `payment.failed.v1` → cập nhật labels.
  - `order.created.v1`, `order.cancelled.v1` → enrich context.
  - `customer.segment.recalculated.v1` → update priors.
- Outgoing events:
  - `fraud.decision.made.v1`: gửi đến payment-service, order-service (fields: `transaction_id`, `risk_score`, `decision`, `reason_codes`).
  - `fraud.case.escalated.v1`: trigger human review workflow.
  - `fraud.blacklist.updated.v1`: propagate tới API Gateway, CDN.
- Đảm bảo event idempotency bằng `decision_id` và Kafka exactly-once producer.

## 6. Integrations
- Payment service gọi `/fraud/evaluate` trước khi capture.
- Support service nhận `fraud.case.escalated.v1` để tạo ticket review.
- ML platform: model artifact lưu trong MinIO, deploy qua CI/CD pipeline.
- Great Expectations kiểm tra feature quality trước khi training.

## 7. Observability & Security
- Metrics: `fraud_decision_latency_seconds`, `fraud_high_risk_total`, `model_drift_score`.
- Logging: mask PII, log `decision_id`, `rule_hits`.
- Tracing: correlate evaluation span với `payment_id`.
- Security: RBAC cho blacklist APIs, audit log khi thêm danh sách đen.

## 8. Testing
- Unit: rule evaluation, threshold logic, Redis blacklist checks.
- Integration: Cassandra enrichment, TorchServe scoring responses, Kafka event publishing.
- ML tests: model performance guardrail (AUC, precision @ K).
- Chaos testing: simulate downstream scoring latency, ensure fallback (rule-based only).

## 9. Backlog
| Task | Description | Priority |
| --- | --- | --- |
| FRD-01 | Implement rule engine with DSL and caching | High |
| FRD-02 | Integrate TorchServe model inference with timeout + fallback | High |
| FRD-03 | Build feature store ingestion pipeline (Flink + Iceberg) | High |
| FRD-04 | Create manual review dashboard (Grafana + annotations) | Medium |
| FRD-05 | Add adaptive learning pipeline (online training) | Low |

## 10. Risks
- **False positives** gây ảnh hưởng doanh thu: thiết lập threshold multi-tier, human review.
- **Model drift**: monitor drift metrics, auto-retrain, alert.
- **Latency**: fallback sang rule-only mode nếu ML inference > 200ms.
