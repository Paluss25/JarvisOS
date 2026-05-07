"""Claude CLI completions for hybrid worker sub-agents (uses OAuth, no API key needed)."""

import asyncio
import subprocess


async def complete(prompt: str, system: str = "") -> str:
    """Single-turn completion via the claude CLI. Returns the text response."""
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            ["claude", "-p", full_prompt, "--output-format", "text"],
            capture_output=True,
            text=True,
            timeout=60,
        ),
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI error (rc={result.returncode}): {result.stderr.strip()[:300]}")
    return result.stdout.strip()
