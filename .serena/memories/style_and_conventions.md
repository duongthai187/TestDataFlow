# Style & Conventions
- Python 3.11, strict type checking via mypy; all new code must be fully typed.
- Formatting with Black (line length 100) and Ruff; follow Ruff lint rules, prefer async/await patterns for FastAPI + SQLAlchemy.
- Services expose FastAPI apps with dependency-injected async session factories; use pydantic v2 models for request/response schemas.
- Tests use pytest with asyncio (HTTPX AsyncClient); keep tests deterministic and cover full service lifecycle.
- Prefer UTC-aware datetimes serialized with ISO8601; monetary values handled as integers (cents) where applicable.
- Config via pydantic-settings and `.env`; keep environment keys prefixed per service.
