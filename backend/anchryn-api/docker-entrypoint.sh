#!/bin/sh
# Apply migrations, then serve.
#
# Running them here rather than by hand means a deploy can never serve traffic
# against a schema it does not match. `set -e` stops the container if a
# migration fails, so a broken deploy fails loudly instead of running with the
# wrong tables.
set -e

echo "Applying database migrations..."
alembic upgrade head

# Render (and most platforms) inject PORT. Binding 0.0.0.0 is required for the
# platform's health check to reach the container.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
