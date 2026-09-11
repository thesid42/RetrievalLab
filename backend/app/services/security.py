from __future__ import annotations

import re

SUSPICIOUS_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"reveal\s+(the\s+)?system\s+prompt", re.IGNORECASE),
    re.compile(r"(?:call|invoke|execute)\s+(?:the\s+)?tool", re.IGNORECASE),
]
SECRET_PATTERN = re.compile(
    r"(?i)\b(?:sk|api|token|key)[-_][a-z0-9]{12,}\b|\b[A-Z0-9]{20,}\b"
)
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)


def safe_evidence_text(value: str) -> tuple[str, bool]:
    suspicious = any(pattern.search(value) for pattern in SUSPICIOUS_PATTERNS)
    if not suspicious:
        return value, False
    sanitized = value
    for pattern in SUSPICIOUS_PATTERNS:
        sanitized = pattern.sub("[untrusted instruction removed]", sanitized)
    return sanitized, True


def redact_sensitive(value: str) -> str:
    value = SECRET_PATTERN.sub("[REDACTED_SECRET]", value)
    return EMAIL_PATTERN.sub("[REDACTED_EMAIL]", value)
