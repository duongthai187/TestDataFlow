# Inventory Service Blueprint

## 1. Domain Scope
- Quản lý tồn kho realtime theo SKU, warehouse, region.
- Cung cấp APIs và events cho các dịch vụ khác để hold, adjust, release stock.
- Dựa trên Cassandra cho write throughput cao và TTL reservation.

## 2. Data Model (Cassandra)
- `inventory.stock_level` (đã mô tả): partition `(sku, warehouse_id)`; `iso_week` clustering.
- `inventory.reservation`: TTL 1 giờ; status `HELD`, `CONFIRMED`, `EXPIRED`.
- `inventory.events` (mới):
  ```sql
  CREATE TABLE inventory.events (
    event_id UUID,
    sku TEXT,
    warehouse_id TEXT,
    event_type TEXT,
    quantity INT,
    source TEXT,
    occurred_at TIMESTAMP,
    metadata TEXT,
    PRIMARY KEY ((sku, warehouse_id), occurred_at, event_id)
  ) WITH CLUSTERING ORDER BY (occurred_at DESC);
  ```

## 3. FastAPI Endpoints
```python
@router.post("/inventory/reserve", response_model=ReservationResponse)
async def reserve_stock(payload: ReservationRequest):
    ...

@router.post("/inventory/release")
async def release_stock(payload: ReleaseRequest):
    ...

@router.post("/inventory/adjust")
async def adjust_stock(payload: AdjustRequest):
    ...

@router.get("/inventory/{sku}")
async def get_stock(sku: str, region: Optional[str] = None):
    ...
```
- Use `fastapi_concurrency.run_in_threadpool` để gọi Cassandra driver.
- Bảo vệ concurrency: sử dụng lightweight transactions (LWT) của Cassandra cho reservation (đánh đổi hiệu năng) hoặc rely on Flink aggregator (future).

## 4. Event Contracts
- Outgoing:
  - `inventory.reserved.v1`: { reservation_id, order_id, items[], ttl_expire }
  - `inventory.released.v1`: { reason (`PAYMENT_FAILED`, `TTL_EXPIRED`) }
  - `inventory.adjusted.v1`: { adjustment_type, qty_delta }
- Incoming:
  - `order.created.v1`: attempt reservation automatically.
  - `order.cancelled.v1`: release.
  - `fulfillment.picked.v1`: final deduction (confirm).

## 5. Integrations
- Cassandra cluster per region (NetworkTopologyStrategy). Use DataStax Java driver via async (Python cassandra-driver).
- Expose gRPC streaming (optional) cho warehouse automation.
- Writes events to Kafka using transactional outbox stored in Cassandra? (Not native). Solution: append to `inventory.events`, Debezium Cassandra connector capture and publish.

## 6. Observability
- Metrics: `inventory_reserve_latency_seconds`, `inventory_ttl_expired_total`, `inventory_adjustment_total`.
- Dashboards: trending stock by SKU, reservation success rate.
- Alerts: TTL expiry > threshold, mismatch between reserved vs available.

## 7. Testing Strategy
- Unit tests: request validation, business rules (no negative qty).
- Integration: Cassandra test keyspace, ensure TTL expiration handled (fast-forward by setting TTL=5s in test).
- Contract: Avro schema compatibility for events.

## 8. Backlog
| Task | Description | Priority |
| --- | --- | --- |
| IV-01 | Implement reservation LWT logic | High |
| IV-02 | Create Debezium Cassandra CDC config | High |
| IV-03 | Build global aggregation (Flink) sink back to Cassandra global table | High |
| IV-04 | Implement compensation workflow for TTL expiry (notify order-service) | Medium |
| IV-05 | Add caching layer (Redis) for high-read SKUs | Medium |

## 9. Risks
- **Cassandra hotspots**: SKUs with extremely high contention; mitigate via per-warehouse partition and caching.
- **TTL mismatch**: Need job to monitor reservations close to expiry and alert order-service.
- **CDC delay**: Cassandra connector not real-time; fallback to streaming aggregator to keep marketing view updated.
