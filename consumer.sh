#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
command="${1:-serve}"
if [ "$#" -gt 0 ]; then shift; fi
if command -v uv >/dev/null 2>&1; then
  if [ "$command" = "mcp" ]; then
    exec uv run --no-project --with 'mcp==2.3.0' --with 'httpx==0.28.1' python -m exchange.consumer_mcp
  fi
  exec uv run --no-project --with 'fastapi==0.150.0' --with 'uvicorn==0.54.0' --with 'networkx==3.6.1' python -m exchange.consumer "$command" "$@"
fi
if [ "$command" = "mcp" ]; then exec python -m exchange.consumer_mcp; fi
exec python -m exchange.consumer "$command" "$@"
