"""Grounding verification.

Schema validity is not grounding. A response can satisfy every type
constraint and still cite evidence that does not exist, or assert a
number nobody computed. Two checks close that gap, and together they are
what separates this from a wrapper around a chat completion.

**Citation verification.** Every `evidence_id` must belong to this case's
packet. One that does not fails the whole response - not just that
hypothesis - because a model willing to invent a citation has told you
its other citations are unreliable too.

**Numeric cross-check.** Every number in the prose must be one the engine
put in the packet. This enforces blueprint section 11 - *do not use AI
for arithmetic* - mechanically, rather than by asking politely in a
prompt and hoping.

A failure here is not an error to swallow. The case keeps its
deterministic finding, the UI says plainly that no grounded answer was
produced, and the violation is counted. A visible refusal is a stronger
demonstration than an answer that is always available.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ledgergraph_domain.enums import AiValidationStatus

from .packet import EvidencePacket
from .schemas import Investigation

#: Numbers below this are read as counts, ordinals, percentages, or day
#: offsets - "2 candidates", "T+3", "18% GST" - rather than as monetary
#: claims, and are not required to appear in the packet.
#:
#: The threshold is a real tradeoff, stated rather than hidden: it means
#: a fabricated small number passes. Set it lower and ordinary prose gets
#: rejected constantly, the check gets disabled in frustration, and the
#: guarantee is worth nothing. Money in this system is in paise, so an
#: invented amount that matters is far above this line.
SMALL_NUMBER_CEILING = 100

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


@dataclass
class VerificationResult:
    status: AiValidationStatus
    errors: list[str] = field(default_factory=list)
    unknown_citations: list[str] = field(default_factory=list)
    ungrounded_numbers: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status is AiValidationStatus.VALID


def verify(
    investigation: Investigation,
    packet: EvidencePacket,
    *,
    check_numbers: bool = True,
) -> VerificationResult:
    """Check a schema-valid response against the evidence it was given."""
    unknown = sorted(investigation.cited_evidence_ids() - packet.evidence_ids)
    if unknown:
        return VerificationResult(
            status=AiValidationStatus.CITATION_VIOLATION,
            errors=[
                f"cited evidence not present in this case: {', '.join(unknown)}"
            ],
            unknown_citations=unknown,
        )

    if check_numbers:
        prose = " ".join(
            [investigation.recommended_action]
            + [h.statement for h in investigation.hypotheses]
            + list(investigation.uncertainties)
        )
        ungrounded = _ungrounded_numbers(prose, packet)
        if ungrounded:
            return VerificationResult(
                status=AiValidationStatus.NUMERIC_VIOLATION,
                errors=[
                    "asserted numbers the engine did not compute: "
                    + ", ".join(ungrounded)
                ],
                ungrounded_numbers=ungrounded,
            )

    return VerificationResult(status=AiValidationStatus.VALID)


def _ungrounded_numbers(prose: str, packet: EvidencePacket) -> list[str]:
    allowed = _allowed_tokens(packet)
    offenders: list[str] = []

    for match in _NUMBER.finditer(prose):
        raw = match.group(0)
        normalised = raw.replace(",", "")
        try:
            value = float(normalised)
        except ValueError:            # pragma: no cover - regex guarantees a number
            continue

        if value < SMALL_NUMBER_CEILING and normalised.count(".") == 0:
            continue                  # a count or an ordinal, not a claim about money

        if normalised in allowed or raw in allowed:
            continue
        # A formatted amount may appear with or without its decimals.
        if normalised.rstrip("0").rstrip(".") in allowed:
            continue
        offenders.append(raw)

    return sorted(set(offenders))


def _allowed_tokens(packet: EvidencePacket) -> set[str]:
    """Every numeric string the engine produced, in each form it may be written.

    A value computed as `48746770` paise is legitimately written as
    `487467.70` or `4,87,467.70`, so all three are accepted. What is not
    accepted is a fourth number that appears nowhere in the packet.
    """
    allowed: set[str] = set()
    for value in packet.computed_values:
        if value is None:
            continue
        text = str(value)
        allowed.add(text)
        allowed.add(text.replace(",", ""))
        stripped = text.replace(",", "")
        if "." in stripped:
            allowed.add(stripped.rstrip("0").rstrip("."))
        # Also allow the raw-paise form of any formatted amount, and vice
        # versa, since the packet carries both and prose may use either.
        try:
            as_float = float(stripped)
        except ValueError:
            continue
        if as_float.is_integer():
            allowed.add(str(int(as_float)))
        allowed.add(str(int(round(as_float * 100))))

    # Dates and identifiers carry digits that are not monetary claims.
    for record in packet.records:
        for key in ("business_date", "id", "reference", "parent"):
            if record.get(key):
                for token in _NUMBER.findall(str(record[key])):
                    allowed.add(token.replace(",", ""))
    for evidence in packet.evidence:
        for token in _NUMBER.findall(evidence.get("statement", "")):
            allowed.add(token.replace(",", ""))
        for value in evidence.get("values_compared", {}).values():
            for token in _NUMBER.findall(str(value)):
                allowed.add(token.replace(",", ""))

    return allowed
