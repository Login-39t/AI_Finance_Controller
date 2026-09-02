"""Reconciliation runs.

`POST` returns 202 immediately and the work happens in a background task
with its state in the run record, so the UI polls a database read rather
than holding a connection open. That is the whole user-visible behaviour
of a job queue with none of the infrastructure - the documented trade is
that a process restart loses an in-flight run, which is safe because runs
are versioned and re-running is idempotent.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from ledgergraph_domain.enums import RunStatus
from ledgergraph_reconciliation import RULESET_VERSION, execute
from ledgergraph_reconciliation.policy import Policy

from ..dto import RunDTO, run_dto
from ..errors import ApiError
from ..store import get_repository, new_audit

router = APIRouter(prefix="/v1/reconciliation-runs", tags=["runs"])


@router.get("", response_model=list[RunDTO], summary="List runs")
async def list_runs() -> list[RunDTO]:
    return [run_dto(r) for r in get_repository().list_runs()]


@router.get("/latest", response_model=RunDTO, summary="Most recent completed run")
async def latest_run() -> RunDTO:
    record = get_repository().latest_run()
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no completed run yet")
    return run_dto(record)


@router.get("/{run_id}", response_model=RunDTO, summary="Run status and metrics")
async def get_run(run_id: str) -> RunDTO:
    record = get_repository().get_run(run_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such run")
    return run_dto(record)


@router.post("", response_model=RunDTO, status_code=status.HTTP_202_ACCEPTED,
              summary="Start a reconciliation run")
async def start_run(background: BackgroundTasks) -> RunDTO:
    repo = get_repository()

    transactions = repo.all_transactions()
    if not transactions:
        raise ApiError(
            "NO_DATA",
            "no completed imports to reconcile; upload source files first",
            status_code=status.HTTP_409_CONFLICT,
        )

    running = [r for r in repo.list_runs() if r.status is RunStatus.RUNNING]
    if running:
        # The advisory-lock equivalent. Two concurrent runs over the same
        # data would produce two sets of groups claiming the same records.
        raise ApiError(
            "RUN_IN_PROGRESS",
            f"run {running[0].run_id} is already in progress",
            status_code=status.HTTP_409_CONFLICT,
            extra={"runId": running[0].run_id},
        )

    record = repo.create_run(RULESET_VERSION)
    background.add_task(_execute_run, record.run_id)
    return run_dto(record)


def _execute_run(run_id: str) -> None:
    """The engine, off the request path.

    Failure is recorded on the run rather than raised into a background
    task nobody is watching: a crashed run must be visibly `failed` with
    its stage, not silently stuck at `running`.
    """
    repo = get_repository()
    record = repo.get_run(run_id)
    if record is None:                       # pragma: no cover - created above
        return

    record.status = RunStatus.RUNNING
    record.started_at = datetime.now(UTC)
    record.current_stage = "matching"
    record.progress_pct = 10

    try:
        result = execute(
            repo.all_transactions(), run_id=run_id, policy=Policy(),
            ruleset_version=record.ruleset_version,
        )
        repo.save_run_result(run_id, result)

        record.status = RunStatus.COMPLETED
        record.current_stage = None
        record.progress_pct = 100
        record.completed_at = datetime.now(UTC)

        summary = result.summary()
        repo.add_audit(new_audit(
            entity_type="run", entity_id=run_id, action="run_completed",
            ruleset_version=record.ruleset_version,
            detail=(
                f"{summary['records_processed']} records, "
                f"{summary['auto_resolved']} auto-resolved, "
                f"{summary['pending_review']} to review, "
                f"{summary['exceptions']} exceptions"
            ),
        ))
    except Exception as exc:  # noqa: BLE001 - the failure is the outcome
        record.status = RunStatus.FAILED
        record.error = f"{type(exc).__name__}: {exc}"
        record.completed_at = datetime.now(UTC)
