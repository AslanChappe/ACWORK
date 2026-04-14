# ── Build stage ────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies into an isolated dir
COPY pyproject.toml .
RUN pip install --upgrade pip \
    && pip install --prefix=/install . --no-cache-dir

# ── Runtime stage ──────────────────────────────────────────
FROM python:3.12-slim AS runtime

WORKDIR /app

# Minimal runtime OS packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev wget \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY app/ ./app/
COPY alembic.ini .
COPY alembic/ ./alembic/

# Non-root user for security
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
