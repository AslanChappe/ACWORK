#!/bin/sh
set -e

# Run Alembic migrations before starting (idempotent — safe on all containers)
alembic upgrade head

# Dispatch: uvicorn gets WEB_CONCURRENCY, anything else (celery) passes through
case "$1" in
    uvicorn)
        exec uvicorn app.main:app \
            --host 0.0.0.0 \
            --port 8000 \
            --workers "${WEB_CONCURRENCY:-4}"
        ;;
    *)
        exec "$@"
        ;;
esac
