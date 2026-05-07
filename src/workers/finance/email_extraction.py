"""Email Transaction Extraction sub-agent — extract transactions from email text.

Regex patterns for Italian bank notification emails + haiku LLM for unstructured text.
Writes extracted transactions to YNAB (whitelist-routed) and the CFO ledger.
"""

import hashlib
import html as html_lib
import logging
import os
import re
import subprocess
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser

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
_MONTH_NUMBERS = {
    "gen": "01",
    "jan": "01",
    "feb": "02",
    "mar": "03",
    "apr": "04",
    "mag": "05",
    "may": "05",
    "giu": "06",
    "jun": "06",
    "lug": "07",
    "jul": "07",
    "ago": "08",
    "aug": "08",
    "set": "09",
    "sep": "09",
    "ott": "10",
    "oct": "10",
    "nov": "11",
    "dic": "12",
    "dec": "12",
}

# Each entry: (pattern, direction, amount_group_index, payee_group_index)
_PATTERNS: list[tuple[re.Pattern, str, int, int]] = [
    # "Pagamento di 45,90 EUR a Amazon"  → groups: (amount, currency, payee)
    (re.compile(r"(?:pagamento|addebito|prelievo)\s+(?:di\s+)?([\d,.]+)\s*(EUR|€)\s+(?:a|da|presso)\s+(.+?)(?:\.|[\n]|$)", re.I), "outflow", 0, 2),
    # "Accredito di 1.500,00 EUR da Stipendio"  → groups: (amount, currency, payee)
    (re.compile(r"accredito\s+(?:di\s+)?([\d,.]+)\s*(EUR|€)\s+da\s+(.+?)(?:\.|[\n]|$)", re.I), "inflow", 0, 2),
    # "Hai pagato / Hai speso / Hai autorizzato un pagamento di 23.50 € EUR da/a COOP"
    # Covers Fineco generic, Satispay, PayPal (both "hai pagato" and "autorizzato" forms)
    # Handles non-breaking spaces (\xa0) via \s and both "€ EUR" and single-symbol forms
    (re.compile(r"(?:hai speso|hai pagato|spesa di|autorizzato\s+un\s+pagamento\s+di|pagamento\s+di)\s*([\d,.]+)\s*(?:€\s*EUR|EUR|€)\s+(?:da|presso|a)\s+(.+?)(?:\.|[\n]|$)", re.I), "outflow", 0, 1),
    # AMEX/Nexi date-line: "21 apr 2026 AMAZON ITALY RETAIL €28,19"  → groups: (merchant, amount)
    (re.compile(rf"\d{{1,2}}\s+{_MONTHS_IT}\s+\d{{4}}\s+([A-Z][A-Z0-9 .&'*/-]{{2,}}?)\s+€\s*([\d,.]+)", re.I), "outflow", 1, 0),
    # Nexi block format: "IMPORTO: € 45,90 … ESERCENTE: MERCHANT"
    (re.compile(r"IMPORTO[:\s]*€?\s*([\d,.]+).*?ESERCENTE[:\s]+(.+?)(?:\n|$)", re.I | re.S), "outflow", 0, 1),
    # PayPal subject / generic: "pagamento a EasyPark Italia Srl: 2,99 EUR"
    (re.compile(r"pagamento\s+a\s+(.+?):\s*([\d,.]+)\s*(?:EUR|€)", re.I), "outflow", 1, 0),
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
    (re.compile(r"\bh\s*&?\s*m\b", re.I), "H&M"),
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
    # PayPal-sourced merchants
    (re.compile(r"apple|itunes", re.I), "Apple"),
    (re.compile(r"\bzwift\b", re.I), "Zwift"),
    (re.compile(r"sky\s+italia|sky\.it", re.I), "Sky Italia"),
    (re.compile(r"\badobe\b", re.I), "Adobe"),
    (re.compile(r"italo\s*treno|italotreno|italo\s+(?:treno|nuovo|trasport)", re.I), "ItaloTreno"),
    (re.compile(r"interflora", re.I), "Interflora"),
    (re.compile(r"\bplex\b", re.I), "Plex"),
    (re.compile(r"microsoft", re.I), "Microsoft"),
    (re.compile(r"glovo", re.I), "Glovo"),
    (re.compile(r"\btim\b", re.I), "TIM"),
    (re.compile(r"\bdazn\b", re.I), "DAZN"),
    (re.compile(r"easypark", re.I), "EasyPark"),
    (re.compile(r"\budemy\b", re.I), "Udemy"),
    (re.compile(r"zalando", re.I), "Zalando"),
    (re.compile(r"\bstrava\b", re.I), "Strava"),
    (re.compile(r"looking.*parking|looking4park", re.I), "Looking4Parking"),
    (re.compile(r"proton\s+(?:tech|ag|mail)", re.I), "Proton"),
    (re.compile(r"groupon", re.I), "Groupon"),
    (re.compile(r"\bskype\b", re.I), "Skype"),
    (re.compile(r"cloudflare", re.I), "CloudFlare"),
    (re.compile(r"\buber\b", re.I), "Uber"),
    (re.compile(r"booking\.com|booking\s+bv", re.I), "Booking.com"),
    (re.compile(r"very\s+mobile", re.I), "Very Mobile"),
]

# PayPal pass-through prefix pattern: "PAYPAL  MERCHANT NAME"
_PAYPAL_PREFIX_RE = re.compile(r"paypal\s{2,}(.+)", re.I)

# PayPal subject prefix "pagamento a favore di" / "favore di" → strip before normalization
_FAVORE_DI_RE = re.compile(r"(?:pagamento\s+a\s+)?favore\s+di\s+", re.I)


class _TextNodeParser(HTMLParser):
    """Collect text nodes from transactional email templates."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.nodes: list[str] = []

    def handle_data(self, data: str) -> None:
        text = re.sub(r"\s+", " ", html_lib.unescape(str(data or ""))).strip()
        if text:
            self.nodes.append(text)


def _normalize_payee(raw: str) -> str:
    # PayPal pass-through: extract merchant from "PAYPAL  MERCHANT" suffix
    pp = _PAYPAL_PREFIX_RE.match(raw)
    if pp:
        suffix = _FAVORE_DI_RE.sub("", pp.group(1).strip()).strip()
        for pattern, canonical in _PAYEE_NORMALIZATIONS:
            if pattern.search(suffix):
                return canonical
        return suffix.title()
    raw = _FAVORE_DI_RE.sub("", raw).strip()
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


def _strip_html(text: str) -> str:
    """Convert HTML to plain text via html-text CLI if body looks like HTML."""
    if not re.search(r"<(?:html|body|div|p|table|td|span)\b", text, re.I):
        return text
    amex_transaction = _extract_amex_transaction_from_html(text)
    try:
        result = subprocess.run(
            ["html-text", "extract", "-", "--format", "text"],
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0:
            stdout = result.stdout.decode("utf-8", errors="replace") if isinstance(result.stdout, bytes) else str(result.stdout)
            stripped = stdout.strip()
            if amex_transaction and amex_transaction not in stripped:
                return f"{amex_transaction}\n\n{stripped}".strip()
            return stripped
    except Exception as exc:
        logger.warning("html-text conversion failed: %s", exc)
    if amex_transaction:
        return amex_transaction
    return text


def _extract_amex_transaction_from_html(text: str) -> str:
    """Recover AmEx transaction details from templates that html-text flattens poorly."""
    raw_html = str(text or "")
    if "american express" not in raw_html.lower() and "conferma operazione" not in raw_html.lower():
        return ""

    parser = _TextNodeParser()
    try:
        parser.feed(raw_html)
    except Exception as exc:
        logger.warning("AmEx HTML text-node parsing failed: %s", exc)
        return ""

    date_payee = ""
    amount = ""
    date_payee_re = re.compile(r"^\d{1,2}\s+[A-Za-zÀ-ÿ]{3,}\s+\d{4}\s+.+")
    amount_re = re.compile(r"^€\s*[0-9.]+,[0-9]{2}$")

    for idx, node in enumerate(parser.nodes):
        if not date_payee and date_payee_re.match(node):
            date_payee = node
            for following in parser.nodes[idx + 1 : idx + 6]:
                if amount_re.match(following):
                    amount = following.replace(" ", "")
                    break
        if date_payee and amount:
            break

    if not date_payee or not amount:
        return ""
    return f"Conferma Operazione\n{date_payee} {amount}"


def _parse_amount(s: str) -> float:
    """Parse Italian-format number (1.234,56) to float."""
    cleaned = s.replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _parse_date_from_text(text: str) -> str | None:
    """Parse a date-line prefix such as '6 mag 2026' to YYYY-MM-DD."""
    match = re.search(rf"\b(\d{{1,2}})\s+({_MONTHS_IT})\s+(\d{{4}})\b", text, re.I)
    if not match:
        return None
    day, month_token, year = match.groups()
    month = _MONTH_NUMBERS.get(month_token.lower()[:3])
    if not month:
        return None
    return f"{year}-{month}-{int(day):02d}"


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


def _dedupe_transactions(transactions: list[dict]) -> list[dict]:
    """Collapse duplicate regex hits from overlapping provider patterns."""
    deduped: list[dict] = []
    seen: set[tuple] = set()
    for tx in transactions:
        key = (
            str(tx.get("payee", "")).strip().lower(),
            round(float(tx.get("amount", 0) or 0), 2),
            str(tx.get("direction", "")),
            str(tx.get("currency", "EUR")),
            tx.get("date"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(tx)
    return deduped


_PAYEES_CACHE: dict = {"payees": None, "expires": 0.0}
_PAYEES_TTL = 300  # seconds


async def _fetch_ynab_payees(api_key: str, budget_id: str) -> list[dict]:
    """Fetch all YNAB payees, cached for 5 minutes."""
    now = time.monotonic()
    if _PAYEES_CACHE["payees"] is not None and now < _PAYEES_CACHE["expires"]:
        return _PAYEES_CACHE["payees"]
    url = f"{_YNAB_BASE}/budgets/{budget_id}/payees"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with httpx.AsyncClient(timeout=_YNAB_TIMEOUT) as client:
            resp = await client.get(url, headers=headers)
        if not resp.is_success:
            return []
        payees = resp.json().get("data", {}).get("payees", [])
        _PAYEES_CACHE["payees"] = payees
        _PAYEES_CACHE["expires"] = now + _PAYEES_TTL
        return payees
    except Exception as exc:
        logger.warning("YNAB payees fetch error: %s", exc)
        return []


async def _infer_category_for_payee(
    payee_name: str,
    api_key: str,
    budget_id: str,
) -> str | None:
    """Return the most-used category_id for a payee based on the last year of transactions.

    Returns None if fewer than 2 past transactions share the same category (no clear pattern).
    """
    payees = await _fetch_ynab_payees(api_key, budget_id)
    payee_lower = payee_name.lower()
    payee_id = next(
        (p["id"] for p in payees if (p.get("name") or "").lower() == payee_lower),
        None,
    )
    if not payee_id:
        return None

    since = (datetime.now(UTC).date() - timedelta(days=365)).isoformat()
    url = f"{_YNAB_BASE}/budgets/{budget_id}/payees/{payee_id}/transactions?since_date={since}"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with httpx.AsyncClient(timeout=_YNAB_TIMEOUT) as client:
            resp = await client.get(url, headers=headers)
        if not resp.is_success:
            return None
        txs = resp.json().get("data", {}).get("transactions", [])
    except Exception as exc:
        logger.warning("YNAB category inference fetch error: %s", exc)
        return None

    cat_counts: Counter = Counter()
    for t in txs:
        cat_id = t.get("category_id")
        cat_name = t.get("category_name") or ""
        if cat_id and "uncategorized" not in cat_name.lower():
            cat_counts[cat_id] += 1

    if not cat_counts:
        return None
    best_id, count = cat_counts.most_common(1)[0]
    return best_id if count >= 2 else None


async def _fetch_ynab_transactions_on_date(
    account_id: str,
    date_str: str,
    api_key: str,
    budget_id: str,
) -> list[dict]:
    """Fetch all YNAB transactions for an account on a specific date."""
    url = (
        f"{_YNAB_BASE}/budgets/{budget_id}/accounts/{account_id}/transactions"
        f"?since_date={date_str}"
    )
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with httpx.AsyncClient(timeout=_YNAB_TIMEOUT) as client:
            resp = await client.get(url, headers=headers)
        if not resp.is_success:
            logger.warning("YNAB dedup fetch failed: HTTP %s", resp.status_code)
            return []
        txs = resp.json().get("data", {}).get("transactions", [])
        return [t for t in txs if t.get("date") == date_str]
    except Exception as exc:
        logger.warning("YNAB dedup fetch error: %s", exc)
        return []


async def _post_ynab_transaction(
    tx: dict,
    *,
    received_at: str,
    ynab_account_id: str,
) -> dict:
    """POST one transaction to YNAB for the given account.

    Returns {'transaction_id': str} on success, {'skipped': True} if a duplicate
    by (amount, payee, date) already exists, or {'error': str} on failure.
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
    payee_name = str(tx.get("payee", "unknown"))[:50]

    # Client-side dedup: skip if same (amount, payee, date) already in YNAB
    existing = await _fetch_ynab_transactions_on_date(
        ynab_account_id, date_str, api_key, budget_id
    )
    for existing_tx in existing:
        if (
            existing_tx.get("amount") == amount_ms
            and (existing_tx.get("payee_name") or "").lower() == payee_name.lower()
        ):
            logger.info(
                "YNAB dedup: skipping %s %s on %s (already exists as id=%s)",
                payee_name, amount_ms, date_str, existing_tx.get("id"),
            )
            return {"skipped": True, "reason": "duplicate_by_amount_payee_date"}

    # Infer category from past transactions for this payee
    category_id = await _infer_category_for_payee(payee_name, api_key, budget_id)

    tx_body: dict = {
        "account_id": ynab_account_id,
        "date": date_str,
        "amount": amount_ms,
        "payee_name": payee_name,
        "memo": f"Auto-ingest from email ({tx.get('method', 'unknown')})"[:200],
        "cleared": "uncleared",
        "approved": False,
        "import_id": _ynab_import_id(tx, received_at),
    }
    if category_id:
        tx_body["category_id"] = category_id

    body = {"transaction": tx_body}
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

    # Convert HTML body to clean plain text (html-text CLI, no-op on plain text)
    email_text = _strip_html(email_text)
    # Prepend subject so PayPal subject-encoded amounts/merchants are extractable
    if subject:
        email_text = f"Subject: {subject}\n\n{email_text}"

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
                    "date": _parse_date_from_text(match.group(0)),
                    "method": "regex",
                })
    transactions = _dedupe_transactions(transactions)

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

    ynab_ok = ynab_failed = ynab_skipped = ledger_ok = ledger_failed = 0
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
                elif ynab_res.get("skipped"):
                    ynab_skipped += 1
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
    result["ynab_skipped"] = ynab_skipped
    result["ynab_failed"] = ynab_failed
    result["ledger_inserted"] = ledger_ok
    result["ledger_failed"] = ledger_failed
    if write_errors:
        result["write_errors"] = write_errors[:10]
    return result
