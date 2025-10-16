# Review Service Blueprint

## 1. Domain Scope
- Thu thập và quản lý đánh giá sản phẩm từ khách hàng (star rating, nội dung, media).
- Hỗ trợ moderation (tự động + thủ công), phân tích cảm xúc để feed vào recommendation & marketing.
- Đảm bảo tuân thủ GDPR (quyền xóa dữ liệu), chống spam, phân vùng theo khu vực.

## 2. Data Model (CouchDB + PostgreSQL + MinIO)
- CouchDB làm primary store cho review documents (multi-region replication):
  ```json
  {
    "_id": "review::SKU123::customer98765",
    "type": "review",
    "sku": "SKU123",
    "customer_id": 98765,
    "tenant_region": "asia",
    "rating": 4,
    "title": "Tốt",
    "body": "Pin khỏe, màn hình đẹp",
    "media": ["s3://reviews/SKU123/img1.jpg"],
    "status": "PUBLISHED",
    "moderation_flags": ["manual_pending"],
    "created_at": "2025-10-15T11:20:00Z",
    "updated_at": "2025-10-16T08:10:00Z"
  }
  ```
- PostgreSQL analytical table (optional) `review_summary` for aggregated stats (avg rating, sentiment) to support SQL queries.
- MinIO bucket `reviews-media/` lưu ảnh/video review; integrate with moderation pipeline (Vision API or custom).

## 3. API Endpoints (FastAPI)
```python
@router.post("/reviews", response_model=ReviewResponse)
async def submit_review(payload: ReviewCreate):
    ...

@router.get("/reviews/{sku}", response_model=ReviewListResponse)
async def list_reviews(sku: str, query: ReviewQuery = Depends()):
    ...

@router.get("/reviews/customers/{customer_id}", response_model=ReviewListResponse)
async def list_customer_reviews(customer_id: int):
    ...

@router.put("/reviews/{review_id}", response_model=ReviewResponse)
async def update_review(review_id: str, payload: ReviewUpdate):
    ...

@router.post("/reviews/{review_id}/moderate", response_model=ReviewResponse)
async def moderate_review(review_id: str, payload: ModerationDecision):
    ...
```
- Bulk moderation endpoint for ops team; support GraphQL query for storefront (filter by rating, region).
- Rate limiting (per customer, per SKU) via Redis to prevent spam.

## 4. Event Contracts
- Outgoing (Kafka):
  - `review.submitted.v1`: includes `review_id`, `sku`, `rating`, `customer_id`, `tenant_region`, `status`.
  - `review.moderated.v1`: moderation decision, reasons.
  - `review.deleted.v1`: for GDPR erasure, remove from downstream caches.
- Incoming:
  - `order.fulfilled.v1`: trigger review invitation workflow (Notification-service).
  - `fraud.blacklist.updated.v1`: mark suspicious customers for moderation priority.
  - `product.updated.v1`: update localized metadata for display.

## 5. Integrations
- **Recommendation-service**: consume `review.submitted` events to enrich user/item embeddings & sentiment features.
- **Marketing automation**: send high rating reviews to email campaigns; detect churn risk from low ratings.
- **Agent-service (Phase 3)**: support agent queries reviews via LangChain tool.
- **Moderation pipeline**: integrate with third-party AI (Perspective API) or custom model served via Ray; asynchronous job writes result to CouchDB doc.

## 6. Observability
- Metrics: `reviews_submitted_total`, `reviews_auto_approved_ratio`, `review_moderation_latency_seconds`, `review_spam_detected_total`.
- Logging: store `review_id`, `moderation_status`; mask PII (customer name/email).
- Tracing: include `review_id`, `sku`, `tenant_region` for request context.
- Alerts: spike in spam detection, high moderation backlog, CouchDB replication lag.

## 7. Testing
- Unit: validation (rating range, banned words), moderation decision flow.
- Integration: CouchDB replication (multi-region), MinIO upload, moderation model API.
- Contract: Avro schema compatibility for events; ensure GDPR deletion triggers aggregator updates.
- Load: high-volume review imports (post-campaign) ensuring CouchDB change feed keeps up.

## 8. Backlog
| Task | Description | Priority |
| --- | --- | --- |
| REV-01 | Implement submission API with spam/rate limits | High |
| REV-02 | Build moderation pipeline (auto + manual queue) | High |
| REV-03 | Sync aggregated stats to PostgreSQL/Trino | Medium |
| REV-04 | Integrate review invitations via Notification-service | Medium |
| REV-05 | Support multi-language sentiment analysis | Low |

## 9. Risks
- **Spam/abuse**: implement CAPTCHA, heuristic & ML detection, banlist integration.
- **Replication delay**: monitor CouchDB `_replicator` jobs; fallback to eventual consistency messaging.
- **PII compliance**: ensure deletion replicates to all downstream stores (MinIO objects, aggregated tables).
