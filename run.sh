#!/usr/bin/env bash
# Run Recall in development mode.
set -e

if [ ! -f ".env" ]; then
  echo "No .env file found. Copying .env.example -> .env"
  cp .env.example .env
fi

exec uvicorn app.main:app --reload --host 0.0.0.0 --port "${PORT:-8000}"
