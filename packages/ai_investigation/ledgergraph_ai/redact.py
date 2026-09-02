"""PII redaction, applied before anything leaves the process.

Blueprint section 17: never send unredacted financial data to an external
model. The rule here is stronger than masking, and the difference matters
for usefulness.

**Stable pseudonyms, not asterisks.** `cust_0417` becomes `CUSTOMER_A7`
consistently within a packet, so the model can still reason about
identity - "the same customer as record 3" - without ever receiving the
value. Replacing it with `****` destroys that reasoning; replacing it
with a random token per occurrence destroys it too.

**The mapping stays server-side.** Nothing sent outward can be reversed
by whoever receives it, and the UI re-substitutes real values for the
analyst from the local map.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

# Ordered most-specific first: an email contains things that would
# otherwise match the phone and card patterns.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("CARD", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    # Digit-boundary lookarounds, not `\b`. A `\b` placed after the
    # optional country code can never match: having consumed `+91`, the
    # next character is a digit and the one before it is too, so there is
    # no word boundary there. The bare form matched and the realistic
    # `+91...` form silently did not - and because `contains_pii` shares
    # these patterns, the guard meant to catch that was blind in exactly
    # the same way.
    ("PHONE", re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)")),
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("IFSC", re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")),
    ("ACCOUNT", re.compile(r"\b(?:a/c|acct|account)[\s:#-]*(\d{6,18})\b", re.IGNORECASE)),
)

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


@dataclass
class Redactor:
    """Deterministic per-run pseudonymisation.

    Seeded by run so the same customer maps to the same pseudonym across
    every case in a run - which is what lets the model notice a pattern -
    while two different runs produce different tokens, so a pseudonym
    leaked from one run means nothing in another.
    """

    seed: str = "run"
    _forward: dict[str, str] = field(default_factory=dict)
    _reverse: dict[str, str] = field(default_factory=dict)

    def pseudonym(self, kind: str, value: str) -> str:
        key = f"{kind}:{value}"
        if key in self._forward:
            return self._forward[key]

        digest = hashlib.sha256(f"{self.seed}:{key}".encode()).digest()
        token = "".join(_ALPHABET[b % len(_ALPHABET)] for b in digest[:4])
        pseudonym = f"{kind}_{token}"

        # Collisions are astronomically unlikely but would silently merge
        # two identities, so they are resolved rather than assumed away.
        suffix = 0
        while pseudonym in self._reverse and self._reverse[pseudonym] != value:
            suffix += 1
            pseudonym = f"{kind}_{token}{suffix}"

        self._forward[key] = pseudonym
        self._reverse[pseudonym] = value
        return pseudonym

    def scrub(self, text: str | None) -> str | None:
        """Replace every recognised PII pattern in free text."""
        if not text:
            return text
        out = text
        for kind, pattern in _PATTERNS:
            def replace(match: re.Match[str], _kind: str = kind) -> str:
                raw = match.group(1) if match.groups() else match.group(0)
                return self.pseudonym(_kind, _canonical(_kind, raw))
            out = pattern.sub(replace, out)
        return out

    def customer(self, value: str | None) -> str | None:
        """Customer references are always pseudonymised, pattern or not."""
        return self.pseudonym("CUSTOMER", value) if value else value

    def reveal(self, pseudonym: str) -> str | None:
        """Server-side only. Never reachable from an outbound payload."""
        return self._reverse.get(pseudonym)

    @property
    def mapping(self) -> dict[str, str]:
        return dict(self._reverse)


def _canonical(kind: str, raw: str) -> str:
    """Reduce a value to one form before pseudonymising it.

    The same phone number written `+91 98765 43210` and `9876543210` must
    map to the same token, or the stability the model relies on to say
    "the same customer as record 3" quietly stops holding while the
    redaction still looks correct.
    """
    if kind == "PHONE":
        digits = re.sub(r"\D", "", raw)
        return digits[-10:] if len(digits) >= 10 else digits
    if kind in ("CARD", "ACCOUNT"):
        return re.sub(r"\D", "", raw)
    if kind == "EMAIL":
        return raw.strip().lower()
    return raw.strip().upper()


def contains_pii(text: str | None) -> bool:
    """True when any recognised pattern is present.

    Used by the outbound assertion in the tests: a packet that still
    matches one of these has not been scrubbed, and that is a release
    blocker rather than a warning.
    """
    if not text:
        return False
    return any(pattern.search(text) for _, pattern in _PATTERNS)
