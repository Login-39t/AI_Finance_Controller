"""Held-out evaluation, asserted.

These are the submission's claims as executable checks. If a rule change
improves the match rate by clearing something it should have escalated,
`test_false_clear_rate_is_zero` fails and the build goes red - which is
the whole point of measuring against ground truth rather than against
"records processed".

Thresholds are the PRD section 7.5 targets. Where the engine currently
exceeds a target the assertion still uses the *target*, so a regression
has to fall below the promise before it fails rather than below today's
number - the tests defend the claim, not the high-water mark.
"""

from __future__ import annotations

import pytest

from tests.evaluation import harness

# PRD section 7.5.
TARGET_AUTO_RESOLUTION_PRECISION = 0.99
TARGET_MATCH_PRECISION = 0.98
TARGET_MATCH_RECALL = 0.85
TARGET_COVERAGE = 0.70
TARGET_CLASSIFICATION_ACCURACY = 0.85


@pytest.fixture(scope="module")
def evaluation(tmp_path_factory):
    return harness.run(tmp_path_factory.mktemp("eval"), count=1200, seed=42)


# --------------------------------------------------------------------------
# The headline
# --------------------------------------------------------------------------

def test_false_clear_rate_is_zero_on_holdout(evaluation):
    """Nothing with a known defect may be auto-resolved.

    The metric to lead the pitch with, because it is the one a system
    optimising for match rate makes worse the harder it tries.
    """
    assert evaluation.holdout.false_clear_rate == 0.0, (
        f"{evaluation.holdout.anomalous_auto_resolved} of "
        f"{evaluation.holdout.anomalous_links} defective records were cleared"
    )


def test_false_clear_rate_is_zero_on_tuning_too(evaluation):
    """A safety property, not a tuned metric - it must hold everywhere."""
    assert evaluation.tuning.false_clear_rate == 0.0


def test_every_injected_anomaly_type_is_detected(evaluation):
    """Per-type, so a single weak detector cannot hide behind a good average.

    "89% detected" can mean one whole category is invisible. This is what
    turns the number into a claim about coverage rather than volume.
    """
    combined: dict[str, tuple[int, int]] = {}
    for metrics in (evaluation.tuning, evaluation.holdout):
        for name, (surfaced, total) in metrics.per_anomaly.items():
            cs, ct = combined.get(name, (0, 0))
            combined[name] = (cs + surfaced, ct + total)

    assert combined, "no anomalies were present to detect"
    missed = {
        name: f"{s}/{t}" for name, (s, t) in combined.items() if s < t
    }
    assert not missed, f"anomaly types not fully detected: {missed}"


# --------------------------------------------------------------------------
# Matching quality
# --------------------------------------------------------------------------

def test_auto_resolution_precision_meets_target(evaluation):
    assert evaluation.holdout.auto_resolution_precision >= TARGET_AUTO_RESOLUTION_PRECISION


def test_match_precision_meets_target(evaluation):
    assert evaluation.holdout.match_precision >= TARGET_MATCH_PRECISION


def test_match_recall_meets_target(evaluation):
    assert evaluation.holdout.match_recall >= TARGET_MATCH_RECALL


def test_coverage_meets_target(evaluation):
    """Auto-resolved correctly, or correctly routed to a human.

    Guards against the degenerate way to reach a zero false-clear rate:
    escalate everything and resolve nothing.
    """
    assert evaluation.holdout.coverage >= TARGET_COVERAGE


def test_holdout_partition_is_a_meaningful_sample(evaluation):
    """A vacuous holdout would make every metric above meaningless."""
    assert evaluation.holdout.matchable >= 100
    assert evaluation.holdout.anomalous_links >= 20


def test_tuning_and_holdout_agree(evaluation):
    """Large divergence between the two would indicate overfitting."""
    delta = abs(
        evaluation.tuning.match_precision - evaluation.holdout.match_precision
    )
    assert delta <= 0.05, f"precision differs by {delta:.3f} between partitions"


# --------------------------------------------------------------------------
# Structural guarantees
# --------------------------------------------------------------------------

def test_no_group_is_resolved_without_evidence(evaluation):
    """The same invariant the database enforces with a constraint trigger."""
    for group in evaluation.result.auto_resolved:
        assert group.has_passing_evidence(), (
            f"{group.group_id} was auto-resolved with no passing evidence"
        )


def test_every_group_needing_review_appears_in_the_queue(evaluation):
    """Work that is neither done nor findable is the worst outcome: the
    reconciliation rate correctly reports it as not-cleared, so the
    numbers look fine while nobody can act on it."""
    queued = {c.group.group_id for c in evaluation.result.cases if c.group is not None}
    orphans = [
        g.group_id for g in evaluation.result.pending_review if g.group_id not in queued
    ]
    assert not orphans, f"groups needing review with no queue entry: {orphans}"


def test_every_auto_resolved_group_passed_all_six_gate_conditions(evaluation):
    for group in evaluation.result.auto_resolved:
        failed = [c.key for c in group.gate if not c.passed]
        assert not failed, f"{group.group_id} cleared while failing {failed}"
        assert len(group.gate) == 6, "the gate must evaluate all six conditions"


def test_gate_records_its_reasoning_for_every_group(evaluation):
    """`gate_result` is what answers 'why was this not cleared' without
    anyone reading code."""
    for group in evaluation.result.groups:
        assert len(group.gate) == 6
        for condition in group.gate:
            assert condition.detail, f"{group.group_id}/{condition.key} has no detail"


def test_queue_is_sorted_by_amount_at_risk(evaluation):
    amounts = [c.amount_at_risk_minor for c in evaluation.result.cases]
    assert amounts == sorted(amounts, reverse=True)


def test_run_is_deterministic(tmp_path):
    """Same input and ruleset, same result - twice."""
    out = tmp_path / "data"
    out.mkdir()
    harness.build_dataset(out, count=300, seed=5)
    transactions = harness.load_transactions(out)

    from ledgergraph_reconciliation import execute

    first = execute(transactions)
    second = execute(transactions)

    assert first.summary() == second.summary()
    assert [g.group_id for g in first.groups] == [g.group_id for g in second.groups]
    assert [g.confidence for g in first.groups] == [g.confidence for g in second.groups]
    assert [c.case_id for c in first.cases] == [c.case_id for c in second.cases]


def test_throughput_is_within_budget(evaluation):
    """NFR-7 allows 10,000 records in under 3 minutes. The in-memory
    engine is orders of magnitude inside that, so this asserts a generous
    ceiling purely to catch an accidental quadratic."""
    total_ms = sum(evaluation.result.stage_timings_ms.values())
    per_1k = total_ms / max(evaluation.transactions / 1000, 1)
    assert per_1k < 5000, f"{per_1k:.0f}ms per 1k records suggests a complexity regression"
