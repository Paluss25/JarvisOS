"""Load and parse the ops-detector index.yaml from RUNBOOKS_PATH.

Re-reads the file on every call — no caching by design.
If index.yaml is absent or malformed, returns an empty list
(detector stays silent rather than crashing).
"""
import logging
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class Pattern:
    id: str
    description: str
    logql: str
    cooldown_minutes: int
    severity: str
    runbook: str


def load_patterns() -> list[Pattern]:
    """Read index.yaml and return parsed Pattern objects."""
    runbooks_path = Path(os.environ.get("RUNBOOKS_PATH", "/app/runbooks"))
    index_file = runbooks_path / "index.yaml"

    if not index_file.exists():
        logger.debug("patterns: index.yaml not found at %s", index_file)
        return []

    try:
        data = yaml.safe_load(index_file.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("patterns: failed to parse index.yaml — %s", exc)
        return []

    patterns = []
    for p in data.get("patterns", []):
        try:
            patterns.append(Pattern(
                id=p["id"],
                description=p.get("description", ""),
                logql=p["logql"],
                cooldown_minutes=int(p.get("cooldown_minutes", 30)),
                severity=p.get("severity", "medium"),
                runbook=p.get("runbook", ""),
            ))
        except (KeyError, ValueError) as exc:
            logger.warning("patterns: skipping malformed entry — %s", exc)

    logger.debug("patterns: loaded %d patterns from %s", len(patterns), index_file)
    return patterns
