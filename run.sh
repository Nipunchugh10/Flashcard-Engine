#!/usr/bin/env bash
# Run Recall in development mode.
set -e

if [ ! -f ".env" ]; then
  echo "No .env file found. Copying .env.example -> .env"
  cp .env.example .env
fi

# Prefer the venv Python if it exists; fall back to whatever is on PATH.
PYTHON=".venv311/Scripts/python"
if [ ! -f "$PYTHON" ]; then
  PYTHON="python"
fi

exec "$PYTHON" -m uvicorn app.main:app --reload --host 0.0.0.0 --port "${PORT:-8000}"
