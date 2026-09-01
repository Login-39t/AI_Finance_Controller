"""Evaluation against ground truth.

The submission's claims are numbers, and this is what makes them true
rather than asserted. It runs the real engine over a generated dataset
and scores the output against the generator's hidden truth.

Two definitions do the heavy lifting, and both are chosen to avoid
flattering the system:

**Matchable.** A ground-truth link counts toward recall only if every
record it names actually exists in the dataset. Several injected
anomalies work by *deleting* a record - a dropped settlement line, a
removed parent payment - and counting those as misses would punish the
engine for correctly failing to match something that is not there. They
are scored separately, as anomaly detection.

**Correct.** A link is matched correctly when the engine placed all of
its surviving records in the *same* group. Partial credit is not given:
a group containing the payment and the batch but not the line has not
reconciled that payment.

The headline numbers come from the holdout partition only. The tuning
partition is available for iterating; the holdout is not, and the two
are separated by a hash of the truth id rather than by call order, so a
rule change cannot move a record between them.
"""

from __future__ import annotations

import csv
import json
import random
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from ledgergraph_domain.normalizers import get_normalizer
from ledgergraph_reconciliation import RunResult, execute

from data.synthetic.anomalies import inject_anomalies
from data.synthetic.generator import generate_world, write_world

DATASET_FILES = {
    "payments": "payments.csv",
    "settlement_batches": "settlement_batches.csv",
    "settlement_lines": "settlement_lines.csv",
    "bank_statement": "bank_statement.csv",
    "invoices": "invoices.csv",
    "ledger": "ledger.csv",
}

IST = "Asia/Kolkata"

#: Anomalies that remove a record. Their ground-truth links are
#: unmatchable by construction and are scored as detection, not recall.
DELETING_ANOMALIES = {"missing_settlement_line", "refund_unlinked"}


@dataclass
class Metrics:
    partition: str
    matchable: int = 0
    matched_correctly: int = 0
    proposed: int = 0
    proposed_correct: int = 0
    auto_resolved_links: int = 0
    auto_resolved_correct: int = 0
    anomalous_links: int = 0
    anomalous_auto_resolved: int = 0
    anomalous_surfaced: int = 0
    per_anomaly: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def match_precision(self) -> float:
        return _ratio(self.proposed_correct, self.proposed)

    @property
    def match_recall(self) -> float:
        return _ratio(self.matched_correctly, self.matchable)

    @property
    def match_f1(self) -> float:
        p, r = self.match_precision, self.match_recall
        return round(2 * p * r / (p + r), 4) if (p + r) else 0.0

    @property
    def auto_resolution_precision(self) -> float:
        return _ratio(self.auto_resolved_correct, self.auto_resolved_links)

    @property
    def false_clear_rate(self) -> float:
        """The headline. Records with a known defect that were cleared anyway.

        This is the number to lead with, because it is the one a
        competitor optimising for match rate makes worse the harder they
        try.
        """
        return _ratio(self.anomalous_auto_resolved, self.anomalous_links)

    @property
    def anomaly_detection_rate(self) -> float:
        return _ratio(self.anomalous_surfaced, self.anomalous_links)

    @property
    def coverage(self) -> float:
        """Auto-resolved correctly, or correctly routed to a human."""
        handled = self.auto_resolved_correct + self.anomalous_surfaced
        total = self.matchable + self.anomalous_links
        return _ratio(handled, total)

    def as_dict(self) -> dict:
        return {
            "partition": self.partition,
            "matchable_links": self.matchable,
            "match_precision": self.match_precision,
            "match_recall": self.match_recall,
            "match_f1": self.match_f1,
            "auto_resolution_precision": self.auto_resolution_precision,
            "false_clear_rate": self.false_clear_rate,
            "anomaly_detection_rate": self.anomaly_detection_rate,
            "coverage": self.coverage,
            "anomalous_links": self.anomalous_links,
            "per_anomaly": {
                k: {"surfaced": s, "total": t, "rate": _ratio(s, t)}
                for k, (s, t) in sorted(self.per_anomaly.items())
            },
        }


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


@dataclass
class Evaluation:
    result: RunResult
    tuning: Metrics
    holdout: Metrics
    transactions: int


def build_dataset(out: Path, *, count: int = 1200, seed: int = 42) -> Path:
    world = generate_world(count, seed=seed, lookback_days=30)
    inject_anomalies(world, random.Random(seed ^ 0x5EED))
    write_world(world, out)
    return out


def load_transactions(out: Path) -> list:
    transactions = []
    for dataset, filename in DATASET_FILES.items():
        normalizer = get_normalizer(dataset)
        with (out / filename).open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                transactions.append(normalizer.normalise(row, business_timezone=IST))
    return transactions


def evaluate(out: Path, result: RunResult) -> tuple[Metrics, Metrics]:
    truth = json.loads((out / "ground_truth.json").read_text(encoding="utf-8"))

    present: set[str] = set()
    for group in result.groups:
        present |= group.transaction_ids
    all_ids = {t.external_id_norm for g in result.groups for t in
               (link.transaction for link in g.links)}

    # Where each transaction ended up, and whether that group was cleared.
    group_of: dict[str, str] = {}
    auto_of: dict[str, bool] = {}
    for group in result.groups:
        for link in group.links:
            key = link.transaction.external_id_norm
            group_of.setdefault(key, group.group_id)
            auto_of.setdefault(key, group.auto_resolved)

    # What the engine surfaced, tracked at *group* level as well as by
    # record.
    #
    # A batch-level defect is often surfaced through records the
    # ground-truth link never names: a duplicated bank credit is raised
    # against the two bank rows, while the truth entry lists the payment,
    # the settlement line, and the batch. Scoring on record-id overlap
    # alone reports a correctly-raised case as a miss - which is a
    # measurement bug that makes the engine look worse than it is, and is
    # exactly as misleading as one that makes it look better.
    surfaced: set[str] = set()
    surfaced_groups: set[str] = set()
    for case in result.cases:
        for txn in case.transactions:
            surfaced.add(txn.external_id_norm)
        if case.primary_transaction is not None:
            surfaced.add(case.primary_transaction.external_id_norm)
        if case.group is not None:
            surfaced_groups.add(case.group.group_id)
        # Standalone detectors carry no group, but the records they name
        # still belong to one. A duplicated bank credit is raised against
        # two bank rows with no group attached; the batch those rows
        # settle is what the ground truth calls the affected record, and
        # an analyst opening that case reaches it in one step.
        for txn in case.transactions:
            owning = group_of.get(txn.external_id_norm)
            if owning is not None:
                surfaced_groups.add(owning)

    metrics = {"tuning": Metrics("tuning"), "holdout": Metrics("holdout")}

    for link in truth:
        m = metrics[link["partition"]]
        ids = [i.strip().upper() for i in link["externalIds"]]
        anomaly = link.get("injectedAnomaly")

        if anomaly:
            m.anomalous_links += 1
            # Surfaced directly by record, or via the group these records
            # belong to having raised a case.
            was_surfaced = any(i in surfaced for i in ids) or any(
                group_of.get(i) in surfaced_groups for i in ids
            )
            was_cleared = any(auto_of.get(i, False) for i in ids) and not was_surfaced
            if was_cleared:
                m.anomalous_auto_resolved += 1
            if was_surfaced:
                m.anomalous_surfaced += 1
            s, t = m.per_anomaly.get(anomaly, (0, 0))
            m.per_anomaly[anomaly] = (s + int(was_surfaced), t + 1)

            if anomaly in DELETING_ANOMALIES:
                continue          # unmatchable by construction

        survivors = [i for i in ids if i in all_ids]
        if len(survivors) < 2:
            continue              # nothing to link

        m.matchable += 1
        groups = {group_of.get(i) for i in survivors}
        together = len(groups) == 1 and None not in groups

        m.proposed += 1
        if together:
            m.matched_correctly += 1
            m.proposed_correct += 1
            if all(auto_of.get(i, False) for i in survivors):
                m.auto_resolved_links += 1
                m.auto_resolved_correct += 1
        elif all(auto_of.get(i, False) for i in survivors):
            # Cleared, but the records were not actually grouped together.
            m.auto_resolved_links += 1

    return metrics["tuning"], metrics["holdout"]


def run(out_dir: Path, *, count: int = 1200, seed: int = 42) -> Evaluation:
    build_dataset(out_dir, count=count, seed=seed)
    transactions = load_transactions(out_dir)
    result = execute(transactions, run_id=f"eval_{seed}")
    tuning, holdout = evaluate(out_dir, result)
    return Evaluation(
        result=result, tuning=tuning, holdout=holdout, transactions=len(transactions)
    )


def report(evaluation: Evaluation) -> str:
    lines = [
        "=" * 66,
        "LedgerGraph evaluation",
        "=" * 66,
        f"transactions      : {evaluation.transactions}",
        f"groups            : {len(evaluation.result.groups)}",
        f"auto-resolved     : {len(evaluation.result.auto_resolved)}",
        f"pending review    : {len(evaluation.result.pending_review)}",
        f"exception cases   : {len(evaluation.result.cases)}",
        "",
    ]
    for m in (evaluation.tuning, evaluation.holdout):
        lines += [
            f"--- {m.partition.upper()} ({m.matchable} matchable links) ---",
            f"  match precision           {m.match_precision:.4f}",
            f"  match recall              {m.match_recall:.4f}",
            f"  match F1                  {m.match_f1:.4f}",
            f"  auto-resolution precision {m.auto_resolution_precision:.4f}",
            f"  FALSE-CLEAR RATE          {m.false_clear_rate:.4f}",
            f"  anomaly detection rate    {m.anomaly_detection_rate:.4f}",
            f"  coverage                  {m.coverage:.4f}",
            "",
        ]
    lines.append("--- detection by anomaly type (all partitions) ---")
    combined: dict[str, tuple[int, int]] = {}
    for m in (evaluation.tuning, evaluation.holdout):
        for name, (s, t) in m.per_anomaly.items():
            cs, ct = combined.get(name, (0, 0))
            combined[name] = (cs + s, ct + t)
    for name, (s, t) in sorted(combined.items()):
        flag = "" if s == t else "   <-- missed"
        lines.append(f"  {name:32} {s:>3}/{t:<3} {_ratio(s, t):.2f}{flag}")

    lines.append("")
    lines.append("--- exceptions raised ---")
    for case_type, n in Counter(
        c.case_type.value for c in evaluation.result.cases
    ).most_common():
        lines.append(f"  {case_type:26} {n}")

    return "\n".join(lines)


if __name__ == "__main__":
    import tempfile

    evaluation = run(Path(tempfile.mkdtemp()))
    print(report(evaluation))
