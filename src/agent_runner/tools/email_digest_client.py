from __future__ import annotations

import json
import os
from pathlib import Path


async def read_email_digest(workspace_path: Path, args: dict) -> dict:
    from agents.mt.tools import _read_digest, _read_processed_ids, _text

    max_items = int(args.get("max_items") or 10)
    digest_path = Path(os.environ.get("MT_DIGEST_PATH", "/app/shared/mt_digest.json"))
    processed_ids = _read_processed_ids(workspace_path)
    items = _read_digest(digest_path, processed_ids, max_items=max_items)
    if not items:
        return _text("No new digest entries.")
    return _text(json.dumps(items, ensure_ascii=False, indent=2))
