# Catalog Service Blueprint

## 1. Domain Scope
- Quản lý toàn bộ product catalog: thông tin sản phẩm, thuộc tính, media, taxonomy, availability.
- Cung cấp API thống nhất cho storefront, search, merchandising.
- Đồng bộ thông tin với inventory-service, pricing-service và recommendation pipeline.

## 2. Data Model (CouchDB + PostgreSQL + MinIO)
- CouchDB lưu `products` (document per SKU) chứa metadata, descriptions đa ngôn ngữ, attribute map.
- PostgreSQL giữ các bảng quan hệ:
  - `product_taxonomy` (category tree, breadcrumbs).
  - `product_relations` (up-sell, cross-sell, bundle).
  - `product_channels` (visibility per region, channel).
- MinIO lưu media assets (images, videos) theo path `catalog/{sku}/{variant}/{size}.jpg`.
- Elasticsearch index (optional) cho faceted search.

## 3. API Endpoints (FastAPI)
```python
@router.post("/products", response_model=ProductResponse)
async def create_product(payload: ProductCreate):
    ...

@router.get("/products/{sku}", response_model=ProductResponse)
async def get_product(sku: str, locale: str = Query("vi-VN")):
    ...

@router.patch("/products/{sku}", response_model=ProductResponse)
async def update_product(sku: str, payload: ProductPatch):
    ...

@router.get("/products", response_model=ProductList)
async def list_products(filter: ProductFilter = Depends(), page: Page = Depends()):
    ...

@router.post("/products/{sku}/media", response_model=MediaUploadResponse)
async def upload_media(sku: str, payload: MediaUploadRequest):
    ...
```
- GraphQL endpoint cho storefront (batched queries, variant selection).
- Async job xử lý media (image resizing, webp conversion) qua Celery/MinIO triggers.

## 4. Event Contracts
- Outgoing:
  - `catalog.product.created.v1`: payload gồm `sku`, `title`, `category_ids`, `attributes`, `status`.
  - `catalog.product.updated.v1`: diff field changes, version number.
  - `catalog.media.updated.v1`: notify CDN, marketing.
- Incoming:
  - `inventory.stock.changed.v1`: update availability flag.
  - `pricing.updated.v1`: update `price_snapshot` trong doc.
  - `fraud.blacklist.updated.v1`: optionally hide SKUs liên quan.
- Debezium cho CouchDB sử dụng connector (CouchDB → Kafka) hoặc custom change feed reader.

## 5. Integrations
- Search service (OpenSearch) ingest events để reindex.
- Recommendation pipeline đọc `catalog.product.*` events để update feature store.
- Content management (CMS) push localized content qua API.
- Export nightly snapshot sang Iceberg `catalog_products` cho BI.

## 6. Observability
- Metrics: `catalog_update_latency_seconds`, `media_processing_failures_total`, `couchdb_replication_lag_seconds`.
- Logging: track `sku`, `locale`, `change_set_size`.
- Tracing: include `catalog_version` tag; monitor Celery tasks.
- Alert: notify khi replication lag > 60s hoặc CouchDB 500 errors > 1%.

## 7. Testing
- Unit: validation cho attributes, category tree integrity.
- Contract: GraphQL schema tests, REST OpenAPI schema.
- Integration: CouchDB change feed → Kafka pipeline, media upload to MinIO.
- Performance: list API pagination, concurrency 1k req/s caches via Redis.

## 8. Backlog
| Task | Description | Priority |
| --- | --- | --- |
| CTL-01 | Implement CouchDB change feed consumer + Kafka producer | High |
| CTL-02 | Build GraphQL gateway with Federation support | High |
| CTL-03 | Add media processing pipeline (image resizing, CDN push) | High |
| CTL-04 | Implement taxonomy admin UI | Medium |
| CTL-05 | Enable variant-specific A/B testing metadata | Low |

## 9. Risks
- **Replication lag** giữa CouchDB cluster -> stale data: implement continuous replication, monitor.
- **Media storage growth**: design lifecycle policies trên MinIO/S3, dedupe assets.
- **Taxonomy drift**: enforce governance, version categories, provide approval workflow.
