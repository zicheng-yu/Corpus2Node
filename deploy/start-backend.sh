#!/bin/sh
set -eu

uv run alembic upgrade head
exec uv run uvicorn corpus2node.api.app:app --host 0.0.0.0 --port 8000
