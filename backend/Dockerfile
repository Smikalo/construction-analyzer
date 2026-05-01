FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# System deps:
#  - git + build-essential: clone & install MemoryPalace from GitHub
#  - curl: container HEALTHCHECK
#  - libpq-dev: psycopg / asyncpg compile fallback
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        build-essential \
        curl \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ---- Python dependencies (cached layer) ----
COPY pyproject.toml ./
RUN pip install --upgrade pip \
    && pip install -e ".[dev]"

# MemoryPalace is not on PyPI; install directly from the upstream repo.
# Pinned to main; bump when the upstream API changes.
RUN pip install "git+https://github.com/jeffpierce/memory-palace.git@main#egg=memory_palace" \
    || echo "memory_palace install failed (continuing; KB falls back to fake)"

# ---- App source ----
COPY app ./app
COPY tests ./tests

# Data directory (mounted from host or used by docker volume).
RUN mkdir -p /app/data/documents

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=10 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
