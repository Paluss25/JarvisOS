#!/usr/bin/env python3
"""Thin wrapper for the Plane sync CLI."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from integrations.plane.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
