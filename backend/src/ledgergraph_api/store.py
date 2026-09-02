"""Persistence, behind a protocol.

There is no Postgres on this machine yet, and the frontend needs a real
API today rather than after a database appears. So persistence is a
protocol with an in-memory implementation, and the Postgres one becomes
a second class implementing the same six-or-so methods.

That is not a workaround dressed up as architecture - it is what lets the
API be built and tested against the real engine now, and it forces the
service layer to talk to an interface rather than to SQLAlchemy sessions
scattered through the routers.

**What the in-memory store does not give you**, stated plainly so nobody
demos on it by accident: no durability across a restart, no concurrent
writers, no transactional guarantee spanning a mutation and its audit
event, and none of the schema's CHECK constraints or triggers. Those are
exactly the guarantees `db/schema.sql` exists to provide, which is why
the Postgres implementation is not optional for a real deployment.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from ledgergraph_ai.client import InvestigationOutcome
from ledgergraph_domain.canonical import CanonicalTransaction
from ledgergraph_domain.enums import (
    CaseResolution,
    ImportStatus,
    ReasonCode,
    RunStatus,
    UserRole,
)
from ledgergraph_reconciliation.models import ExceptionCase, MatchGroup, RunResult


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@dataclass
class ImportRecord:
    import_id: str
    dataset: str
    filename: str
    status: ImportStatus
    rows_total: int = 0
    rows_accepted: int = 0
    rows_rejected: int = 0
    rejections: list[dict] = field(default_factory=list)
    idempotency_key: str | None = None
    content_sha256: str = ""
    created_at: datetime = field(default_factory=_now)
    completed_at: datetime | None = None
    error: str | None = None


@dataclass
class RunRecord:
    run_id: str
    status: RunStatus
    ruleset_version: str
    current_stage: str | None = None
    progress_pct: int = 0
    created_at: datetime = field(default_factory=_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    result: RunResult | None = None
    metrics: dict = field(default_factory=dict)


@dataclass
class User:
    user_id: str
    email: str
    hashed_password: str
    full_name: str
    role: UserRole
    is_active: bool = True
    #: No SMTP in this environment, so accounts are created verified and
    #: the field exists to carry the flow once mail is wired. Recording
    #: that honestly beats pretending a verification step ran.
    is_verified: bool = True
    created_at: datetime = field(default_factory=_now)
    last_login_at: datetime | None = None


@dataclass
class RefreshToken:
    token_id: str
    user_id: str
    digest: str
    #: All tokens descended from one login share a family. Presenting a
    #: consumed token revokes the whole family, which is what turns a
    #: stolen token from indefinitely usable into usable once.
    family_id: str
    expires_at: datetime
    issued_at: datetime = field(default_factory=_now)
    consumed_at: datetime | None = None
    revoked_at: datetime | None = None

    @property
    def is_live(self) -> bool:
        return (
            self.consumed_at is None
            and self.revoked_at is None
            and self.expires_at > _now()
        )


@dataclass
class CaseDecision:
    """A human's verdict on one case.

    Held beside the run result rather than mutating `ExceptionCase`,
    because a run's output is what the engine computed at a point in
    time and a decision is what a person did afterwards. Folding the
    second into the first would mean a re-run either silently erases
    decisions or has to merge them back - and it would make the
    engine's dataclasses depend on the API's notion of a user.
    """

    case_id: str
    resolution: CaseResolution
    reason_code: ReasonCode | None
    note: str
    decided_by: str
    decided_by_name: str
    decided_by_role: UserRole
    decided_at: datetime = field(default_factory=_now)


@dataclass
class AuditEvent:
    event_id: str
    entity_type: str
    entity_id: str
    action: str
    actor_type: str
    actor_name: str | None
    actor_role: str | None
    reason_code: str | None
    detail: str
    ruleset_version: str | None
    created_at: datetime = field(default_factory=_now)


class Repository(Protocol):
    """What the service layer needs. Deliberately narrow."""

    def create_import(self, *, dataset: str, filename: str,
                       idempotency_key: str | None, content_sha256: str) -> ImportRecord: ...
    def find_import_by_key(self, key: str) -> ImportRecord | None: ...
    def find_import_by_hash(self, sha: str) -> ImportRecord | None: ...
    def get_import(self, import_id: str) -> ImportRecord | None: ...
    def list_imports(self) -> list[ImportRecord]: ...
    def add_transactions(self, import_id: str,
                          transactions: list[CanonicalTransaction]) -> None: ...
    def all_transactions(self) -> list[CanonicalTransaction]: ...
    def create_run(self, ruleset_version: str) -> RunRecord: ...
    def get_run(self, run_id: str) -> RunRecord | None: ...
    def list_runs(self) -> list[RunRecord]: ...
    def latest_run(self) -> RunRecord | None: ...
    def save_run_result(self, run_id: str, result: RunResult) -> None: ...
    def get_case(self, case_id: str) -> ExceptionCase | None: ...
    def get_group(self, group_id: str) -> MatchGroup | None: ...
    def add_investigation(self, case_id: str, outcome: InvestigationOutcome) -> None: ...
    def investigations(self, case_id: str) -> list[InvestigationOutcome]: ...
    def record_decision(self, decision: CaseDecision) -> None: ...
    def get_decision(self, case_id: str) -> CaseDecision | None: ...
    def all_decisions(self) -> dict[str, CaseDecision]: ...
    def add_audit(self, event: AuditEvent) -> None: ...
    def audit_for(self, entity_id: str) -> list[AuditEvent]: ...
    def create_user(self, *, email: str, hashed_password: str, full_name: str,
                     role: UserRole) -> User: ...
    def get_user(self, user_id: str) -> User | None: ...
    def find_user_by_email(self, email: str) -> User | None: ...
    def list_users(self) -> list[User]: ...
    def store_refresh(self, *, user_id: str, digest: str, family_id: str,
                       expires_at: datetime) -> RefreshToken: ...
    def find_refresh(self, digest: str) -> RefreshToken | None: ...
    def consume_refresh(self, token: RefreshToken) -> None: ...
    def revoke_family(self, family_id: str) -> int: ...


class InMemoryRepository:
    """Single-process, non-durable. Correct for development and tests."""

    def __init__(self) -> None:
        self._imports: dict[str, ImportRecord] = {}
        self._transactions: dict[str, list[CanonicalTransaction]] = {}
        self._runs: dict[str, RunRecord] = {}
        self._cases: dict[str, ExceptionCase] = {}
        self._groups: dict[str, MatchGroup] = {}
        self._investigations: dict[str, list[InvestigationOutcome]] = defaultdict(list)
        self._audit: dict[str, list[AuditEvent]] = defaultdict(list)
        self._decisions: dict[str, CaseDecision] = {}
        self._users: dict[str, User] = {}
        self._refresh: dict[str, RefreshToken] = {}

    # -- imports ---------------------------------------------------------

    def create_import(self, *, dataset: str, filename: str,
                       idempotency_key: str | None, content_sha256: str) -> ImportRecord:
        record = ImportRecord(
            import_id=_new_id("imp"), dataset=dataset, filename=filename,
            status=ImportStatus.PENDING, idempotency_key=idempotency_key,
            content_sha256=content_sha256,
        )
        self._imports[record.import_id] = record
        return record

    def find_import_by_key(self, key: str) -> ImportRecord | None:
        return next((i for i in self._imports.values() if i.idempotency_key == key), None)

    def find_import_by_hash(self, sha: str) -> ImportRecord | None:
        return next(
            (i for i in self._imports.values()
             if i.content_sha256 == sha and i.status is not ImportStatus.FAILED),
            None,
        )

    def get_import(self, import_id: str) -> ImportRecord | None:
        return self._imports.get(import_id)

    def list_imports(self) -> list[ImportRecord]:
        return sorted(self._imports.values(), key=lambda i: i.created_at, reverse=True)

    def add_transactions(self, import_id: str,
                          transactions: list[CanonicalTransaction]) -> None:
        self._transactions[import_id] = transactions

    def all_transactions(self) -> list[CanonicalTransaction]:
        out: list[CanonicalTransaction] = []
        for import_id, txns in self._transactions.items():
            record = self._imports.get(import_id)
            if record and record.status is ImportStatus.COMPLETED:
                out.extend(txns)
        return out

    # -- runs ------------------------------------------------------------

    def create_run(self, ruleset_version: str) -> RunRecord:
        record = RunRecord(
            run_id=_new_id("run"), status=RunStatus.QUEUED, ruleset_version=ruleset_version
        )
        self._runs[record.run_id] = record
        return record

    def get_run(self, run_id: str) -> RunRecord | None:
        return self._runs.get(run_id)

    def list_runs(self) -> list[RunRecord]:
        return sorted(self._runs.values(), key=lambda r: r.created_at, reverse=True)

    def latest_run(self) -> RunRecord | None:
        completed = [r for r in self._runs.values() if r.status is RunStatus.COMPLETED]
        return max(completed, key=lambda r: r.created_at, default=None)

    def save_run_result(self, run_id: str, result: RunResult) -> None:
        record = self._runs[run_id]
        record.result = result
        for case in result.cases:
            self._cases[case.case_id] = case
        for group in result.groups:
            self._groups[group.group_id] = group

    # -- cases -----------------------------------------------------------

    def get_case(self, case_id: str) -> ExceptionCase | None:
        return self._cases.get(case_id)

    def get_group(self, group_id: str) -> MatchGroup | None:
        return self._groups.get(group_id)

    def add_investigation(self, case_id: str, outcome: InvestigationOutcome) -> None:
        self._investigations[case_id].append(outcome)

    def investigations(self, case_id: str) -> list[InvestigationOutcome]:
        return list(self._investigations[case_id])

    # -- decisions ---------------------------------------------------------

    def record_decision(self, decision: CaseDecision) -> None:
        self._decisions[decision.case_id] = decision

    def get_decision(self, case_id: str) -> CaseDecision | None:
        return self._decisions.get(case_id)

    def all_decisions(self) -> dict[str, CaseDecision]:
        return dict(self._decisions)

    # -- audit -----------------------------------------------------------

    def add_audit(self, event: AuditEvent) -> None:
        # Append-only by construction here; enforced by a trigger in Postgres.
        self._audit[event.entity_id].append(event)

    def audit_for(self, entity_id: str) -> list[AuditEvent]:
        return list(self._audit[entity_id])

    # -- users -----------------------------------------------------------

    def create_user(self, *, email: str, hashed_password: str, full_name: str,
                     role: UserRole) -> User:
        user = User(
            user_id=_new_id("usr"), email=email.strip().lower(),
            hashed_password=hashed_password, full_name=full_name, role=role,
        )
        self._users[user.user_id] = user
        return user

    def get_user(self, user_id: str) -> User | None:
        return self._users.get(user_id)

    def find_user_by_email(self, email: str) -> User | None:
        target = email.strip().lower()
        return next((u for u in self._users.values() if u.email == target), None)

    def list_users(self) -> list[User]:
        return sorted(self._users.values(), key=lambda u: u.created_at)

    # -- refresh tokens ---------------------------------------------------

    def store_refresh(self, *, user_id: str, digest: str, family_id: str,
                       expires_at: datetime) -> RefreshToken:
        token = RefreshToken(
            token_id=_new_id("rft"), user_id=user_id, digest=digest,
            family_id=family_id, expires_at=expires_at,
        )
        self._refresh[digest] = token
        return token

    def find_refresh(self, digest: str) -> RefreshToken | None:
        return self._refresh.get(digest)

    def consume_refresh(self, token: RefreshToken) -> None:
        token.consumed_at = _now()

    def revoke_family(self, family_id: str) -> int:
        """Kill every token descended from one login.

        Called when a consumed token is presented again, which means
        either a copy is in circulation or the legitimate client
        replayed. Both warrant re-authentication; only one is benign,
        and there is no way to tell them apart from here.
        """
        revoked = 0
        for token in self._refresh.values():
            if token.family_id == family_id and token.revoked_at is None:
                token.revoked_at = _now()
                revoked += 1
        return revoked


#: Process-wide instance. Replaced by a Postgres-backed repository via the
#: same protocol once a database is reachable.
_repository: Repository = InMemoryRepository()


def get_repository() -> Repository:
    return _repository


def reset_repository() -> None:
    """Fresh state between tests."""
    global _repository
    _repository = InMemoryRepository()


def new_audit(
    *, entity_type: str, entity_id: str, action: str, detail: str,
    actor_type: str = "system", actor_name: str | None = None,
    actor_role: str | None = None, reason_code: str | None = None,
    ruleset_version: str | None = None,
) -> AuditEvent:
    return AuditEvent(
        event_id=_new_id("aud"), entity_type=entity_type, entity_id=entity_id,
        action=action, actor_type=actor_type, actor_name=actor_name,
        actor_role=actor_role, reason_code=reason_code, detail=detail,
        ruleset_version=ruleset_version,
    )
