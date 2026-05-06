"""Chat Hub orchestration endpoints."""

import json
import logging
import os
from typing import Any
from uuid import UUID, uuid4

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from agent_runner.comms.message import A2AMessage
from platform_api.a2a import normalize_a2a_event
from platform_api.audit import AuditEvent, audit
from platform_api.db import get_pool
from platform_api.decisions import normalize_decision

router = APIRouter(prefix="/api/chat", tags=["chat"])
_security = HTTPBearer()
logger = logging.getLogger(__name__)


async def _get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> dict[str, Any]:
    from platform_api.auth import decode_access_token

    return decode_access_token(credentials.credentials)


class ChatContextRequest(BaseModel):
    agent_id: str
    task_id: str | None = None
    trace_id: str | None = None
    log_event_id: str | None = None
    memory_event_id: str | None = None


class ChatA2AForwardRequest(BaseModel):
    from_agent: str
    to_agent: str
    message: str = Field(min_length=1)
    task_id: str | None = None
    trace_id: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class ChatDecisionRequest(BaseModel):
    agent_id: str
    reply: str = Field(min_length=1)
    title: str | None = None
    task_id: str | None = None
    trace_id: str | None = None
    message_id: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


def _uuid_or_none(value: str | UUID | None) -> UUID | None:
    if value is None or isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except ValueError:
        return None


def build_chat_context(
    *,
    agent_id: str,
    task_id: str | None = None,
    trace_id: str | None = None,
    log_event_id: str | None = None,
    memory_event_id: str | None = None,
) -> dict[str, Any]:
    attachments: list[dict[str, str]] = []
    if task_id:
        attachments.append({"kind": "task", "id": task_id, "href": f"/tasks/{task_id}"})
    if trace_id:
        attachments.append({"kind": "trace", "id": trace_id, "href": f"/traces/{trace_id}"})
    if log_event_id:
        attachments.append({"kind": "log", "id": log_event_id, "href": f"/logs/{log_event_id}"})
    if memory_event_id:
        attachments.append({"kind": "memory", "id": memory_event_id, "href": f"/memory/events/{memory_event_id}"})

    return {
        "agent_id": agent_id,
        "metrics": {"attachment_count": len(attachments)},
        "links": {
            "agent": f"/agents/{agent_id}",
            "chat": f"/agents/{agent_id}/chat",
            "cockpit": f"/agents/{agent_id}/cockpit",
            "task": f"/tasks/{task_id}" if task_id else None,
            "trace": f"/traces/{trace_id}" if trace_id else None,
            "log": f"/logs/{log_event_id}" if log_event_id else None,
            "logs": f"/logs?trace_id={trace_id}" if trace_id else f"/logs?task_id={task_id}" if task_id else "/logs",
            "memory": f"/memory/events/{memory_event_id}" if memory_event_id else "/memory",
            "a2a": "/a2a",
        },
        "attachments": attachments,
    }


def build_chat_a2a_event(
    *,
    from_agent: str,
    to_agent: str,
    message: str,
    task_id: str | UUID | None = None,
    trace_id: str | None = None,
    context: dict[str, Any] | None = None,
    message_id: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    resolved_message_id = message_id or str(uuid4())
    resolved_correlation_id = correlation_id or resolved_message_id
    payload = {
        "id": resolved_message_id,
        "from_agent": from_agent,
        "to_agent": to_agent,
        "type": "request",
        "mode": "async",
        "status": "queued",
        "correlation_id": resolved_correlation_id,
        "root_correlation_id": resolved_correlation_id,
        "hop_count": 0,
        "max_hops": 5,
        "message": message,
        "context": context or {},
    }
    return {
        "event_type": "a2a_request",
        "severity": "info",
        "agent_id": from_agent,
        "task_id": _uuid_or_none(task_id),
        "trace_id": trace_id,
        "a2a_message_id": resolved_message_id,
        "source": "chat_hub",
        "payload": payload,
    }


def build_chat_a2a_message(event: dict[str, Any]) -> A2AMessage:
    payload = event.get("payload") or {}
    return A2AMessage(
        from_agent=payload["from_agent"],
        to_agent=payload["to_agent"],
        type=payload.get("type") or "request",
        payload=payload.get("message") or "",
        id=payload.get("id") or event.get("a2a_message_id") or str(uuid4()),
        correlation_id=payload.get("correlation_id"),
        mode=payload.get("mode") or "async",
        root_correlation_id=payload.get("root_correlation_id"),
        parent_correlation_id=payload.get("parent_correlation_id"),
        hop_count=payload.get("hop_count") or 0,
        max_hops=payload.get("max_hops") or 5,
    )


async def _publish_a2a_message(message: A2AMessage) -> None:
    url = os.environ.get("REDIS_URL", "")
    password = os.environ.get("REDIS_PASSWORD", "")
    if not url or not (url.startswith("redis://") or url.startswith("rediss://")):
        host = os.environ.get("REDIS_HOST", "localhost")
        port = os.environ.get("REDIS_PORT", "6379")
        url = f"redis://{host}:{port}"

    kwargs: dict[str, Any] = {"decode_responses": True}
    if password:
        kwargs["password"] = password
    redis = aioredis.from_url(url, **kwargs)
    try:
        await redis.publish(f"a2a:{message.to_agent}", json.dumps(message.__dict__))
    finally:
        await redis.aclose()


def build_chat_decision_payload(
    *,
    agent_id: str,
    reply: str,
    title: str | None = None,
    task_id: str | UUID | None = None,
    trace_id: str | None = None,
    message_id: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_message_id = message_id or str(uuid4())
    resolved_title = title or (reply[:88] + "..." if len(reply) > 91 else reply)
    resolved_context = context or {}
    return {
        "agent_id": agent_id,
        "task_id": _uuid_or_none(task_id),
        "trace_id": trace_id,
        "title": resolved_title,
        "summary": reply,
        "decision_type": "chat_saved_reply",
        "status": "approved",
        "evidence": [
            {"kind": "chat_message", "id": resolved_message_id},
            {"kind": "context", "value": resolved_context},
        ],
        "payload": {
            "source": "chat_hub",
            "message_id": resolved_message_id,
            "reply": reply,
            "context": resolved_context,
        },
    }


@router.get("/context")
async def get_chat_context(
    agent_id: str = Query(...),
    task_id: str | None = Query(None),
    trace_id: str | None = Query(None),
    log_event_id: str | None = Query(None),
    memory_event_id: str | None = Query(None),
    _user=Depends(_get_current_user),
):
    return build_chat_context(
        agent_id=agent_id,
        task_id=task_id,
        trace_id=trace_id,
        log_event_id=log_event_id,
        memory_event_id=memory_event_id,
    )


@router.post("/context")
async def post_chat_context(req: ChatContextRequest, _user=Depends(_get_current_user)):
    return build_chat_context(
        agent_id=req.agent_id,
        task_id=req.task_id,
        trace_id=req.trace_id,
        log_event_id=req.log_event_id,
        memory_event_id=req.memory_event_id,
    )


@router.post("/a2a", status_code=201)
async def forward_chat_a2a(req: ChatA2AForwardRequest, user=Depends(_get_current_user)):
    pool = await get_pool()
    event = build_chat_a2a_event(
        from_agent=req.from_agent,
        to_agent=req.to_agent,
        message=req.message,
        task_id=req.task_id,
        trace_id=req.trace_id,
        context=req.context,
    )
    try:
        await _publish_a2a_message(build_chat_a2a_message(event))
        event["payload"]["status"] = "sent"
    except Exception as exc:
        logger.warning("chat: A2A publish failed — %s", exc)
        event["severity"] = "warning"
        event["payload"]["status"] = "publish_failed"
        event["payload"]["publish_error"] = str(exc)

    row = await pool.fetchrow(
        """
        INSERT INTO platform_events
            (event_type, severity, agent_id, task_id, trace_id, a2a_message_id, source, payload)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
        RETURNING id, ts, event_type, severity, task_id, trace_id, a2a_message_id, payload
        """,
        event["event_type"],
        event["severity"],
        event["agent_id"],
        event["task_id"],
        event["trace_id"],
        event["a2a_message_id"],
        event["source"],
        json.dumps(event["payload"]),
    )
    normalized = normalize_a2a_event(dict(row))
    await audit.log(AuditEvent(
        category="platform",
        action="chat_a2a_forwarded",
        source="api",
        agent_id=req.from_agent,
        user_id=user.get("sub") if hasattr(user, "get") else None,
        detail={
            "from_agent": req.from_agent,
            "to_agent": req.to_agent,
            "a2a_message_id": normalized["message_id"],
            "task_id": req.task_id,
            "trace_id": req.trace_id,
        },
    ))
    return normalized


@router.post("/decisions", status_code=201)
async def save_chat_decision(req: ChatDecisionRequest, user=Depends(_get_current_user)):
    pool = await get_pool()
    decision = build_chat_decision_payload(
        agent_id=req.agent_id,
        reply=req.reply,
        title=req.title,
        task_id=req.task_id,
        trace_id=req.trace_id,
        message_id=req.message_id,
        context=req.context,
    )
    row = await pool.fetchrow(
        """
        INSERT INTO decisions
            (agent_id, task_id, trace_id, title, summary, decision_type, status, evidence, payload)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb)
        RETURNING id, ts, agent_id, task_id, trace_id, title, summary,
                  decision_type, confidence, status, evidence, payload
        """,
        decision["agent_id"],
        decision["task_id"],
        decision["trace_id"],
        decision["title"],
        decision["summary"],
        decision["decision_type"],
        decision["status"],
        json.dumps(decision["evidence"]),
        json.dumps(decision["payload"]),
    )
    normalized = normalize_decision(dict(row))
    await audit.log(AuditEvent(
        category="platform",
        action="chat_decision_saved",
        source="api",
        agent_id=req.agent_id,
        user_id=user.get("sub") if hasattr(user, "get") else None,
        detail={
            "decision_id": normalized["id"],
            "message_id": req.message_id,
            "task_id": req.task_id,
            "trace_id": req.trace_id,
        },
    ))
    return normalized
