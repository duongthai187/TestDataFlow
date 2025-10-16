# Pricing Service Blueprint

## 1. Domain Scope
- Quản lý price book, discount rules, promo campaign và currency conversion cho toàn bộ kênh.
- Cung cấp giá realtime cho order-service, storefront và recommendation engine.
- Hỗ trợ A/B testing giá, promotions theo segment, region, device.

## 2. Data Model (PostgreSQL + Redis + MinIO)
- PostgreSQL schema tách riêng `price_books`, `price_rules`, `promotion_campaigns`, `currency_rates`.
- `price_rules`:
  ```sql
  CREATE TABLE price_rules (
    rule_id UUID PRIMARY KEY,
    sku VARCHAR(64) NOT NULL,
    price_book_id UUID NOT NULL REFERENCES price_books(price_book_id),
    base_price NUMERIC(12,2) NOT NULL,
    min_price NUMERIC(12,2),
    max_price NUMERIC(12,2),
    effective_from TIMESTAMPTZ NOT NULL,
    effective_to TIMESTAMPTZ,
    conditions JSONB,
    priority SMALLINT NOT NULL DEFAULT 10,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
  );
  ```
- `promotion_campaigns` chứa mức giảm, loại trigger (coupon, segment, cart value) và metadata (GDPR safe).
- `currency_rates` cập nhật 30 phút/lần từ provider FX.
- Redis cluster cache key `price::{sku}::{customer_segment}` TTL 2 phút + pub/sub invalidation.
- MinIO: lưu cấu hình A/B test và ML feature dumps.

## 3. API Endpoints
```python
@router.get("/pricing/{sku}", response_model=PriceQuote)
async def get_price_quote(sku: str, customer_segment: str = Query("general"), currency: str = Query("USD")):
    ...

@router.post("/pricing/rules", response_model=PriceRuleResponse)
async def upsert_price_rule(payload: PriceRuleUpsert):
    ...

@router.post("/promotions", response_model=PromotionResponse)
async def create_promotion(payload: PromotionCreate):
    ...

@router.post("/pricing/{sku}/simulate", response_model=PriceSimulationResponse)
async def simulate_price(sku: str, scenario: PriceSimulationRequest):
    ...
```
- Admin endpoints bảo vệ bởi RBAC + throttling.
- Background task đồng bộ currency rates và publish event khi cập nhật.

## 4. Event Contracts
- Outgoing:
  - `pricing.updated.v1`: gửi khi price rule thay đổi; payload gồm `sku`, `price_book_id`, `base_price`, `segment_targets`, `effective_from`.
  - `promotion.activated.v1`: broadcast tới marketing, storefront.
  - `fx.rate.changed.v1`: cho checkout-service, finance.
- Incoming:
  - `catalog.sku.updated.v1`: refresh price rule mapping, disable orphan rule.
  - `order.completed.v1`: feed demand data cho dynamic pricing engine.
  - `marketing.segment.updated.v1`: align promotion targeting.
- Sử dụng Avro + Schema Registry; maintain backwards compatibility với version bump (v2 khi thêm field).

## 5. Integrations
- Connect ML pricing engine (Spark job) ghi kết quả vào `price_rules` qua REST batch endpoint.
- Debezium capture `price_rules` → Flink stream cập nhật cache của storefront.
- Order service gọi `/pricing/{sku}` trước khi tạo line item để lock price snapshot.
- Finance warehouse lấy dữ liệu từ Iceberg `pricing_rules` và `promotion_redemptions`.

## 6. Observability
- Metrics: `price_quote_latency_seconds`, `price_cache_hit_ratio`, `promotion_activation_total`.
- Logging: ghi rule_id, sku, segment; ẩn thông tin chiến lược nhạy cảm trong log debug.
- Tracing: annotate spans với `pricing_strategy` để dễ debug pipeline.
- Alerts: cảnh báo nếu FX rate không cập nhật > 1 giờ hoặc cache miss > 40%.

## 7. Testing
- Unit: điều kiện rule evaluation, stackable promotions, currency conversion rounding.
- Property-based tests: fuzz combinations segments + channel + coupons.
- Integration: kiểm tra sync với Redis cache, verify Debezium CDC record integrity.
- Performance: benchmark 2k price quotes/giây, SLA < 50ms P95.

## 8. Backlog
| Task | Description | Priority |
| --- | --- | --- |
| PRC-01 | Implement rule evaluation engine với AST + caching | High |
| PRC-02 | Build synchronous currency rate updater + retries | High |
| PRC-03 | Expose bulk import endpoint cho price book | Medium |
| PRC-04 | Add promotion analytics dashboard (Grafana) | Medium |
| PRC-05 | Support real-time A/B test assignment API | Low |

## 9. Risks
- **Race condition** khi nhiều rule cùng cập nhật: sử dụng advisory locks + versioning.
- **Cache stale** dẫn tới mismatch giá: implement pub/sub invalidation, add circuit breaker fallback trực tiếp DB.
- **Regulatory/Compliance** với giá: log audit khi thay đổi price book, enforce approval workflow.
