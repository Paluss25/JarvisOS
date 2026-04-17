"""Shared memory MCP tools — cross-agent knowledge with ACL enforcement."""

import logging
from pathlib import Path

from agent_runner.memory.domain_acl import can_access_domain

logger = logging.getLogger(__name__)

_SHARED_ROOT = Path("/app/shared")


def create_shared_memory_tools(agent_id: str):
    """Return MCP tool callables for cross-agent shared memory."""

    async def shared_memory_write(domain: str, key: str, content: str) -> str:
        """Write a knowledge entry to a shared memory domain.

        Args:
            domain: Domain name (e.g. "sport", "global", "health").
            key: Entry key — used as filename (no extension needed).
            content: Markdown content to store.
        """
        if not can_access_domain(agent_id, domain, mode="write"):
            return f"error: agent '{agent_id}' does not have write access to domain '{domain}'"

        domain_path = _SHARED_ROOT / domain
        domain_path.mkdir(parents=True, exist_ok=True)

        safe_key = key.replace("/", "_").replace("..", "")
        out = domain_path / f"{safe_key}.md"
        out.write_text(content, encoding="utf-8")
        logger.info("shared_memory: %s wrote %s/%s.md", agent_id, domain, safe_key)
        return f"written: {out}"

    async def shared_memory_read(domain: str, key: str) -> str:
        """Read a knowledge entry from a shared memory domain.

        Args:
            domain: Domain name.
            key: Entry key (filename without .md extension).
        """
        if not can_access_domain(agent_id, domain, mode="read"):
            return f"error: agent '{agent_id}' does not have read access to domain '{domain}'"

        safe_key = key.replace("/", "_").replace("..", "")
        path = _SHARED_ROOT / domain / f"{safe_key}.md"
        if not path.exists():
            return f"not found: {domain}/{key}"
        return path.read_text(encoding="utf-8")

    async def shared_memory_search(query: str, domains: list[str] | None = None) -> str:
        """Search for a keyword across accessible shared memory domains.

        Args:
            query: Text to search for (case-insensitive).
            domains: Optional list of domains to restrict search. Defaults to all accessible.
        """
        results: list[str] = []
        _SHARED_ROOT.mkdir(parents=True, exist_ok=True)

        target_domains = domains or [d.name for d in _SHARED_ROOT.iterdir() if d.is_dir()]
        q = query.lower()

        for domain in target_domains:
            if not can_access_domain(agent_id, domain, mode="read"):
                continue
            domain_path = _SHARED_ROOT / domain
            for md_file in sorted(domain_path.glob("*.md")):
                text = md_file.read_text(encoding="utf-8")
                if q in text.lower():
                    results.append(f"[{domain}/{md_file.stem}]\n{text[:500]}")

        if not results:
            return f"no results for '{query}'"
        return "\n\n---\n\n".join(results)

    return [shared_memory_write, shared_memory_read, shared_memory_search]
