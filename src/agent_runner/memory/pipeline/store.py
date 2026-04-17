"""Dual-write memory store — filesystem router + vector stub.

Routing by memory type:
  fact / preference      → workspace/MEMORY.md  + vector stub
  feedback               → workspace/AGENTS.md  + vector stub
  context / action /
  episode                → workspace/memory/YYYY-MM-DD.md + vector stub
  scope=domain:{name}    → also /app/shared/{domain}/{key}.md  (ACL enforced)
"""

import hashlib
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

from agent_runner.memory.domain_acl import can_access_domain

logger = logging.getLogger(__name__)

# Types that route to the durable MEMORY.md / AGENTS.md files
_PERSISTENT_TYPES = {"fact", "preference"}
_FEEDBACK_TYPES = {"feedback"}
_DAILY_TYPES = {"context", "action", "episode"}

_SHARED_ROOT = Path("/app/shared")


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------

def _safe_key(text: str) -> str:
    """Turn arbitrary text into a safe 8-char hex filename stem."""
    return hashlib.sha1(text.encode()).hexdigest()[:8]


def _append_section(path: Path, heading: str, content: str) -> None:
    """Append a headed block to a markdown file, creating it if absent."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    # Skip if same content already present (basic dedup guard)
    if content.strip() in existing:
        return
    with path.open("a", encoding="utf-8") as fh:
        if existing and not existing.endswith("\n"):
            fh.write("\n")
        fh.write(f"\n### {heading}\n\n{content.strip()}\n")


def _update_section(path: Path, old_content: str, new_content: str) -> bool:
    """Replace a section whose body matches old_content. Returns True on success."""
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    if old_content.strip() not in text:
        return False
    path.write_text(text.replace(old_content.strip(), new_content.strip()), encoding="utf-8")
    return True


def _delete_section(path: Path, content: str) -> bool:
    """Remove a section whose body matches content. Returns True on success."""
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    if content.strip() not in text:
        return False
    # Remove heading + content block
    pattern = r"\n### [^\n]+\n\n" + re.escape(content.strip()) + r"\n?"
    updated = re.sub(pattern, "", text)
    path.write_text(updated, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# Vector stub
# ---------------------------------------------------------------------------

def _vector_write_stub(agent_id: str, entry: dict[str, Any], key: str) -> None:
    """No-op vector write — placeholder until memory-api is integrated."""
    logger.debug("store[%s]: vector stub write key=%s type=%s", agent_id, key, entry.get("type"))


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def _workspace_path(config: Any) -> Path:
    """Extract workspace Path from config (AgentConfig or plain Path)."""
    if isinstance(config, Path):
        return config
    return Path(getattr(config, "workspace_path", "/app/workspace"))


async def store_entry(
    agent_id: str,
    entry: dict[str, Any],
    action: dict[str, Any],
    config: Any,
) -> None:
    """Persist a deduplicated memory entry to the appropriate store.

    Args:
        agent_id:  The owning agent's ID.
        entry:     {text, type, scope} dict from the extractor.
        action:    {action, ...} dict from the deduplicator.
        config:    AgentConfig (or workspace Path) for resolving filesystem paths.
    """
    act = action.get("action", "NOOP")
    if act == "NOOP":
        return

    mem_type = entry.get("type", "context")
    scope = entry.get("scope", "agent")
    text = entry.get("text", "")
    workspace = _workspace_path(config)

    # --- Resolve target file ------------------------------------------------
    if mem_type in _PERSISTENT_TYPES:
        target = workspace / "MEMORY.md"
    elif mem_type in _FEEDBACK_TYPES:
        target = workspace / "AGENTS.md"
    else:
        target = workspace / "memory" / f"{date.today().isoformat()}.md"

    key = _safe_key(text)
    heading = f"{mem_type.capitalize()} [{key}]"

    # --- Apply action -------------------------------------------------------
    if act == "ADD":
        _append_section(target, heading, text)
        _vector_write_stub(agent_id, entry, key)
        logger.info("store[%s]: ADD %s → %s", agent_id, mem_type, target.name)

    elif act == "UPDATE":
        replace_id = action.get("replace_id", "")
        # Try to find and update the old entry; fallback to append
        old_entries = _load_existing(target)
        old = next((e for e in old_entries if e.get("id") == replace_id), None)
        if old and _update_section(target, old["text"], text):
            logger.info("store[%s]: UPDATE %s id=%s", agent_id, mem_type, replace_id)
        else:
            _append_section(target, heading, text)
            logger.info("store[%s]: UPDATE→ADD %s (old not found)", agent_id, mem_type)
        _vector_write_stub(agent_id, entry, key)

    elif act == "DELETE":
        replace_id = action.get("replace_id", "")
        old_entries = _load_existing(target)
        old = next((e for e in old_entries if e.get("id") == replace_id), None)
        if old:
            _delete_section(target, old["text"])
            logger.info("store[%s]: DELETE id=%s from %s", agent_id, replace_id, target.name)

    # --- Shared domain write ------------------------------------------------
    if scope.startswith("domain:"):
        domain = scope.split(":", 1)[1]
        if can_access_domain(agent_id, domain, mode="write"):
            domain_path = _SHARED_ROOT / domain
            domain_path.mkdir(parents=True, exist_ok=True)
            out = domain_path / f"{key}.md"
            out.write_text(f"# {heading}\n\n{text}\n", encoding="utf-8")
            logger.info("store[%s]: shared write → %s/%s.md", agent_id, domain, key)
        else:
            logger.warning(
                "store[%s]: no write ACL for domain '%s' — skipping shared write",
                agent_id, domain,
            )


def _load_existing(path: Path) -> list[dict[str, Any]]:
    """Parse existing headed sections from a markdown file into [{id, text}] list."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    entries: list[dict[str, Any]] = []
    # Match "### Heading [key]\n\ncontent"
    for m in re.finditer(r"### [^\n]+ \[([a-f0-9]+)\]\n\n(.*?)(?=\n### |\Z)", text, re.DOTALL):
        eid, body = m.group(1), m.group(2).strip()
        entries.append({"id": eid, "text": body})
    return entries


def load_existing_for_agent(config: Any) -> list[dict[str, Any]]:
    """Load all known memory entries from an agent's workspace for dedup comparison."""
    workspace = _workspace_path(config)
    entries: list[dict[str, Any]] = []
    for filename in ("MEMORY.md", "AGENTS.md"):
        entries.extend(_load_existing(workspace / filename))
    mem_dir = workspace / "memory"
    if mem_dir.is_dir():
        for md in sorted(mem_dir.glob("*.md"))[-7:]:   # last 7 days
            entries.extend(_load_existing(md))
    return entries
