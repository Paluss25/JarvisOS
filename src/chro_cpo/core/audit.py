from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


class AuditLogger:
    def __init__(self, path: str = "audit.log") -> None:
        self.path = Path(path)

    def log(self, event: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
