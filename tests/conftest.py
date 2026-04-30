"""Shared test configuration and fixtures.

Installs module-level mocks for optional heavy dependencies (claude_agent_sdk,
agno, etc.) before any test module is collected, so that imports in src.*
never fail due to missing packages in the test venv.
"""
import sys
import types
from datetime import timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

_UNIT_TEST_FILES = {
    "test_agent_runner_config.py",
    "test_audit_writer.py",
    "test_base_agent_client.py",
    "test_classifier.py",
    "test_config_loader.py",
    "test_content_isolator.py",
    "test_cos_routing.py",
    "test_cron_interval.py",
    "test_daily_fitness_migration.py",
    "test_daily_logger_multiuser.py",
    "test_dos_daily_fitness_import.py",
    "test_drhouse_router.py",
    "test_eia_digest.py",
    "test_email_sorter.py",
    "test_fallback_model.py",
    "test_fatsecret.py",
    "test_fusion.py",
    "test_garmin_fit_migration.py",
    "test_ingest_gate.py",
    "test_medical_gate.py",
    "test_model_factory.py",
    "test_model_routing_guard.py",
    "test_permission_layer.py",
    "test_redaction_engine.py",
    "test_telegram_webhook.py",
}

_INTEGRATION_TEST_FILES = {
    "test_chro_pipeline.py",
    "test_calendar_client.py",
    "test_contacts_client.py",
    "test_dos_fit_import.py",
    "test_drhouse_integration.py",
    "test_eia_mt_email_fixes.py",
    "test_memory_box_tool.py",
    "test_memory_p4.py",
    "test_mt_calendar_tools.py",
    "test_mt_contacts_tools.py",
    "test_mt_remind_fast_path.py",
    "test_mt_tools.py",
    "test_pipeline_integration.py",
}

_E2E_TEST_FILES = {
    "test_docker_compose_mounts.py",
    "test_dos_push_training.py",
    "test_sync_training_week.py",
}

_SLOW_TEST_FILES = {
    "test_telegram_typing.py",
}

_CLASSIFIED_TEST_FILES = (
    _UNIT_TEST_FILES
    | _INTEGRATION_TEST_FILES
    | _E2E_TEST_FILES
    | _SLOW_TEST_FILES
)


def pytest_collection_modifyitems(config, items):
    """Assign suite markers by test module.

    Keep this map explicit so every new test file must be intentionally placed
    in a gate before it can run unnoticed in CI.
    """
    unclassified: set[str] = set()
    for item in items:
        filename = Path(str(item.fspath)).name
        if filename in _UNIT_TEST_FILES:
            item.add_marker(pytest.mark.unit)
        if filename in _INTEGRATION_TEST_FILES:
            item.add_marker(pytest.mark.integration)
        if filename in _E2E_TEST_FILES:
            item.add_marker(pytest.mark.e2e)
        if filename in _SLOW_TEST_FILES:
            item.add_marker(pytest.mark.slow)
        if filename.startswith("test_") and filename not in _CLASSIFIED_TEST_FILES:
            unclassified.add(filename)

    if unclassified:
        names = ", ".join(sorted(unclassified))
        raise pytest.UsageError(f"Unclassified test files in pytest gate map: {names}")

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
# Optional dependency shims
# ---------------------------------------------------------------------------
try:
    import httpx as _httpx  # noqa: F401
except ImportError:
    _httpx_mock = types.ModuleType("httpx")

    class _HTTPStatusError(Exception):
        def __init__(self, message="", *, request=None, response=None):
            super().__init__(message)
            self.request = request
            self.response = response

    _httpx_mock.HTTPStatusError = _HTTPStatusError
    _httpx_mock.AsyncClient = MagicMock
    sys.modules["httpx"] = _httpx_mock

if "redis" not in sys.modules:
    _redis_mock = types.ModuleType("redis")
    _redis_asyncio_mock = types.ModuleType("redis.asyncio")
    _redis_asyncio_mock.Redis = MagicMock
    _redis_mock.asyncio = _redis_asyncio_mock
    sys.modules["redis"] = _redis_mock
    sys.modules["redis.asyncio"] = _redis_asyncio_mock

if "caldav" not in sys.modules:
    _caldav_mock = types.ModuleType("caldav")
    _caldav_lib_mock = types.ModuleType("caldav.lib")
    _caldav_error_mock = types.ModuleType("caldav.lib.error")

    class _CalDAVNotFoundError(Exception):
        pass

    _caldav_mock.DAVClient = MagicMock
    _caldav_mock.Calendar = MagicMock
    _caldav_error_mock.NotFoundError = _CalDAVNotFoundError
    _caldav_lib_mock.error = _caldav_error_mock
    _caldav_mock.lib = _caldav_lib_mock
    sys.modules["caldav"] = _caldav_mock
    sys.modules["caldav.lib"] = _caldav_lib_mock
    sys.modules["caldav.lib.error"] = _caldav_error_mock

if "vobject" not in sys.modules:
    _vobject_mock = types.ModuleType("vobject")
    _vobject_icalendar_mock = types.ModuleType("vobject.icalendar")
    _vobject_icalendar_mock.utc = timezone.utc

    def _parse_lines(raw: str) -> dict[str, str]:
        values = {}
        for line in raw.replace("\r\n", "\n").splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            values[key.split(";", 1)[0].lower()] = value
        return values

    def _prop(value: str):
        return SimpleNamespace(value=value)

    def _read_one(raw: str):
        values = _parse_lines(raw)
        if "begin" in values and values["begin"].upper() == "VCARD":
            card = SimpleNamespace()
            for key in ("uid", "fn", "email", "tel", "note"):
                if key in values:
                    setattr(card, key, _prop(values[key]))
            return card

        event = SimpleNamespace()
        for key in ("uid", "summary", "dtstart", "dtend", "description"):
            if key in values:
                setattr(event, key, _prop(values[key]))
        return SimpleNamespace(vevent=event)

    class _FakeComponent:
        def __init__(self, name: str):
            self.name = name.upper()
            self._props: list[tuple[str, object]] = []

        def add(self, name: str):
            entry = SimpleNamespace(value="")
            self._props.append((name.upper(), entry))
            return entry

        def lines(self) -> list[str]:
            rendered = [f"BEGIN:{self.name}"]
            for name, entry in self._props:
                rendered.append(f"{name}:{entry.value}")
            rendered.append(f"END:{self.name}")
            return rendered

    class _FakeCalendar:
        def __init__(self):
            self._components: list[_FakeComponent] = []

        def add(self, name: str):
            component = _FakeComponent(name)
            self._components.append(component)
            return component

        def serialize(self) -> str:
            lines = ["BEGIN:VCALENDAR", "VERSION:2.0"]
            for component in self._components:
                lines.extend(component.lines())
            lines.append("END:VCALENDAR")
            return "\r\n".join(lines) + "\r\n"

    _vobject_mock.readOne = _read_one
    _vobject_mock.iCalendar = _FakeCalendar
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
