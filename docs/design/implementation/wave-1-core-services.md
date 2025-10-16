# Wave 1 – Core Service Implementation Plan

## 1. Objectives
- Xây dựng 4 dịch vụ nền tảng: `customer-service`, `catalog-service`, `pricing-service`, `cart-service` với chức năng tối thiểu nhưng phản ánh vấn đề thực tế (schema drift, cache TTL, segmentation, price rules).
- Thiết lập contract API (OpenAPI) và event schemas cho các service này.
- Tạo data seed & scenario scripts để chuẩn bị cho các wave sau.

## 2. Scope & Deliverables
| Service | Deliverables |
| --- | --- |
| customer-service | CRUD hồ sơ khách hàng, segment assignment, Redis cache, Avro events `customer.updated`, `customer.segment.recalculated`. |
| catalog-service | CouchDB integration, GraphQL API, media placeholder, change feed emitter `catalog.product.updated`. |
| pricing-service | Rule evaluation engine (baseline), currency rate sync stub, events `pricing.updated`, offline storage `price_rules`. |
| cart-service | Session/cart persistence (MySQL + Redis), integrations with pricing, events `cart.item.added`, `cart.checkedout`, TTL handling. |

Common deliverables: migration scripts, OpenAPI specs, unit/integration tests, observability instrumentation, seed scripts.

## 3. Implementation Breakdown
### 3.1 Customer Service
- **Data Layer**: SQLAlchemy models (`customer_profiles`, `customer_addresses`, `customer_segments`). Alembic migration.
- **API**:
  - `POST /customers`
  - `GET /customers/{id}`
  - `PUT /customers/{id}`
  - `POST /customers/{id}/segments`
  - `POST /customers/{id}/erasure` (simulate GDPR request, queue job).
- **Cache**: Redis key `customer::{id}` storing JSON snapshot; invalidation on update.
- **Events**: use `aiokafka` or `confluent-kafka` producer to publish to Kafka.
- **Observability**: metrics `customer_create_total`, `customer_update_latency_seconds`.
- **Testing**: unit tests for validators, integration test hitting API with test DB & Redis.

### 3.2 Catalog Service
- **Data Layer**: couchdb driver (python-cloudant) or direct HTTP; PostgreSQL optional for taxonomy. Migration for taxonomy tables.
- **API**:
  - REST `/products` CRUD.
  - GraphQL endpoint `/graphql` using Strawberry (schema definitions for product, variant, category).
  - Media stub upload to MinIO (signed URL or direct upload to local file). Provide asynchronous processing stub.
- **Events**: On create/update, publish `catalog.product.updated.v1` with diff.
- **Change feed**: background worker reading CouchDB `_changes` to push to Kafka (simulate asynchronous replication). Configurable to simulate schema drift.
- **Testing**: unit tests for GraphQL resolvers, integration test with CouchDB container.

### 3.3 Pricing Service
- **Data Layer**: SQLAlchemy models for `price_books`, `price_rules`, `promotion_campaigns`, `currency_rates`. Alembic migrations.
- **Rule Engine**: start with simple evaluation (apply priority order, conditions on segment/region). Later extend to AST engine.
- **API**:
  - `GET /pricing/{sku}` (with query params `customerSegment`, `currency`).
  - `POST /pricing/rules` (upsert rule).
  - `POST /promotions` (create promotion).
  - `POST /pricing/{sku}/simulate` (scenario testing).
- **Background Tasks**: `currency_rate_sync` (fake provider) update `currency_rates` table.
- **Events**: `pricing.updated.v1`, `promotion.activated.v1`, `fx.rate.changed.v1`.
- **Testing**: unit tests for rule evaluation (various conditions), integration tests verifying API + DB state.

### 3.4 Cart Service
- **Data Layer**: MySQL tables `carts`, `cart_items`, `cart_events` (with Alembic migrations). Redis for caching.
- **API**:
  - `POST /carts`
  - `GET /carts/{id}` + `GET /carts/by-session/{token}`
  - `POST /carts/{id}/items`
  - `PUT /carts/{id}/items/{sku}`
  - `DELETE /carts/{id}/items/{sku}`
  - `POST /carts/{id}/apply-coupon`
  - `POST /carts/{id}/checkout`
- **Integrations**:
  - Call Pricing API when adding items.
  - Publish events to Kafka.
  - Manage TTL (MySQL `expires_at`, Redis TTL).
- **Testing**: integration tests with MySQL + Redis, concurrency tests (optimistic locking).

## 4. Cross-Cutting Concerns
- **Common Library Enhancements**: add Kafka producer wrapper, DB session management, redis helper, event schema registry load (mock). Provide `@instrument_route` decorator for metrics.
- **Outbox Pattern**: implement optional outbox for reliability (persist event in DB, background worker flush to Kafka). Introduce for pricing/cart as example.
- **OpenAPI/AsyncAPI**: generate with FastAPI + `datamodel-code-generator`. Store schema files under `docs/api/`.
- **Config Management**: Pydantic settings reading `.env`, fallback to docker env variables.
- **Logging**: JSON structured logging with correlation ID; integrate with Loki pipeline.

## 5. Data & Scenario Preparation
- Seed script `scripts/seed/wave1_seed.py`:
  - Create 1k customers with segmentation (VIP, general).
  - Import sample catalog items with attributes.
  - Generate price rules for key SKUs (region/channel combos).
  - Populate carts with random items for scenario testing.
- Scenario script `scripts/scenarios/schema_drift_catalog.py` to add new fields to CouchDB doc to mimic drift.

## 6. Testing & Quality Gates
- CI updates to include service-specific unit tests (target 70% coverage for new modules).
- Contract tests verifying responses conform to OpenAPI spec (use `schemathesis`).
- Event schema validation tests (Avro) to ensure producers emit expected fields.
- Pre-commit hook extended to run tests for modified services only (optional).

## 7. Timeline & Dependencies
| Week | Focus | Dependencies |
| --- | --- | --- |
| Week 2 (start) | Customer + Catalog service core CRUD | Wave 0 done |
| Week 2 (mid) | Pricing service + integration with catalog | Customer segmentation available |
| Week 3 | Cart service + integration with pricing & events | Pricing API ready |
| Week 3 (late) | Seed data & scenario scripts, final tests | All services implemented |

## 8. Risks & Mitigation
- **Complex CouchDB change feed**: start with simple delta; plan to improve resilience later.
- **Rule engine complexity**: keep initial engine simple; plan backlog items for AST caching.
- **Redis cache coherence**: use version numbers per cart, publish invalidation events.
- **OpenAPI drift**: enforce generated schema in CI (fail if not matched).

## 9. Exit Criteria
- Four services running with basic functionality, passing tests.
- API docs published and event schemas cataloged.
- Seed scripts produce baseline dataset accessible via APIs.
- Issues (schema drift, TTL) reproducible via scenario scripts.

## 10. Next Steps
- After Wave 1, proceed to Wave 2 plan focusing on Order-Payment-Inventory transactional flows (
  ensure sagas/outbox implemented).
- Start aligning Debezium connectors for these services in preparation for CDC in Wave 2.
