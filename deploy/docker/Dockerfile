# Atlas container image (Sprint 9, ADR-0053).
# Build context is the repo root:  docker build -f deploy/docker/Dockerfile -t atlas .
FROM python:3.12-slim

# pg_dump/pg_restore (backups) + build basics.
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# uv for reproducible, locked installs.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies first (better layer caching), then the app.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev
COPY . .
RUN uv sync --frozen --no-dev

# Bind on all interfaces inside the container (compose maps the port).
ENV ATLAS_API_HOST=0.0.0.0
EXPOSE 8000

CMD ["uv", "run", "atlas", "serve"]
