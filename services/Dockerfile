FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_HOME=/opt/poetry \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl build-essential && \
    rm -rf /var/lib/apt/lists/*

RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="${POETRY_HOME}/bin:${PATH}"

WORKDIR /app

COPY pyproject.toml ./
RUN poetry install --no-root --with dev

COPY services ./services
ENV PYTHONPATH=/app

ARG SERVICE_MODULE="services.catalog_service.app.main:app"
ENV SERVICE_MODULE=${SERVICE_MODULE}

ENTRYPOINT ["sh", "-c"]
CMD ["poetry run uvicorn ${SERVICE_MODULE} --host 0.0.0.0 --port 8000"]
