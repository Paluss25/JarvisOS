"""Failing unit tests for push_training_to_calendar (P3.T1).

These tests are written before the implementation exists (P3.T2).
They will fail with KeyError / StopIteration until the tool is registered
in create_chief_mcp_server with a redis_a2a dependency.
"""
import asyncio
import datetime
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# ---------------------------------------------------------------------------
# Mock heavy optional deps (must happen before any agent_runner import).
# ---------------------------------------------------------------------------
if "opentelemetry" not in sys.modules:
    _otel_mock = MagicMock()
    _otel_trace_mock = MagicMock()
    _otel_trace_mock.StatusCode = type("StatusCode", (), {"ERROR": "ERROR", "OK": "OK"})
    sys.modules["opentelemetry"] = _otel_mock
    sys.modules["opentelemetry.trace"] = _otel_trace_mock
    sys.modules["opentelemetry.sdk"] = MagicMock()
    sys.modules["opentelemetry.sdk.trace"] = MagicMock()
    sys.modules["opentelemetry.exporter"] = MagicMock()
    sys.modules["opentelemetry.exporter.otlp"] = MagicMock()
    sys.modules["opentelemetry.exporter.otlp.proto"] = MagicMock()
    sys.modules["opentelemetry.exporter.otlp.proto.grpc"] = MagicMock()
    sys.modules["opentelemetry.exporter.otlp.proto.grpc.trace_exporter"] = MagicMock()
    sys.modules["opentelemetry.instrumentation"] = MagicMock()

if "prometheus_client" not in sys.modules:
    _prom_mock = MagicMock()
    _prom_mock.Counter = MagicMock(return_value=MagicMock())
    _prom_mock.Gauge = MagicMock(return_value=MagicMock())
    _prom_mock.Histogram = MagicMock(return_value=MagicMock())
    sys.modules["prometheus_client"] = _prom_mock

if "asyncpg" not in sys.modules:
    sys.modules["asyncpg"] = MagicMock()

if "httpx" not in sys.modules:
    sys.modules["httpx"] = MagicMock()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _find_tool(server, name: str):
    """Return the tool function registered under *name* in the MCP server."""
    for tool in server._tools:
        if tool.name == name:
            return tool.fn
    raise KeyError(f"Tool '{name}' not registered")


def _make_redis_a2a_mock():
    """Return a minimal RedisA2A-like mock that satisfies create_send_message_tool."""
    redis_a2a = MagicMock()
    # on_message is called synchronously at server construction time
    redis_a2a.on_message = MagicMock()
    return redis_a2a


def _make_send_message_fn_mock():
    """Return an AsyncMock that replaces the inner send_message fn."""
    mock_fn = AsyncMock(return_value="ok")
    return mock_fn


def _build_dos_server_with_mock_a2a(mock_send_message_fn):
    """Build the DoS MCP server with a mock redis_a2a.

    The create_send_message_tool factory is patched so the inner send_message
    coroutine is replaced with *mock_send_message_fn*, allowing us to inspect
    the exact args forwarded to the A2A transport.
    """
    from agents.dos.tools import create_chief_mcp_server

    redis_a2a = _make_redis_a2a_mock()

    with patch(
        "agent_runner.tools.send_message.create_send_message_tool",
        return_value=mock_send_message_fn,
    ):
        server = create_chief_mcp_server(Path("/tmp"), redis_a2a=redis_a2a)

    return server


# ---------------------------------------------------------------------------
# Test 1 — push_training_to_calendar sends correct A2A message
# ---------------------------------------------------------------------------


def test_push_sends_correct_a2a_message():
    """push_training_to_calendar must send an A2A message to 'mt' containing
    'sync training week 21' and the current ISO year.
    """
    mock_send_fn = _make_send_message_fn_mock()
    server = _build_dos_server_with_mock_a2a(mock_send_fn)

    tool_fn = _find_tool(server, "push_training_to_calendar")
    _run(tool_fn({"week_number": 21}))

    mock_send_fn.assert_called_once()
    call_args = mock_send_fn.call_args
    # The tool calls _send_message_fn({"to": "mt", "message": "..."})
    sent_payload = call_args.args[0] if call_args.args else call_args.kwargs

    assert sent_payload.get("to") == "mt", (
        f"Expected to='mt', got: {sent_payload.get('to')!r}"
    )

    current_year = datetime.date.today().isocalendar()[0]
    msg = sent_payload.get("message", "")
    assert "sync training week 21" in msg, (
        f"Expected 'sync training week 21' in message, got: {msg!r}"
    )
    assert str(current_year) in msg, (
        f"Expected year {current_year} in message, got: {msg!r}"
    )


# ---------------------------------------------------------------------------
# Test 2 — push_training_to_calendar returns error when week_number is missing
# ---------------------------------------------------------------------------


def test_push_missing_week_number_returns_error():
    """push_training_to_calendar must return an error response when week_number
    is absent (or zero/falsy) without calling the A2A send function.
    """
    mock_send_fn = _make_send_message_fn_mock()
    server = _build_dos_server_with_mock_a2a(mock_send_fn)

    tool_fn = _find_tool(server, "push_training_to_calendar")
    result = _run(tool_fn({}))

    mock_send_fn.assert_not_called()

    # Result must communicate the error — check the MCP text content structure
    if isinstance(result, dict) and "content" in result:
        text = result["content"][0]["text"]
    elif isinstance(result, str):
        text = result
    else:
        text = str(result)

    assert text, "Expected a non-empty error message for missing week_number"
    # The response should signal an error, not silently succeed
    lower = text.lower()
    assert any(kw in lower for kw in ("error", "required", "missing", "week")), (
        f"Expected an error message, got: {text!r}"
    )
