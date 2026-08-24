#!/bin/sh
set -eu

exec uvicorn monatise.application.production:app \
  --host 0.0.0.0 \
  --port "${PORT:-4174}" \
  --workers 1 \
  --timeout-graceful-shutdown 30
