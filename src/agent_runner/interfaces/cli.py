"""Generic Rich terminal CLI — direct interaction from the shell.

Designed to be called from an agent-specific entrypoint that supplies
the agent client, session manager, and AgentConfig.

Special commands (prefix with /):
    /quit   /exit       Exit the CLI
    /session            Print the current session ID
    /status             Agent model chain and uptime
    /memory             Show today's memory log
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_HELP_TEXT = """[bold]Commands[/bold]
  /status    — model chain and uptime
  /session   — current session ID
  /memory    — today's memory log
  /quit      — exit (also: /exit, Ctrl-D)
"""


def _handle_command(
    cmd: str,
    agent,
    session_id: str,
    start_time: float,
    console,
    workspace_path: Path,
    agent_name: str = "Agent",
) -> bool:
    """Handle a /command.  Returns True if the CLI should exit."""
    from rich.markdown import Markdown

    cmd = cmd.strip().lower()

    if cmd in ("/quit", "/exit"):
        console.print("[dim]Goodbye.[/dim]")
        return True

    if cmd == "/help":
        console.print(_HELP_TEXT)

    elif cmd == "/session":
        console.print(f"[bold]Session ID:[/bold] [cyan]{session_id}[/cyan]")

    elif cmd == "/status":
        uptime = int(time.time() - start_time)
        console.print(
            f"[bold]Agent:[/bold] {agent_name}\n"
            f"[bold]Model:[/bold] claude (sdk)\n"
            f"[bold]Uptime:[/bold] {uptime}s"
        )

    elif cmd == "/memory":
        from agent_runner.memory.daily_logger import DailyLogger
        content = DailyLogger(workspace_path).read_today()
        if content:
            console.print(Markdown(f"```\n{content}\n```"))
        else:
            console.print("[dim](no entries today)[/dim]")

    else:
        console.print(f"[red]Unknown command:[/red] {cmd}  (type /help for a list)")

    return False


def run(agent, session_manager, config, session_id: str | None = None) -> None:
    """Start the interactive CLI loop.

    Args:
        agent: The agent client (must implement ``query(prompt, session_id)``).
        session_manager: SessionManager instance.
        config: AgentConfig — provides workspace_path and name.
        session_id: Optional existing session to resume (shared with Telegram).
    """
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import InMemoryHistory
    from rich.console import Console
    from rich.markdown import Markdown

    workspace_path = Path(config.workspace_path)
    agent_name = config.name

    banner = (
        f"\n[bold cyan]{agent_name}[/bold cyan] [dim]— AI Agent[/dim]\n"
        "Type [bold]/help[/bold] for commands or just start talking.\n"
        "─────────────────────────────────────────────────────"
    )

    console = Console()
    console.print(banner)

    # --- Session ------------------------------------------------------------
    if session_id:
        console.print(f"[dim]Resuming session:[/dim] [cyan]{session_id}[/cyan]")
    else:
        try:
            session_id = session_manager.start()
        except Exception:
            import uuid
            session_id = str(uuid.uuid4())
        console.print(f"[dim]New session:[/dim] [cyan]{session_id}[/cyan]")

    console.print(
        "[dim]Model:[/dim] claude (sdk)\n"
        "─────────────────────────────────────────────────────"
    )

    start_time = time.time()
    prompt_session: PromptSession = PromptSession(history=InMemoryHistory())

    # --- Main loop ----------------------------------------------------------
    while True:
        try:
            user_input = prompt_session.prompt("You › ")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye.[/dim]")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        # Slash commands
        if user_input.startswith("/"):
            should_exit = _handle_command(
                user_input, agent, session_id, start_time, console,
                workspace_path=workspace_path,
                agent_name=agent_name,
            )
            if should_exit:
                break
            continue

        # Agent invocation
        console.print(f"[dim]{agent_name} is thinking…[/dim]")
        try:
            content = asyncio.run(agent.query(user_input, session_id=session_id))

            console.print()
            console.print(f"{agent_name} ›", style="bold cyan", end=" ")
            try:
                console.print(Markdown(content))
            except Exception:
                console.print(content)
            console.print()

        except Exception as exc:
            logger.error("cli: agent error — %s", exc, exc_info=True)
            console.print(f"[red bold]Error:[/red bold] {exc}")


def main(agent, session_manager, config) -> None:
    """Argument-parsing entrypoint.  Call from agent-specific __main__.py.

    Args:
        agent: Initialised agent client.
        session_manager: SessionManager for this agent.
        config: AgentConfig — provides workspace_path and name.
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog=f"{config.name.lower()}-cli",
        description=f"{config.name} AI Agent — terminal CLI",
    )
    parser.add_argument(
        "--session",
        metavar="SESSION_ID",
        default=None,
        help="Resume an existing session (shared with Telegram)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable DEBUG logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    run(agent, session_manager, config, session_id=args.session)
