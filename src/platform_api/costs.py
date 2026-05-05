"""Cost and model usage endpoints backed by trace spans."""

from collections import defaultdict
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from platform_api.db import get_pool

router = APIRouter(prefix="/api/costs", tags=["costs"])
_security = HTTPBearer()


async def _get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> dict[str, Any]:
    from platform_api.auth import decode_access_token

    return decode_access_token(credentials.credentials)


def _money(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _int(value: Any) -> int:
    if value is None:
        return 0
    return int(value)


def normalize_cost_group(row: dict) -> dict:
    input_tokens = _int(row.get("input_tokens"))
    output_tokens = _int(row.get("output_tokens"))
    return {
        "key": row.get("key") or "unknown",
        "cost_usd": round(_money(row.get("cost_usd")), 6),
        "tokens": input_tokens + output_tokens,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "span_count": _int(row.get("span_count")),
        "duration_ms": _int(row.get("duration_ms")),
    }


def _percentile_nearest(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(min(round((len(ordered) - 1) * percentile), len(ordered) - 1), 0)
    return ordered[index]


def _group_spans(spans: list[dict], key_fn) -> list[dict]:
    grouped: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "cost_usd": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "span_count": 0,
        "duration_ms": 0,
    })
    for span in spans:
        key = key_fn(span) or "unknown"
        row = grouped[str(key)]
        row["cost_usd"] += _money(span.get("cost_usd"))
        row["input_tokens"] += _int(span.get("input_tokens"))
        row["output_tokens"] += _int(span.get("output_tokens"))
        row["span_count"] += 1
        row["duration_ms"] += _int(span.get("duration_ms"))

    rows = [normalize_cost_group({"key": key, **value}) for key, value in grouped.items()]
    return sorted(rows, key=lambda item: item["cost_usd"], reverse=True)


def build_cost_summary(spans: list[dict]) -> dict:
    input_tokens = sum(_int(span.get("input_tokens")) for span in spans)
    output_tokens = sum(_int(span.get("output_tokens")) for span in spans)
    total_cost = sum(_money(span.get("cost_usd")) for span in spans)
    durations = [_int(span.get("duration_ms")) for span in spans if span.get("duration_ms") is not None]

    return {
        "total_cost_usd": round(total_cost, 6),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "tokens": input_tokens + output_tokens,
        "span_count": len(spans),
        "p95_latency_ms": _percentile_nearest(durations, 0.95),
        "by_agent": _group_spans(spans, lambda span: span.get("agent_id")),
        "by_model": _group_spans(
            spans,
            lambda span: "/".join(
                part for part in [span.get("provider"), span.get("model")] if part
            ),
        ),
        "by_task": _group_spans(spans, lambda span: span.get("task_id")),
        "by_session": _group_spans(spans, lambda span: span.get("session_id")),
    }


@router.get("/summary")
async def get_cost_summary(
    agent_id: str | None = Query(None),
    task_id: str | None = Query(None),
    limit: int = Query(1000, ge=1, le=5000),
    _user=Depends(_get_current_user),
):
    pool = await get_pool()
    conditions: list[str] = []
    params: list[Any] = []

    if agent_id:
        params.append(agent_id)
        conditions.append(f"agent_id = ${len(params)}")
    if task_id:
        params.append(task_id)
        conditions.append(f"task_id = ${len(params)}")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)
    rows = await pool.fetch(
        f"""
        SELECT agent_id, task_id, session_id, model, provider, duration_ms,
               input_tokens, output_tokens, cost_usd
        FROM trace_spans
        {where}
        ORDER BY ts_start DESC
        LIMIT ${len(params)}
        """,
        *params,
    )
    return build_cost_summary([dict(row) for row in rows])
