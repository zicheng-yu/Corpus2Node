#!/bin/sh
set -eu

.venv/bin/alembic upgrade head
exec .venv/bin/uvicorn corpus2node.api.app:app --host 0.0.0.0 --port 8000
