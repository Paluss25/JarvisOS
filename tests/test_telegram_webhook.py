"""Tests for Telegram webhook mode — config fields, route handler, proxy."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# P0.T1 — AgentConfig webhook fields
# ---------------------------------------------------------------------------

def test_agent_config_webhook_fields_default_none():
    """telegram_webhook_url_env and telegram_webhook_secret_env default to None."""
    from agent_runner.config import AgentConfig

    config = AgentConfig(
        id="test",
        name="Test",
        port=9999,
        workspace_path=Path("/tmp/test"),
        telegram_token_env="TEST_TOKEN",
        telegram_chat_id_env="TEST_CHAT",
    )
    assert config.telegram_webhook_url_env is None
    assert config.telegram_webhook_secret_env is None


def test_agent_config_webhook_fields_accept_values():
    """Both webhook env var fields accept string values."""
    from agent_runner.config import AgentConfig

    config = AgentConfig(
        id="ceo",
        name="CEO",
        port=8000,
        workspace_path=Path("/tmp/ceo"),
        telegram_token_env="CEO_TELEGRAM_TOKEN",
        telegram_chat_id_env="CEO_TELEGRAM_CHAT",
        telegram_webhook_url_env="CEO_TELEGRAM_WEBHOOK_URL",
        telegram_webhook_secret_env="CEO_TELEGRAM_WEBHOOK_SECRET",
    )
    assert config.telegram_webhook_url_env == "CEO_TELEGRAM_WEBHOOK_URL"
    assert config.telegram_webhook_secret_env == "CEO_TELEGRAM_WEBHOOK_SECRET"


# ---------------------------------------------------------------------------
# P1.T1 — platform_api webhook proxy
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_proxy_forwards_body_to_agent_port():
    """Gateway must forward the raw body to localhost:{port}/telegram/webhook."""
    import httpx
    import respx
    from fastapi import FastAPI
    from platform_api.webhooks import router

    app = FastAPI()
    app.include_router(router)
    transport = httpx.ASGITransport(app=app)

    with respx.mock:
        route = respx.post("http://localhost:8000/telegram/webhook").mock(
            return_value=httpx.Response(200)
        )
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/webhooks/ceo",
                content=b'{"update_id": 1}',
                headers={
                    "Content-Type": "application/json",
                    "X-Telegram-Bot-Api-Secret-Token": "mysecret",
                },
            )
        assert resp.status_code == 200
        assert route.called
        assert "localhost:8000" in str(respx.calls[0].request.url)
        assert respx.calls[0].request.headers["X-Telegram-Bot-Api-Secret-Token"] == "mysecret"


@pytest.mark.asyncio
async def test_proxy_returns_404_for_unknown_agent():
    """Gateway must return 404 if agent_id is not in AGENT_PORTS."""
    import httpx
    from fastapi import FastAPI
    from platform_api.webhooks import router

    app = FastAPI()
    app.include_router(router)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/webhooks/unknown_agent",
            content=b"{}",
            headers={"Content-Type": "application/json"},
        )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# P2.T1 — _make_webhook_handler
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handler_calls_process_update_on_valid_request():
    """Handler must call ptb_app.process_update() with the parsed Update."""
    import httpx
    from fastapi import FastAPI
    from agent_runner.interfaces.telegram_bot import _make_webhook_handler
    from telegram import Update

    ptb = MagicMock()
    ptb.bot = MagicMock()
    ptb.process_update = AsyncMock()

    fake_update = MagicMock(spec=Update)

    with patch("agent_runner.interfaces.telegram_bot.Update") as mock_cls:
        mock_cls.de_json.return_value = fake_update
        handler = _make_webhook_handler(ptb, webhook_secret="")
        app = FastAPI()
        app.add_api_route("/telegram/webhook", handler, methods=["POST"])

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/telegram/webhook",
                json={"update_id": 1},
            )

    assert resp.status_code == 200
    ptb.process_update.assert_awaited_once_with(fake_update)


@pytest.mark.asyncio
async def test_handler_rejects_wrong_secret():
    """Handler must return 403 when the secret-token header does not match."""
    import httpx
    from fastapi import FastAPI
    from agent_runner.interfaces.telegram_bot import _make_webhook_handler

    ptb = MagicMock()
    ptb.process_update = AsyncMock()

    handler = _make_webhook_handler(ptb, webhook_secret="correct_secret")
    app = FastAPI()
    app.add_api_route("/telegram/webhook", handler, methods=["POST"])

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/telegram/webhook",
            json={"update_id": 1},
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong_secret"},
        )

    assert resp.status_code == 403
    ptb.process_update.assert_not_awaited()


@pytest.mark.asyncio
async def test_handler_skips_secret_check_when_secret_empty():
    """Handler must not check the secret header if webhook_secret is empty."""
    import httpx
    from fastapi import FastAPI
    from agent_runner.interfaces.telegram_bot import _make_webhook_handler

    ptb = MagicMock()
    ptb.bot = MagicMock()
    ptb.process_update = AsyncMock()

    with patch("agent_runner.interfaces.telegram_bot.Update") as mock_cls:
        mock_cls.de_json.return_value = MagicMock()
        handler = _make_webhook_handler(ptb, webhook_secret="")
        app = FastAPI()
        app.add_api_route("/telegram/webhook", handler, methods=["POST"])

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/telegram/webhook",
                json={"update_id": 1},
                # No secret header at all
            )

    assert resp.status_code == 200
    ptb.process_update.assert_awaited_once()


@pytest.mark.asyncio
async def test_handler_returns_200_even_when_process_update_raises():
    """Handler must swallow process_update exceptions and return 200 to Telegram."""
    import httpx
    from fastapi import FastAPI
    from agent_runner.interfaces.telegram_bot import _make_webhook_handler

    ptb = MagicMock()
    ptb.bot = MagicMock()
    ptb.process_update = AsyncMock(side_effect=RuntimeError("boom"))

    with patch("agent_runner.interfaces.telegram_bot.Update") as mock_cls:
        mock_cls.de_json.return_value = MagicMock()
        handler = _make_webhook_handler(ptb, webhook_secret="")
        app = FastAPI()
        app.add_api_route("/telegram/webhook", handler, methods=["POST"])

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/telegram/webhook", json={"update_id": 1})

    assert resp.status_code == 200
