"""Ingestion.

Upload a CSV, get back exactly what was accepted and what was rejected
and why. FR-3's requirement is that nothing is coerced: a row with a bad
amount is quarantined with its column, its raw value, and a stable code -
never rounded into looking valid.

Two idempotency layers, because they catch different mistakes:

* an `Idempotency-Key` header catches a retried request;
* a SHA-256 of the file bytes catches the same content uploaded again
  under a different name, which a key alone would let through.
"""

from __future__ import annotations

import csv
import hashlib
import io

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, status
from ledgergraph_domain.enums import ImportStatus
from ledgergraph_domain.normalizers import NORMALIZERS, RejectionError, get_normalizer

from ..config import get_settings
from ..deps import CanRead, current_user
from ..dto import ImportDetailDTO, ImportDTO, import_dto
from ..errors import ApiError
from ..store import get_repository, new_audit

# Auth at the router rather than per-route: a new endpoint added here
# later is protected by default. Forgetting a decorator is how an
# unauthenticated endpoint ships.
router = APIRouter(
    prefix="/v1/imports", tags=["imports"],
    dependencies=[Depends(current_user)],
)

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


@router.get("", response_model=list[ImportDTO], summary="List imports")
async def list_imports() -> list[ImportDTO]:
    return [import_dto(r) for r in await get_repository().list_imports()]


@router.get("/datasets", summary="Datasets that can be uploaded")
async def list_datasets() -> dict:
    """The declared source types. Selection is never sniffed from content -
    a mislabelled upload must error rather than parse as the wrong source."""
    return {
        "datasets": [
            {
                "dataset": name,
                "sourceSystem": n.source_system.value,
                "requiredColumns": list(n.required_columns),
            }
            for name, n in sorted(NORMALIZERS.items())
        ]
    }


@router.get("/{import_id}", response_model=ImportDetailDTO, summary="Import detail")
async def get_import(import_id: str) -> ImportDetailDTO:
    record = await get_repository().get_import(import_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such import")
    return import_dto(record, detail=True)


@router.post("", response_model=ImportDetailDTO, status_code=status.HTTP_201_CREATED,
              summary="Upload a source file")
async def create_import(
    user: CanRead,
    dataset: str = Form(...),
    file: UploadFile = File(...),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ImportDetailDTO:
    repo = get_repository()

    if dataset not in NORMALIZERS:
        raise ApiError(
            "UNKNOWN_DATASET",
            f"{dataset!r} is not a known dataset; expected one of {sorted(NORMALIZERS)}",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    if idempotency_key:
        existing = await repo.find_import_by_key(idempotency_key)
        if existing is not None:
            # A replay returns the original result rather than importing twice.
            return import_dto(existing, detail=True)

    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ApiError(
            "FILE_TOO_LARGE",
            f"file is {len(raw)} bytes; the limit is {MAX_UPLOAD_BYTES}",
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )

    content_sha = hashlib.sha256(raw).hexdigest()
    duplicate = await repo.find_import_by_hash(content_sha)
    if duplicate is not None:
        # Same bytes, different filename. Reported rather than re-imported,
        # because a second copy of a bank statement inflates every total.
        record = await repo.create_import(
            dataset=dataset, filename=file.filename or "upload.csv",
            idempotency_key=idempotency_key, content_sha256=content_sha,
        )
        record.status = ImportStatus.DUPLICATE
        record.error = (
            f"identical content was already imported as {duplicate.import_id} "
            f"({duplicate.filename})"
        )
        await repo.save_import(record)
        return import_dto(record, detail=True)

    record = await repo.create_import(
        dataset=dataset, filename=file.filename or "upload.csv",
        idempotency_key=idempotency_key, content_sha256=content_sha,
    )
    record.status = ImportStatus.VALIDATING

    try:
        text = raw.decode("utf-8-sig")       # tolerate a BOM
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        record.status = ImportStatus.FAILED
        record.error = "file has no header row"
        await repo.save_import(record)
        return import_dto(record, detail=True)

    normalizer = get_normalizer(dataset)
    missing = [c for c in normalizer.required_columns if c not in reader.fieldnames]
    if missing:
        # A file-level problem fails the file. Rejecting row by row here
        # would produce thousands of identical rejections and bury the
        # one fact that matters.
        record.status = ImportStatus.FAILED
        record.error = f"missing required column(s): {', '.join(missing)}"
        await repo.save_import(record)
        return import_dto(record, detail=True)

    settings = get_settings()
    accepted, rejections = [], []

    for line_number, row in enumerate(reader, start=2):   # header is line 1
        record.rows_total += 1
        try:
            accepted.append(
                normalizer.normalise(row, business_timezone=settings.business_timezone)
            )
        except RejectionError as exc:
            rejections.append({"row_number": line_number, **exc.as_dict()})

    record.rows_accepted = len(accepted)
    record.rows_rejected = len(rejections)
    record.rejections = rejections
    record.status = ImportStatus.COMPLETED
    await repo.add_transactions(record.import_id, accepted)
    await repo.save_import(record)

    await repo.add_audit(new_audit(
        entity_type="import", entity_id=record.import_id, action="imported",
        actor_type="user", actor_id=user.user_id, actor_name=user.full_name,
        actor_role=user.role.value,
        detail=(
            f"{record.rows_accepted} accepted, {record.rows_rejected} rejected "
            f"from {record.filename}"
        ),
    ))

    return import_dto(record, detail=True)
