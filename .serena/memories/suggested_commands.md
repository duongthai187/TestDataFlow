# Suggested Commands
- `poetry install --no-root --with dev` – install dependencies including dev tooling.
- `poetry run pre-commit install` – enable local linters/hooks.
- `make fmt` / `make fmt-check` – auto-format / verify with Black + Ruff.
- `make lint` – run mypy (strict) and Ruff lint checks.
- `make test` or `poetry run pytest` – execute full pytest suite across services.
- `make run-service SERVICE=<service_name>` – start a FastAPI service via Uvicorn locally.
- `docker compose up -d` / `docker compose down` – launch or stop infrastructure stack.
- `docker compose logs <service>` – tail logs for a specific container; `docker compose ps` for status.
