"""Tests for ledger + YNAB write logic in email_extraction worker."""
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


# ---------------------------------------------------------------------------
# P1.T2 — post_ledger_event
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_ledger_event_calls_sidecar(monkeypatch):
    monkeypatch.setenv("CFO_CLI_TOKEN", "test-token")
    monkeypatch.setenv("CFO_SIDECAR_URL", "http://test-sidecar:8000")

    from workers.shared import cfo_sidecar

    payload = {
        "source": "email",
        "event_type": "expense",
        "external_id": "email-abc-1",
        "amount": -45.90,
        "currency": "EUR",
        "happened_at": "2026-05-03T10:00:00+00:00",
        "raw_payload": {},
    }

    fake_response = AsyncMock()
    fake_response.raise_for_status = lambda: None
    fake_response.content = b'{"id": 42}'
    fake_response.json = lambda: {"id": 42}

    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_response)
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None

    with patch.object(cfo_sidecar.httpx, "AsyncClient", return_value=fake_client):
        result = await cfo_sidecar.post_ledger_event(payload)

    fake_client.post.assert_awaited_once()
    assert result == {"id": 42}


# ---------------------------------------------------------------------------
# P1.T3 — _email_to_ledger_payload
# ---------------------------------------------------------------------------

def test_email_to_ledger_payload_outflow():
    from workers.finance.email_extraction import _email_to_ledger_payload

    tx = {
        "payee": "Amazon",
        "amount": 45.90,
        "direction": "outflow",
        "currency": "EUR",
        "date": "2026-05-03",
        "method": "regex",
    }
    payload = _email_to_ledger_payload(
        tx,
        email_id="email-abc-1",
        received_at="2026-05-03T10:00:00+00:00",
    )

    assert payload["source"] == "email"
    assert payload["event_type"] == "expense"
    assert payload["external_id"] == "email-email-abc-1-Amazon-45.90"
    assert payload["amount"] == -45.90
    assert payload["currency"] == "EUR"
    assert payload["category"] is None
    assert payload["raw_payload"] == tx


def test_email_to_ledger_payload_inflow():
    from workers.finance.email_extraction import _email_to_ledger_payload

    tx = {
        "payee": "Stipendio",
        "amount": 1500.00,
        "direction": "inflow",
        "currency": "EUR",
        "date": None,
        "method": "regex",
    }
    payload = _email_to_ledger_payload(
        tx,
        email_id="email-xyz-9",
        received_at="2026-05-03T08:00:00+00:00",
    )

    assert payload["event_type"] == "income"
    assert payload["amount"] == 1500.00


# ---------------------------------------------------------------------------
# P1.T4 — _resolve_ynab_account_from_body + _post_ynab_transaction
# ---------------------------------------------------------------------------

def test_resolve_ynab_account_from_body_fineco():
    from workers.finance.email_extraction import _resolve_ynab_account_from_body

    body_map = {
        "FINECO": "6a5f6142-31c7-43e9-bf0c-ebd8bd27a37a",
        "FINECO GOLD": "d51958c6-1bc8-442b-8586-e155a7e55671",
        "AMEX": "2609b853-bc94-4e26-bd97-6e1b81d17ead",
        "AMERICAN EXPRESS": "2609b853-bc94-4e26-bd97-6e1b81d17ead",
    }
    # Exact match
    assert _resolve_ynab_account_from_body(
        "Hai pagato Apple Services con FINECO.", body_map
    ) == "6a5f6142-31c7-43e9-bf0c-ebd8bd27a37a"

    # Multi-word provider
    assert _resolve_ynab_account_from_body(
        "Hai pagato Netflix con AMERICAN EXPRESS.", body_map
    ) == "2609b853-bc94-4e26-bd97-6e1b81d17ead"

    # No match → None
    assert _resolve_ynab_account_from_body(
        "Pagamento effettuato.", body_map
    ) is None


@pytest.mark.asyncio
async def test_post_ynab_transaction_outflow(monkeypatch):
    monkeypatch.setenv("YNAB_API_KEY", "ynab-test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")

    from workers.finance import email_extraction

    tx = {
        "payee": "Amazon",
        "amount": 45.90,
        "direction": "outflow",
        "currency": "EUR",
        "date": "2026-05-03",
    }

    captured = {}

    fake_response = AsyncMock()
    fake_response.is_success = True
    fake_response.status_code = 201
    fake_response.text = '{"data": {"transaction": {"id": "tx-789"}}}'
    fake_response.json = lambda: {"data": {"transaction": {"id": "tx-789"}}}

    async def fake_post(url, json=None, headers=None):
        captured["url"] = url
        captured["body"] = json
        captured["headers"] = headers
        return fake_response

    fake_client = AsyncMock()
    fake_client.post = fake_post
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None

    with patch.object(email_extraction.httpx, "AsyncClient", return_value=fake_client):
        result = await email_extraction._post_ynab_transaction(
            tx,
            received_at="2026-05-03T10:00:00+00:00",
            ynab_account_id="account-456",
        )

    assert result["transaction_id"] == "tx-789"
    assert captured["url"] == "https://api.ynab.com/v1/budgets/budget-123/transactions"
    assert captured["headers"]["Authorization"] == "Bearer ynab-test-key"
    sent = captured["body"]["transaction"]
    assert sent["account_id"] == "account-456"
    assert sent["amount"] == -45900  # YNAB milliunits, negative for outflow
    assert sent["payee_name"] == "Amazon"
    assert sent["date"] == "2026-05-03"
    assert sent["cleared"] == "uncleared"
    assert sent["approved"] is False
    assert sent["import_id"]  # dedupe key present


# ---------------------------------------------------------------------------
# P1.T5 — analyze integration (write path)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_analyze_routes_to_whitelist_account(monkeypatch):
    monkeypatch.setenv("YNAB_API_KEY", "ynab-test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    monkeypatch.setenv("CFO_CLI_TOKEN", "test-token")
    monkeypatch.setenv("CFO_SIDECAR_URL", "http://test-sidecar:8000")

    from workers.finance import email_extraction

    envelope = email_extraction.TaskEnvelope(
        goal="ingest_transaction",
        scope={
            "email_text": "Pagamento di 45,90 EUR a Amazon. Grazie.",
            "email_id": "email-abc-1",
            "received_at": "2026-05-03T10:00:00+00:00",
            "subject": "Notifica pagamento",
            "ynab_account_id": "account-456",
            "ynab_account_source": "static",
        },
    )

    ynab_call = AsyncMock(return_value={"transaction_id": "tx-789"})
    ledger_call = AsyncMock(return_value={"id": 42})

    with patch.object(email_extraction, "_post_ynab_transaction", ynab_call), \
         patch.object(email_extraction.cfo_sidecar, "post_ledger_event", ledger_call):
        result = await email_extraction.analyze(envelope)

    assert result["transaction_count"] == 1
    assert result["ynab_inserted"] == 1
    assert result["ledger_inserted"] == 1
    call_kwargs = ynab_call.call_args
    assert call_kwargs.kwargs["ynab_account_id"] == "account-456"


@pytest.mark.asyncio
async def test_analyze_body_extract_resolves_account(monkeypatch):
    monkeypatch.setenv("YNAB_API_KEY", "ynab-test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    monkeypatch.setenv("CFO_CLI_TOKEN", "test-token")
    monkeypatch.setenv("CFO_SIDECAR_URL", "http://test-sidecar:8000")

    from workers.finance import email_extraction

    envelope = email_extraction.TaskEnvelope(
        goal="ingest_transaction",
        scope={
            "email_text": "Pagamento di 12,99 EUR a Apple Services. Hai pagato con FINECO.",
            "email_id": "paypal-001",
            "received_at": "2026-05-03T10:00:00+00:00",
            "subject": "Pagamento confermato",
            "ynab_account_id": None,
            "ynab_account_source": "body_extract",
            "body_account_map": {
                "FINECO": "6a5f6142-31c7-43e9-bf0c-ebd8bd27a37a",
                "AMEX": "2609b853-bc94-4e26-bd97-6e1b81d17ead",
            },
        },
    )

    ynab_call = AsyncMock(return_value={"transaction_id": "tx-paypal"})
    ledger_call = AsyncMock(return_value={"id": 99})

    with patch.object(email_extraction, "_post_ynab_transaction", ynab_call), \
         patch.object(email_extraction.cfo_sidecar, "post_ledger_event", ledger_call):
        result = await email_extraction.analyze(envelope)

    assert result["ynab_inserted"] == 1
    call_kwargs = ynab_call.call_args
    assert call_kwargs.kwargs["ynab_account_id"] == "6a5f6142-31c7-43e9-bf0c-ebd8bd27a37a"


@pytest.mark.asyncio
async def test_analyze_subject_must_match_skips_ynab(monkeypatch):
    monkeypatch.setenv("YNAB_API_KEY", "ynab-test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")

    from workers.finance import email_extraction

    envelope = email_extraction.TaskEnvelope(
        goal="ingest_transaction",
        scope={
            "email_text": "Il tuo documento è disponibile per il download.",
            "email_id": "mediobanca-doc-001",
            "received_at": "2026-05-03T10:00:00+00:00",
            "subject": "Nuovi documenti disponibili",
            "ynab_account_id": "e586d58c-bcac-48c6-848c-b219e00e0ea4",
            "subject_must_match": "mutuo|rata|addebito|bonifico|pagamento|trasferimento|scadenza",
        },
    )

    ynab_call = AsyncMock()
    ledger_call = AsyncMock()

    with patch.object(email_extraction, "_post_ynab_transaction", ynab_call), \
         patch.object(email_extraction.cfo_sidecar, "post_ledger_event", ledger_call):
        result = await email_extraction.analyze(envelope)

    assert result["transaction_count"] == 0
    assert result.get("skipped_reason") == "subject_must_match"
    ynab_call.assert_not_called()
    ledger_call.assert_not_called()


# ---------------------------------------------------------------------------
# AMEX pattern + payee normalization
# ---------------------------------------------------------------------------

def test_regex_amex_pattern_extracts_merchant_and_amount():
    """AMEX alert format: '21 apr 2026 AMAZON ITALY RETAIL €28,19'."""
    from workers.finance.email_extraction import _PATTERNS, _parse_amount

    amex_pattern, direction, amount_idx, payee_idx = _PATTERNS[3]  # 4th pattern
    text = "21 apr 2026 AMAZON ITALY RETAIL €28,19"
    match = amex_pattern.search(text)
    assert match is not None, "AMEX pattern did not match"
    groups = match.groups()
    assert _parse_amount(groups[amount_idx]) == pytest.approx(28.19)
    assert groups[payee_idx].strip() == "AMAZON ITALY RETAIL"
    assert direction == "outflow"


def test_normalize_payee_amazon_variants():
    from workers.finance.email_extraction import _normalize_payee

    assert _normalize_payee("AMAZON ITALY RETAIL") == "Amazon"
    assert _normalize_payee("Amazon.it") == "Amazon"
    assert _normalize_payee("AMAZON PRIME") == "Amazon"
    assert _normalize_payee("AMAZON IT MARKETPLACE APE") == "Amazon"
    assert _normalize_payee("AMZN INSTALLMENTS IT") == "Amazon"
    assert _normalize_payee("netflix") == "netflix"  # no normalization


def test_normalize_payee_esselunga():
    from workers.finance.email_extraction import _normalize_payee

    assert _normalize_payee("ESSELUNGA FILIALE 42") == "Esselunga"
    assert _normalize_payee("Esselunga S.p.A.") == "Esselunga"
    assert _normalize_payee("CONAD") == "CONAD"  # no normalization


def test_normalize_payee_extended_brands():
    from workers.finance.email_extraction import _normalize_payee

    assert _normalize_payee("RYANAIR WEB EURO") == "Ryanair"
    assert _normalize_payee("DELIVEROOIT") == "Deliveroo"
    assert _normalize_payee("TRENITALIA   PT WL") == "Trenitalia"
    assert _normalize_payee("TRENITALIAS") == "Trenitalia"
    assert _normalize_payee("H M") == "H&M"
    assert _normalize_payee("H&M") == "H&M"
    assert _normalize_payee("ZARA 6437") == "Zara"
    assert _normalize_payee("ZARA HOME 10668") == "Zara"
    assert _normalize_payee("DRMAXECOMM") == "DrMax"
    assert _normalize_payee("DRMAX ECOMM ITALIA") == "DrMax"
    assert _normalize_payee("WETAXI SRL") == "WeTaxi"
    assert _normalize_payee("CHECKOUT COM ECOMM MEDIUM EEA") == "Checkout.com"
    assert _normalize_payee("IKEA ITALIA RETAIL") == "IKEA"
    assert _normalize_payee("IPER IL CASTELLO") == "Ipercoop"
    assert _normalize_payee("EU STORE UI COM") == "UbiquityStore"
    assert _normalize_payee("UBIQUITI STORE EUROPE") == "UbiquityStore"


def test_normalize_payee_paypal_passthrough():
    from workers.finance.email_extraction import _normalize_payee

    # Bare PayPal → PayPal
    assert _normalize_payee("PAYPAL") == "PayPal"
    # Pass-through with known merchant → normalize merchant
    assert _normalize_payee("PAYPAL  TRENITALIAS") == "Trenitalia"
    # Pass-through with unknown merchant → title-cased suffix
    assert _normalize_payee("PAYPAL  PRENATALSPA") == "Prenatalspa"


def test_normalize_payee_paypal_brands():
    from workers.finance.email_extraction import _normalize_payee

    assert _normalize_payee("Apple Inc.") == "Apple"
    assert _normalize_payee("ITUNES COM BILL") == "Apple"
    assert _normalize_payee("ZWIFT INC") == "Zwift"
    assert _normalize_payee("SKY ITALIA SRL") == "Sky Italia"
    assert _normalize_payee("ADOBE SYSTEMS SOFTWA") == "Adobe"
    assert _normalize_payee("ITALOTRENO") == "ItaloTreno"
    assert _normalize_payee("INTERFLORA ITALIA") == "Interflora"
    assert _normalize_payee("PLEX INC") == "Plex"
    assert _normalize_payee("MICROSOFT IRELAND") == "Microsoft"
    assert _normalize_payee("GLOVO SPAIN") == "Glovo"
    assert _normalize_payee("TIM SPA") == "TIM"
    assert _normalize_payee("DAZN GROUP") == "DAZN"
    assert _normalize_payee("EASYPARK AB") == "EasyPark"
    assert _normalize_payee("UDEMY INC.") == "Udemy"
    assert _normalize_payee("ZALANDO SE") == "Zalando"
    assert _normalize_payee("STRAVA INC") == "Strava"
    assert _normalize_payee("LOOKING FOR PARKING") == "Looking4Parking"
    assert _normalize_payee("PROTON AG") == "Proton"
    assert _normalize_payee("GROUPON GOODS") == "Groupon"
    assert _normalize_payee("SKYPE COMMUNICATIONS") == "Skype"
    assert _normalize_payee("CLOUDFLARE INC") == "CloudFlare"
    assert _normalize_payee("UBER TRIP") == "Uber"
    assert _normalize_payee("BOOKING BV") == "Booking.com"
    assert _normalize_payee("VERY MOBILE SRL") == "Very Mobile"


def test_normalize_payee_favore_di_strip():
    from workers.finance.email_extraction import _normalize_payee

    # Plain "favore di" prefix stripped before normalization
    assert _normalize_payee("favore di EasyPark Italia Srl") == "EasyPark"
    assert _normalize_payee("favore di Adobe Systems Softwa") == "Adobe"
    assert _normalize_payee("favore di Sconosciuto Srl") == "Sconosciuto Srl"

    # Full PayPal subject prefix stripped
    assert _normalize_payee("pagamento a favore di Apple Inc.") == "Apple"

    # PayPal pass-through + favore di
    assert _normalize_payee("PAYPAL  favore di Adobe Systems") == "Adobe"


@pytest.mark.asyncio
async def test_analyze_amex_email_extracts_amazon_payee(monkeypatch):
    """End-to-end: AMEX email body → payee='Amazon', amount=28.19."""
    monkeypatch.setenv("YNAB_API_KEY", "ynab-test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    monkeypatch.setenv("CFO_CLI_TOKEN", "test-token")
    monkeypatch.setenv("CFO_SIDECAR_URL", "http://test-sidecar:8000")

    from workers.finance import email_extraction

    email_body = (
        "Conferma Operazione\n"
        "21 apr 2026 AMAZON ITALY RETAIL €28,19\n"
        "Il pagamento è stato addebitato sulla tua Carta."
    )

    envelope = email_extraction.TaskEnvelope(
        goal="ingest_transaction",
        scope={
            "email_text": email_body,
            "email_id": "amex-274",
            "received_at": "2026-04-21T10:00:00+00:00",
            "subject": "Conferma Operazione",
            "ynab_account_id": "2609b853-bc94-4e26-bd97-6e1b81d17ead",
            "ynab_account_source": "static",
        },
    )

    ynab_call = AsyncMock(return_value={"transaction_id": "tx-amex-amazon"})
    ledger_call = AsyncMock(return_value={"id": 99})

    with patch.object(email_extraction, "_post_ynab_transaction", ynab_call), \
         patch.object(email_extraction.cfo_sidecar, "post_ledger_event", ledger_call):
        result = await email_extraction.analyze(envelope)

    assert result["transaction_count"] == 1
    tx = result["transactions"][0]
    assert tx["payee"] == "Amazon"
    assert tx["amount"] == pytest.approx(28.19)
    assert tx["direction"] == "outflow"
    assert result["ynab_inserted"] == 1
    ynab_args = ynab_call.call_args
    assert ynab_args.kwargs["ynab_account_id"] == "2609b853-bc94-4e26-bd97-6e1b81d17ead"


@pytest.mark.asyncio
async def test_analyze_no_writes_when_no_email_id(monkeypatch):
    """Without email_id we cannot dedupe — skip writes and just return extraction."""
    monkeypatch.setenv("YNAB_API_KEY", "ynab-test-key")
    monkeypatch.setenv("YNAB_BUDGET_ID", "budget-123")
    monkeypatch.setenv("YNAB_FALLBACK_ACCOUNT_ID", "fallback-account")

    from workers.finance import email_extraction

    envelope = email_extraction.TaskEnvelope(
        goal="ingest_transaction",
        scope={"email_text": "Pagamento di 45,90 EUR a Amazon."},
    )

    ynab_call = AsyncMock(return_value={"transaction_id": "tx-789"})
    ledger_call = AsyncMock(return_value={"id": 42})

    with patch.object(email_extraction, "_post_ynab_transaction", ynab_call), \
         patch.object(email_extraction.cfo_sidecar, "post_ledger_event", ledger_call):
        result = await email_extraction.analyze(envelope)

    assert result["transaction_count"] >= 0
    ynab_call.assert_not_called()
    ledger_call.assert_not_called()
