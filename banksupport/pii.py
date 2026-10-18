"""PII scrubbing: runs BEFORE any model call.

Credit-card numbers (Luhn-validated), SSN-like patterns and long digit
runs are replaced with typed placeholders. Originals are sealed in a
PIIVault keyed by session: they never leave the trust boundary except
through explicit, audited tool calls.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Tuple

CARD_RE = re.compile(r"\b(?:\d[ \-\.]?){13,19}\b")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
ACCT_RE = re.compile(r"\b\d{9,12}\b")


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


@dataclass
class Redaction:
    placeholder: str
    pii_type: str
    original: str


class PIIScrubber:
    """Detect and redact PII, returning (scrubbed_text, redactions)."""

    def scrub(self, text: str) -> Tuple[str, List[Redaction]]:
        redactions: List[Redaction] = []
        counter = [0]

        def _next_placeholder(pii_type: str, original: str) -> str:
            counter[0] += 1
            ph = f"[REDACTED:{pii_type}:{counter[0]}]"
            redactions.append(Redaction(ph, pii_type, original))
            return ph

        def _card_sub(match: re.Match) -> str:
            raw = match.group(0)
            digits = re.sub(r"\D", "", raw)
            if 13 <= len(digits) <= 19 and _luhn_ok(digits):
                return _next_placeholder("CARD", raw)
            if len(digits) >= 9:
                return _next_placeholder("ACCOUNT_NUMBER", raw)
            return raw

        out = CARD_RE.sub(_card_sub, text)

        def _ssn_sub(match: re.Match) -> str:
            return _next_placeholder("SSN", match.group(0))

        out = SSN_RE.sub(_ssn_sub, out)

        def _acct_sub(match: re.Match) -> str:
            return _next_placeholder("ACCOUNT_NUMBER", match.group(0))

        out = ACCT_RE.sub(_acct_sub, out)
        return out, redactions


class PIIVault:
    """Sealed store for redacted originals, keyed by session.

    Tools inside the trust boundary may unseal a value they need;
    nothing else ever sees the raw PII.
    """

    def __init__(self) -> None:
        self._store: Dict[str, Dict[str, str]] = {}

    def seal(self, session_id: str, mapping: Dict[str, str]) -> None:
        self._store.setdefault(session_id, {}).update(mapping)

    def unseal(self, session_id: str, placeholder: str) -> str:
        try:
            return self._store[session_id][placeholder]
        except KeyError:
            raise KeyError(f"no sealed value for {placeholder!r}") from None
