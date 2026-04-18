"""Workspace-scoped file operation tools for Jarvis.

All paths are sandboxed to /app/workspace/ (or the configured workspace_path).
Write operations are routed through the permission gate.
All operations are logged to daily memory.
"""

import logging
import os
from pathlib import Path

from agno.tools.toolkit import Toolkit

logger = logging.getLogger(__name__)

_MAX_READ_BYTES = 50_000  # chars before truncation


class WorkspaceFileTools(Toolkit):
    """File operations sandboxed to the Jarvis workspace directory."""

    def __init__(self, workspace_path: str | None = None):
        super().__init__(name="workspace_file_tools")
        if workspace_path:
            self._workspace = Path(workspace_path).resolve()
        else:
            # Fallback: /app/workspace when running inside the container
            self._workspace = Path(os.environ.get("WORKSPACE_PATH", "/app/workspace")).resolve()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve(self, user_path: str) -> Path | None:
        """Return an absolute path within the workspace, or None if outside."""
        try:
            resolved = (self._workspace / user_path).resolve()
            resolved.relative_to(self._workspace)  # raises if outside
            return resolved
        except (ValueError, OSError):
            return None

    def _log(self, msg: str) -> None:
        try:
            from config import settings
            from memory.daily_logger import DailyLogger
            DailyLogger(settings.workspace_path).log(msg)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Tool methods (auto-registered by Agno Toolkit)
    # ------------------------------------------------------------------

    def read_file(self, path: str) -> str:
        """Read a file from the Jarvis workspace.

        Args:
            path: Relative path inside the workspace directory.

        Returns:
            File contents as a string (truncated at 50 000 chars).
        """
        resolved = self._resolve(path)
        if resolved is None:
            return f"Access denied: '{path}' is outside the workspace."

        if not resolved.exists():
            return f"File not found: {path}"
        if not resolved.is_file():
            return f"Not a file: {path}"

        try:
            text = resolved.read_text(errors="replace")
            if len(text) > _MAX_READ_BYTES:
                text = text[:_MAX_READ_BYTES] + f"\n[…truncated at {_MAX_READ_BYTES} chars]"
            self._log(f"[FILE:READ] {path}")
            logger.info("file_tools: read %s (%d chars)", path, len(text))
            return text
        except OSError as exc:
            logger.error("file_tools: read error — %s", exc)
            return f"Error reading file: {exc}"

    def write_file(self, path: str, content: str) -> str:
        """Write content to a file in the Jarvis workspace.

        Requires approval via the permission gate before executing.

        Args:
            path:    Relative path inside the workspace directory.
            content: Text content to write.

        Returns:
            Confirmation message or error.
        """
        from tools import permission_gate

        resolved = self._resolve(path)
        if resolved is None:
            return f"Access denied: '{path}' is outside the workspace."

        approved = permission_gate.request_approval(
            action="Write file",
            details=f"Path: {resolved}\nSize: {len(content)} chars\nPreview:\n{content[:500]}",
        )
        if not approved:
            return f"Write denied by permission gate: {path}"

        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content)
            self._log(f"[FILE:WRITE] {path} ({len(content)} chars)")
            logger.info("file_tools: wrote %s (%d chars)", path, len(content))
            return f"File written: {path} ({len(content)} chars)"
        except OSError as exc:
            logger.error("file_tools: write error — %s", exc)
            return f"Error writing file: {exc}"

    def list_files(self, directory: str = "") -> str:
        """List files in a workspace directory.

        Args:
            directory: Relative path inside the workspace (empty = workspace root).

        Returns:
            Newline-separated list of paths relative to the workspace root.
        """
        resolved = self._resolve(directory or ".")
        if resolved is None:
            return f"Access denied: '{directory}' is outside the workspace."

        if not resolved.exists():
            return f"Directory not found: {directory}"
        if not resolved.is_dir():
            return f"Not a directory: {directory}"

        try:
            entries = sorted(resolved.iterdir())
            lines = []
            for entry in entries:
                rel = entry.relative_to(self._workspace)
                suffix = "/" if entry.is_dir() else ""
                lines.append(str(rel) + suffix)
            self._log(f"[FILE:LIST] {directory or '/'}")
            return "\n".join(lines) if lines else "(empty directory)"
        except OSError as exc:
            logger.error("file_tools: list error — %s", exc)
            return f"Error listing directory: {exc}"
