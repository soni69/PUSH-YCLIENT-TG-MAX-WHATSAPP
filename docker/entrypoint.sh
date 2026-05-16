#!/bin/sh
# ============================================================
#  docker/entrypoint.sh
#  Runs Alembic migrations before starting the main process.
#  Exits with code 1 if migrations fail so Docker restarts
#  the container rather than running a broken application.
# ============================================================

set -e

echo "[entrypoint] Starting yclients-notification-bot..."

# ── Wait for PostgreSQL to be ready ──────────────────────────────────────────
# Simple retry loop — avoids a hard dependency on wait-for-it.sh
MAX_RETRIES=30
RETRY_INTERVAL=2
attempt=0

echo "[entrypoint] Waiting for PostgreSQL at ${DATABASE_URL}..."
until python -c "
import asyncio, asyncpg, os, sys
async def check():
    try:
        conn = await asyncpg.connect(os.environ['DATABASE_URL'].replace('postgresql+asyncpg://', 'postgresql://'))
        await conn.close()
    except Exception as e:
        sys.exit(1)
asyncio.run(check())
" 2>/dev/null; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge "$MAX_RETRIES" ]; then
        echo "[entrypoint] ERROR: PostgreSQL is not available after ${MAX_RETRIES} attempts. Exiting."
        exit 1
    fi
    echo "[entrypoint] PostgreSQL not ready yet (attempt ${attempt}/${MAX_RETRIES}). Retrying in ${RETRY_INTERVAL}s..."
    sleep "$RETRY_INTERVAL"
done

echo "[entrypoint] PostgreSQL is ready."

# ── Run Alembic migrations ────────────────────────────────────────────────────
echo "[entrypoint] Running database migrations..."
alembic upgrade head

if [ $? -ne 0 ]; then
    echo "[entrypoint] ERROR: Alembic migrations failed. Exiting."
    exit 1
fi

echo "[entrypoint] Migrations completed successfully."

# ── Start the main process ────────────────────────────────────────────────────
echo "[entrypoint] Starting application: $*"
exec "$@"
