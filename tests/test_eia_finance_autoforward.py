"""Tests for forward_to_cfo hint and _dispatch_to_cfo_worker in EIA tools."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


# ---------------------------------------------------------------------------
# P3.T1 — _compute_action_hint: forward_to_cfo branch
# ---------------------------------------------------------------------------

def _make_payload(domain: str, classification_extra: dict | None = None, **overrides) -> dict:
    classification = {
        "primary_domain": domain,
        "secondary_domain": None,
        "sensitivity": "medium",
        "risk_level": "low",
        "priority": "normal",
        "confidence": 0.95,
        "ynab_account_id": None,
        "subject_must_match": None,
        "ynab_account_source": "static",
        "body_account_map": None,
    }
    if classification_extra:
        classification.update(classification_extra)
    payload = {
        "blocked": False,
        "policy": {"decision": "allow", "allow": True},
        "classification": classification,
        "subject": "Pagamento confermato",
        "body_redacted": "Hai pagato 45,90 EUR a Amazon.",
        "sender": "fineco@fineco.it",
    }
    payload.update(overrides)
    return payload


def test_compute_action_hint_static_ynab_account():
    """Finance email with static whitelist YNAB account -> forward_to_cfo."""
    from agents.email_intelligence_agent.tools import _compute_action_hint

    payload = _make_payload(
        "finance",
        {"ynab_account_id": "6a5f6142-31c7-43e9-bf0c-ebd8bd27a37a", "ynab_account_source": "static"},
    )
    assert _compute_action_hint(payload) == "forward_to_cfo"


def test_compute_action_hint_body_extract_source():
    """Finance email with body_extract source (PayPal) -> forward_to_cfo even without account_id."""
    from agents.email_intelligence_agent.tools import _compute_action_hint

    payload = _make_payload(
        "finance",
        {
            "ynab_account_id": None,
            "ynab_account_source": "body_extract",
            "body_account_map": {"FINECO": "6a5f6142-31c7-43e9-bf0c-ebd8bd27a37a"},
        },
    )
    assert _compute_action_hint(payload) == "forward_to_cfo"


def test_compute_action_hint_finance_no_whitelist_routing():
    """Finance email without YNAB routing (suppressed sender) -> NOT forward_to_cfo."""
    from agents.email_intelligence_agent.tools import _compute_action_hint

    payload = _make_payload(
        "finance",
        {"ynab_account_id": None, "ynab_account_source": "static"},
        subject="Conferma ordine Amazon",
        body_redacted="Il tuo ordine #123 e stato confermato.",
        sender="order-update@amazon.it",
    )
    hint = _compute_action_hint(payload)
    assert hint != "forward_to_cfo"


def test_compute_action_hint_non_finance_with_ynab_fields():
    """Non-finance domain with YNAB fields set (edge case) -> NOT forward_to_cfo."""
    from agents.email_intelligence_agent.tools import _compute_action_hint

    payload = _make_payload(
        "travel",
        {"ynab_account_id": "some-id", "ynab_account_source": "static"},
    )
    hint = _compute_action_hint(payload)
    assert hint != "forward_to_cfo"


def test_compute_action_hint_blocked_overrides_cfo():
    """Blocked finance email with YNAB routing -> forward_to_cos (block takes priority)."""
    from agents.email_intelligence_agent.tools import _compute_action_hint

    payload = _make_payload(
        "finance",
        {"ynab_account_id": "6a5f6142-31c7-43e9-bf0c-ebd8bd27a37a"},
        blocked=True,
    )
    assert _compute_action_hint(payload) == "forward_to_cos"


# ---------------------------------------------------------------------------
# P4.T1 — _dispatch_to_cfo_worker tests
# ---------------------------------------------------------------------------

import pytest


@pytest.mark.asyncio
async def test_dispatch_to_cfo_worker_posts_to_finance_worker(monkeypatch):
    """_dispatch_to_cfo_worker sends the correct payload to the finance worker."""
    monkeypatch.setenv("CFO_FINANCE_WORKER_URL", "http://cfo-finance-workers:8000")
    monkeypatch.setenv("CFO_CLI_TOKEN", "test-token")
    monkeypatch.setenv("EIA_FINANCE_AUTOFORWARD_ENABLED", "true")

    from unittest.mock import AsyncMock, patch
    from agents.email_intelligence_agent import tools as eia_tools

    fake_response = AsyncMock()
    fake_response.raise_for_status = lambda: None
    fake_response.json = lambda: {"transaction_count": 1, "ynab_inserted": 1}

    captured = {}

    async def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["body"] = json
        return fake_response

    fake_client = AsyncMock()
    fake_client.post = fake_post
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None

    with patch.object(eia_tools.httpx, "AsyncClient", return_value=fake_client):
        await eia_tools._dispatch_to_cfo_worker(
            email_id="email-abc-1",
            received_at="2026-05-03T10:00:00+00:00",
            subject="Pagamento confermato",
            email_text="Pagamento di 45,90 EUR a Amazon.",
            ynab_account_id="6a5f6142-31c7-43e9-bf0c-ebd8bd27a37a",
            ynab_account_source="static",
            subject_must_match=None,
            body_account_map=None,
        )

    assert captured["url"] == "http://cfo-finance-workers:8000/email-transaction-extraction/analyze"
    body = captured["body"]
    assert body["goal"] == "ingest_transaction"
    scope = body["scope"]
    assert scope["email_id"] == "email-abc-1"
    assert scope["ynab_account_id"] == "6a5f6142-31c7-43e9-bf0c-ebd8bd27a37a"
    assert scope["ynab_account_source"] == "static"


@pytest.mark.asyncio
async def test_dispatch_to_cfo_worker_uses_plural_live_env(monkeypatch):
    """Live docker-compose exports CFO_FINANCE_WORKERS_URL, not the singular name."""
    monkeypatch.delenv("CFO_FINANCE_WORKER_URL", raising=False)
    monkeypatch.setenv("CFO_FINANCE_WORKERS_URL", "http://localhost:8010")
    monkeypatch.setenv("EIA_FINANCE_AUTOFORWARD_ENABLED", "true")

    from unittest.mock import AsyncMock, patch
    from agents.email_intelligence_agent import tools as eia_tools

    fake_response = AsyncMock()
    fake_response.raise_for_status = lambda: None
    fake_response.json = lambda: {"transaction_count": 1, "ynab_inserted": 1}

    captured = {}

    async def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        return fake_response

    fake_client = AsyncMock()
    fake_client.post = fake_post
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None

    with patch.object(eia_tools.httpx, "AsyncClient", return_value=fake_client):
        await eia_tools._dispatch_to_cfo_worker(
            email_id="email-live-env",
            received_at="2026-05-06T10:00:00+00:00",
            subject="Conferma Operazione",
            email_text="6 mag 2026 EASYPARKITA €1,41",
            ynab_account_id="2609b853-bc94-4e26-bd97-6e1b81d17ead",
            ynab_account_source="static",
            subject_must_match="conferma operazione",
            body_account_map=None,
        )

    assert captured["url"] == "http://localhost:8010/email-transaction-extraction/analyze"


@pytest.mark.asyncio
async def test_dispatch_to_cfo_worker_disabled_when_env_false(monkeypatch):
    """When EIA_FINANCE_AUTOFORWARD_ENABLED=false, dispatch is a no-op."""
    monkeypatch.setenv("EIA_FINANCE_AUTOFORWARD_ENABLED", "false")
    monkeypatch.setenv("CFO_FINANCE_WORKER_URL", "http://cfo-finance-workers:8000")
    monkeypatch.setenv("CFO_CLI_TOKEN", "test-token")

    from unittest.mock import AsyncMock, patch
    from agents.email_intelligence_agent import tools as eia_tools

    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None

    with patch.object(eia_tools.httpx, "AsyncClient", return_value=fake_client):
        await eia_tools._dispatch_to_cfo_worker(
            email_id="email-xyz",
            received_at="2026-05-03T10:00:00+00:00",
            subject="Irrelevant",
            email_text="Some text",
            ynab_account_id="acct-id",
            ynab_account_source="static",
            subject_must_match=None,
            body_account_map=None,
        )

    fake_client.__aenter__.assert_not_called()
