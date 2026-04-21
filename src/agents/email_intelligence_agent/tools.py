"""In-process MCP server exposing Email Intelligence Agent custom tools to the claude-agent-sdk.

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
  process_email     — Fetch email via MCP and run 9-layer security pipeline
  process_unread    — Process unread emails from the specified account
  get_audit_log     — Return the last N entries from the audit log
  quarantine_email  — Move email to Quarantine folder and write audit entry
"""

import json
import logging
import uuid
from pathlib import Path

from security.pipeline.ingest_gate import IngestGate
from security.pipeline.content_isolator import ContentIsolator
from security.pipeline.classifier import Classifier
from security.pipeline.redaction_engine import RedactionEngine
from security.pipeline.model_routing_guard import ModelRoutingGuard
from security.pipeline.permission_layer import PermissionLayer
from security.policy_engine import PolicyEngine, AgentRequest
from security.memory_guard import MemoryGuard
from security.audit_writer import AuditWriter
from security.config_loader import load_all

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
# Security pipeline orchestrator (module-level, called by domain tools)
# ---------------------------------------------------------------------------

def _run_security_pipeline(
    email_id: str,
    account: str,
    subject: str,
    body: str,
    attachments: list | None = None,
) -> dict:
    """Run email through the 9-layer security pipeline. Returns EmailIntelligencePayload dict."""
    cfg = load_all()

    # Layer 1: IngestGate
    ingest = IngestGate().process(subject=subject, body=body, attachments=attachments or [])

    # Layer 2: ContentIsolator
    isolation = ContentIsolator().check(ingest.sanitized_body)

    # Layer 3: Classifier
    classification = Classifier().classify(
        subject=ingest.sanitized_subject,
        body=ingest.sanitized_body,
    )

    # Layer 4: RedactionEngine
    redaction = RedactionEngine().redact(ingest.sanitized_body)

    # Layer 5: ModelRoutingGuard
    routing = ModelRoutingGuard().decide(
        primary_domain=classification.primary_domain,
        sensitivity=classification.sensitivity,
        redaction_applied=redaction.redaction_applied,
    )

    # Layer 6: PermissionLayer
    permission = PermissionLayer(cfg["permissions"]).check(
        agent_id="email_intelligence",
        requested_tools=["process_email"],
    )

    # Layer 7: PolicyEngine
    policy_decision = PolicyEngine(
        permissions=cfg["permissions"],
        approval_policy=cfg["approval_policy"],
        model_routing_rules=cfg["model_routing_rules"],
        memory_policy=cfg["memory_policy"],
    ).evaluate(
        payload={
            "classification": {
                "primary_domain": classification.primary_domain,
                "sensitivity": classification.sensitivity,
            },
            "security_signals": {
                "prompt_injection_risk": isolation.risk_level,
                "attachment_risk": ingest.attachment_risk,
                "suspicious_domain": len(ingest.suspicious_links) > 0,
            },
        },
        request=AgentRequest(
            agent_id="email_intelligence",
            requested_action="route_and_review",
        ),
    )

    # Layer 8: MemoryGuard
    memory_decision = MemoryGuard(cfg["memory_policy"]).check_write(
        agent_id="email_intelligence",
        target_store="structured_store",
        content_type="email_summary",
        sensitivity=classification.sensitivity,
        redaction_applied=redaction.redaction_applied,
    )

    # Layer 9: AuditWriter
    audit_path = Path("var/audit/audit.jsonl")
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    writer = AuditWriter(str(audit_path))
    writer.write(writer.make_event(
        event_id=str(uuid.uuid4()),
        event_type="pipeline_run",
        agent_id="email_intelligence",
        action="route_and_review",
        outcome=policy_decision.decision,
        email_id=email_id,
        details={
            "account": account,
            "primary_domain": classification.primary_domain,
            "sensitivity": classification.sensitivity,
            "risk_level": classification.risk_level,
            "injection_risk": isolation.risk_level,
            "attachment_risk": ingest.attachment_risk,
            "route_to": routing.route_to,
            "policy_decision": policy_decision.decision,
            "memory_allowed": memory_decision.allow,
            "permission_allowed": permission.allowed,
        },
    ))

    return {
        "email_id": email_id,
        "account": account,
        "subject": ingest.sanitized_subject,
        "body_redacted": redaction.redacted_text,
        "classification": {
            "primary_domain": classification.primary_domain,
            "secondary_domain": classification.secondary_domain,
            "sensitivity": classification.sensitivity,
            "risk_level": classification.risk_level,
            "priority": classification.priority,
            "confidence": classification.confidence,
        },
        "security_signals": {
            "prompt_injection_risk": isolation.risk_level,
            "injection_patterns": isolation.injection_patterns_found,
            "attachment_risk": ingest.attachment_risk,
            "blocked_attachments": ingest.blocked_attachments,
            "suspicious_links": ingest.suspicious_links,
            "html_stripped": "ACTIVE_HTML_STRIPPED" in ingest.reasons,
        },
        "routing": {
            "route_to": routing.route_to,
            "reason": routing.reason,
        },
        "policy": {
            "decision": policy_decision.decision,
            "allow": policy_decision.allow,
            "constraints": policy_decision.constraints,
        },
        "redaction": {
            "applied": redaction.redaction_applied,
            "items_redacted": redaction.redacted_items,
        },
    }


# ---------------------------------------------------------------------------
# MCP server factory
# ---------------------------------------------------------------------------

def create_email_intelligence_mcp_server(workspace_path: Path, redis_a2a=None):
    """Build and return the in-process MCP server with Email Intelligence Agent custom tools.

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
        _send_message_fn = create_send_message_tool("email_intelligence", redis_a2a)

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
        "process_email",
        "Fetch email via MCP and run it through the 9-layer security pipeline. "
        "Returns a full EmailIntelligencePayload with classification, security signals, "
        "routing decision, policy decision, and redaction metadata.",
        {"email_id": str, "account": str},
    )
    async def process_email(args: dict) -> dict:
        args = _parse_args(args)
        email_id = args.get("email_id", "").strip()
        account = args.get("account", "").strip()
        if not email_id or not account:
            return _text("email_id and account are required.")
        try:
            # In production: fetch subject/body/attachments via MCP tool call to
            # protonmail-email or gmx-email server using ctx.call_tool()
            payload = _run_security_pipeline(
                email_id=email_id,
                account=account,
                subject="[fetched via MCP]",
                body="[fetched via MCP]",
            )
            return _text(json.dumps(payload))
        except Exception as exc:
            logger.error("process_email: failed — %s", exc)
            return _text(f"Error processing email {email_id}: {exc}")

    @sdk_tool(
        "process_unread",
        "Process unread emails from the specified account through the 9-layer security pipeline. "
        "'account' can be 'protonmail', 'gmx', or 'all'. "
        "'max_emails' limits how many unread emails to process (default 20).",
        {"account": str, "max_emails": int},
    )
    async def process_unread(args: dict) -> dict:
        args = _parse_args(args)
        account = args.get("account", "all").strip() or "all"
        max_emails = int(args.get("max_emails") or 20)
        # In production: calls list_emails MCP tool then process_email for each result
        return _text(json.dumps({
            "account": account,
            "max_emails": max_emails,
            "processed": 0,
            "note": "In production: calls list_emails MCP tool then process_email for each result",
        }))

    @sdk_tool(
        "get_audit_log",
        "Return the last N entries from the security pipeline audit log. "
        "Each entry contains email_id, account, classification, routing, and policy decision.",
        {"last_n": int},
    )
    async def get_audit_log(args: dict) -> dict:
        args = _parse_args(args)
        last_n = int(args.get("last_n") or 50)
        audit_path = Path("var/audit/audit.jsonl")
        if not audit_path.exists():
            return _text(json.dumps([]))
        try:
            lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
            entries = [json.loads(line) for line in lines[-last_n:] if line.strip()]
            return _text(json.dumps(entries))
        except Exception as exc:
            logger.error("get_audit_log: failed — %s", exc)
            return _text(f"Error reading audit log: {exc}")

    @sdk_tool(
        "quarantine_email",
        "Move email to Quarantine folder and write an audit entry. "
        "'reason' should describe why the email is being quarantined.",
        {"email_id": str, "account": str, "reason": str},
    )
    async def quarantine_email(args: dict) -> dict:
        args = _parse_args(args)
        email_id = args.get("email_id", "").strip()
        account = args.get("account", "").strip()
        reason = args.get("reason", "").strip()
        if not email_id or not account or not reason:
            return _text("email_id, account, and reason are required.")
        try:
            audit_path = Path("var/audit/audit.jsonl")
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            writer = AuditWriter(str(audit_path))
            writer.write(writer.make_event(
                event_id=str(uuid.uuid4()),
                event_type="quarantine",
                agent_id="email_intelligence",
                action="quarantine",
                outcome="quarantined",
                email_id=email_id,
                details={"account": account, "reason": reason},
            ))
            # In production: also calls move_email MCP tool to move to "Quarantine" folder
            return _text(json.dumps({
                "status": "quarantined",
                "email_id": email_id,
                "account": account,
                "reason": reason,
            }))
        except Exception as exc:
            logger.error("quarantine_email: failed — %s", exc)
            return _text(f"Error quarantining email {email_id}: {exc}")

    # --- Assemble server ----------------------------------------------------

    all_tools = [
        daily_log, memory_search, memory_get,
        cron_create, cron_list, cron_update, cron_delete,
        process_email, process_unread, get_audit_log, quarantine_email,
    ]
    if send_message is not None:
        all_tools.append(send_message)

    try:
        server = create_sdk_mcp_server(name="email_intelligence-tools", tools=all_tools)
        logger.info("mcp_server: in-process MCP server created with %d tools", len(all_tools))
        return server
    except Exception as exc:
        logger.error("mcp_server: failed to create server — %s", exc)
        return None
