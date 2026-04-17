"""MemoryBackend protocol — abstracts filesystem vs future agentic memory."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class MemoryBackend(Protocol):
    """Minimal interface for memory storage backends."""

    def write(self, key: str, content: str, scope: str = "private") -> None:
        """Write a memory entry."""
        ...

    def read(self, key: str, scope: str = "private") -> str:
        """Read a memory entry. Returns empty string if not found."""
        ...

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Search memory entries. Returns list of {key, content, score}."""
        ...
