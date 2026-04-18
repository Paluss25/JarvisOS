"""Code execution tools for Jarvis.

Executes Python code or Bash scripts in a subprocess.
All executions are gated through the permission gate and logged to daily memory.
"""

import logging
import subprocess
import tempfile
from pathlib import Path

from agno.tools.toolkit import Toolkit

logger = logging.getLogger(__name__)

_EXEC_TIMEOUT = 30  # seconds
_MAX_OUTPUT = 10_000  # chars


class CodeExecutorTools(Toolkit):
    """Run Python or Bash code in a sandboxed subprocess."""

    def __init__(self):
        super().__init__(name="code_executor")

    def _log(self, msg: str) -> None:
        try:
            from config import settings
            from memory.daily_logger import DailyLogger
            DailyLogger(settings.workspace_path).log(msg)
        except Exception:
            pass

    def _run_subprocess(self, cmd: list[str], input_text: str | None = None) -> tuple[int, str]:
        """Run a subprocess and return (returncode, output)."""
        try:
            result = subprocess.run(
                cmd,
                input=input_text,
                capture_output=True,
                text=True,
                timeout=_EXEC_TIMEOUT,
            )
            output = result.stdout + result.stderr
            if len(output) > _MAX_OUTPUT:
                output = output[:_MAX_OUTPUT] + f"\n[…output truncated at {_MAX_OUTPUT} chars]"
            return result.returncode, output
        except subprocess.TimeoutExpired:
            return -1, f"Execution timed out after {_EXEC_TIMEOUT}s"
        except Exception as exc:
            return -1, f"Execution error: {exc}"

    def execute_python(self, code: str) -> str:
        """Execute Python code in a subprocess and return its output.

        All executions require approval via the permission gate.

        Args:
            code: Python source code to execute.

        Returns:
            Combined stdout + stderr output (truncated at 10 000 chars).
        """
        from tools import permission_gate

        preview = code[:400] + ("…" if len(code) > 400 else "")
        approved = permission_gate.request_approval(
            action="Execute Python code",
            details=preview,
        )
        if not approved:
            return "Execution denied by permission gate."

        with tempfile.NamedTemporaryFile(
            suffix=".py", mode="w", delete=False, prefix="jarvis_exec_"
        ) as tmp:
            tmp.write(code)
            tmp_path = tmp.name

        try:
            rc, output = self._run_subprocess(["python3", tmp_path])
            status = "OK" if rc == 0 else f"rc={rc}"
            self._log(f"[EXEC:PYTHON:{status}] {code[:80].strip()!r}")
            logger.info("code_executor: python exec done (rc=%d)", rc)
            return output or f"(exit code {rc}, no output)"
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def execute_bash(self, script: str) -> str:
        """Execute a Bash script in a subprocess and return its output.

        All executions require approval via the permission gate.

        Args:
            script: Bash script content to execute.

        Returns:
            Combined stdout + stderr output (truncated at 10 000 chars).
        """
        from tools import permission_gate

        preview = script[:400] + ("…" if len(script) > 400 else "")
        approved = permission_gate.request_approval(
            action="Execute Bash script",
            details=preview,
        )
        if not approved:
            return "Execution denied by permission gate."

        rc, output = self._run_subprocess(["bash", "-s"], input_text=script)
        status = "OK" if rc == 0 else f"rc={rc}"
        self._log(f"[EXEC:BASH:{status}] {script[:80].strip()!r}")
        logger.info("code_executor: bash exec done (rc=%d)", rc)
        return output or f"(exit code {rc}, no output)"
