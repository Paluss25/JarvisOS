"""Layer 3 — Classifier: domain, sensitivity, risk, and priority classification."""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml


@dataclass
class ClassificationResult:
    primary_domain: str      # "finance" | "legal" | "security" | "hr" | "ops" | "marketing" | "general"
    secondary_domain: Optional[str]
    sensitivity: str         # "public" | "internal" | "sensitive" | "critical"
    risk_level: str          # "none" | "low" | "medium" | "high" | "critical"
    priority: str            # "low" | "normal" | "high" | "urgent"
    confidence: float        # 0.0–1.0


class Classifier:
    """Classify an email by business domain, sensitivity, risk, and priority."""

    _DOMAIN_KEYWORDS: Dict[str, List[str]] = {
        "finance": [
            "invoice", "payment", "bank", "transfer", "iban", "wire", "billing",
            "vat", "tax", "accounting", "budget", "expense", "payroll", "receipt",
            "purchase",
        ],
        "legal": [
            "contract", "agreement", "clause", "lawsuit", "litigation", "gdpr",
            "compliance", "attorney", "legal", "jurisdiction", "court", "subpoena",
            "nda",
        ],
        "security": [
            "breach", "attack", "vulnerability", "cve", "malware", "phishing",
            "ransomware", "credential", "firewall", "intrusion", "exploit", "patch",
        ],
        "hr": [
            "employee", "onboarding", "resignation", "salary", "benefits",
            "performance", "interview", "recruitment", "termination", "leave",
        ],
        "ops": [
            "server", "deploy", "incident", "outage", "monitor", "backup",
            "maintenance", "uptime", "sla", "kubernetes", "docker",
        ],
        "marketing": [
            "campaign", "newsletter", "promotion", "discount", "offer", "subscribe",
            "unsubscribe", "click", "open rate", "conversion",
        ],
    }

    _SENSITIVITY_KEYWORDS: Dict[str, List[str]] = {
        "critical": [
            "password", "secret", "api key", "private key", "credential", "ssn",
            "passport",
        ],
        "sensitive": [
            "iban", "bank account", "salary", "medical", "health", "confidential",
            "gdpr", "personal data",
        ],
        "internal": ["internal", "employee", "team", "project"],
    }

    # Domains that boost priority to "high" (if not already urgent)
    _HIGH_PRIORITY_DOMAINS = frozenset({"finance", "legal", "security"})

    _WHITELIST_PATH = Path(__file__).parent.parent / "config" / "sender-whitelist.yaml"
    _WHITELIST_RELOAD_INTERVAL = 30  # seconds between mtime checks

    def __init__(self) -> None:
        self._whitelist_data: Dict[str, Any] = {}
        self._whitelist_mtime: float = 0.0
        self._whitelist_checked_at: float = 0.0

    def _load_whitelist(self) -> None:
        now = time.monotonic()
        if now - self._whitelist_checked_at < self._WHITELIST_RELOAD_INTERVAL:
            return
        self._whitelist_checked_at = now
        try:
            mtime = self._WHITELIST_PATH.stat().st_mtime
            if mtime != self._whitelist_mtime:
                with self._WHITELIST_PATH.open() as fh:
                    data = yaml.safe_load(fh) or {}
                self._whitelist_data = data
                self._whitelist_mtime = mtime
        except FileNotFoundError:
            self._whitelist_data = {}

    def _whitelist_lookup(self, sender: str) -> Optional[Dict[str, Any]]:
        """Return override dict if sender matches, else None."""
        self._load_whitelist()
        sender = sender.strip().lower()

        email_overrides: Dict[str, Any] = self._whitelist_data.get("email_overrides") or {}
        if sender in email_overrides:
            return email_overrides[sender]

        domain_overrides: Dict[str, Any] = self._whitelist_data.get("domain_overrides") or {}
        for pattern, entry in domain_overrides.items():
            if sender.endswith(pattern.lower()):
                return entry

        return None

    def classify(self, subject: str, body: str, sender: Optional[str] = None) -> ClassificationResult:
        text = (subject + " " + body).lower()

        # ------------------------------------------------------------------
        # 0. Sender whitelist (takes precedence over keyword scoring)
        # ------------------------------------------------------------------
        if sender:
            override = self._whitelist_lookup(sender)
            if override:
                forced_domain: str = override.get("domain", "general")
                forced_confidence: float = float(override.get("confidence", 1.0))
                sensitivity = "public"
                for level in ("critical", "sensitive", "internal"):
                    for kw in self._SENSITIVITY_KEYWORDS[level]:
                        if kw in text:
                            sensitivity = level
                            break
                    if sensitivity != "public":
                        break
                _risk_map_wl = {"critical": "critical", "sensitive": "high", "internal": "medium", "public": "low"}
                priority_wl = "urgent" if sensitivity == "critical" else (
                    "high" if sensitivity == "sensitive" or forced_domain in self._HIGH_PRIORITY_DOMAINS else "normal"
                )
                return ClassificationResult(
                    primary_domain=forced_domain,
                    secondary_domain=None,
                    sensitivity=sensitivity,
                    risk_level=_risk_map_wl[sensitivity],
                    priority=priority_wl,
                    confidence=forced_confidence,
                )

        # ------------------------------------------------------------------
        # 1. Domain scoring
        # ------------------------------------------------------------------
        domain_scores: Dict[str, int] = {}
        for domain, keywords in self._DOMAIN_KEYWORDS.items():
            count = sum(1 for kw in keywords if kw in text)
            domain_scores[domain] = count

        total_keyword_hits = sum(domain_scores.values())

        # Sort by score (desc) preserving dict insertion order for ties
        sorted_domains: List[Tuple[str, int]] = sorted(
            self._DOMAIN_KEYWORDS.keys(),
            key=lambda d: -domain_scores[d],
        )

        top_domain = sorted_domains[0]
        top_score = domain_scores[top_domain]

        # Confidence
        confidence = min(1.0, total_keyword_hits / 5.0)

        # If confidence < 0.3, domain = "general"
        if confidence < 0.3:
            primary_domain = "general"
            secondary_domain = None
        else:
            # Winning domain (highest count; all-zero → general)
            if top_score == 0:
                primary_domain = "general"
                secondary_domain = None
            else:
                primary_domain = top_domain
                # Secondary: second-highest with count > 0
                secondary_domain = None
                for d in sorted_domains[1:]:
                    if domain_scores[d] > 0:
                        secondary_domain = d
                        break

        # ------------------------------------------------------------------
        # 2. Sensitivity
        # ------------------------------------------------------------------
        sensitivity = "public"
        for level in ("critical", "sensitive", "internal"):
            for kw in self._SENSITIVITY_KEYWORDS[level]:
                if kw in text:
                    sensitivity = level
                    break
            if sensitivity != "public":
                break

        # ------------------------------------------------------------------
        # 3. Risk level
        # ------------------------------------------------------------------
        _risk_map = {
            "critical": "critical",
            "sensitive": "high",
            "internal": "medium",
            "public": "low",
        }
        risk_level = _risk_map[sensitivity]

        # ------------------------------------------------------------------
        # 4. Priority
        # ------------------------------------------------------------------
        if sensitivity == "critical":
            priority = "urgent"
        elif sensitivity == "sensitive":
            priority = "high"
        elif primary_domain in self._HIGH_PRIORITY_DOMAINS:
            priority = "high"
        else:
            priority = "normal"

        return ClassificationResult(
            primary_domain=primary_domain,
            secondary_domain=secondary_domain,
            sensitivity=sensitivity,
            risk_level=risk_level,
            priority=priority,
            confidence=confidence,
        )
