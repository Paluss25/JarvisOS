"""Tests for YNAB CLI — src/tools/ynab_cli.py."""
import json
import os
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from tools.ynab_cli import app, _milliunits

runner = CliRunner()


def _fake_resp(data, key=None, status_code=200):
    """Build a fake httpx.Response with is_success based on status_code."""
    resp = MagicMock()
    resp.is_success = status_code < 400
    resp.status_code = status_code
    resp.text = json.dumps(data)
    if key:
        resp.json.return_value = {"data": {key: data}}
    else:
        resp.json.return_value = {"data": data}
    return resp


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------

def test_milliunits_outflow():
    assert _milliunits(45.90, "outflow") == -45900


def test_milliunits_inflow():
    assert _milliunits(1500.0, "inflow") == 1500000


def test_milliunits_zero():
    assert _milliunits(0.0, "outflow") == 0
