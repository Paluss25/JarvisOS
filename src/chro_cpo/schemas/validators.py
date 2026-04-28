from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from jsonschema import validate


def load_schema(path: str) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_payload(schema_path: str, payload: Dict[str, Any]) -> None:
    schema = load_schema(schema_path)
    validate(instance=payload, schema=schema)
