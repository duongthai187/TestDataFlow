# TestDataFlow Microservices Platform
- FastAPI-based ecommerce microservices mono-repo (Wave 0/1) for the DataFlow program.
- Provides full stack for domain services (catalog, pricing, cart, order, payment, inventory, notification, etc.) plus shared common libs.
- Supports realtime + lakehouse data infrastructure orchestrated via Docker Compose (Kafka, Flink, Trino, MinIO, Cassandra, etc.).
- Documentation in `docs/` details architecture, components, operations, and monitoring strategy.
- Primary goal: implement transactional services with async SQLAlchemy persistence, Kafka integration stubs, and comprehensive API tests.
