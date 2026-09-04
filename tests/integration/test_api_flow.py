"""The critical path, over HTTP.

Upload five CSVs, start a run, read the queue, open a case. This is the
demo script and it is also the only test that proves the pieces built
separately - generator, normalisers, engine, packet - actually fit
together behind an API.

No database and no network: the repository is in-memory and the AI
provider is faked, which is what lets the whole path run in a second.
"""

from __future__ import annotations

import asyncio
import random
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from ledgergraph_api.main import app
from ledgergraph_api.routers.auth import seed_demo_users
from ledgergraph_api.store import reset_repository

from data.synthetic.anomalies import inject_anomalies
from data.synthetic.generator import generate_world, write_world

DEMO_PASSWORD = "tallyproof-demo-2026"

DATASETS = {
    "payments": "payments.csv",
    "settlement_batches": "settlement_batches.csv",
    "settlement_lines": "settlement_lines.csv",
    "bank_statement": "bank_statement.csv",
    "invoices": "invoices.csv",
    "ledger": "ledger.csv",
}


@pytest.fixture(scope="module")
def dataset(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("api_data")
    world = generate_world(300, seed=17, lookback_days=30)
    inject_anomalies(world, random.Random(17 ^ 0x5EED))
    write_world(world, out)
    return out


async def _sign_in(c: AsyncClient, role: str = "controller") -> AsyncClient:
    """Attach a real access token for one of the demo roles.

    Every endpoint below the auth router needs an identity now, so this
    logs in for real rather than stubbing the dependency. That costs one
    Argon2 verification per test and buys the guarantee that the token
    these tests carry is the token a browser would carry.
    """
    response = await c.post(
        "/v1/auth/login",
        json={"email": f"{role}@tallyproof.dev", "password": DEMO_PASSWORD},
    )
    assert response.status_code == 200, response.text
    c.headers["Authorization"] = f"Bearer {response.json()['accessToken']}"
    return c


@pytest.fixture
async def anonymous():
    reset_repository()
    await seed_demo_users()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    reset_repository()


@pytest.fixture
async def client(anonymous):
    yield await _sign_in(anonymous)


async def _upload_all(client, dataset: Path) -> list[dict]:
    results = []
    for name, filename in DATASETS.items():
        response = await client.post(
            "/v1/imports",
            data={"dataset": name},
            files={"file": (filename, (dataset / filename).read_bytes(), "text/csv")},
        )
        assert response.status_code == 201, response.text
        results.append(response.json())
    return results


async def _run_to_completion(client, *, max_polls: int = 50) -> dict:
    """Start a run and poll until it reaches a terminal state.

    The polling is deliberate rather than incidental. Under
    `ASGITransport` a background task finishes before the response is
    readable, so a single GET straight after the POST appears to work -
    and that is an artefact of the test transport, not the contract.
    Against a real server the task runs *after* the response is sent, and
    a client that does not poll sees `queued` with null metrics.

    Polling here means this test exercises the same sequence the frontend
    does, instead of passing for a reason that disappears in production.
    """
    started = await client.post("/v1/reconciliation-runs")
    assert started.status_code == 202, started.text
    run_id = started.json()["id"]
    assert started.json()["status"] in ("queued", "running")

    for _ in range(max_polls):
        response = await client.get(f"/v1/reconciliation-runs/{run_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] in ("completed", "failed", "cancelled"):
            return body
        await asyncio.sleep(0.05)

    raise AssertionError(f"run {run_id} did not reach a terminal state")


# --------------------------------------------------------------------------
# Ingestion
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_datasets_are_declared_not_sniffed(client):
    response = await client.get("/v1/imports/datasets")
    assert response.status_code == 200
    names = {d["dataset"] for d in response.json()["datasets"]}
    assert names == set(DATASETS)


@pytest.mark.asyncio
async def test_upload_reports_accepted_and_rejected(client, dataset):
    imports = await _upload_all(client, dataset)
    for record in imports:
        assert record["status"] == "completed"
        assert record["rowsAccepted"] > 0
        assert record["rowsRejected"] == 0, record["rejections"]
        assert record["rowsTotal"] == record["rowsAccepted"] + record["rowsRejected"]


@pytest.mark.asyncio
async def test_a_malformed_row_is_quarantined_with_its_reason(client):
    """FR-3. The row is rejected with column, value and a stable code -
    never coerced into looking valid."""
    csv_bytes = (
        b"payment_id,order_id,amount,currency,status,created_at,method,record_type,"
        b"parent_payment_id\n"
        b"pay_GOOD,order_1,100.00,INR,captured,2026-03-04T10:00:00+05:30,upi,payment,\n"
        b"pay_BAD,order_2,1;2 34.00,INR,captured,2026-03-04T10:00:00+05:30,upi,payment,\n"
        b"pay_PREC,order_3,100.005,INR,captured,2026-03-04T10:00:00+05:30,upi,payment,\n"
    )
    response = await client.post(
        "/v1/imports",
        data={"dataset": "payments"},
        files={"file": ("payments.csv", csv_bytes, "text/csv")},
    )
    body = response.json()

    assert body["rowsAccepted"] == 1
    assert body["rowsRejected"] == 2
    codes = {r["errorCode"] for r in body["rejections"]}
    assert "AMOUNT_PRECISION_LOSS" in codes
    for rejection in body["rejections"]:
        assert rejection["rowNumber"] >= 2      # header is line 1
        assert rejection["columnName"] == "amount"
        assert rejection["rawValue"]


@pytest.mark.asyncio
async def test_missing_required_column_fails_the_file_not_each_row(client):
    """Rejecting row by row here would bury the one fact that matters
    under thousands of identical rejections."""
    response = await client.post(
        "/v1/imports",
        data={"dataset": "payments"},
        files={"file": ("bad.csv", b"payment_id,amount\npay_1,100.00\n", "text/csv")},
    )
    body = response.json()
    assert body["status"] == "failed"
    assert "missing required column" in body["error"]
    assert body["rejections"] == []


@pytest.mark.asyncio
async def test_unknown_dataset_is_rejected(client):
    response = await client.post(
        "/v1/imports",
        data={"dataset": "not_a_dataset"},
        files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "UNKNOWN_DATASET"


@pytest.mark.asyncio
async def test_idempotency_key_replay_does_not_import_twice(client, dataset):
    payload = (dataset / "bank_statement.csv").read_bytes()
    kwargs = dict(
        data={"dataset": "bank_statement"},
        files={"file": ("bank_statement.csv", payload, "text/csv")},
        headers={"Idempotency-Key": "abc-123"},
    )
    first = await client.post("/v1/imports", **kwargs)
    second = await client.post("/v1/imports", **kwargs)

    assert first.json()["id"] == second.json()["id"]
    assert len((await client.get("/v1/imports")).json()) == 1


@pytest.mark.asyncio
async def test_same_content_under_a_different_filename_is_caught(client, dataset):
    """An idempotency key alone would let this through, and a second copy
    of a bank statement inflates every total."""
    payload = (dataset / "bank_statement.csv").read_bytes()
    await client.post(
        "/v1/imports", data={"dataset": "bank_statement"},
        files={"file": ("march.csv", payload, "text/csv")},
    )
    again = await client.post(
        "/v1/imports", data={"dataset": "bank_statement"},
        files={"file": ("march-copy.csv", payload, "text/csv")},
    )
    assert again.json()["status"] == "duplicate"
    assert "already imported" in again.json()["error"]


# --------------------------------------------------------------------------
# Runs
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_without_data_is_refused(client):
    response = await client.post("/v1/reconciliation-runs")
    assert response.status_code == 409
    assert response.json()["code"] == "NO_DATA"


@pytest.mark.asyncio
async def test_a_started_run_is_not_immediately_complete(client, dataset):
    """The POST must return before the work is done, or the request is
    holding a connection open for the length of a reconciliation."""
    await _upload_all(client, dataset)
    started = await client.post("/v1/reconciliation-runs")
    assert started.status_code == 202
    body = started.json()
    assert body["status"] in ("queued", "running")
    assert body["metrics"] is None, "metrics cannot exist before the run does"


@pytest.mark.asyncio
async def test_run_produces_metrics(client, dataset):
    await _upload_all(client, dataset)
    run = await _run_to_completion(client)

    assert run["status"] == "completed"
    assert run["progressPct"] == 100
    metrics = run["metrics"]
    assert metrics["recordsProcessed"] > 500
    assert metrics["autoResolved"] > 0
    assert metrics["exceptions"] > 0
    assert metrics["stageTimingsMs"]


@pytest.mark.asyncio
async def test_money_crosses_the_wire_as_strings(client, dataset):
    """A JSON number over 2^53 loses precision silently, and typing it
    `string` is what stops the frontend multiplying money by accident."""
    await _upload_all(client, dataset)
    run = await _run_to_completion(client)

    assert isinstance(run["metrics"]["grossProcessedMinor"], str)
    assert isinstance(run["metrics"]["unresolvedValueMinor"], str)

    queue = (await client.get("/v1/exceptions")).json()
    for item in queue["items"]:
        assert isinstance(item["amountAtRiskMinor"], str)
        assert item["amountAtRiskMinor"].lstrip("-").isdigit()


# --------------------------------------------------------------------------
# Queue and case detail
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_queue_is_sorted_by_amount_at_risk(client, dataset):
    await _upload_all(client, dataset)
    await _run_to_completion(client)

    queue = (await client.get("/v1/exceptions?limit=200")).json()
    amounts = [int(i["amountAtRiskMinor"]) for i in queue["items"]]
    assert amounts == sorted(amounts, reverse=True)


@pytest.mark.asyncio
async def test_queue_filters_and_paginates(client, dataset):
    await _upload_all(client, dataset)
    await _run_to_completion(client)

    everything = (await client.get("/v1/exceptions?limit=200")).json()
    assert everything["total"] > 0

    first = (await client.get("/v1/exceptions?limit=2")).json()
    assert len(first["items"]) == 2
    assert first["nextCursor"]

    second = (await client.get(f"/v1/exceptions?limit=2&cursor={first['nextCursor']}")).json()
    assert {i["id"] for i in first["items"]}.isdisjoint({i["id"] for i in second["items"]})

    a_type = everything["items"][0]["caseType"]
    filtered = (await client.get(f"/v1/exceptions?caseType={a_type}&limit=200")).json()
    assert all(i["caseType"] == a_type for i in filtered["items"])


@pytest.mark.asyncio
async def test_bad_cursor_is_a_client_error(client, dataset):
    await _upload_all(client, dataset)
    await _run_to_completion(client)
    response = await client.get("/v1/exceptions?cursor=not-a-cursor")
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_CURSOR"


@pytest.mark.asyncio
async def test_case_packet_arrives_in_one_request(client, dataset):
    """The fat endpoint. Six requests to render one page would be slower,
    and would make packet assembly a second code path that can drift from
    what the model is shown."""
    await _upload_all(client, dataset)
    await _run_to_completion(client)

    queue = (await client.get("/v1/exceptions?limit=200")).json()
    target = next(
        i for i in queue["items"] if i["caseType"] == "missing_bank_credit"
    )
    packet = (await client.get(f"/v1/exceptions/{target['id']}")).json()

    assert packet["id"] == target["id"]
    assert packet["transactions"], "a case must name its records"
    assert packet["evidence"], "a case must show what was compared"
    assert len(packet["gate"]) == 6, "all six gate conditions must be reported"
    assert any(not g["passed"] for g in packet["gate"]), (
        "a case in the queue must have failed at least one condition"
    )
    for condition in packet["gate"]:
        assert condition["detail"], "each condition must report its evaluated value"


@pytest.mark.asyncio
async def test_evidence_ids_match_the_ids_the_verifier_checks(client, dataset):
    """The UI and the grounding verifier must speak about the same
    citations, or a reviewer cannot follow one to the other."""
    await _upload_all(client, dataset)
    await _run_to_completion(client)

    queue = (await client.get("/v1/exceptions?limit=200")).json()
    case_id = queue["items"][0]["id"]
    packet = (await client.get(f"/v1/exceptions/{case_id}")).json()

    for i, evidence in enumerate(packet["evidence"], start=1):
        assert evidence["id"] == f"{case_id}:ev{i}"


@pytest.mark.asyncio
async def test_unknown_case_is_404(client, dataset):
    await _upload_all(client, dataset)
    await _run_to_completion(client)
    response = await client.get("/v1/exceptions/exc_does_not_exist")
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_queue_before_any_run_is_404_not_an_empty_list(client):
    """An empty list would read as 'nothing to reconcile', which is a
    different and much more comfortable claim than 'no run has happened'."""
    response = await client.get("/v1/exceptions")
    assert response.status_code == 404


# --------------------------------------------------------------------------
# AI investigation
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_investigation_is_refused_cleanly_when_ai_is_disabled(
    client, dataset, monkeypatch
):
    """AI off must be a clear 503, not a crash.

    `AI_ENABLED=false` is forced rather than assumed. Reading it from the
    developer's `.env` made this test pass or fail depending on a setting
    that has nothing to do with what it checks.
    """
    from ledgergraph_api.config import get_settings

    await _upload_all(client, dataset)
    await _run_to_completion(client)

    queue = (await client.get("/v1/exceptions?limit=200")).json()
    case_id = queue["items"][0]["id"]

    get_settings.cache_clear()
    monkeypatch.setenv("AI_ENABLED", "false")
    monkeypatch.delenv("AI_API_KEY", raising=False)
    try:
        response = await client.post(f"/v1/exceptions/{case_id}/investigate")
        assert response.status_code == 503
        assert response.json()["code"] == "AI_DISABLED"
    finally:
        get_settings.cache_clear()
