#!/usr/bin/env bash
# Start the System One tool-routing demo at http://localhost:8000
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT/demo/backend"
exec "$ROOT/.venv/bin/uvicorn" app:app --host 127.0.0.1 --port "${PORT:-8000}" "$@"
