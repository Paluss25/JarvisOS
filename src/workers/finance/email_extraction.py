"""Email Transaction Extraction sub-agent — extract transactions from email text.

Regex patterns for Italian bank notification emails + haiku LLM for unstructured text.
Writes extracted transactions to YNAB (whitelist-routed) and the CFO ledger.
"""

import hashlib
import logging
import os
import re
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from workers.shared import cfo_sidecar, llm

logger = logging.getLogger(__name__)

router = APIRouter()

_YNAB_BASE = "https://api.ynab.com/v1"
_YNAB_TIMEOUT = 15.0

# Italian bank email patterns
_MONTHS_IT = r"(?:gen|feb|mar|apr|mag|giu|lug|ago|set|ott|nov|dic|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"

# Each entry: (pattern, direction, amount_group_index, payee_group_index)
_PATTERNS: list[tuple[re.Pattern, str, int, int]] = [
    # "Pagamento di 45,90 EUR a Amazon"  → groups: (amount, currency, payee)
    (re.compile(r"(?:pagamento|addebito|prelievo)\s+(?:di\s+)?([\d,.]+)\s*(EUR|€)\s+(?:a|da|presso)\s+(.+?)(?:\.|$)", re.I), "outflow", 0, 2),
    # "Accredito di 1.500,00 EUR da Stipendio"  → groups: (amount, currency, payee)
    (re.compile(r"accredito\s+(?:di\s+)?([\d,.]+)\s*(EUR|€)\s+da\s+(.+?)(?:\.|$)", re.I), "inflow", 0, 2),
    # "Hai speso 23.50€ da COOP"  → groups: (amount, payee)
    (re.compile(r"(?:hai speso|spesa di)\s*([\d,.]+)\s*(?:EUR|€)\s+(?:da|presso|a)\s+(.+?)(?:\.|$)", re.I), "outflow", 0, 1),
    # AMEX/Nexi alert: "21 apr 2026 AMAZON ITALY RETAIL €28,19"  → groups: (merchant, amount)
    (re.compile(rf"\d{{1,2}}\s+{_MONTHS_IT}\s+\d{{4}}\s+([A-Z][A-Z0-9 .&'*/-]{{2,}}?)\s+€\s*([\d,.]+)", re.I), "outflow", 1, 0),
    # Generic: "€ 99,99 - Netflix"  → groups: (amount, payee)
    (re.compile(r"(?:EUR|€)\s*([\d,.]+)\s*[-–]\s*(.+?)(?:\.|$)", re.I), "unknown", 0, 1),
]

# Payee normalization: raw extracted payee → canonical YNAB payee name.
# Keys are case-insensitive prefix/substring patterns; first match wins.
_PAYEE_NORMALIZATIONS: list[tuple[re.Pattern, str]] = [
    # Amazon cluster (AMZN INSTALLMENTS, AMAZON IT MARKETPLACE, etc.)
    (re.compile(r"amzn\b|amazon\b", re.I), "Amazon"),
    (re.compile(r"esselunga\b", re.I), "Esselunga"),
    (re.compile(r"ryanair\b", re.I), "Ryanair"),
    (re.compile(r"deliveroo", re.I), "Deliveroo"),
    (re.compile(r"trenitalia", re.I), "Trenitalia"),
    # H&M — AMEX strips & so it arrives as "H M"
    (re.compile(r"\bh\s*&?\s*m\b", re.I), "HM"),
    (re.compile(r"\bzara\b", re.I), "Zara"),
    (re.compile(r"drmax", re.I), "DrMax"),
    (re.compile(r"wetaxi", re.I), "WeTaxi"),
    (re.compile(r"checkout\s*com", re.I), "Checkout.com"),
    (re.compile(r"\bikea\b", re.I), "IKEA"),
    # Iper il Castello and other Ipercoop branches
    (re.compile(r"\biper\b", re.I), "Ipercoop"),
    # Ubiquiti Store (appears as "UBIQUITI STORE EUROPE" or "EU STORE UI COM")
    (re.compile(r"ubiquiti|eu\s+store\s+ui", re.I), "UbiquityStore"),
    (re.compile(r"\bpaypal\b", re.I), "PayPal"),
]

# PayPal pass-through prefix pattern: "PAYPAL  MERCHANT NAME"
_PAYPAL_PREFIX_RE = re.compile(r"paypal\s{2,}(.+)", re.I)


def _normalize_payee(raw: str) -> str:
    # PayPal pass-through: extract merchant from "PAYPAL  MERCHANT" suffix
    pp = _PAYPAL_PREFIX_RE.match(raw)
    if pp:
        suffix = pp.group(1).strip()
        for pattern, canonical in _PAYEE_NORMALIZATIONS:
            if pattern.search(suffix):
                return canonical
        return suffix.title()
    for pattern, canonical in _PAYEE_NORMALIZATIONS:
        if pattern.search(raw):
            return canonical
    return raw

_SYSTEM = (
    "You are a financial data extractor. Given an email text, extract all financial transactions. "
    "For each transaction return a JSON object with: "
    "payee (string), amount (float, always positive), direction ('inflow' or 'outflow'), "
    "currency (string, default 'EUR'), date (YYYY-MM-DD if found, else null). "
    "Return a JSON array of transaction objects. If no transactions found, return []. "
    "Return ONLY the JSON array, no explanation."
)


class TaskEnvelope(BaseModel):
    goal: str
    scope: dict = {}


def _parse_amount(s: str) -> float:
    """Parse Italian-format number (1.234,56) to float."""
    cleaned = s.replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _email_to_ledger_payload(
    tx: dict,
    *,
    email_id: str,
    received_at: str,
) -> dict:
    """Convert an extracted email transaction to the ledger event schema."""
    direction = tx.get("direction", "unknown")
    amount = float(tx.get("amount", 0) or 0)
    if direction == "outflow":
        signed_amount = -amount
        event_type = "expense"
    elif direction == "inflow":
        signed_amount = amount
        event_type = "income"
    else:
        signed_amount = -amount
        event_type = "expense"

    payee = str(tx.get("payee", "unknown")).strip()
    external_id = f"email-{email_id}-{payee}-{amount:.2f}"

    if received_at:
        try:
            happened_at = datetime.fromisoformat(received_at.replace("Z", "+00:00")).isoformat()
        except ValueError:
            happened_at = datetime.now(UTC).isoformat()
    else:
        happened_at = datetime.now(UTC).isoformat()

    return {
        "source": "email",
        "event_type": event_type,
        "external_id": external_id,
        "account_id": None,
        "asset_id": None,
        "amount": signed_amount,
        "currency": tx.get("currency") or "EUR",
        "fiat_value_eur": signed_amount,
        "fee_eur": None,
        "tx_hash": None,
        "happened_at": happened_at,
        "counterparty_type": None,
        "category": None,
        "tax_treatment_candidate": None,
        "confidence_score": None,
        "evidence_link": None,
        "raw_payload": tx,
    }


def _resolve_ynab_account_from_body(body: str, body_account_map: dict) -> str | None:
    """Parse 'Hai pagato X con PROVIDER' from body text and resolve YNAB account UUID.

    Longer keys take precedence so 'FINECO GOLD' wins over 'FINECO'.
    """
    match = re.search(r"\bcon\s+([A-Z][A-Z0-9 ]+?)(?=\s*[\.\n,]|$)", body, re.I | re.M)
    if not match:
        return None
    provider = match.group(1).strip().upper()
    normalized = {k.upper(): v for k, v in body_account_map.items()}
    if provider in normalized:
        return normalized[provider]
    for key in sorted(normalized.keys(), key=len, reverse=True):
        if provider.startswith(key):
            return normalized[key]
    return None


def _ynab_milliunits(amount: float, direction: str) -> int:
    """Convert a positive amount + direction to YNAB milliunits (signed)."""
    base = int(round(abs(amount) * 1000))
    return -base if direction == "outflow" else base


def _ynab_import_id(tx: dict, received_at: str) -> str:
    """Build a stable YNAB import_id (max 36 chars) for dedupe across re-runs.

    Format: 'EML:<sha8>:<YYYYMMDD>'.
    """
    payee = str(tx.get("payee", ""))
    amount = float(tx.get("amount", 0) or 0)
    raw = f"{payee}|{amount:.2f}|{received_at}".encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()[:8]
    date_part = (received_at[:10].replace("-", "")) if received_at else "00000000"
    return f"EML:{digest}:{date_part}"


async def _post_ynab_transaction(
    tx: dict,
    *,
    received_at: str,
    ynab_account_id: str,
) -> dict:
    """POST one transaction to YNAB for the given account.

    Returns {'transaction_id': str} on success, {'error': str} on failure.
    YNAB deduplicates by import_id, so re-posting the same email is safe.
    """
    api_key = os.environ.get("YNAB_API_KEY", "")
    budget_id = os.environ.get("YNAB_BUDGET_ID", "")
    if not (api_key and budget_id and ynab_account_id):
        return {
            "error": f"YNAB env not fully configured "
                     f"(key={bool(api_key)}, budget={bool(budget_id)}, account={bool(ynab_account_id)})"
        }

    direction = tx.get("direction", "unknown")
    if direction not in {"outflow", "inflow"}:
        direction = "outflow"
    amount_ms = _ynab_milliunits(float(tx.get("amount", 0) or 0), direction)
    date_str = tx.get("date") or (
        received_at[:10] if received_at else datetime.now(UTC).strftime("%Y-%m-%d")
    )

    body = {
        "transaction": {
            "account_id": ynab_account_id,
            "date": date_str,
            "amount": amount_ms,
            "payee_name": str(tx.get("payee", "unknown"))[:50],
            "memo": f"Auto-ingest from email ({tx.get('method', 'unknown')})"[:200],
            "cleared": "uncleared",
            "approved": False,
            "import_id": _ynab_import_id(tx, received_at),
        }
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    url = f"{_YNAB_BASE}/budgets/{budget_id}/transactions"

    async with httpx.AsyncClient(timeout=_YNAB_TIMEOUT) as client:
        response = await client.post(url, json=body, headers=headers)

    if not response.is_success:
        return {"error": f"YNAB API HTTP {response.status_code}: {response.text[:200]}"}

    data = response.json()
    tx_id = (data.get("data", {}).get("transaction") or {}).get("id")
    return {"transaction_id": tx_id}


@router.post("/analyze")
async def analyze(task: TaskEnvelope) -> dict:
    email_text = task.scope.get("email_text", "")
    if not email_text:
        return {"error": "scope.email_text is required"}

    email_id = str(task.scope.get("email_id", "")).strip()
    received_at = str(task.scope.get("received_at", "")).strip()
    subject = str(task.scope.get("subject", "")).strip()

    # YNAB routing context from EIA classification (passed by _dispatch_to_cfo_worker)
    ynab_account_id: str = task.scope.get("ynab_account_id") or ""
    ynab_account_source: str = task.scope.get("ynab_account_source") or "static"
    body_account_map: dict = task.scope.get("body_account_map") or {}
    subject_must_match: str = task.scope.get("subject_must_match") or ""

    # subject_must_match gate: skip entirely if subject doesn't match the required pattern
    if subject_must_match and not re.search(subject_must_match, subject, re.I):
        return {
            "transaction_count": 0,
            "transactions": [],
            "skipped_reason": "subject_must_match",
            "subject_must_match_pattern": subject_must_match,
        }

    # Resolve account for body_extract senders (e.g. PayPal)
    if ynab_account_source == "body_extract" and body_account_map and not ynab_account_id:
        ynab_account_id = _resolve_ynab_account_from_body(email_text, body_account_map) or ""

    # Fall back to env if still unresolved
    if not ynab_account_id:
        ynab_account_id = os.environ.get("YNAB_FALLBACK_ACCOUNT_ID", "")

    # Try regex patterns first
    transactions: list[dict] = []
    for pattern, direction, amount_idx, payee_idx in _PATTERNS:
        for match in pattern.finditer(email_text):
            groups = match.groups()
            if len(groups) > max(amount_idx, payee_idx):
                amount_str = groups[amount_idx]
                payee = _normalize_payee(groups[payee_idx].strip())
                transactions.append({
                    "payee": payee,
                    "amount": _parse_amount(amount_str),
                    "direction": direction,
                    "currency": "EUR",
                    "date": None,
                    "method": "regex",
                })

    # If regex found nothing, use LLM
    if not transactions:
        try:
            import json
            response = await llm.complete(email_text, system=_SYSTEM)
            response = re.sub(r"```(?:json)?\s*", "", response).strip().rstrip("`")
            parsed = json.loads(response)
            if isinstance(parsed, list):
                for tx in parsed:
                    tx["method"] = "llm"
                transactions = parsed
        except Exception as exc:
            return {"transactions": [], "error": f"LLM extraction failed: {exc}"}

    result: dict = {
        "transaction_count": len(transactions),
        "transactions": transactions,
    }

    # Skip writes if no email_id (cannot dedupe) or no transactions extracted
    if not email_id or not transactions:
        return result

    ynab_ok = ynab_failed = ledger_ok = ledger_failed = 0
    write_errors: list[str] = []

    for tx in transactions:
        # YNAB write
        if ynab_account_id:
            try:
                ynab_res = await _post_ynab_transaction(
                    tx, received_at=received_at, ynab_account_id=ynab_account_id
                )
                if "error" in ynab_res:
                    ynab_failed += 1
                    write_errors.append(f"ynab:{ynab_res['error']}")
                else:
                    ynab_ok += 1
            except Exception as exc:
                ynab_failed += 1
                write_errors.append(f"ynab:{exc}")
                logger.exception("YNAB write failed for tx=%s", tx)
        else:
            ynab_failed += 1
            write_errors.append("ynab:no_account_resolved")

        # Ledger write (always attempted — independent of YNAB account)
        try:
            await cfo_sidecar.post_ledger_event(
                _email_to_ledger_payload(tx, email_id=email_id, received_at=received_at)
            )
            ledger_ok += 1
        except Exception as exc:
            ledger_failed += 1
            write_errors.append(f"ledger:{exc}")
            logger.exception("Ledger write failed for tx=%s", tx)

    result["ynab_inserted"] = ynab_ok
    result["ynab_failed"] = ynab_failed
    result["ledger_inserted"] = ledger_ok
    result["ledger_failed"] = ledger_failed
    if write_errors:
        result["write_errors"] = write_errors[:10]
    return result
