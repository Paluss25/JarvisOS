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

## Integration Gate

Run tests that exercise multiple modules or mocked service adapters:

```bash
PYTHON=.venv/bin/python3 bash scripts/test-integration.sh
```

Equivalent selector:

```bash
python -m pytest -m "integration"
```

## E2E / Slow Gate

Run tests that touch real runtime boundaries or are intentionally slow:

```bash
PYTHON=.venv/bin/python3 bash scripts/test-e2e.sh
```

Equivalent selector:

```bash
python -m pytest -m "e2e or slow"
```

## Notes

The marker taxonomy is declared in `pytest.ini`. Existing test files are
assigned to suite markers centrally in `tests/conftest.py`; collection fails if
a new `test_*.py` file is added without a suite classification.
