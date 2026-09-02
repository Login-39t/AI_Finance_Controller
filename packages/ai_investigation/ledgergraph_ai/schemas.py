"""The structured output contract.

One Pydantic model, shared across every provider adapter. Each adapter
hands the provider its native constrained-decoding hook - `responseSchema`
for Gemini, `response_format={"type": "json_schema"}` for the
OpenAI-compatible set - and then validates the result against this model
regardless.

That belt-and-braces is deliberate. The provider's constraint removes a
failure class; this validation is the actual guarantee, and it runs even
when a provider's enforcement is weak, absent, or silently degraded. The
system's correctness must not depend on a vendor's feature matrix.
"""

from __future__ import annotations

from typing import Literal

from ledgergraph_domain.enums import ExceptionType
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Hypothesis(BaseModel):
    """One ranked explanation, with the evidence it rests on."""

    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=10, max_length=600)
    #: Must reference evidence present in this case's packet. Enforced by
    #: verify.py, not here - a schema can require a list of strings but
    #: cannot know which strings are real.
    evidence_ids: list[str] = Field(min_length=1, max_length=8)
    likelihood: Literal["high", "medium", "low"]


class Investigation(BaseModel):
    """What the model is allowed to return. Nothing else parses."""

    model_config = ConfigDict(extra="forbid")

    #: Validates against the eight-value taxonomy. A hallucinated category
    #: fails here, before any of the grounding checks run.
    classification: ExceptionType
    hypotheses: list[Hypothesis] = Field(min_length=1, max_length=5)
    recommended_action: str = Field(min_length=10, max_length=1000)
    requires_human_approval: bool
    #: Advisory only. The auto-resolution gate never reads this - a model
    #: that is confident and wrong changes nothing about what gets
    #: cleared. It is displayed so a reviewer can weigh the explanation,
    #: not so the system can act on it.
    confidence: float = Field(ge=0.0, le=1.0)
    #: Required and non-empty. A model that states no uncertainty about a
    #: case a human is being asked to judge is not being useful, and the
    #: UI gives this the same prominence as the hypotheses.
    uncertainties: list[str] = Field(min_length=1, max_length=6)

    @field_validator("uncertainties")
    @classmethod
    def _no_empty_uncertainties(cls, v: list[str]) -> list[str]:
        cleaned = [u.strip() for u in v if u and u.strip()]
        if not cleaned:
            raise ValueError("uncertainties must contain at least one non-empty statement")
        return cleaned

    def cited_evidence_ids(self) -> set[str]:
        return {eid for h in self.hypotheses for eid in h.evidence_ids}


#: JSON Schema handed to providers that support constrained decoding.
#: Generated from the model so the two cannot drift.
def json_schema() -> dict:
    schema = Investigation.model_json_schema()
    # Gemini and several OpenAI-compatible endpoints reject $defs/$ref;
    # inline them so one schema serves every adapter.
    return _inline_refs(schema)


def _inline_refs(schema: dict) -> dict:
    defs = schema.pop("$defs", {})

    def resolve(node):
        if isinstance(node, dict):
            ref = node.get("$ref")
            if ref and ref.startswith("#/$defs/"):
                target = defs.get(ref.split("/")[-1], {})
                merged = {k: v for k, v in node.items() if k != "$ref"}
                return resolve({**target, **merged})
            return {k: resolve(v) for k, v in node.items()}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)
