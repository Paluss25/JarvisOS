"""Shared test configuration and fixtures.

Installs module-level mocks for optional heavy dependencies (claude_agent_sdk,
agno, etc.) before any test module is collected, so that imports in src.*
never fail due to missing packages in the test venv.
"""
import sys
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Mock claude_agent_sdk — not installed in test venv
# ---------------------------------------------------------------------------
if "claude_agent_sdk" not in sys.modules:
    _sdk_mock = MagicMock()
    _sdk_mock.ClaudeAgentOptions = MagicMock
    _sdk_mock.ClaudeSDKClient = MagicMock
    _sdk_mock.RateLimitEvent = type("RateLimitEvent", (), {})
    _sdk_mock.ResultMessage = type(
        "ResultMessage", (), {"total_cost_usd": 0.0, "duration_ms": 0, "num_turns": 0}
    )
    _sdk_mock.StreamEvent = type("StreamEvent", (), {"event": {}})
    _sdk_mock.TaskNotificationMessage = type("TaskNotificationMessage", (), {})
    _sdk_mock.TaskProgressMessage = type("TaskProgressMessage", (), {})
    _sdk_mock.TaskStartedMessage = type("TaskStartedMessage", (), {})
    _sdk_mock.ThinkingConfigAdaptive = MagicMock

    # Make `tool` (sdk_tool) a faithful decorator factory so that tests can
    # call the registered tool functions via server._tools.
    class _ToolEntry:
        """Minimal stand-in for a registered SDK tool."""
        __slots__ = ("name", "description", "schema", "fn")

        def __init__(self, name: str, description: str, schema, fn):
            self.name = name
            self.description = description
            self.schema = schema
            self.fn = fn

    def _sdk_tool_factory(name, description="", schema=None):
        """Return a decorator that wraps fn in a _ToolEntry."""
        def decorator(fn):
            return _ToolEntry(name=name, description=description, schema=schema, fn=fn)
        return decorator

    class _FakeServer:
        """Minimal stand-in for the SDK MCP server returned by create_sdk_mcp_server."""
        def __init__(self, name: str, tools: list):
            self._name = name
            self._tools = list(tools)

    def _create_sdk_mcp_server(name, tools):
        return _FakeServer(name=name, tools=tools)

    _sdk_mock.tool = _sdk_tool_factory
    _sdk_mock.create_sdk_mcp_server = _create_sdk_mcp_server

    sys.modules["claude_agent_sdk"] = _sdk_mock

# ---------------------------------------------------------------------------
# Mock rapidfuzz — heavy dependency not needed for unit tests
# ---------------------------------------------------------------------------
if "rapidfuzz" not in sys.modules:
    _rf_mock = MagicMock()
    _rf_mock.fuzz = MagicMock()
    sys.modules["rapidfuzz"] = _rf_mock
    sys.modules["rapidfuzz.fuzz"] = _rf_mock.fuzz

# ---------------------------------------------------------------------------
# Mock caldav — not needed by MT unit tests that exercise email helpers
# ---------------------------------------------------------------------------
if "caldav" not in sys.modules:
    _caldav_mock = MagicMock()
    _caldav_lib_mock = MagicMock()
    _caldav_error_mock = MagicMock()
    _caldav_lib_mock.error = _caldav_error_mock
    _caldav_mock.lib = _caldav_lib_mock
    sys.modules["caldav"] = _caldav_mock
    sys.modules["caldav.lib"] = _caldav_lib_mock
    sys.modules["caldav.lib.error"] = _caldav_error_mock

if "vobject" not in sys.modules:
    _vobject_mock = MagicMock()
    _vobject_icalendar_mock = MagicMock()
    _vobject_mock.icalendar = _vobject_icalendar_mock
    sys.modules["vobject"] = _vobject_mock
    sys.modules["vobject.icalendar"] = _vobject_icalendar_mock

# ---------------------------------------------------------------------------
# Mock telegram — for testing Telegram bot without python-telegram-bot
# ---------------------------------------------------------------------------
if "telegram" not in sys.modules:
    _tg_mock = MagicMock()
    _tg_mock.InlineKeyboardButton = MagicMock
    _tg_mock.InlineKeyboardMarkup = MagicMock
    _tg_mock.Update = MagicMock

    # telegram.constants
    _tg_constants = MagicMock()
    _tg_constants.ParseMode = MagicMock()

    # telegram.error
    _tg_error = MagicMock()
    _tg_error.BadRequest = Exception
    _tg_error.NetworkError = Exception
    _tg_error.RetryAfter = Exception

    # telegram.ext
    _tg_ext = MagicMock()
    _tg_ext.Application = MagicMock
    _tg_ext.CallbackQueryHandler = MagicMock
    _tg_ext.CommandHandler = MagicMock
    _tg_ext.MessageHandler = MagicMock
    _tg_ext.filters = MagicMock()

    # ContextTypes needs DEFAULT_TYPE as a class attribute
    _context_types = MagicMock()
    _context_types.DEFAULT_TYPE = MagicMock()
    _tg_ext.ContextTypes = _context_types

    sys.modules["telegram"] = _tg_mock
    sys.modules["telegram.constants"] = _tg_constants
    sys.modules["telegram.error"] = _tg_error
    sys.modules["telegram.ext"] = _tg_ext

# ---------------------------------------------------------------------------
# Mock opentelemetry — not installed in test venv
# ---------------------------------------------------------------------------
if "opentelemetry" not in sys.modules:
    _otel = MagicMock()
    _otel_trace = MagicMock()
    _otel_trace.StatusCode = type("StatusCode", (), {"OK": "OK", "ERROR": "ERROR"})
    _otel.trace = _otel_trace
    sys.modules["opentelemetry"] = _otel
    sys.modules["opentelemetry.trace"] = _otel_trace
    sys.modules["opentelemetry.sdk"] = MagicMock()
    sys.modules["opentelemetry.sdk.resources"] = MagicMock()
    sys.modules["opentelemetry.sdk.trace"] = MagicMock()
    sys.modules["opentelemetry.sdk.trace.export"] = MagicMock()
    sys.modules["opentelemetry.exporter"] = MagicMock()
    sys.modules["opentelemetry.exporter.otlp"] = MagicMock()
    sys.modules["opentelemetry.exporter.otlp.proto"] = MagicMock()
    sys.modules["opentelemetry.exporter.otlp.proto.grpc"] = MagicMock()
    sys.modules["opentelemetry.exporter.otlp.proto.grpc.trace_exporter"] = MagicMock()
    sys.modules["opentelemetry.instrumentation"] = MagicMock()
    sys.modules["opentelemetry.instrumentation.httpx"] = MagicMock()
    sys.modules["opentelemetry.instrumentation.fastapi"] = MagicMock()

# ---------------------------------------------------------------------------
# caldav.error compatibility shim
# caldav >= 2.x moved errors to caldav.lib.error; re-export at caldav.error
# so that test imports (import caldav.error) work regardless of version.
# ---------------------------------------------------------------------------
if "caldav.error" not in sys.modules:
    try:
        import types as _types
        import caldav.lib.error as _caldav_lib_error
        _caldav_error_mod = _types.ModuleType("caldav.error")
        for _attr in dir(_caldav_lib_error):
            setattr(_caldav_error_mod, _attr, getattr(_caldav_lib_error, _attr))
        sys.modules["caldav.error"] = _caldav_error_mod
    except ImportError:
        pass
