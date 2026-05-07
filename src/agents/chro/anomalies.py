"""Anomaly detection per HR doc type.

Each detector is a pure function that returns a list of
{severity, code, message[, escalate_to]} dicts. Persisted into
hr_audit_log.metadata['anomalies'] by the API layer.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _num(value: Any) -> float | None:
    """Best-effort numeric coercion that tolerates None, str, Decimal."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def detect_payslip_anomalies(
    new_fields: dict, prior_payslips: list[dict]
) -> list[dict]:
    """Compare the freshly-extracted payslip against the most recent prior.

    Field names follow the new payslips schema (net_amount,
    contribution_amount). For backward-compatibility we also accept the
    legacy aliases (net_pay, inps_employee).
    """
    anomalies: list[dict] = []
    if not prior_payslips:
        return anomalies
    prev = prior_payslips[0]

    # Net pay delta (>5%)
    np_new = _num(new_fields.get("net_amount") or new_fields.get("net_pay"))
    np_prev = _num(prev.get("net_amount") or prev.get("net_pay"))
    if np_new is not None and np_prev not in (None, 0):
        delta = abs((np_new - np_prev) / np_prev)
        if delta > 0.05:
            anomalies.append({
                "severity": "warning",
                "code": "net_pay_delta",
                "message": (
                    f"Net pay changed {delta:.1%} "
                    f"({np_prev:.2f} -> {np_new:.2f} EUR)"
                ),
            })

    # INPS / contribution delta (>10%, escalate to CEO)
    inps_new = _num(
        new_fields.get("contribution_amount") or new_fields.get("inps_employee")
    )
    inps_prev = _num(
        prev.get("contribution_amount") or prev.get("inps_employee")
    )
    if inps_new is not None and inps_prev not in (None, 0):
        d = abs((inps_new - inps_prev) / inps_prev)
        if d > 0.10:
            anomalies.append({
                "severity": "critical",
                "code": "inps_anomaly",
                "message": (
                    f"INPS contribution changed {d:.1%} "
                    "— possible rate or base change"
                ),
                "escalate_to": "ceo",
            })

    return anomalies


def detect_expense_anomalies(new_fields: dict) -> list[dict]:
    anomalies: list[dict] = []
    amount = _num(new_fields.get("amount_eur"))
    if amount is not None and amount > 1000:
        anomalies.append({
            "severity": "info",
            "code": "expense_high_amount",
            "message": f"Expense above 1000 EUR: {amount}",
        })
    return anomalies


def detect_leave_anomalies(new_fields: dict) -> list[dict]:
    anomalies: list[dict] = []
    residual = _num(new_fields.get("leave_residual_days"))
    if residual is not None and residual < 5:
        anomalies.append({
            "severity": "warning",
            "code": "leave_low",
            "message": f"Residual leave below 5 days: {residual}",
        })
    return anomalies
