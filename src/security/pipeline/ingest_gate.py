"""Layer 1 — IngestGate: sanitize and triage raw email content."""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse


@dataclass
class IngestResult:
    safe: bool
    sanitized_body: str
    sanitized_subject: str
    attachment_risk: str  # "none" | "low" | "medium" | "high" | "critical"
    suspicious_links: List[str]
    blocked_attachments: List[str]
    reasons: List[str]


class IngestGate:
    """Strip dangerous content from inbound email before it touches any agent."""

    # Dangerous attachment extensions
    _DANGEROUS_EXTENSIONS = frozenset(
        {
            ".exe",
            ".bat",
            ".cmd",
            ".ps1",
            ".vbs",
            ".js",
            ".jar",
            ".msi",
            ".dmg",
            ".com",
            ".scr",
            ".pif",
        }
    )

    # URL shortener domains
    _SHORTENER_DOMAINS = frozenset(
        {
            "bit.ly",
            "tinyurl.com",
            "t.co",
            "goo.gl",
            "ow.ly",
            "short.link",
            "rb.gy",
            "shorturl.at",
        }
    )

    # Regex: strip dangerous block-level tags and their full content
    _BLOCK_TAG_RE = re.compile(
        r"<(script|iframe|object|embed)[^>]*>.*?</\1>",
        re.IGNORECASE | re.DOTALL,
    )

    # Regex: strip on* event attributes (e.g. onclick="...", onmouseover='...')
    _EVENT_ATTR_RE = re.compile(
        r'\s+on\w+\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^\s>]*)',
        re.IGNORECASE,
    )

    # Regex: strip all remaining HTML tags (for subject sanitization)
    _ALL_TAGS_RE = re.compile(r"<[^>]+>", re.IGNORECASE)

    # Regex: extract href and src values from the original body
    _LINK_RE = re.compile(
        r"""(?:href|src)\s*=\s*(?:"([^"]+)"|'([^']+)'|(\S+))""",
        re.IGNORECASE,
    )

    def process(
        self,
        subject: str,
        body: str,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> IngestResult:
        if attachments is None:
            attachments = []

        reasons: List[str] = []
        suspicious_links: List[str] = []
        blocked_attachments: List[str] = []
        attachment_risk = "none"

        # --- 1. Extract links from ORIGINAL body BEFORE sanitization ----------
        for match in self._LINK_RE.finditer(body):
            url = match.group(1) or match.group(2) or match.group(3)
            if not url:
                continue
            try:
                parsed = urlparse(url)
                domain = parsed.hostname or ""
            except Exception:
                domain = ""

            flagged = False
            # Punycode / non-ASCII domain
            if domain:
                try:
                    domain.encode("ascii")
                except UnicodeEncodeError:
                    suspicious_links.append(url)
                    reasons.append("PUNYCODE_DOMAIN")
                    flagged = True

            # xn-- prefix also indicates punycode
            if not flagged and domain and (domain.startswith("xn--") or ".xn--" in domain):
                suspicious_links.append(url)
                reasons.append("PUNYCODE_DOMAIN")
                flagged = True

            # URL shortener
            if not flagged and domain:
                bare = domain.lower().lstrip("www.")
                if bare in self._SHORTENER_DOMAINS or domain.lower() in self._SHORTENER_DOMAINS:
                    suspicious_links.append(url)
                    reasons.append("URL_SHORTENER")

        # --- 2. HTML sanitization of body ------------------------------------
        sanitized_body = self._BLOCK_TAG_RE.sub("", body)
        sanitized_body = self._EVENT_ATTR_RE.sub("", sanitized_body)
        html_stripped = sanitized_body != body
        if html_stripped:
            reasons.append("ACTIVE_HTML_STRIPPED")

        # --- 3. Subject sanitization -----------------------------------------
        sanitized_subject = self._ALL_TAGS_RE.sub("", subject)

        # --- 4. Attachment analysis ------------------------------------------
        for att in attachments:
            filename: str = att.get("filename", "")
            content_type: str = att.get("content_type", "")

            # Check dangerous extension
            ext = ""
            dot_pos = filename.rfind(".")
            if dot_pos != -1:
                ext = filename[dot_pos:].lower()

            if ext in self._DANGEROUS_EXTENSIONS:
                blocked_attachments.append(filename)
                attachment_risk = "critical"
            elif "macro" in content_type.lower():
                blocked_attachments.append(filename)
                if attachment_risk not in ("critical",):
                    attachment_risk = "high"

        # --- 5. Safe flag ----------------------------------------------------
        safe = len(blocked_attachments) == 0 and len(suspicious_links) == 0 and not html_stripped

        return IngestResult(
            safe=safe,
            sanitized_body=sanitized_body,
            sanitized_subject=sanitized_subject,
            attachment_risk=attachment_risk,
            suspicious_links=suspicious_links,
            blocked_attachments=blocked_attachments,
            reasons=reasons,
        )
