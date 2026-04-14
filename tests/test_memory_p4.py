"""Unit tests for P4 memory modules.

Covers:
- workspace_loader   (P4.T1)
- daily_logger       (P4.T2)
- memory_api_client  (P4.T3)
- session_manager    (P4.T4)

All tests are offline — no real HTTP calls, no filesystem side-effects
beyond tmp_path.
"""

import asyncio
import sys
import types
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Stub src.config so tests run without pydantic-settings installed
# ---------------------------------------------------------------------------
def _stub_src_config():
    if "src.config" not in sys.modules:
        mod = types.ModuleType("src.config")
        # Minimal settings stub — tests override via patch("src.config.settings")
        settings_stub = MagicMock()
        settings_stub.workspace_path = Path("/tmp/jarvis-stub-workspace")
        mod.settings = settings_stub
        sys.modules["src.config"] = mod


_stub_src_config()


# ===========================================================================
# Helpers
# ===========================================================================

def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ===========================================================================
# workspace_loader
# ===========================================================================

class TestWorkspaceLoader:

    def test_loads_existing_files(self, tmp_path):
        _write(tmp_path / "SOUL.md", "soul content")
        _write(tmp_path / "AGENTS.md", "agents content")
        _write(tmp_path / "USER.md", "user content")

        from src.memory.workspace_loader import load_workspace_context
        ctx = load_workspace_context(tmp_path)

        assert ctx["soul"] == "soul content"
        assert ctx["agents"] == "agents content"
        assert ctx["user"] == "user content"

    def test_missing_optional_files_return_empty(self, tmp_path):
        # No files at all in tmp_path
        from src.memory.workspace_loader import load_workspace_context
        ctx = load_workspace_context(tmp_path)

        assert ctx["tools_md"] == ""
        assert ctx["memory"] == ""
        assert ctx["heartbeat"] == ""
        assert ctx["identity"] == ""

    def test_daily_memory_loaded(self, tmp_path):
        from datetime import date
        today = date.today().isoformat()
        _write(tmp_path / "memory" / f"{today}.md", "# Daily\n- entry")

        from src.memory.workspace_loader import load_workspace_context
        ctx = load_workspace_context(tmp_path)

        assert "Daily" in ctx["daily"]

    def test_daily_empty_when_not_created(self, tmp_path):
        from src.memory.workspace_loader import load_workspace_context
        ctx = load_workspace_context(tmp_path)
        assert ctx["daily"] == ""

    def test_all_expected_keys_present(self, tmp_path):
        from src.memory.workspace_loader import load_workspace_context
        ctx = load_workspace_context(tmp_path)
        expected = {"soul", "agents", "user", "tools_md", "memory", "heartbeat", "identity", "daily"}
        assert set(ctx.keys()) == expected

    def test_get_today_memory_path_creates_dir(self, tmp_path):
        from src.memory.workspace_loader import get_today_memory_path
        p = get_today_memory_path(tmp_path)
        assert p.parent.exists()
        assert p.name.endswith(".md")


# ===========================================================================
# daily_logger
# ===========================================================================

class TestDailyLogger:

    def test_log_creates_file(self, tmp_path):
        from src.memory.daily_logger import DailyLogger
        dl = DailyLogger(tmp_path)
        dl.log("hello world")

        files = list((tmp_path / "memory").glob("*.md"))
        assert len(files) == 1
        content = files[0].read_text()
        assert "hello world" in content

    def test_log_has_header_on_first_write(self, tmp_path):
        from src.memory.daily_logger import DailyLogger
        dl = DailyLogger(tmp_path)
        dl.log("first entry")

        from datetime import date
        content = (tmp_path / "memory" / f"{date.today().isoformat()}.md").read_text()
        assert "# Memory" in content

    def test_log_appends_multiple_entries(self, tmp_path):
        from src.memory.daily_logger import DailyLogger
        dl = DailyLogger(tmp_path)
        dl.log("entry one")
        dl.log("entry two")

        files = list((tmp_path / "memory").glob("*.md"))
        content = files[0].read_text()
        assert "entry one" in content
        assert "entry two" in content

    def test_log_fallback_event(self, tmp_path):
        from src.memory.daily_logger import DailyLogger
        dl = DailyLogger(tmp_path)
        dl.log_fallback_event("jarvis", "gpt-5.4", "llama-3.3", "ConnectionError")

        files = list((tmp_path / "memory").glob("*.md"))
        content = files[0].read_text()
        assert "[FALLBACK]" in content
        assert "gpt-5.4" in content
        assert "llama-3.3" in content

    def test_log_session_summary(self, tmp_path):
        from src.memory.daily_logger import DailyLogger
        dl = DailyLogger(tmp_path)
        dl.log_session_summary("Deployed Jarvis successfully.")

        files = list((tmp_path / "memory").glob("*.md"))
        content = files[0].read_text()
        assert "Session Summary" in content
        assert "Deployed Jarvis" in content

    def test_read_today_returns_content(self, tmp_path):
        from src.memory.daily_logger import DailyLogger
        dl = DailyLogger(tmp_path)
        dl.log("test read")
        assert "test read" in dl.read_today()

    def test_read_today_empty_when_no_file(self, tmp_path):
        from src.memory.daily_logger import DailyLogger
        dl = DailyLogger(tmp_path)
        assert dl.read_today() == ""

    def test_module_level_fallback_log(self, tmp_path):
        """Module-level log_fallback_event uses settings.workspace_path."""
        with patch("src.config.settings") as ms:
            ms.workspace_path = tmp_path
            from src.memory.daily_logger import log_fallback_event
            log_fallback_event("jarvis", "gpt-5.4", "groq", "TimeoutError")

        files = list((tmp_path / "memory").glob("*.md"))
        assert len(files) == 1
        assert "FALLBACK" in files[0].read_text()


# ===========================================================================
# memory_api_client
# ===========================================================================

class TestMemoryAPIClient:

    def _make_client(self, base_url="https://memory-api.example.com"):
        from src.memory.memory_api_client import MemoryAPIClient
        return MemoryAPIClient(base_url, user_id="jarvis-test")

    def test_init_strips_trailing_slash(self):
        client = self._make_client("https://example.com/")
        assert not client.base_url.endswith("/")

    def test_write_posts_to_correct_url(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "abc123", "status": "ok"}

        async def _run():
            with patch("httpx.AsyncClient") as MockClient:
                instance = AsyncMock()
                instance.post = AsyncMock(return_value=mock_resp)
                instance.__aenter__ = AsyncMock(return_value=instance)
                instance.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = instance

                result = await client.write("test memory", {"tag": "test"})

            instance.post.assert_called_once()
            call_args = instance.post.call_args
            assert "/memory/write" in call_args[0][0]
            payload = call_args[1]["json"]
            assert payload["content"] == "test memory"
            assert payload["user_id"] == "jarvis-test"
            assert payload["metadata"] == {"tag": "test"}
            return result

        result = asyncio.run(_run())
        assert result["id"] == "abc123"

    def test_query_returns_list(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"results": [{"content": "found it", "score": 0.9}]}

        async def _run():
            with patch("httpx.AsyncClient") as MockClient:
                instance = AsyncMock()
                instance.post = AsyncMock(return_value=mock_resp)
                instance.__aenter__ = AsyncMock(return_value=instance)
                instance.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = instance

                return await client.query("deployment history", top_k=3)

        results = asyncio.run(_run())
        assert len(results) == 1
        assert results[0]["content"] == "found it"

    def test_query_accepts_bare_list_response(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{"content": "bare", "score": 0.8}]

        async def _run():
            with patch("httpx.AsyncClient") as MockClient:
                instance = AsyncMock()
                instance.post = AsyncMock(return_value=mock_resp)
                instance.__aenter__ = AsyncMock(return_value=instance)
                instance.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = instance

                return await client.query("query")

        results = asyncio.run(_run())
        assert results[0]["content"] == "bare"

    def test_health_check_returns_true_on_200(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        async def _run():
            with patch("httpx.AsyncClient") as MockClient:
                instance = AsyncMock()
                instance.get = AsyncMock(return_value=mock_resp)
                instance.__aenter__ = AsyncMock(return_value=instance)
                instance.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = instance

                return await client.health_check()

        assert asyncio.run(_run()) is True

    def test_health_check_returns_false_on_exception(self):
        client = self._make_client()

        async def _run():
            with patch("httpx.AsyncClient") as MockClient:
                instance = AsyncMock()
                instance.get = AsyncMock(side_effect=ConnectionError("unreachable"))
                instance.__aenter__ = AsyncMock(return_value=instance)
                instance.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = instance

                return await client.health_check()

        assert asyncio.run(_run()) is False


# ===========================================================================
# session_manager
# ===========================================================================

class TestSessionManager:

    def _make_sm(self, tmp_path, memory_client=None):
        from src.memory.session_manager import SessionManager
        return SessionManager(tmp_path, memory_client=memory_client)

    def test_start_generates_uuid(self, tmp_path):
        sm = self._make_sm(tmp_path)
        sid = sm.start()
        assert len(sid) == 36  # UUID4 format
        assert "-" in sid

    def test_start_with_explicit_id(self, tmp_path):
        sm = self._make_sm(tmp_path)
        sid = sm.start("my-session-id")
        assert sid == "my-session-id"

    def test_session_id_property_generates_if_none(self, tmp_path):
        sm = self._make_sm(tmp_path)
        assert sm.session_id  # not None, not empty

    def test_start_logs_to_daily(self, tmp_path):
        sm = self._make_sm(tmp_path)
        sm.start()

        files = list((tmp_path / "memory").glob("*.md"))
        assert len(files) == 1
        assert "SESSION START" in files[0].read_text()

    def test_end_logs_to_daily(self, tmp_path):
        sm = self._make_sm(tmp_path)
        sm.start()
        asyncio.run(sm.end())

        content = list((tmp_path / "memory").glob("*.md"))[0].read_text()
        assert "SESSION END" in content

    def test_end_with_summary_writes_to_daily(self, tmp_path):
        sm = self._make_sm(tmp_path)
        sm.start()
        asyncio.run(sm.end("Session done. Deployed service X."))

        content = list((tmp_path / "memory").glob("*.md"))[0].read_text()
        assert "Session Summary" in content
        assert "Deployed service X" in content

    def test_end_calls_memory_api(self, tmp_path):
        mock_client = AsyncMock()
        mock_client.write = AsyncMock(return_value={"id": "x"})

        sm = self._make_sm(tmp_path, memory_client=mock_client)
        sm.start()
        asyncio.run(sm.end("Summary for API"))

        mock_client.write.assert_called_once()
        call_content = mock_client.write.call_args[1]["content"] if mock_client.write.call_args[1] else mock_client.write.call_args[0][0]
        assert "Summary for API" in call_content

    def test_end_without_summary_does_not_call_memory_api(self, tmp_path):
        mock_client = AsyncMock()
        sm = self._make_sm(tmp_path, memory_client=mock_client)
        sm.start()
        asyncio.run(sm.end())

        mock_client.write.assert_not_called()

    def test_end_memory_api_failure_does_not_raise(self, tmp_path):
        mock_client = AsyncMock()
        mock_client.write = AsyncMock(side_effect=ConnectionError("api down"))

        sm = self._make_sm(tmp_path, memory_client=mock_client)
        sm.start()
        # Should not raise even if memory-api is down
        asyncio.run(sm.end("Summary"))

    def test_reset_clears_session(self, tmp_path):
        sm = self._make_sm(tmp_path)
        sm.start("test-id")
        sm.reset()
        assert sm._session_id is None

    def test_end_without_active_session_is_noop(self, tmp_path):
        sm = self._make_sm(tmp_path)
        # Should not raise
        asyncio.run(sm.end("summary"))
