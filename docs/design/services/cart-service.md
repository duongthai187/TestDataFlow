# Cart Service Blueprint

## 1. Domain Scope
- Quản lý giỏ hàng realtime đa thiết bị, cho phép lưu trữ session tạm (anonymous) và khách hàng đăng nhập.
- Đảm bảo đồng bộ số lượng hàng với inventory-service (soft reservation) và pricing-service (price snapshot).
- Hỗ trợ chiến dịch marketing (coupon, cross-sell), kiểm soát TTL để tránh oversell.

## 2. Data Model (MySQL + Redis)
- MySQL schema (transactional persistence):
  ```sql
  CREATE TABLE carts (
    cart_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    customer_id BIGINT,
    session_token CHAR(36) UNIQUE NOT NULL,
    currency_code CHAR(3) NOT NULL,
    channel VARCHAR(16) NOT NULL,
    tenant_region VARCHAR(8) NOT NULL,
    status ENUM('ACTIVE','CHECKED_OUT','ABANDONED') DEFAULT 'ACTIVE',
    expires_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
  );

  CREATE TABLE cart_items (
    cart_item_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    cart_id BIGINT NOT NULL,
    sku VARCHAR(64) NOT NULL,
    quantity INT NOT NULL,
    unit_price DECIMAL(12,2) NOT NULL,
    discount_amount DECIMAL(12,2) DEFAULT 0,
    promotion_codes JSON,
    added_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    UNIQUE KEY uk_cart_sku (cart_id, sku),
    CONSTRAINT fk_cart_items_cart FOREIGN KEY (cart_id) REFERENCES carts(cart_id) ON DELETE CASCADE
  );

  CREATE TABLE cart_events (
    event_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    cart_id BIGINT NOT NULL,
    event_type VARCHAR(32) NOT NULL,
    payload JSON,
    created_at DATETIME NOT NULL
  );
  ```
- Redis cache (cluster) giữ snapshot `cart::{session_token}` (JSON) để trả lời nhanh, TTL 30 phút; invalidation khi update MySQL.
- Use Redis streams `cart_events` để emit realtime update cho marketing/inventory.

## 3. API Endpoints (FastAPI)
```python
@router.post("/carts", response_model=CartResponse)
async def create_cart(payload: CartCreate):
    ...

@router.get("/carts/{cart_id}", response_model=CartResponse)
async def get_cart(cart_id: int):
    ...

@router.post("/carts/{cart_id}/items", response_model=CartItemResponse)
async def add_item(cart_id: int, payload: CartItemCreate):
    ...

@router.put("/carts/{cart_id}/items/{sku}", response_model=CartItemResponse)
async def update_item(cart_id: int, sku: str, payload: CartItemUpdate):
    ...

@router.delete("/carts/{cart_id}/items/{sku}", status_code=204)
async def remove_item(cart_id: int, sku: str):
    ...

@router.post("/carts/{cart_id}/apply-coupon", response_model=CartResponse)
async def apply_coupon(cart_id: int, payload: CouponApplyRequest):
    ...
```
- Webhook `/carts/{cart_id}/checkout` triggered by checkout orchestrator (calls order-service) to mark cart `CHECKED_OUT`.
- Background task purge expired carts, log abandon events.

## 4. Event Contracts
- Outgoing events (Kafka + Avro):
  - `cart.item.added.v1`: `cart_id`, `customer_id`, `sku`, `quantity`, `price`, `tenant_region`.
  - `cart.item.removed.v1`.
  - `cart.checkedout.v1`: includes `order_id` placeholder or `checkout_token`.
  - `cart.abandoned.v1`: triggered when cart expires without checkout.
- Incoming events:
  - `inventory.stock.reserved.v1`: adjust availability/reservation; maybe add backorder notification.
  - `pricing.updated.v1`: refresh item price snapshot.
  - `promotion.campaign.updated.v1`: update eligibility caches.

## 5. Integrations
- **Inventory-service**: when adding item, call `/inventory/reserve` (soft hold) and release if removal/expire.
- **Pricing-service**: synchronous call to get latest price + promotions; store snapshot in cart item.
- **Recommendation-service**: consume `cart.item.added` for cross-sell suggestions.
- **Notification-service**: trigger `cart.abandoned` campaigns.
- **Analytics**: Debezium CDC feed -> Kafka for customer behavior analytics.

## 6. Observability
- Metrics: `cart_active_total`, `cart_add_item_latency_seconds`, `cart_checkout_conversion_rate`, `cart_abandonment_rate`.
- Logging: include `cart_id`, `customer_id`, `tenant_region`; mask coupon codes.
- Tracing: propagate `session_token`, correlate with checkout/order traces.
- Alerts: high abandonment, failure to reserve inventory, Redis lag.

## 7. Testing
- Unit: pricing recalculations, coupon stacking, TTL handling.
- Integration: MySQL + Redis consistency, inventory reservation contract tests.
- Contract: Avro schema regression for events; AsyncAPI tests.
- Load: simulate flash sale (5k add-to-cart/min) ensure TTL/reservation logic holds.

## 8. Backlog
| Task | Description | Priority |
| --- | --- | --- |
| CART-01 | Implement cart cache with Redis + invalidation hooks | High |
| CART-02 | Integrate inventory soft reservation API | High |
| CART-03 | Build coupon engine (stacking, exclusions) | Medium |
| CART-04 | Implement cart abandonment job + notification trigger | Medium |
| CART-05 | Add real-time analytics pipeline for cart events | Low |

## 9. Risks
- **Oversell**: ensure reservation release flows cover all paths (failure, timeout); double-check TTL with inventory.
- **Cache inconsistency**: implement optimistic locking, version numbers for cart updates.
- **Promotion abuse**: add rate-limiting + eligibility checks in coupon validation.
