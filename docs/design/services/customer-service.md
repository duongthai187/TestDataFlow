# Customer Service Blueprint

## 1. Domain Scope
- Quản lý hồ sơ khách hàng, preferences, loyalty status, địa chỉ giao hàng.
- Là nguồn dữ liệu chuẩn cho segment marketing và customer 360.
- Đảm bảo tuân thủ GDPR (quyền truy cập/xóa dữ liệu).

## 2. Data Model (PostgreSQL + Redis)
- `customer_profiles` (tài liệu tổng).
- `customer_addresses`:
  ```sql
  CREATE TABLE customer_addresses (
    address_id BIGSERIAL PRIMARY KEY,
    customer_id BIGINT NOT NULL REFERENCES customer_profiles(customer_id),
    type VARCHAR(16) NOT NULL,
    line1 TEXT NOT NULL,
    line2 TEXT,
    city VARCHAR(64) NOT NULL,
    state VARCHAR(64),
    postal_code VARCHAR(16),
    country_code CHAR(2) NOT NULL,
    is_default BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL
  );
  ```
- `customer_segments`:
  ```sql
  CREATE TABLE customer_segments (
    customer_id BIGINT NOT NULL,
    segment_code VARCHAR(32) NOT NULL,
    assigned_at TIMESTAMPTZ NOT NULL,
    score NUMERIC(5,2),
    PRIMARY KEY (customer_id, segment_code)
  );
  ```
- Redis: cache customer profile + segments (key `customer::{id}`). TTL 5 phút.

## 3. API Endpoints
```python
@router.post("/customers", response_model=CustomerResponse)
async def create_customer(payload: CustomerCreate): ...

@router.get("/customers/{customer_id}", response_model=CustomerResponse)
async def get_customer(customer_id: int): ...

@router.put("/customers/{customer_id}", response_model=CustomerResponse)
async def update_customer(customer_id: int, payload: CustomerUpdate): ...

@router.post("/customers/{customer_id}/addresses", response_model=AddressResponse)
async def add_address(customer_id: int, payload: AddressCreate): ...

@router.post("/customers/{customer_id}/segments", response_model=SegmentAssignResponse)
async def assign_segment(customer_id: int, payload: SegmentAssign): ...
```
- GDPR endpoints: `/customers/{customer_id}/erasure` (async job to anonymize data).
- Background tasks for marketing sync.

## 4. Event Contracts
- Outgoing events:
  - `customer.updated.v1`: include changed fields.
  - `customer.segment.recalculated.v1`: triggered by marketing pipeline.
- Incoming events:
  - `order.created.v1`: update last_order_at, order_count.
  - `support.case.closed.v1`: adjust satisfaction score.
- Schema contains PII → ensure encryption or restricted topics.

## 5. Integrations
- Marketing analytics: writes to Iceberg `customer_profile` table; segmentation job updates `customer_segments`.
- Authentication service: pulls basic profile data for login.
- Consent management: store marketing opt-in/out changes (subject to audit).

## 6. Observability
- Metrics: `customer_profile_updates`, `segment_assign_latency_seconds`.
- Logging: PII safe (use hashed emails when logging).
- Tracing: propagate `customer_id` in traces; monitor cache hit rate.

## 7. Testing
- Unit: validation rules (email format, locale codes), GDPR flows.
- Integration: Redis caching, Postgres queries, event publishing.
- Contract: Avro schema compatibility, ensure sensitive fields flagged.

## 8. Backlog
| Task | Description | Priority |
| --- | --- | --- |
| CU-01 | Implement GDPR erasure workflow | High |
| CU-02 | Add Redis caching with invalidation on update | High |
| CU-03 | Integrate with segmentation pipeline (Kafka consumer) | High |
| CU-04 | Build audit trail for consent changes | Medium |
| CU-05 | Provide GraphQL endpoint for customer portal | Low |

## 9. Risks
- **PII exposure**: enforce data masking, encryption, role-based access.
- **Cache inconsistency**: implement pub/sub invalidation or use Redis streams.
- **Compliance**: keep erasure logs, meet regulatory SLAs.
