"""The Postgres implementation of `Repository`.

The second class behind the protocol, and the one a deployment uses. The
in-memory store's module docstring lists what it does not provide —
durability, concurrent writers, a transaction spanning a mutation and its
audit event, and every CHECK and trigger in `db/schema.sql`. This is
where those come back.

**Honest status.** No Postgres has been reachable from the machine this
was written on, so this code has never executed against a server. What
*has* been checked, without one:

* every table and column it names exists in `db/schema.sql`, parsed with
  libpg_query (`tests/unit/test_tables.py`);
* every statement it builds compiles against the PostgreSQL dialect,
  which resolves each column reference against those definitions.

That catches the whole class of "renamed a column and this file still
says the old name". It does not catch a wrong join, a constraint
violation, or a transaction that should have been one statement. Those
need `make migrate` and a run. Treat this as reviewed and unexercised
rather than as working, and say so to anyone who asks.

**Three design points that are not incidental:**

1. *Domain ids are text; the schema's ids are UUID.* The engine generates
   readable ids like `grp_SETL_20260220` because they appear in evidence,
   audit lines and CSV exports, where a UUID would be unreadable. They
   are carried in `metadata`/`payload_json` and the UUID primary key is
   derived deterministically with `uuid5`, so the same domain id always
   maps to the same row and a re-import is idempotent rather than a
   duplicate.

2. *A run's result is written in one transaction.* Groups, links,
   evidence and cases go in together or not at all. A half-written run
   would be indistinguishable from a run that genuinely found fewer
   exceptions, which is exactly the failure this system exists to
   prevent.

3. *Single tenant, for now.* `org_id` is on every table because the
   schema is multi-tenant by design, but there is one organisation and it
   is resolved once at startup. Threading a tenant through the protocol
   before there is a second tenant would be scaffolding for a
   requirement nobody has stated.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from ledgergraph_ai.client import InvestigationOutcome
from ledgergraph_domain.canonical import CanonicalTransaction
from ledgergraph_domain.enums import ImportStatus, RunStatus, UserRole
from ledgergraph_reconciliation.models import ExceptionCase, MatchGroup, RunResult
from sqlalchemy import and_, delete, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from . import tables as t
from .store import (
    AuditEvent,
    CaseDecision,
    ImportRecord,
    RefreshToken,
    RunRecord,
    User,
)

#: Namespace for deriving a stable UUID from a domain id. Fixed forever:
#: changing it would remap every existing row.
NAMESPACE = uuid.UUID("6f1b7d1e-1a24-4f0e-9c7a-0a4d2b6e8c31")


def row_id(domain_id: str) -> uuid.UUID:
    """The UUID primary key for a domain id, derived not random.

    `uuid5` is a hash, so the same domain id always yields the same key.
    That makes a re-run idempotent at the row level and makes a row
    traceable back to the id that appears in an export, without a lookup
    table nobody would remember to maintain.
    """
    return uuid.uuid5(NAMESPACE, domain_id)


def _jsonable(value: Any) -> Any:
    """Domain objects to JSONB-safe structures. No float coercion."""
    if is_dataclass(value) and not isinstance(value, type):
        return {k: _jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_jsonable(v) for v in value]
    return value


def _now() -> datetime:
    return datetime.now(UTC)


class PostgresRepository:
    """`Repository`, backed by Postgres. Async throughout.

    Every method opens its own session and commits. That is right for the
    coarse-grained operations this protocol exposes — each one is a
    complete unit of work — and it keeps session lifetime out of the
    routers, which is what let the in-memory implementation exist at all.
    """

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        org_id: uuid.UUID,
        policy_id: uuid.UUID,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._org_id = org_id
        self._policy_id = policy_id

    # -- imports -----------------------------------------------------------

    async def create_import(
        self, *, dataset: str, filename: str,
        idempotency_key: str | None, content_sha256: str,
    ) -> ImportRecord:
        import_id = uuid.uuid4()
        file_id = uuid.uuid4()

        # The source_system column is the `source_system` enum, whose values
        # are the five systems - not the finer-grained upload dataset name
        # (settlement_batches and settlement_lines are both
        # razorpay_settlements). Map through the normaliser so the value is
        # a legal enum label; storing the raw dataset name made Postgres
        # reject it with "invalid input value for enum source_system".
        from ledgergraph_domain.normalizers import get_normalizer
        source_system = get_normalizer(dataset).source_system.value

        async with self._sessionmaker() as session:
            # The file row first: imports.source_file_id is NOT NULL, so
            # there is no order in which this can be a single insert.
            #
            # Upsert on uq_file_sha (org_id, file_sha256): a failed import
            # (wrong source type, say) already inserted a source_files row
            # for this content, and find_import_by_hash ignores FAILED
            # imports - so a plain insert on retry hit the unique
            # constraint and 500'd. Reuse the existing file row instead,
            # refreshing the fields the retry corrects, and take back
            # whichever id ends up there for the import to point at.
            file_stmt = pg_insert(t.source_files).values(
                id=file_id, org_id=self._org_id, source_system=source_system,
                original_filename=filename, byte_size=1,
                file_sha256=content_sha256, storage_uri=f"import://{import_id}",
            ).on_conflict_do_update(
                index_elements=["org_id", "file_sha256"],
                set_={
                    "source_system": source_system,
                    "original_filename": filename,
                    "storage_uri": f"import://{import_id}",
                },
            ).returning(t.source_files.c.id)
            file_id = (await session.execute(file_stmt)).scalar_one()

            await session.execute(insert(t.imports).values(
                id=import_id, org_id=self._org_id, source_file_id=file_id,
                source_system=source_system, idempotency_key=idempotency_key,
                status=ImportStatus.PENDING.value,
                rows_total=0, rows_accepted=0, rows_rejected=0,
            ))
            await session.commit()

        return ImportRecord(
            import_id=str(import_id), dataset=dataset, filename=filename,
            status=ImportStatus.PENDING, idempotency_key=idempotency_key,
            content_sha256=content_sha256,
        )

    async def _import_from_row(self, row) -> ImportRecord:
        return ImportRecord(
            import_id=str(row.id), dataset=str(row.source_system),
            filename=row.original_filename, status=ImportStatus(row.status),
            rows_total=row.rows_total, rows_accepted=row.rows_accepted,
            rows_rejected=row.rows_rejected, idempotency_key=row.idempotency_key,
            content_sha256=row.file_sha256, created_at=row.started_at,
            completed_at=row.completed_at, error=row.error,
        )

    async def _select_import(self, whereclause) -> ImportRecord | None:
        async with self._sessionmaker() as session:
            row = (await session.execute(
                _import_select().where(whereclause)
            )).first()
        return await self._import_from_row(row) if row else None

    async def find_import_by_key(self, key: str) -> ImportRecord | None:
        return await self._select_import(t.imports.c.idempotency_key == key)

    async def find_import_by_hash(self, sha: str) -> ImportRecord | None:
        return await self._select_import(and_(
            t.source_files.c.file_sha256 == sha,
            t.imports.c.status != ImportStatus.FAILED.value,
        ))

    async def get_import(self, import_id: str) -> ImportRecord | None:
        return await self._select_import(t.imports.c.id == uuid.UUID(import_id))

    async def list_imports(self) -> list[ImportRecord]:
        async with self._sessionmaker() as session:
            rows = (await session.execute(
                _import_select().order_by(t.imports.c.started_at.desc())
            )).all()
        return [await self._import_from_row(r) for r in rows]

    async def save_import(self, record: ImportRecord) -> None:
        """Write the router's final import state back to the row.

        The router mutates the ImportRecord in place - status, row counts,
        error - which the in-memory store sees for free because it handed
        out the live object. Postgres handed out a detached copy, so the
        run counted zero completed imports (NO_DATA) until this wrote the
        terminal state back. completed_at is stamped for any terminal
        status so `all_transactions` sees the import as done.
        """
        terminal = record.status in (
            ImportStatus.COMPLETED, ImportStatus.FAILED, ImportStatus.DUPLICATE
        )
        async with self._sessionmaker() as session:
            await session.execute(
                update(t.imports)
                .where(t.imports.c.id == uuid.UUID(record.import_id))
                .values(
                    status=record.status.value,
                    rows_total=record.rows_total,
                    rows_accepted=record.rows_accepted,
                    rows_rejected=record.rows_rejected,
                    error=record.error,
                    completed_at=record.completed_at or (_now() if terminal else None),
                )
            )
            await session.commit()

    async def add_transactions(
        self, import_id: str, transactions: list[CanonicalTransaction]
    ) -> None:
        """Source records and canonical rows, in one transaction.

        A canonical row without its source record would break the FK, and
        - worse - would lose the raw payload FR-2 requires be kept
        unchanged. So the two inserts are one unit.
        """
        if not transactions:
            return

        import_uuid = uuid.UUID(import_id)
        source_rows, canon_rows = [], []

        async with self._sessionmaker() as session:
            file_id = (await session.execute(
                select(t.imports.c.source_file_id).where(t.imports.c.id == import_uuid)
            )).scalar_one()

            for number, txn in enumerate(transactions, start=1):
                record_id = row_id(f"{import_id}:{txn.external_id_norm}")
                source_rows.append({
                    "id": record_id, "org_id": self._org_id,
                    "import_id": import_uuid, "source_file_id": file_id,
                    "source_system": txn.source_system.value,
                    "external_id": txn.external_id, "row_number": number,
                    "raw_payload": _jsonable(txn.metadata),
                    "row_hash": f"{import_id}:{txn.external_id_norm}",
                })
                canon_rows.append({
                    "id": row_id(txn.external_id_norm), "org_id": self._org_id,
                    "source_record_id": record_id,
                    "entity_type": txn.entity_type.value,
                    "source_system": txn.source_system.value,
                    "external_id": txn.external_id,
                    "external_id_norm": txn.external_id_norm,
                    "parent_external_id": txn.parent_external_id,
                    "reference_id": txn.reference_id,
                    "customer_ref": txn.customer_ref,
                    "currency": txn.currency,
                    "gross_amount_minor": txn.gross_amount_minor,
                    "fee_amount_minor": txn.fee_amount_minor,
                    "tax_amount_minor": txn.tax_amount_minor,
                    "net_amount_minor": txn.net_amount_minor,
                    "direction": txn.direction.value,
                    "status": txn.status.value,
                    "event_at": txn.event_at,
                    "available_at": txn.available_at,
                    "business_date": txn.business_date,
                    "business_timezone": txn.business_timezone,
                    "tz_assumed": txn.tz_assumed,
                    "counterparty": txn.counterparty,
                    "description": txn.description,
                    "metadata": _jsonable(txn.metadata),
                    "data_quality_flags": list(txn.data_quality_flags),
                })

            await session.execute(insert(t.source_records), source_rows)
            await session.execute(insert(t.canonical_transactions), canon_rows)
            await session.commit()

    async def all_transactions(self) -> list[CanonicalTransaction]:
        """Every canonical row from a completed import.

        Read in one query rather than per import. The engine's whole
        design assumes it is handed the population at once - it builds
        hash indexes over it - so paging here would only move the memory
        cost, not remove it.
        """
        from ledgergraph_domain.enums import (
            EntityType,
            SourceSystem,
            TxnDirection,
            TxnStatus,
        )

        query = (
            select(t.canonical_transactions)
            .select_from(
                t.canonical_transactions
                .join(
                    t.source_records,
                    t.canonical_transactions.c.source_record_id == t.source_records.c.id,
                )
                .join(t.imports, t.source_records.c.import_id == t.imports.c.id)
            )
            .where(t.imports.c.status == ImportStatus.COMPLETED.value)
        )

        async with self._sessionmaker() as session:
            rows = (await session.execute(query)).mappings().all()

        return [
            CanonicalTransaction(
                entity_type=EntityType(r["entity_type"]),
                source_system=SourceSystem(r["source_system"]),
                external_id=r["external_id"],
                parent_external_id=r["parent_external_id"],
                reference_id=r["reference_id"],
                customer_ref=r["customer_ref"],
                currency=r["currency"],
                gross_amount_minor=r["gross_amount_minor"],
                fee_amount_minor=r["fee_amount_minor"],
                tax_amount_minor=r["tax_amount_minor"],
                net_amount_minor=r["net_amount_minor"],
                direction=TxnDirection(r["direction"]),
                status=TxnStatus(r["status"]),
                event_at=r["event_at"],
                available_at=r["available_at"],
                business_date=r["business_date"],
                business_timezone=r["business_timezone"],
                tz_assumed=r["tz_assumed"],
                counterparty=r["counterparty"],
                description=r["description"],
                metadata=r["metadata"] or {},
                data_quality_flags=list(r["data_quality_flags"] or []),
            )
            for r in rows
        ]

    # -- runs --------------------------------------------------------------

    async def create_run(self, ruleset_version: str) -> RunRecord:
        run_uuid = uuid.uuid4()
        snapshot_id = uuid.uuid4()

        async with self._sessionmaker() as session:
            # reconciliation_runs.snapshot_id is NOT NULL: a run must name
            # the population it ran over, or its metrics mean nothing.
            await session.execute(insert(t.dataset_snapshots).values(
                id=snapshot_id, org_id=self._org_id,
                name=f"run {run_uuid}", date_from=_now().date(),
                date_to=_now().date(), source_systems=[],
                record_count=0, snapshot_hash=str(run_uuid),
            ))
            await session.execute(insert(t.reconciliation_runs).values(
                id=run_uuid, org_id=self._org_id, snapshot_id=snapshot_id,
                policy_id=self._policy_id, ruleset_version=ruleset_version,
                status=RunStatus.QUEUED.value, progress_pct=0,
            ))
            await session.commit()

        return RunRecord(
            run_id=str(run_uuid), status=RunStatus.QUEUED,
            ruleset_version=ruleset_version,
        )

    async def _run_from_row(self, row) -> RunRecord:
        # Attach the computed result from the working set if it is present,
        # so run_dto can derive metrics and the exception queue can read
        # `record.result`. Absent after a restart, which reads as "no
        # completed run" until the run is re-executed - the documented
        # trade for not rebuilding the object graph from rows here.
        return RunRecord(
            run_id=str(row.id), status=RunStatus(row.status),
            ruleset_version=row.ruleset_version,
            current_stage=row.current_stage, progress_pct=row.progress_pct,
            created_at=row.queued_at, started_at=row.started_at,
            completed_at=row.completed_at, error=row.error,
            result=self._results.get(str(row.id)),
        )

    async def get_run(self, run_id: str) -> RunRecord | None:
        async with self._sessionmaker() as session:
            row = (await session.execute(
                select(t.reconciliation_runs)
                .where(t.reconciliation_runs.c.id == uuid.UUID(run_id))
            )).first()
        return await self._run_from_row(row) if row else None

    async def list_runs(self) -> list[RunRecord]:
        async with self._sessionmaker() as session:
            rows = (await session.execute(
                select(t.reconciliation_runs)
                .order_by(t.reconciliation_runs.c.queued_at.desc())
            )).all()
        return [await self._run_from_row(r) for r in rows]

    async def latest_run(self) -> RunRecord | None:
        async with self._sessionmaker() as session:
            row = (await session.execute(
                select(t.reconciliation_runs)
                .where(t.reconciliation_runs.c.status == RunStatus.COMPLETED.value)
                .order_by(t.reconciliation_runs.c.queued_at.desc())
                .limit(1)
            )).first()
        return await self._run_from_row(row) if row else None

    async def save_run(self, record: RunRecord) -> None:
        """Persist a run's status transition (queued -> running -> done).

        The background task mutates a RunRecord in place; the in-memory
        store sees that for free, Postgres does not, so without this the
        run row stayed 'queued' forever and `latest_run` found nothing.
        """
        async with self._sessionmaker() as session:
            await session.execute(
                update(t.reconciliation_runs)
                .where(t.reconciliation_runs.c.id == uuid.UUID(record.run_id))
                .values(
                    status=record.status.value,
                    current_stage=record.current_stage,
                    progress_pct=record.progress_pct,
                    started_at=record.started_at,
                    completed_at=record.completed_at,
                    error=record.error,
                )
            )
            await session.commit()

    async def save_run_result(self, run_id: str, result: RunResult) -> None:
        """Groups, links, evidence and cases, in one transaction.

        Partially written results are the failure mode that matters here:
        a run missing half its exceptions looks exactly like a run that
        found fewer problems, and there is no way to tell them apart
        afterwards. All or nothing.
        """
        run_uuid = uuid.UUID(run_id)

        async with self._sessionmaker() as session:
            # Idempotent re-save: a retried run replaces its own output
            # rather than doubling it. The FK cascades take links,
            # evidence and case members with the groups.
            await session.execute(
                delete(t.exception_cases).where(t.exception_cases.c.run_id == run_uuid)
            )
            await session.execute(
                delete(t.reconciliation_groups)
                .where(t.reconciliation_groups.c.run_id == run_uuid)
            )

            for group in result.groups:
                group_uuid = row_id(group.group_id)
                await session.execute(insert(t.reconciliation_groups).values(
                    id=group_uuid, run_id=run_uuid, org_id=self._org_id,
                    group_type=group.group_type.value,
                    status=group.status.value,
                    matched_by_rule=group.matched_by_rule,
                    tier=group.tier.value,
                    confidence=round(group.confidence, 4),
                    confidence_components=_jsonable(group.confidence_components),
                    gate_result={"conditions": _jsonable(group.gate)},
                    bridge=_jsonable(group.bridge) if group.bridge else None,
                    total_amount_minor=group.total_amount_minor,
                    currency=group.currency,
                    explanation=group.explanation or None,
                    auto_resolved=group.auto_resolved,
                    ruleset_version=result.ruleset_version,
                    policy_version=1,
                ))

                if group.links:
                    await session.execute(insert(t.reconciliation_links), [
                        {
                            "id": row_id(f"{group.group_id}:{link.transaction.external_id_norm}"),
                            "group_id": group_uuid,
                            "run_id": run_uuid,
                            "transaction_id": row_id(link.transaction.external_id_norm),
                            "role": link.role.value,
                            "matched_amount_minor": link.matched_amount_minor,
                            "evidence_json": {},
                        }
                        for link in group.links
                    ])

                if group.evidence:
                    await session.execute(insert(t.reconciliation_evidence), [
                        {
                            "id": row_id(f"{group.group_id}:ev{i}"),
                            "group_id": group_uuid,
                            "rule_code": ev.rule_code,
                            "evidence_type": ev.evidence_type,
                            "statement": ev.statement,
                            "computed": _jsonable(ev.computed),
                            "passed": ev.passed,
                        }
                        for i, ev in enumerate(group.evidence, start=1)
                    ])

            for case in result.cases:
                case_uuid = row_id(case.case_id)
                await session.execute(insert(t.exception_cases).values(
                    id=case_uuid, run_id=run_uuid, org_id=self._org_id,
                    group_id=row_id(case.group.group_id) if case.group else None,
                    primary_transaction_id=(
                        row_id(case.primary_transaction.external_id_norm)
                        if case.primary_transaction else None
                    ),
                    case_type=case.case_type.value,
                    severity=case.severity.value,
                    status="open",
                    amount_at_risk_minor=case.amount_at_risk_minor,
                    currency=case.currency,
                    hypothesis=case.hypothesis or None,
                    recommendation=case.recommendation or None,
                    confidence=(
                        round(case.confidence, 4) if case.confidence is not None else None
                    ),
                ))

                members = {
                    txn.external_id_norm for txn in case.transactions
                }
                if members:
                    await session.execute(insert(t.exception_case_transactions), [
                        {
                            "case_id": case_uuid,
                            "transaction_id": row_id(norm),
                            "role": "subject",
                        }
                        for norm in sorted(members)
                    ])

            summary = result.summary()
            await session.execute(insert(t.run_metrics).values(
                run_id=run_uuid,
                records_processed=summary["records_processed"],
                records_auto_resolved=summary["auto_resolved"],
                records_pending_review=summary["pending_review"],
                records_unresolved=summary["exceptions"],
                gross_processed_minor=sum(
                    g.total_amount_minor for g in result.groups
                ),
                unresolved_value_minor=sum(
                    c.amount_at_risk_minor for c in result.cases
                ),
                groups_created=len(result.groups),
                exceptions_created=len(result.cases),
                stage_timings=_jsonable(result.stage_timings_ms),
            ))

            await session.commit()

        # Keep the computed result in the working set. get_case/get_group and
        # the run's own `result` read from here rather than rebuilding the
        # whole object graph from rows on every request - the durable record
        # is the rows above; this is what the API serves. Lost on restart,
        # which for a single free instance is acceptable and documented.
        self._results[run_id] = result

    # -- cases -------------------------------------------------------------
    #
    # `get_case` and `get_group` return the engine's own dataclasses,
    # which carry the full transaction objects. Rebuilding those from
    # rows means reassembling the whole object graph, and doing it per
    # case would be the N+1 the architecture doc names as risk P1.
    #
    # So the run's result is held in memory once it has been computed,
    # and these read from it. The rows above are the durable record and
    # the audit trail; this is the working set. When a process restart
    # has to survive, the reassembly goes here - it is a query, not a
    # redesign.

    def __post_init__(self) -> None:  # pragma: no cover - dataclass parity
        pass

    _results: dict[str, RunResult] = {}

    async def get_case(self, case_id: str) -> ExceptionCase | None:
        for result in self._results.values():
            for case in result.cases:
                if case.case_id == case_id:
                    return case
        return None

    async def get_group(self, group_id: str) -> MatchGroup | None:
        for result in self._results.values():
            for group in result.groups:
                if group.group_id == group_id:
                    return group
        return None

    # -- investigations ----------------------------------------------------

    async def add_investigation(
        self, case_id: str, outcome: InvestigationOutcome
    ) -> None:
        inv = outcome.investigation
        async with self._sessionmaker() as session:
            await session.execute(insert(t.ai_investigations).values(
                id=uuid.uuid4(), case_id=row_id(case_id),
                model_version=outcome.model_version,
                prompt_version=getattr(outcome, "prompt_version", "investigate@v1"),
                packet_hash=outcome.packet_fingerprint,
                validation_status=outcome.status.value,
                validation_errors=_jsonable(outcome.errors),
                classification=(
                    inv.classification.value if inv and inv.classification else None
                ),
                hypotheses=_jsonable(inv.hypotheses) if inv else [],
                recommended_action=inv.recommended_action if inv else None,
                requires_human_approval=(
                    inv.requires_human_approval if inv else None
                ),
                # Advisory only. The gate never reads this column, which is
                # why it can be stored at all.
                confidence=round(inv.confidence, 4) if inv and inv.confidence else None,
                uncertainties=_jsonable(inv.uncertainties) if inv else [],
                cited_evidence_ids=list(outcome.cited_evidence_ids),
                latency_ms=outcome.latency_ms,
            ))
            await session.commit()

    async def investigations(self, case_id: str) -> list[InvestigationOutcome]:
        # Returned from the working set for the same reason as get_case:
        # rehydrating an InvestigationOutcome from JSONB would duplicate
        # the schema module's parsing, and two parsers eventually disagree.
        return list(self._investigations.get(case_id, []))

    _investigations: dict[str, list[InvestigationOutcome]] = {}

    # -- decisions ---------------------------------------------------------

    async def record_decision(self, decision: CaseDecision) -> None:
        """The decision and its audit event, in one transaction.

        This is the guarantee the in-memory store cannot make, and the
        reason the Postgres implementation is not optional: a decision
        without its audit row, or an audit row for a decision that was
        rolled back, would each make the trail a record of something
        other than what happened.
        """
        async with self._sessionmaker() as session:
            await session.execute(
                update(t.exception_cases)
                .where(t.exception_cases.c.id == row_id(decision.case_id))
                .values(
                    status=(
                        "dismissed" if decision.resolution.value == "dismissed"
                        else "resolved"
                    ),
                    resolution=decision.resolution.value,
                    resolution_reason_code=(
                        decision.reason_code.value if decision.reason_code else None
                    ),
                    resolution_note=decision.note or None,
                    resolved_at=decision.decided_at,
                    resolved_by=uuid.UUID(decision.decided_by)
                    if _is_uuid(decision.decided_by) else None,
                )
            )
            await session.execute(insert(t.decision_audit_events).values(
                id=uuid.uuid4(), org_id=self._org_id,
                entity_type="exception_case",
                entity_id=row_id(decision.case_id),
                action=decision.resolution.value,
                actor_type="user",
                actor_id=uuid.UUID(decision.decided_by)
                if _is_uuid(decision.decided_by) else None,
                actor_role=decision.decided_by_role.value,
                reason_code=(
                    decision.reason_code.value if decision.reason_code else None
                ),
                payload_json={"note": decision.note},
            ))
            await session.commit()

        self._decisions[decision.case_id] = decision

    _decisions: dict[str, CaseDecision] = {}

    async def get_decision(self, case_id: str) -> CaseDecision | None:
        return self._decisions.get(case_id)

    async def all_decisions(self) -> dict[str, CaseDecision]:
        return dict(self._decisions)

    # -- audit -------------------------------------------------------------

    async def add_audit(self, event: AuditEvent) -> None:
        # ck_audit_actor: actor_id must be present exactly when
        # actor_type='user' and absent otherwise. A 'user' event carries
        # the acting user's id; a system/ai event carries none.
        actor_id = (
            uuid.UUID(event.actor_id)
            if event.actor_id and _is_uuid(event.actor_id) else None
        )
        async with self._sessionmaker() as session:
            await session.execute(insert(t.decision_audit_events).values(
                id=uuid.uuid4(), org_id=self._org_id,
                entity_type=event.entity_type,
                entity_id=row_id(event.entity_id),
                action=event.action,
                actor_type=event.actor_type,
                actor_id=actor_id,
                actor_role=event.actor_role,
                reason_code=event.reason_code,
                ruleset_version=event.ruleset_version,
                # actor_name is not a column; it rides in the payload so
                # audit_for can read the human name back for display.
                payload_json={"detail": event.detail, "actor_name": event.actor_name},
            ))
            await session.commit()

    async def audit_for(self, entity_id: str) -> list[AuditEvent]:
        target = row_id(entity_id)
        async with self._sessionmaker() as session:
            rows = (await session.execute(
                select(t.decision_audit_events)
                .where(t.decision_audit_events.c.entity_id == target)
                .order_by(t.decision_audit_events.c.created_at)
            )).mappings().all()

        return [
            AuditEvent(
                event_id=str(r["id"]), entity_type=r["entity_type"],
                entity_id=entity_id, action=str(r["action"]),
                actor_type=str(r["actor_type"]),
                actor_name=(r["payload_json"] or {}).get("actor_name"),
                actor_role=str(r["actor_role"]) if r["actor_role"] else None,
                reason_code=r["reason_code"],
                detail=(r["payload_json"] or {}).get("detail", ""),
                ruleset_version=r["ruleset_version"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    # -- users -------------------------------------------------------------

    async def create_user(
        self, *, email: str, hashed_password: str, full_name: str, role: UserRole
    ) -> User:
        user_uuid = uuid.uuid4()
        async with self._sessionmaker() as session:
            await session.execute(insert(t.users).values(
                id=user_uuid, org_id=self._org_id, email=email.strip().lower(),
                hashed_password=hashed_password, full_name=full_name,
                role=role.value, is_active=True, is_verified=True,
            ))
            await session.commit()

        return User(
            user_id=str(user_uuid), email=email.strip().lower(),
            hashed_password=hashed_password, full_name=full_name, role=role,
        )

    def _user_from_row(self, r) -> User:
        return User(
            user_id=str(r["id"]), email=r["email"],
            hashed_password=r["hashed_password"], full_name=r["full_name"] or "",
            role=UserRole(r["role"]), is_active=r["is_active"],
            is_verified=r["is_verified"], created_at=r["created_at"],
            last_login_at=r["last_login_at"],
        )

    async def get_user(self, user_id: str) -> User | None:
        if not _is_uuid(user_id):
            return None
        async with self._sessionmaker() as session:
            row = (await session.execute(
                select(t.users).where(t.users.c.id == uuid.UUID(user_id))
            )).mappings().first()
        return self._user_from_row(row) if row else None

    async def find_user_by_email(self, email: str) -> User | None:
        async with self._sessionmaker() as session:
            row = (await session.execute(
                select(t.users).where(t.users.c.email == email.strip().lower())
            )).mappings().first()
        return self._user_from_row(row) if row else None

    async def list_users(self) -> list[User]:
        async with self._sessionmaker() as session:
            rows = (await session.execute(
                select(t.users).order_by(t.users.c.created_at)
            )).mappings().all()
        return [self._user_from_row(r) for r in rows]

    async def update_user_role(self, user_id: str, role: UserRole) -> User | None:
        if not _is_uuid(user_id):
            return None
        async with self._sessionmaker() as session:
            await session.execute(
                update(t.users)
                .where(t.users.c.id == uuid.UUID(user_id))
                .values(role=role.value)
            )
            await session.commit()
        # A read after the write, so the caller sees exactly what the row
        # holds - and None if the id named no one (the UPDATE hit 0 rows).
        return await self.get_user(user_id)

    # -- refresh tokens ----------------------------------------------------

    async def store_refresh(
        self, *, user_id: str, digest: str, family_id: str, expires_at: datetime
    ) -> RefreshToken:
        token_uuid = uuid.uuid4()
        family_uuid = uuid.UUID(family_id) if _is_uuid(family_id) else row_id(family_id)

        async with self._sessionmaker() as session:
            await session.execute(insert(t.refresh_tokens).values(
                id=token_uuid, user_id=uuid.UUID(user_id), token_hash=digest,
                family_id=family_uuid, expires_at=expires_at,
            ))
            await session.commit()

        return RefreshToken(
            token_id=str(token_uuid), user_id=user_id, digest=digest,
            family_id=str(family_uuid), expires_at=expires_at,
        )

    async def find_refresh(self, digest: str) -> RefreshToken | None:
        async with self._sessionmaker() as session:
            row = (await session.execute(
                select(t.refresh_tokens)
                .where(t.refresh_tokens.c.token_hash == digest)
            )).mappings().first()
        if row is None:
            return None
        return RefreshToken(
            token_id=str(row["id"]), user_id=str(row["user_id"]),
            digest=row["token_hash"], family_id=str(row["family_id"]),
            expires_at=row["expires_at"], issued_at=row["issued_at"],
            consumed_at=row["consumed_at"], revoked_at=row["revoked_at"],
        )

    async def consume_refresh(self, token: RefreshToken) -> None:
        async with self._sessionmaker() as session:
            await session.execute(
                update(t.refresh_tokens)
                .where(t.refresh_tokens.c.id == uuid.UUID(token.token_id))
                .values(consumed_at=_now())
            )
            await session.commit()
        token.consumed_at = _now()

    async def revoke_family(self, family_id: str) -> int:
        family_uuid = uuid.UUID(family_id) if _is_uuid(family_id) else row_id(family_id)
        async with self._sessionmaker() as session:
            result = await session.execute(
                update(t.refresh_tokens)
                .where(and_(
                    t.refresh_tokens.c.family_id == family_uuid,
                    t.refresh_tokens.c.revoked_at.is_(None),
                ))
                .values(revoked_at=_now())
            )
            await session.commit()
        return result.rowcount or 0


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def _import_select():
    """Imports joined to the file that carries the filename and hash."""
    return select(
        t.imports.c.id,
        t.imports.c.source_system,
        t.imports.c.idempotency_key,
        t.imports.c.status,
        t.imports.c.rows_total,
        t.imports.c.rows_accepted,
        t.imports.c.rows_rejected,
        t.imports.c.error,
        t.imports.c.started_at,
        t.imports.c.completed_at,
        t.source_files.c.original_filename,
        t.source_files.c.file_sha256,
    ).select_from(
        t.imports.join(
            t.source_files, t.imports.c.source_file_id == t.source_files.c.id
        )
    )


def statements_for_compilation() -> dict[str, Any]:
    """Every distinct statement shape this module builds.

    Consumed by `tests/unit/test_tables.py`, which compiles each one
    against the PostgreSQL dialect. That is the closest thing to
    executing them available without a server, and it resolves every
    column reference against the table definitions - so a column renamed
    in `db/schema.sql` and not here fails in CI rather than in
    production.
    """
    run_uuid = uuid.uuid4()

    return {
        "import_by_key": _import_select().where(
            t.imports.c.idempotency_key == "k"
        ),
        "import_by_hash": _import_select().where(and_(
            t.source_files.c.file_sha256 == "sha",
            t.imports.c.status != ImportStatus.FAILED.value,
        )),
        "imports_listed": _import_select().order_by(t.imports.c.started_at.desc()),
        "insert_source_file": insert(t.source_files),
        "insert_import": insert(t.imports),
        "insert_source_records": insert(t.source_records),
        "insert_canonical": insert(t.canonical_transactions),
        "all_transactions": (
            select(t.canonical_transactions)
            .select_from(
                t.canonical_transactions
                .join(
                    t.source_records,
                    t.canonical_transactions.c.source_record_id == t.source_records.c.id,
                )
                .join(t.imports, t.source_records.c.import_id == t.imports.c.id)
            )
            .where(t.imports.c.status == ImportStatus.COMPLETED.value)
        ),
        "insert_snapshot": insert(t.dataset_snapshots),
        "insert_run": insert(t.reconciliation_runs),
        "run_by_id": select(t.reconciliation_runs).where(
            t.reconciliation_runs.c.id == run_uuid
        ),
        "runs_listed": select(t.reconciliation_runs).order_by(
            t.reconciliation_runs.c.queued_at.desc()
        ),
        "latest_completed_run": (
            select(t.reconciliation_runs)
            .where(t.reconciliation_runs.c.status == RunStatus.COMPLETED.value)
            .order_by(t.reconciliation_runs.c.queued_at.desc())
            .limit(1)
        ),
        "delete_cases_for_run": delete(t.exception_cases).where(
            t.exception_cases.c.run_id == run_uuid
        ),
        "delete_groups_for_run": delete(t.reconciliation_groups).where(
            t.reconciliation_groups.c.run_id == run_uuid
        ),
        "insert_group": insert(t.reconciliation_groups),
        "insert_links": insert(t.reconciliation_links),
        "insert_evidence": insert(t.reconciliation_evidence),
        "insert_case": insert(t.exception_cases),
        "insert_case_transactions": insert(t.exception_case_transactions),
        "insert_run_metrics": insert(t.run_metrics),
        # The hottest query in the product. Money first, always.
        "cases_for_run": (
            select(t.exception_cases)
            .where(t.exception_cases.c.run_id == run_uuid)
            .order_by(t.exception_cases.c.amount_at_risk_minor.desc())
        ),
        "insert_investigation": insert(t.ai_investigations),
        "update_case_decision": (
            update(t.exception_cases)
            .where(t.exception_cases.c.id == run_uuid)
            .values(status="resolved", resolution="approved")
        ),
        "insert_audit": insert(t.decision_audit_events),
        "audit_for_entity": (
            select(t.decision_audit_events)
            .where(t.decision_audit_events.c.entity_id == run_uuid)
            .order_by(t.decision_audit_events.c.created_at)
        ),
        "insert_user": insert(t.users),
        "user_by_id": select(t.users).where(t.users.c.id == run_uuid),
        "user_by_email": select(t.users).where(t.users.c.email == "a@b.dev"),
        "users_listed": select(t.users).order_by(t.users.c.created_at),
        "update_user_role": (
            update(t.users)
            .where(t.users.c.id == run_uuid)
            .values(role=UserRole.ADMIN.value)
        ),
        "insert_refresh": insert(t.refresh_tokens),
        "refresh_by_digest": select(t.refresh_tokens).where(
            t.refresh_tokens.c.token_hash == "d"
        ),
        "consume_refresh": (
            update(t.refresh_tokens)
            .where(t.refresh_tokens.c.id == run_uuid)
            .values(consumed_at=_now())
        ),
        "revoke_family": (
            update(t.refresh_tokens)
            .where(and_(
                t.refresh_tokens.c.family_id == run_uuid,
                t.refresh_tokens.c.revoked_at.is_(None),
            ))
            .values(revoked_at=_now())
        ),
    }


__all__ = [
    "NAMESPACE",
    "PostgresRepository",
    "bootstrap",
    "row_id",
    "statements_for_compilation",
]


async def bootstrap(sessionmaker: async_sessionmaker[AsyncSession]) -> PostgresRepository:
    """Find or create the organisation and active policy, then build the repo.

    Every table in the schema carries `org_id` because it is multi-tenant
    by design, and `reconciliation_runs.policy_id` is NOT NULL because a
    run's numbers are meaningless without the thresholds that produced
    them. There is one tenant and one policy today, so both are resolved
    once here rather than threaded through a protocol that has no second
    caller to justify it.

    Idempotent: a restart finds the existing rows. The policy is written
    from `Policy()` so the database and `packages/reconciliation` cannot
    disagree about the thresholds - the code is the source, the row is
    the record.
    """
    from ledgergraph_reconciliation.policy import Policy

    policy = Policy()

    async with sessionmaker() as session:
        org_id = (await session.execute(
            select(t.organizations.c.id).order_by(t.organizations.c.created_at).limit(1)
        )).scalar_one_or_none()

        if org_id is None:
            org_id = uuid.uuid4()
            await session.execute(insert(t.organizations).values(
                id=org_id, name="LedgerGraph",
                business_timezone="Asia/Kolkata", base_currency="INR",
            ))

        policy_id = (await session.execute(
            select(t.policies.c.id).where(and_(
                t.policies.c.org_id == org_id,
                t.policies.c.is_active.is_(True),
            ))
        )).scalar_one_or_none()

        if policy_id is None:
            policy_id = uuid.uuid4()
            await session.execute(insert(t.policies).values(
                id=policy_id, org_id=org_id, version=1, name="default",
                is_active=True,
                auto_resolve_min_confidence=policy.auto_resolve_min_confidence,
                auto_resolve_max_minor=policy.auto_resolve_max_minor,
                review_required_above_minor=policy.review_required_above_minor,
                candidate_margin=policy.candidate_margin,
                settlement_window_days=policy.settlement_window_days,
                amount_tolerance_minor=policy.amount_tolerance_minor,
            ))

        await session.commit()

    return PostgresRepository(sessionmaker, org_id=org_id, policy_id=policy_id)
