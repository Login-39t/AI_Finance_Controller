"""Grounded AI investigation.

Evidence packet in, schema-validated and grounding-verified JSON out.
Imports nothing from `backend/` or `frontend/`, and the whole pipeline
except the network call itself is testable without an API key - because
the parts that decide whether an answer is trustworthy do not involve
HTTP.
"""

from .client import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    FakeProvider,
    InvestigationOutcome,
    build_provider,
    investigate,
)
from .packet import EvidencePacket, build_packet
from .redact import Redactor, contains_pii
from .schemas import Hypothesis, Investigation, json_schema
from .verify import VerificationResult, verify

__all__ = [
    "PROMPT_VERSION",
    "SYSTEM_PROMPT",
    "EvidencePacket",
    "FakeProvider",
    "Hypothesis",
    "Investigation",
    "InvestigationOutcome",
    "Redactor",
    "VerificationResult",
    "build_packet",
    "build_provider",
    "contains_pii",
    "investigate",
    "json_schema",
    "verify",
]
