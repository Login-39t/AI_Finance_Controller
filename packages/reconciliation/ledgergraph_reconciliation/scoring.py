"""Confidence.

Confidence here is a decision-control signal, not a model probability. It
is computed from four deterministic inputs and stored with its components
so any score can be re-derived from the record rather than taken on
trust.

    confidence = 0.50 * rule_strength      how strong was the evidence
               + 0.20 * data_quality       how complete were the records
               + 0.20 * consistency        does the arithmetic balance
               + 0.10 * unambiguity        margin to the runner-up

**The caps matter more than the weights.** A weighted sum lets three
strong signals drag the score up while the one signal that should veto
gets averaged away - a group whose bridge does not balance can still
score 0.88 on identifiers alone. The caps make the veto structural
rather than statistical.
"""

from __future__ import annotations

from ledgergraph_domain.enums import RuleTier

from .models import Bridge, MatchGroup

WEIGHTS = {
    "rule_strength": 0.50,
    "data_quality": 0.20,
    "consistency": 0.20,
    "unambiguity": 0.10,
}

#: Base strength per rule. R1 and R2 join on exact identifiers, so they
#: sit at the top; the scored rules cannot reach the auto-resolve floor
#: by construction, which is intentional.
RULE_STRENGTH = {
    "R1": 0.99,
    "R2": 0.98,
    "R3": 0.98,
    "R4": 0.97,
    "R5": 0.95,
    "R6": 0.85,
    "R7": 0.75,
}

CAP_BRIDGE_UNBALANCED = 0.60
CAP_COMPETING_CANDIDATE = 0.70
CAP_DATA_QUALITY_FLAG = 0.75


def score_group(
    group: MatchGroup,
    *,
    bridge: Bridge | None = None,
    margin_to_runner_up: float | None = None,
    candidate_margin: float = 0.05,
) -> tuple[float, dict[str, float]]:
    """Compute confidence and return it with its components.

    Returns the raw component scores alongside the final value, including
    any cap that was applied, so the case detail can show how the number
    was reached rather than just asserting it.
    """
    components: dict[str, float] = {}

    components["rule_strength"] = RULE_STRENGTH.get(group.matched_by_rule, 0.5)

    flags = {f for link in group.links for f in link.transaction.data_quality_flags}
    components["data_quality"] = 1.0 if not flags else max(0.0, 1.0 - 0.25 * len(flags))

    if bridge is None:
        components["consistency"] = 1.0 if group.has_passing_evidence() else 0.5
    elif bridge.balances_exactly:
        components["consistency"] = 1.0
    elif bridge.balances:
        # Balanced only by consuming tolerance. Correct, but weaker
        # evidence than an exact balance, and the difference is visible.
        components["consistency"] = 0.85
    else:
        components["consistency"] = 0.0

    if margin_to_runner_up is None:
        components["unambiguity"] = 1.0
    else:
        # Scales to 1.0 at twice the required margin; a bare pass scores 0.5.
        components["unambiguity"] = min(1.0, margin_to_runner_up / (candidate_margin * 2))

    raw = sum(WEIGHTS[k] * v for k, v in components.items())

    # Caps. Each expresses a veto that a weighted average would dilute.
    caps: list[tuple[str, float]] = []
    if bridge is not None and not bridge.balances:
        caps.append(("bridge_unbalanced", CAP_BRIDGE_UNBALANCED))
    if margin_to_runner_up is not None and margin_to_runner_up <= candidate_margin:
        caps.append(("competing_candidate", CAP_COMPETING_CANDIDATE))
    if flags:
        caps.append(("data_quality_flag", CAP_DATA_QUALITY_FLAG))
    if group.tier is RuleTier.SCORED:
        caps.append(("scored_tier", RULE_STRENGTH.get(group.matched_by_rule, 0.85)))

    final = raw
    for name, ceiling in caps:
        if final > ceiling:
            final = ceiling
            components[f"cap_{name}"] = ceiling

    return round(min(1.0, max(0.0, final)), 4), components


def score_candidate(
    subject_identifier: str | None,
    candidate_identifier: str | None,
    *,
    amount_equal: bool,
    date_distance_days: int,
    window_days: int,
    status_compatible: bool,
    counterparty_similarity: float,
) -> tuple[float, dict[str, float]]:
    """Score one candidate against a subject, per blueprint section 8.

        0.35 identifier + 0.25 amount + 0.15 date
      + 0.15 status     + 0.10 counterparty

    Identifier similarity is deliberately binary-ish rather than a fuzzy
    string ratio: a reference either matches, prefix-matches, or does not.
    A continuous similarity over identifiers invites a near-miss to score
    high enough to look convincing.
    """
    identifier = _identifier_similarity(subject_identifier, candidate_identifier)
    amount = 1.0 if amount_equal else 0.0
    date_proximity = max(0.0, 1.0 - (date_distance_days / max(window_days, 1)))
    status = 1.0 if status_compatible else 0.0

    components = {
        "identifier": identifier,
        "amount": amount,
        "date": round(date_proximity, 4),
        "status": status,
        "counterparty": round(counterparty_similarity, 4),
    }
    score = (
        0.35 * identifier
        + 0.25 * amount
        + 0.15 * date_proximity
        + 0.15 * status
        + 0.10 * counterparty_similarity
    )
    return round(score, 4), components


def _identifier_similarity(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    a, b = a.strip().upper(), b.strip().upper()
    if a == b:
        return 1.0
    # A truncated narration reference is a usable prefix, but it is
    # explicitly weaker - and on its own it must never resolve a case.
    if len(a) >= 6 and len(b) >= 6 and (a.startswith(b) or b.startswith(a)):
        return 0.7
    return 0.0


def margin_between(scores: list[float]) -> float | None:
    """Gap between the best and second-best candidate.

    `None` when there is no competitor, which is a different fact from a
    large margin and is what the gate's `margin` condition reports.
    """
    if len(scores) < 2:
        return None
    ordered = sorted(scores, reverse=True)
    return round(ordered[0] - ordered[1], 4)
