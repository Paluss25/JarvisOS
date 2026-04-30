#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec bash "$SCRIPT_DIR/_pytest-suite.sh" integration "${PYTEST_INTEGRATION_TIMEOUT:-180s}" "integration" "$@"
