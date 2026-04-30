#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec bash "$SCRIPT_DIR/_pytest-suite.sh" e2e "${PYTEST_E2E_TIMEOUT:-300s}" "e2e or slow" "$@"
