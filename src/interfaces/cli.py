"""Jarvis Rich terminal CLI — direct interaction from the shell.

Usage (inside the container):
    python -m src.interfaces.cli
    python -m src.interfaces.cli --session <session-id>

Arguments:
    --session SESSION_ID    Resume an existing session (shared with Telegram)

Special commands (prefix with /):
    /quit   /exit       Exit the CLI
    /session            Print the current session ID
    /status             Agent model chain and uptime
    /memory             Show today's memory log
"""

import argparse
import logging
import sys
import time

logger = logging.getLogger(__name__)

_BANNER = """
[bold cyan]Jarvis[/bold cyan] [dim]— AI Executive Assistant[/dim]
Type [bold]/help[/bold] for commands or just start talking.
─────────────────────────────────────────────────────
"""

_HELP_TEXT = """[bold]Commands[/bold]
  /status    — model chain and uptime
  /session   — current session ID
  /memory    — today's memory log
  /quit      — exit (also: /exit, Ctrl-D)
"""


def _model_chain_str(agent) -> str:
    primary = agent.model
    parts = [f"{getattr(primary, 'provider', '?')}/{getattr(primary, 'id', '?')}"]
    for fb in getattr(agent, "fallback_models", None) or []:
        parts.append(f"{getattr(fb, 'provider', '?')}/{getattr(fb, 'id', '?')}")
    return " → ".join(parts)


def _handle_command(cmd: str, agent, session_id: str, start_time: float, console) -> bool:
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
        chain = _model_chain_str(agent)
        console.print(
            f"[bold]Agent:[/bold] {agent.name}\n"
            f"[bold]Model chain:[/bold] {chain}\n"
            f"[bold]Uptime:[/bold] {uptime}s"
        )

    elif cmd == "/memory":
        from src.config import settings
        from src.memory.daily_logger import DailyLogger
        content = DailyLogger(settings.workspace_path).read_today()
        if content:
            console.print(Markdown(f"```\n{content}\n```"))
        else:
            console.print("[dim](no entries today)[/dim]")

    else:
        console.print(f"[red]Unknown command:[/red] {cmd}  (type /help for a list)")

    return False


def run(session_id: str | None = None) -> None:
    """Start the interactive CLI loop.

    Args:
        session_id: Optional existing session to resume (shared with Telegram).
    """
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import InMemoryHistory
    from rich.console import Console
    from rich.markdown import Markdown

    from src.agent import create_jarvis_agent, create_session_manager

    console = Console()
    console.print(_BANNER)

    # --- Init agent ---------------------------------------------------------
    console.print("[dim]Initialising Jarvis agent…[/dim]")
    try:
        agent = create_jarvis_agent()
        session_manager = create_session_manager()
    except Exception as exc:
        console.print(f"[red bold]Failed to initialise agent:[/red bold] {exc}")
        sys.exit(1)

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
        f"[dim]Model chain:[/dim] {_model_chain_str(agent)}\n"
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
                user_input, agent, session_id, start_time, console
            )
            if should_exit:
                break
            continue

        # Agent invocation
        console.print("[dim]Jarvis is thinking…[/dim]")
        try:
            response = agent.run(user_input, session_id=session_id)
            content = response.content if hasattr(response, "content") else str(response)

            # Render Markdown if the response looks like it contains markup
            console.print()
            console.print("Jarvis ›", style="bold cyan", end=" ")
            try:
                console.print(Markdown(content))
            except Exception:
                console.print(content)
            console.print()

        except Exception as exc:
            logger.error("cli: agent error — %s", exc, exc_info=True)
            console.print(f"[red bold]Error:[/red bold] {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="jarvis-cli",
        description="Jarvis AI Executive Assistant — terminal CLI",
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

    run(session_id=args.session)


if __name__ == "__main__":
    main()
