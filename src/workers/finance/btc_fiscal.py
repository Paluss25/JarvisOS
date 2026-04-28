"""BTC Fiscal Analysis sub-agent — BTC portfolio + Italian Quadro W data."""

import os
from datetime import UTC, datetime
from decimal import Decimal

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from workers.shared import btc_fiscal as bfa

router = APIRouter()

_BITPANDA_BASE = "https://api.bitpanda.com/v1"
_TIMEOUT = 15.0


class TaskEnvelope(BaseModel):
    goal: str
    scope: dict = {}


def _sidecar_url() -> str:
    return os.environ.get("CFO_SIDECAR_URL", "http://cfo-data-service:8000").rstrip("/")


def _ledger_headers() -> dict[str, str]:
    token = os.environ.get("CFO_CLI_TOKEN", "")
    if not token:
        raise ValueError("CFO_CLI_TOKEN not configured")
    return {"Authorization": f"Bearer {token}"}


async def _bitpanda_trades(api_key: str) -> list:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{_BITPANDA_BASE}/trades",
                headers={"X-API-KEY": api_key},
            )
            resp.raise_for_status()
            return resp.json().get("data", [])
    except Exception:
        return []


def _transaction_timestamp(tx: dict) -> str:
    raw = tx.get("timestamp") or tx.get("date") or tx.get("time") or datetime.now(tz=UTC).isoformat()
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.isoformat()


def _transaction_amount_btc(tx: dict) -> Decimal:
    for key in ("amount_btc", "amount", "btc_amount", "quantity"):
        value = tx.get(key)
        if value is not None:
            return Decimal(str(value))
    return Decimal("0")


def _transaction_fiat_value_eur(tx: dict) -> Decimal:
    for key in ("fiat_value_eur", "eur_value", "value_eur", "amount_eur"):
        value = tx.get(key)
        if value is not None:
            return Decimal(str(value))
    return Decimal("0")


def _transaction_external_id(tx: dict) -> str:
    return str(tx.get("txid") or tx.get("id") or tx.get("hash") or tx.get("external_id"))


def _transaction_direction(tx: dict) -> str:
    direction = str(tx.get("direction") or tx.get("type") or "").lower()
    amount = _transaction_amount_btc(tx)
    if direction in {"receive", "in", "deposit"}:
        return "receive"
    if direction in {"send", "out", "withdraw"}:
        return "send"
    return "receive" if amount >= 0 else "send"


def _normalize_transactions(payload: list[dict] | dict) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        transactions = payload.get("transactions")
        if isinstance(transactions, list):
            return transactions
    return []


def _build_ledger_payloads(transactions: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    asset_payloads = [
        {
            "symbol": "BTC",
            "name": "Bitcoin",
            "asset_class": "crypto",
            "base_currency": "EUR",
        }
    ]

    event_payloads: list[dict] = []
    open_lots: list[dict] = []

    for tx in sorted(transactions, key=_transaction_timestamp):
        amount_btc = _transaction_amount_btc(tx)
        fiat_value_eur = _transaction_fiat_value_eur(tx)
        direction = _transaction_direction(tx)
        external_id = _transaction_external_id(tx)
        happened_at = _transaction_timestamp(tx)

        event_payloads.append(
            {
                "source": "btc",
                "event_type": direction,
                "external_id": external_id,
                "account_id": None,
                "asset_id": None,
                "amount": float(amount_btc),
                "currency": "BTC",
                "fiat_value_eur": float(fiat_value_eur),
                "fee_eur": None,
                "tx_hash": external_id,
                "happened_at": happened_at,
                "counterparty_type": None,
                "category": "btc",
                "tax_treatment_candidate": "capital_gain",
                "confidence_score": 0.95,
                "evidence_link": None,
                "raw_payload": tx,
            }
        )

        if direction == "receive" and amount_btc > 0:
            unit_cost = fiat_value_eur / amount_btc if amount_btc != 0 else Decimal("0")
            open_lots.append(
                {
                    "financial_event_id": None,
                    "account_id": None,
                    "asset_id": None,
                    "acquired_at": happened_at,
                    "quantity_open": float(amount_btc),
                    "unit_cost_eur": float(unit_cost),
                    "method": "fifo",
                    "source_lot_ref": f"btc:{external_id}",
                }
            )
        elif direction == "send" and amount_btc < 0:
            quantity_to_dispose = abs(amount_btc)
            for lot in open_lots:
                if quantity_to_dispose <= Decimal("0"):
                    break
                available = Decimal(str(lot["quantity_open"]))
                if available <= Decimal("0"):
                    continue
                consumed = min(available, quantity_to_dispose)
                lot["quantity_open"] = float(available - consumed)
                quantity_to_dispose -= consumed

    return asset_payloads, event_payloads, open_lots


async def _sync_transactions_to_ledger(transactions: list[dict]) -> dict:
    headers = _ledger_headers()
    asset_payloads, event_payloads, tax_lot_payloads = _build_ledger_payloads(transactions)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        asset_id = None
        for asset_payload in asset_payloads:
            response = await client.post(
                f"{_sidecar_url()}/ledger/assets",
                json=asset_payload,
                headers=headers,
            )
            response.raise_for_status()
            asset_id = response.json()["id"]

        events_succeeded = 0
        for event_payload in event_payloads:
            event_payload["asset_id"] = asset_id
            response = await client.post(
                f"{_sidecar_url()}/ledger/events",
                json=event_payload,
                headers=headers,
            )
            response.raise_for_status()
            events_succeeded += 1

        tax_lots_succeeded = 0
        for tax_lot_payload in tax_lot_payloads:
            if Decimal(str(tax_lot_payload["quantity_open"])) <= Decimal("0"):
                continue
            tax_lot_payload["asset_id"] = asset_id
            response = await client.post(
                f"{_sidecar_url()}/ledger/tax-lots",
                json=tax_lot_payload,
                headers=headers,
            )
            response.raise_for_status()
            tax_lots_succeeded += 1

    return {
        "events_attempted": len(event_payloads),
        "events_succeeded": events_succeeded,
        "tax_lots_attempted": sum(
            1 for item in tax_lot_payloads if Decimal(str(item["quantity_open"])) > Decimal("0")
        ),
        "tax_lots_succeeded": tax_lots_succeeded,
    }


@router.post("/analyze")
async def analyze(task: TaskEnvelope) -> dict:
    year = task.scope.get("year")
    include_bitpanda = bool(task.scope.get("include_bitpanda", False))

    result: dict = {}
    errors: list[str] = []

    # --- Balance ---
    try:
        balance = await bfa.get_balance()
        result["balance"] = balance
    except Exception as exc:
        errors.append(f"balance: {exc}")

    # --- Addresses ---
    try:
        addresses = await bfa.get_addresses()
        result["addresses"] = addresses
    except Exception as exc:
        errors.append(f"addresses: {exc}")

    # --- Transactions ---
    try:
        txns_payload = await bfa.get_transactions(year=year)
        txns = _normalize_transactions(txns_payload)
        result["transactions"] = txns_payload
        result["transaction_count"] = len(txns)
        if txns:
            try:
                result["ledger_sync"] = await _sync_transactions_to_ledger(txns)
            except Exception as exc:
                errors.append(f"ledger_sync: {exc}")
    except Exception as exc:
        errors.append(f"transactions: {exc}")

    # --- Quadro W (if year specified) ---
    if year:
        try:
            quadro_w = await bfa.get_quadro_w(int(year))
            result["quadro_w"] = quadro_w
            result["fiscal_year"] = year
        except Exception as exc:
            errors.append(f"quadro_w({year}): {exc}")

    # --- Bitpanda (optional) ---
    bitpanda_key = os.environ.get("BITPANDA_API_KEY", "")
    if include_bitpanda and bitpanda_key:
        trades = await _bitpanda_trades(bitpanda_key)
        result["bitpanda_trades"] = trades
        result["bitpanda_trade_count"] = len(trades)

    if errors:
        result["errors"] = errors

    return result
