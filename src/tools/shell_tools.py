"""Shell execution tools for Jarvis.

Read-only commands execute freely.
Write/destructive commands are routed through the permission gate.
All executions are logged to daily memory.
"""

import logging
import shlex
import subprocess

from agno.tools.toolkit import Toolkit

logger = logging.getLogger(__name__)

_CMD_TIMEOUT = 60  # seconds
_MAX_OUTPUT = 10_000  # chars

# Commands whose first token is considered safe (read-only)
_READ_ONLY_PREFIXES = {
    "ls", "cat", "head", "tail", "grep", "find", "df", "du", "ps",
    "top", "free", "uptime", "uname", "whoami", "id", "env", "printenv",
    "echo", "pwd", "wc", "sort", "uniq", "awk", "sed",
    "docker ps", "docker logs", "docker inspect", "docker images",
    "docker stats", "docker top",
    "kubectl get", "kubectl describe", "kubectl logs", "kubectl top",
    "kubectl explain",
    "git status", "git log", "git diff", "git show", "git branch",
    "ping", "curl", "wget", "dig", "nslookup", "ss", "netstat",
    "systemctl status", "journalctl",
}


def _is_read_only(command: str) -> bool:
    """Return True if the command is safe to run without approval."""
    cmd = command.strip()
    for prefix in _READ_ONLY_PREFIXES:
        if cmd == prefix or cmd.startswith(prefix + " "):
            return True
    return False


class ShellTools(Toolkit):
    """Run shell commands with a permission gate for destructive operations."""

    def __init__(self):
        super().__init__(name="shell_tools")

    def run_command(self, command: str) -> str:
        """Execute a shell command and return its output.

        Read-only commands (ls, cat, docker ps, kubectl get, …) run immediately.
        All other commands require approval via Telegram before executing.

        Args:
            command: The shell command to run.

        Returns:
            Combined stdout + stderr output (truncated at 10 000 chars).
        """
        from src.config import settings
        from src.memory.daily_logger import DailyLogger
        from src.tools import permission_gate

        if not _is_read_only(command):
            approved = permission_gate.request_approval(
                action="Shell command",
                details=command,
            )
            if not approved:
                return f"Command denied by permission gate: {command}"

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=_CMD_TIMEOUT,
            )
            output = result.stdout + result.stderr
            if len(output) > _MAX_OUTPUT:
                output = output[:_MAX_OUTPUT] + f"\n[…output truncated at {_MAX_OUTPUT} chars]"

            try:
                dl = DailyLogger(settings.workspace_path)
                status = "OK" if result.returncode == 0 else f"rc={result.returncode}"
                dl.log(f"[SHELL:{status}] {command[:120]}")
            except Exception:
                pass

            logger.info("shell: ran %r (rc=%d)", command[:80], result.returncode)
            return output or f"(exit code {result.returncode}, no output)"

        except subprocess.TimeoutExpired:
            return f"Command timed out after {_CMD_TIMEOUT}s: {command}"
        except Exception as exc:
            logger.error("shell: error running command — %s", exc)
            return f"Error: {exc}"
