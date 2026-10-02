#!/bin/sh
set -eu
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi
PYTHON_BIN=${PYTHON_BIN:-python3}
if [ -x .venv/bin/python3 ]; then
  PYTHON_BIN=.venv/bin/python3
fi
exec "$PYTHON_BIN" app.py
