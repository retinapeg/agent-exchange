#!/bin/sh
set -eu
cd "$(dirname "$0")"
export UV_CACHE_DIR="$PWD/.cache/uv"
if [ ! -x .venv/bin/python ]; then
  uv sync --frozen
fi
exec .venv/bin/python -m exchange.cli "$@"
