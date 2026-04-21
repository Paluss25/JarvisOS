"""In-process MCP server exposing ChiefOfStaffAgent custom tools to the claude-agent-sdk.

Core tools (platform-standard — do not remove):
  daily_log      — Append to today's memory log
  memory_search  — Text search across MEMORY.md + memory/*.md
  memory_get     — Read a specific memory file from workspace
  send_message   — Send a message to another agent via Redis pub/sub
  cron_create    — Create a scheduled task
  cron_list      — List scheduled tasks
  cron_update    — Update a scheduled task
  cron_delete    — Delete a scheduled task

Domain-specific tools:
  route_email_payload  — Route a structured email intelligence payload via HybridChiefOfStaffAgent
  get_routing_history  — Return last N routing decisions from the audit log
  route_case           — Legacy: produce a routing decision for a case derived from external data
"""

import json
import logging
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers — do NOT remove these; they fix known SDK/MCP compatibility issues
# ---------------------------------------------------------------------------

def _parse_args(args) -> dict:
    """Normalize tool args — older SDK versions pass a JSON string instead of a dict."""
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, ValueError):
            return {}
    return args if isinstance(args, dict) else {}


def _text(s: str) -> dict:
    """Wrap a plain string as an MCP text content response.

    The SDK's call_tool handler calls result.get("is_error") unconditionally,
    so every tool MUST return a dict — never a bare string.
    """
    return {"content": [{"type": "text", "text": str(s)}]}


# ---------------------------------------------------------------------------
# SDK import guard — graceful degradation if SDK not installed
# ---------------------------------------------------------------------------

try:
    from claude_agent_sdk import create_sdk_mcp_server, tool as sdk_tool
    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False
    create_sdk_mcp_server = None
    sdk_tool = None


# ---------------------------------------------------------------------------
# MCP server factory
# ---------------------------------------------------------------------------

def create_chief_of_staff_mcp_server(workspace_path: Path, redis_a2a=None):
    """Build and return the in-process MCP server with ChiefOfStaff custom tools.

    Returns None if the SDK MCP server API is not available.
    """
    if not _SDK_AVAILABLE or create_sdk_mcp_server is None:
        logger.warning("mcp_server: claude_agent_sdk MCP API not available — custom tools disabled")
        return None

    # --- Core platform tools ------------------------------------------------

    @sdk_tool(
        "daily_log",
        "Append a timestamped entry to today's memory log. "
        "Use this to record significant events, decisions, or facts worth remembering.",
        {"message": str},
    )
    async def daily_log(args: dict) -> dict:
        args = _parse_args(args)
        message = args.get("message", "")
        if not message:
            return _text("No message provided.")
        try:
            from agent_runner.memory.daily_logger import DailyLogger
            DailyLogger(workspace_path).log(message)
            return _text(f"Logged: {message[:80]}")
        except Exception as exc:
            logger.error("daily_log: failed — %s", exc)
            return _text(f"Failed to log: {exc}")

    @sdk_tool(
        "memory_search",
        "Search across long-term memory (MEMORY.md) and all daily logs (memory/*.md) "
        "using text matching. Use this to recall past events, decisions, or facts. "
        "Results include matching lines with surrounding context, most recent files first.",
        {"query": str, "top_k": int},
    )
    async def memory_search(args: dict) -> dict:
        args = _parse_args(args)
        query = args.get("query", "").strip()
        if not query:
            return _text("No query provided.")

        top_k = int(args.get("top_k") or 5)
        query_lower = query.lower()

        memory_dir = workspace_path / "memory"
        dated_files = sorted(memory_dir.glob("*.md"), reverse=True) if memory_dir.exists() else []
        files_to_search = list(dated_files) + [workspace_path / "MEMORY.md"]

        results = []
        for f in files_to_search:
            if not f.exists():
                continue
            try:
                lines = f.read_text(encoding="utf-8").split("\n")
            except OSError:
                continue

            for i, line in enumerate(lines):
                if query_lower in line.lower():
                    start = max(0, i - 2)
                    end = min(len(lines), i + 3)
                    snippet = "\n".join(lines[start:end])
                    results.append(f"**{f.name}** (line {i + 1}):\n```\n{snippet}\n```")
                    if len(results) >= top_k:
                        break
            if len(results) >= top_k:
                break

        if not results:
            return _text(f"No results found for '{query}'.")
        return _text("\n\n---\n\n".join(results))

    @sdk_tool(
        "memory_get",
        "Read a specific memory file from the workspace. "
        "Use path relative to workspace root, e.g. 'MEMORY.md' or 'memory/2026-04-16.md'. "
        "Optionally specify start_line and num_lines to read a slice.",
        {"path": str, "start_line": int, "num_lines": int},
    )
    async def memory_get(args: dict) -> dict:
        args = _parse_args(args)
        rel_path = args.get("path", "").strip()
        if not rel_path:
            return _text("No path provided.")

        target = (workspace_path / rel_path).resolve()
        # Security: path traversal guard — must stay inside workspace
        if not str(target).startswith(str(workspace_path.resolve())):
            return _text("Access denied: path is outside the workspace directory.")

        if not target.exists():
            return _text(f"File not found: {rel_path}")

        try:
            content = target.read_text(encoding="utf-8")
        except OSError as exc:
            return _text(f"Error reading {rel_path}: {exc}")

        start_line = args.get("start_line")
        num_lines = args.get("num_lines")
        if start_line is not None or num_lines is not None:
            lines = content.split("\n")
            s = int(start_line or 1) - 1  # 1-indexed → 0-indexed
            n = int(num_lines) if num_lines is not None else len(lines)
            content = "\n".join(lines[s: s + n])

        return _text(content)

    # --- A2A send_message (Redis pub/sub) -----------------------------------

    if redis_a2a is not None:
        from agent_runner.tools.send_message import create_send_message_tool
        _send_message_fn = create_send_message_tool("mark", redis_a2a)

        @sdk_tool(
            "send_message",
            "Send a message to another agent and wait for their response. "
            "Use 'to' to specify the target agent ID (e.g. 'jarvis'). "
            "'message' is the natural language request to send.",
            {"to": str, "message": str},
        )
        async def send_message(args: dict) -> dict:
            args = _parse_args(args)
            return _text(await _send_message_fn(args))
    else:
        send_message = None  # Redis not configured

    # --- Cron tools ---------------------------------------------------------

    @sdk_tool(
        "cron_create",
        "Create a new scheduled task. "
        "schedule format: 'daily@HH:MM' | 'weekly@DOW@HH:MM' (mon/tue/.../sun) | "
        "'once@YYYY-MM-DD@HH:MM'. All times are Europe/Rome (CET/CEST). "
        "telegram_notify: set to true to receive a Telegram message with the result.",
        {"name": str, "schedule": str, "prompt": str, "session_id": str, "telegram_notify": bool},
    )
    async def cron_create(args: dict) -> dict:
        args = _parse_args(args)
        name = args.get("name", "").strip()
        schedule = args.get("schedule", "").strip()
        prompt_text = args.get("prompt", "").strip()
        if not name or not schedule or not prompt_text:
            return _text("name, schedule, and prompt are required.")
        try:
            from agent_runner.scheduler.cron_store import get_store
            store = get_store(workspace_path)
            entry = store.create(
                name=name,
                schedule=schedule,
                prompt=prompt_text,
                session_id=args.get("session_id") or "",
                telegram_notify=bool(args.get("telegram_notify", False)),
            )
            return _text(f"Created cron '{entry.name}' (id={entry.id}, schedule={entry.schedule})")
        except Exception as exc:
            return _text(f"Error: {exc}")

    @sdk_tool(
        "cron_list",
        "List all scheduled tasks (built-in and user-created) with their current status.",
        {},
    )
    async def cron_list(args: dict) -> dict:
        try:
            from agent_runner.scheduler.cron_store import get_store
            store = get_store(workspace_path)
            entries = store.all()
            if not entries:
                return _text("No scheduled tasks.")
            lines = []
            for e in entries:
                status = e.last_status if e.last_run else "never run"
                enabled = "enabled" if e.enabled else "disabled"
                builtin_tag = " [builtin]" if e.builtin else ""
                lines.append(
                    f"- **{e.name}** (id={e.id}){builtin_tag}\n"
                    f"  schedule={e.schedule}, {enabled}, last={status}\n"
                    f"  telegram_notify={e.telegram_notify}"
                )
            return _text("\n\n".join(lines))
        except Exception as exc:
            return _text(f"Error: {exc}")

    @sdk_tool(
        "cron_update",
        "Update a scheduled task by its id. "
        "Updatable fields: name, schedule, prompt, session_id, telegram_notify, enabled.",
        {"id": str, "name": str, "schedule": str, "prompt": str,
          "session_id": str, "telegram_notify": bool, "enabled": bool},
    )
    async def cron_update(args: dict) -> dict:
        args = _parse_args(args)
        cron_id = args.get("id", "").strip()
        if not cron_id:
            return _text("id is required.")
        updates = {k: v for k, v in args.items() if k != "id" and v is not None}
        if not updates:
            return _text("No fields to update.")
        try:
            from agent_runner.scheduler.cron_store import get_store
            store = get_store(workspace_path)
            entry = store.update(cron_id, **updates)
            return _text(f"Updated cron '{entry.name}' (id={entry.id})")
        except Exception as exc:
            return _text(f"Error: {exc}")

    @sdk_tool(
        "cron_delete",
        "Delete a user-created scheduled task by its id. "
        "Built-in tasks cannot be deleted — use cron_update with enabled=false to disable them.",
        {"id": str},
    )
    async def cron_delete(args: dict) -> dict:
        args = _parse_args(args)
        cron_id = args.get("id", "").strip()
        if not cron_id:
            return _text("id is required.")
        try:
            from agent_runner.scheduler.cron_store import get_store
            store = get_store(workspace_path)
            store.delete(cron_id)
            return _text(f"Deleted cron id={cron_id}")
        except Exception as exc:
            return _text(f"Error: {exc}")

    # --- Domain-specific tools -----------------------------------------------

    @sdk_tool(
        "route_email_payload",
        "Route a structured email intelligence payload received from EmailIntelligenceAgent. "
        "Input is a JSON string matching the EmailIntelligencePayload schema (email_id, "
        "classification, security_signals, routing, policy, redaction). "
        "Returns a JSON routing decision produced by HybridChiefOfStaffAgent.",
        {"payload": str},
    )
    async def route_email_payload(args: dict) -> dict:
        args = _parse_args(args)
        payload_raw = args.get("payload", "").strip()
        if not payload_raw:
            return _text("payload is required.")

        try:
            payload_dict = json.loads(payload_raw)
        except (json.JSONDecodeError, ValueError) as exc:
            return _text(f"Invalid JSON payload: {exc}")

        try:
            from security.config_loader import load_all
            from security.policy_engine import PolicyEngine
            from security.chief_of_staff_agent import HybridChiefOfStaffAgent
            from security.audit_writer import AuditWriter

            cfg = load_all()
            policy_engine = PolicyEngine(
                permissions=cfg["permissions"],
                approval_policy=cfg["approval_policy"],
                model_routing_rules=cfg["model_routing_rules"],
                memory_policy=cfg["memory_policy"],
            )
            agent = HybridChiefOfStaffAgent(policy_engine=policy_engine)
            routing_decision = agent.route(payload_dict)

            # Write audit entry
            audit_path = Path("var/audit/audit.jsonl")
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            writer = AuditWriter(str(audit_path))
            writer.write(writer.make_event(
                event_id=str(uuid.uuid4()),
                event_type="routing",
                agent_id="mark",
                action="route_email_payload",
                outcome=routing_decision.get("decision_type", "unknown"),
                email_id=payload_dict.get("email_id"),
                details={
                    "decision_id": routing_decision.get("decision_id"),
                    "final_targets": routing_decision.get("final_targets", []),
                    "actions": routing_decision.get("actions", []),
                    "confidence": routing_decision.get("confidence"),
                    "priority": routing_decision.get("priority"),
                },
            ))

            return _text(json.dumps(routing_decision, ensure_ascii=False))
        except Exception as exc:
            logger.error("route_email_payload: failed — %s", exc)
            return _text(f"Error routing payload: {exc}")

    @sdk_tool(
        "get_routing_history",
        "Return the last N routing decisions from the audit log. "
        "Filters audit entries to those produced by route_email_payload. "
        "Each entry includes decision_id, email_id, final_targets, actions, and confidence.",
        {"last_n": int},
    )
    async def get_routing_history(args: dict) -> dict:
        args = _parse_args(args)
        last_n = int(args.get("last_n") or 20)
        audit_path = Path("var/audit/audit.jsonl")
        if not audit_path.exists():
            return _text(json.dumps([]))
        try:
            lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
            entries = []
            for line in lines:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("action") == "route_email_payload":
                        entries.append(entry)
                except (json.JSONDecodeError, ValueError):
                    continue
            return _text(json.dumps(entries[-last_n:], ensure_ascii=False))
        except Exception as exc:
            logger.error("get_routing_history: failed — %s", exc)
            return _text(f"Error reading routing history: {exc}")

    @sdk_tool(
        "route_case",
        "Produce a routing decision for a case derived from external email intelligence. "
        "Input is structured case data (case_id, summary, detected_domains, detected_entities, "
        "raw_signals). Returns a JSON routing decision matching routing-decision-schema.json. "
        "Actions: ignore | archive | route | escalate. "
        "Always set human_approval_required=true when the case involves irreversible actions "
        "(payments, external communications, deletions) or genuine policy ambiguity.",
        {
            "case_id": str,
            "summary": str,
            "detected_domains": str,  # comma-separated list
            "detected_entities": str,  # comma-separated key entities
            "raw_signals": str,        # JSON string: {"urgency": bool, "authority_claim": bool, ...}
        },
    )
    async def route_case(args: dict) -> dict:
        args = _parse_args(args)
        case_id = args.get("case_id", "").strip()
        summary = args.get("summary", "").strip()

        if not case_id or not summary:
            return _text("case_id and summary are required.")

        # Parse raw signals for security flag detection
        raw_signals_str = args.get("raw_signals", "{}")
        try:
            signals = json.loads(raw_signals_str) if isinstance(raw_signals_str, str) else raw_signals_str
        except (json.JSONDecodeError, ValueError):
            signals = {}

        # Detect security flags
        security_flags = []
        flag_map = {
            "urgency_pressure": signals.get("urgency", False),
            "authority_claim": signals.get("authority_claim", False),
            "legal_threat": signals.get("legal_threat", False),
            "financial_pressure": signals.get("financial_pressure", False),
            "emotional_pressure": signals.get("emotional_pressure", False),
        }
        for flag, detected in flag_map.items():
            if detected:
                security_flags.append(flag)

        # Build the decision skeleton — the agent fills action/owners/rationale via reasoning
        decision = {
            "case_id": case_id,
            "action": "route",          # agent will override via reasoning
            "owners": [],
            "urgency": "low",
            "rationale": "",
            "routing_target": None,
            "human_approval_required": False,
            "security_flags": security_flags,
            "metadata": {
                "detected_domains": [d.strip() for d in args.get("detected_domains", "").split(",") if d.strip()],
                "detected_entities": [e.strip() for e in args.get("detected_entities", "").split(",") if e.strip()],
            },
        }

        result = json.dumps(decision, ensure_ascii=False, indent=2)
        return _text(result)

    # --- Assemble server ----------------------------------------------------

    all_tools = [
        daily_log, memory_search, memory_get,
        cron_create, cron_list, cron_update, cron_delete,
        route_email_payload, get_routing_history, route_case,
    ]
    if send_message is not None:
        all_tools.append(send_message)

    try:
        server = create_sdk_mcp_server(name="mark-tools", tools=all_tools)
        logger.info("mcp_server: in-process MCP server created with %d tools", len(all_tools))
        return server
    except Exception as exc:
        logger.error("mcp_server: failed to create server — %s", exc)
        return None
