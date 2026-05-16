# ============================================================
#  Multi-stage Dockerfile for yclients-notification-bot
#  Stage 1 (builder) — install dependencies into a venv
#  Stage 2 (production) — copy only the venv + app source
# ============================================================

# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Install system build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        gcc \
    && rm -rf /var/lib/apt/lists/*

# Create an isolated virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies first (layer-cached unless requirements change)
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt


# ── Stage 2: production ───────────────────────────────────────────────────────
FROM python:3.11-slim AS production

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# Install only runtime system libraries (no build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user for security
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser

WORKDIR /app

# Copy the virtual environment from the builder stage
COPY --from=builder /opt/venv /opt/venv

# Copy application source code
COPY --chown=appuser:appgroup app/ ./app/
COPY --chown=appuser:appgroup migrations/ ./migrations/
COPY --chown=appuser:appgroup alembic.ini ./alembic.ini
COPY --chown=appuser:appgroup docker/entrypoint.sh ./entrypoint.sh

# Make entrypoint executable
RUN chmod +x ./entrypoint.sh

# Switch to non-root user
USER appuser

# Expose the FastAPI port
EXPOSE 8000

# Health check — calls the /health endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["./entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
