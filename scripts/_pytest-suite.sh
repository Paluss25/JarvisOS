#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 ]]; then
  echo "Usage: $0 <suite-name> <suite-timeout> <marker-expression> [pytest args...]" >&2
  exit 2
fi

SUITE_NAME="$1"
SUITE_TIMEOUT="$2"
MARK_EXPR="$3"
shift 3

if [[ -n "${PYTHON:-}" ]]; then
  PYTHON_BIN="$PYTHON"
elif [[ -x ".venv/bin/python3" ]]; then
  PYTHON_BIN=".venv/bin/python3"
else
  PYTHON_BIN="python3"
fi

CACHE_ROOT="${PYTEST_CACHE_ROOT:-${TMPDIR:-/tmp}/jarvisos-pytest-cache}"
CACHE_DIR="${CACHE_ROOT}/${SUITE_NAME}"
mkdir -p "$CACHE_DIR"

PYTEST_CMD=(
  "$PYTHON_BIN" -m pytest
  -o "cache_dir=$CACHE_DIR"
  -m "$MARK_EXPR"
  "$@"
)

if command -v timeout >/dev/null 2>&1; then
  exec timeout --kill-after=10s "$SUITE_TIMEOUT" "${PYTEST_CMD[@]}"
fi

echo "warning: coreutils timeout not found; running pytest without suite-level timeout" >&2
exec "${PYTEST_CMD[@]}"
