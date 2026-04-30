# Testing

JarvisOS uses pytest markers to split the suite by runtime boundary and speed.

## Fast Gate

Run deterministic unit tests that should not require external services:

```bash
PYTHON=.venv/bin/python3 bash scripts/test-unit.sh
```

Equivalent selector:

```bash
python -m pytest -m "unit and not slow"
```

The unit script defaults to a 60-second suite timeout. Override it with
`PYTEST_UNIT_TIMEOUT=120s` when needed.

## Integration Gate

Run tests that exercise multiple modules or mocked service adapters:

```bash
PYTHON=.venv/bin/python3 bash scripts/test-integration.sh
```

Equivalent selector:

```bash
python -m pytest -m "integration"
```

The integration script defaults to a 180-second suite timeout. Override it with
`PYTEST_INTEGRATION_TIMEOUT=300s` when needed.

## E2E / Slow Gate

Run tests that touch real runtime boundaries or are intentionally slow:

```bash
PYTHON=.venv/bin/python3 bash scripts/test-e2e.sh
```

Equivalent selector:

```bash
python -m pytest -m "e2e or slow"
```

The e2e script defaults to a 300-second suite timeout. Override it with
`PYTEST_E2E_TIMEOUT=600s` when needed.

## Notes

The marker taxonomy is declared in `pytest.ini`. Existing test files are
assigned to suite markers centrally in `tests/conftest.py`; collection fails if
a new `test_*.py` file is added without a suite classification.

The suite scripts automatically prefer `.venv/bin/python3` when `PYTHON` is not
set, so the configured pytest plugins are used consistently. They also redirect
pytest's cache to `/tmp/jarvisos-pytest-cache` by default to keep the repository
tree clean in read-only or mounted workspaces.
