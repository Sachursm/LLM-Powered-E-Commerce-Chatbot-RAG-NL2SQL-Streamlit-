"""Small redaction helpers for conversational text crossing logs or model APIs."""

import re


_REDACTIONS = (
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer [REDACTED]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"), "[JWT REDACTED]"),
    (re.compile(r"\bgsk_[A-Za-z0-9_-]+\b"), "[API KEY REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "[API KEY REDACTED]"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"), "[API TOKEN REDACTED]"),
    (re.compile(r"\b\d{5,}:[A-Za-z0-9_-]{20,}\b"), "[BOT TOKEN REDACTED]"),
    (
        re.compile(r"(?i)\b(password|passwd|otp|token|secret|api[_ -]?key)\s*[:=]\s*[^\s,;]+"),
        r"\1=[REDACTED]",
    ),
)


def redact_sensitive_text(value: str, *, max_length: int = 1200) -> str:
    """Redact recognizable credentials before storing, logging, or prompting."""
    safe = value[:max_length]
    for pattern, replacement in _REDACTIONS:
        safe = pattern.sub(replacement, safe)
    return safe
