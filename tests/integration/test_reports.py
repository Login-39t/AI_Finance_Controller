"""Reports and exports.

The property worth proving here is not "a CSV came back". It is that the
CSV says the same thing the screen said, and that the money in it is
exact.

An export is where a rounding bug survives: the number leaves the system,
gets summed in Excel, and reappears in a close pack weeks later with
nobody able to trace where the paise went. So the amount column is
checked against the integer it came from, digit for digit.
"""

from __future__ import annotations

import asyncio
import csv
import io
import random
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from ledgergraph_api.main import app
from ledgergraph_api.routers.auth import seed_demo_users
from ledgergraph_api.routers.reports import _rupees
from ledgergraph_api.store import reset_repository

from data.synthetic.anomalies import inject_anomalies
from data.synthetic.generator import generate_world, write_world

DEMO_PASSWORD = "ledgergraph-demo-2026"

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
    out = tmp_path_factory.mktemp("report_data")
    world = generate_world(400, seed=23, lookback_days=30)
    inject_anomalies(world, random.Random(23 ^ 0x5EED))
    write_world(world, out)
    return out


@pytest.fixture
async def client(dataset):
    reset_repository()
    seed_demo_users()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        token = (await c.post("/v1/auth/login", json={
            "email": "controller@ledgergraph.dev", "password": DEMO_PASSWORD,
        })).json()["accessToken"]
        c.headers["Authorization"] = f"Bearer {token}"

        for name, filename in DATASETS.items():
            response = await c.post(
                "/v1/imports",
                data={"dataset": name},
                files={"file": (filename, (dataset / filename).read_bytes(), "text/csv")},
            )
            assert response.status_code == 201, response.text

        run = await c.post("/v1/reconciliation-runs")
        run_id = run.json()["id"]
        for _ in range(200):
            state = (await c.get(f"/v1/reconciliation-runs/{run_id}")).json()
            if state["status"] in ("completed", "failed"):
                break
            await asyncio.sleep(0.05)
        assert state["status"] == "completed", state

        yield c
    reset_repository()


def _read_csv(body: str) -> tuple[str, list[str], list[dict]]:
    """Split the provenance comment off, then parse."""
    comment, _, rest = body.partition("\n")
    assert comment.startswith("#"), "an export must name the run that produced it"
    reader = csv.DictReader(io.StringIO(rest))
    rows = list(reader)
    return comment, reader.fieldnames or [], rows


# --------------------------------------------------------------------------
# Money, exactly
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("minor", "expected"),
    [
        (0, "0.00"),
        (1, "0.01"),
        (99, "0.99"),
        (100, "1.00"),
        (26713994, "267139.94"),
        (-4550, "-45.50"),
        (-5, "-0.05"),
        # The value that breaks a float path: 8.70 is not representable,
        # and `870 / 100` prints 8.7 in some formats and 8.699999 in others.
        (870, "8.70"),
        (999999999999, "9999999999.99"),
    ],
)
def test_export_amounts_are_exact(minor: int, expected: str):
    assert _rupees(minor) == expected


def test_export_formatting_round_trips_for_every_paise_in_a_range():
    """No float in the path, proven rather than asserted."""
    for minor in range(-500, 500):
        rendered = _rupees(minor)
        whole, _, paise = rendered.lstrip("-").partition(".")
        recovered = int(whole) * 100 + int(paise)
        if minor < 0:
            recovered = -recovered
        assert recovered == minor, f"{minor} -> {rendered} -> {recovered}"


# --------------------------------------------------------------------------
# The overview
# --------------------------------------------------------------------------

async def test_overview_requires_a_signed_in_caller(dataset):
    reset_repository()
    seed_demo_users()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        assert (await c.get("/v1/reports/overview")).status_code == 401
    reset_repository()


async def test_overview_totals_agree_with_the_queue(client):
    overview = (await client.get("/v1/reports/overview")).json()
    queue = (await client.get("/v1/exceptions", params={"limit": 200})).json()

    assert overview["exceptions"] == queue["total"]

    # And the money agrees to the paise, not approximately.
    from_queue = sum(int(i["amountAtRiskMinor"]) for i in queue["items"])
    assert int(overview["exceptionValueMinor"]) == from_queue


async def test_overview_severity_and_type_buckets_partition_the_cases(client):
    overview = (await client.get("/v1/reports/overview")).json()

    by_severity = sum(b["count"] for b in overview["bySeverity"])
    by_type = sum(b["count"] for b in overview["byType"])

    assert by_severity == overview["exceptions"], "a case fell out of the severity buckets"
    assert by_type == overview["exceptions"], "a case fell out of the type buckets"

    severity_value = sum(int(b["amountAtRiskMinor"]) for b in overview["bySeverity"])
    assert severity_value == int(overview["exceptionValueMinor"])


async def test_overview_types_are_ordered_by_money_not_by_name(client):
    """The list is a work queue. Alphabetical would waste attention."""
    overview = (await client.get("/v1/reports/overview")).json()
    amounts = [int(b["amountAtRiskMinor"]) for b in overview["byType"]]
    assert amounts == sorted(amounts, reverse=True)


async def test_overview_tracks_decisions_as_they_land(client):
    before = (await client.get("/v1/reports/overview")).json()
    assert before["decisions"]["decided"] == 0
    assert before["decisions"]["open"] == before["exceptions"]

    case = (await client.get("/v1/exceptions", params={"limit": 1})).json()["items"][0]
    await client.post(f"/v1/exceptions/{case['id']}/decision",
                      json={"resolution": "approved", "note": "checked"})

    after = (await client.get("/v1/reports/overview")).json()
    assert after["decisions"]["decided"] == 1
    assert after["decisions"]["open"] == before["decisions"]["open"] - 1
    assert int(after["decisions"]["decidedValueMinor"]) == int(case["amountAtRiskMinor"])


async def test_a_run_with_no_data_reports_404_rather_than_zeroes(dataset):
    """Zeroes would read as a clean close. There is a difference between
    "nothing is wrong" and "nothing has been checked"."""
    reset_repository()
    seed_demo_users()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        token = (await c.post("/v1/auth/login", json={
            "email": "analyst@ledgergraph.dev", "password": DEMO_PASSWORD,
        })).json()["accessToken"]
        response = await c.get("/v1/reports/overview",
                               headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 404
    reset_repository()


# --------------------------------------------------------------------------
# Exports
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "path",
    ["/v1/exports/exceptions.csv", "/v1/exports/matches.csv", "/v1/exports/audit.csv"],
)
async def test_every_export_is_a_download_that_names_its_run(client, path):
    response = await client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment;" in response.headers["content-disposition"]

    comment, header, rows = _read_csv(response.text)
    assert "ruleset" in comment and "run" in comment
    assert header, "an export with no header row is not a spreadsheet"


async def test_the_exception_export_covers_the_same_cases_as_the_queue(client):
    queue = (await client.get("/v1/exceptions", params={"limit": 200})).json()
    _, _, rows = _read_csv((await client.get("/v1/exports/exceptions.csv")).text)

    assert len(rows) == queue["total"]
    assert {r["case_id"] for r in rows} == {i["id"] for i in queue["items"]}


async def test_exported_amounts_match_the_integers_they_came_from(client):
    queue = (await client.get("/v1/exceptions", params={"limit": 200})).json()
    by_id = {i["id"]: int(i["amountAtRiskMinor"]) for i in queue["items"]}

    _, _, rows = _read_csv((await client.get("/v1/exports/exceptions.csv")).text)
    for row in rows:
        assert row["amount_at_risk"] == _rupees(by_id[row["case_id"]])


async def test_the_export_filter_mirrors_the_queue_filter(client):
    """An export that silently covers a different set than the screen is
    worse than no export."""
    queue = (await client.get("/v1/exceptions",
                              params={"severity": "critical", "limit": 200})).json()
    _, _, rows = _read_csv(
        (await client.get("/v1/exports/exceptions.csv",
                          params={"severity": "critical"})).text
    )
    assert {r["case_id"] for r in rows} == {i["id"] for i in queue["items"]}
    assert all(r["severity"] == "critical" for r in rows)


async def test_a_decision_reaches_the_export(client):
    case = (await client.get("/v1/exceptions", params={"limit": 1})).json()["items"][0]
    await client.post(f"/v1/exceptions/{case['id']}/decision", json={
        "resolution": "overridden", "reasonCode": "bank_error_confirmed",
        "note": "bank confirmed the credit posted late",
    })

    _, _, rows = _read_csv((await client.get("/v1/exports/exceptions.csv")).text)
    row = next(r for r in rows if r["case_id"] == case["id"])

    assert row["resolution"] == "overridden"
    assert row["reason_code"] == "bank_error_confirmed"
    assert row["decided_by"] == "Chitra Controller"
    assert row["decided_by_role"] == "controller"
    assert row["note"] == "bank confirmed the credit posted late"


async def test_undecided_only_narrows_the_export(client):
    total_before = len(_read_csv(
        (await client.get("/v1/exports/exceptions.csv")).text)[2])

    case = (await client.get("/v1/exceptions", params={"limit": 1})).json()["items"][0]
    await client.post(f"/v1/exceptions/{case['id']}/decision",
                      json={"resolution": "dismissed"})

    _, _, remaining = _read_csv(
        (await client.get("/v1/exports/exceptions.csv",
                          params={"undecidedOnly": "true"})).text
    )
    assert len(remaining) == total_before - 1
    assert case["id"] not in {r["case_id"] for r in remaining}


async def test_the_match_export_includes_what_was_auto_resolved(client):
    """A report showing only failures is half a report - the cleared rows
    are what an auditor samples."""
    _, _, rows = _read_csv((await client.get("/v1/exports/matches.csv")).text)
    statuses = {r["status"] for r in rows}
    assert "auto_resolved" in statuses
    assert len(rows) > 0

    # Nothing the gate cleared may carry a bridge that does not balance.
    # A blank here would be indistinguishable from "no", which is why the
    # column writes n/a for a group with no bridge at all.
    cleared = [r for r in rows if r["status"] == "auto_resolved"]
    assert all(r["bridge_balances"] != "no" for r in cleared)
    assert any(r["bridge_balances"] == "yes" for r in cleared), (
        "no auto-resolved group carries a balancing bridge - the column is not "
        "reporting anything"
    )


async def test_the_audit_export_carries_the_decision_that_was_made(client):
    case = (await client.get("/v1/exceptions", params={"limit": 1})).json()["items"][0]
    await client.post(f"/v1/exceptions/{case['id']}/decision", json={
        "resolution": "rejected", "reasonCode": "evidence_insufficient",
        "note": "settlement file for this window has not arrived",
    })

    _, _, rows = _read_csv((await client.get("/v1/exports/audit.csv")).text)
    decisions = [r for r in rows if r["action"] == "rejected"]

    assert len(decisions) == 1
    assert decisions[0]["actor_name"] == "Chitra Controller"
    assert decisions[0]["actor_role"] == "controller"
    assert decisions[0]["reason_code"] == "evidence_insufficient"
    assert decisions[0]["entity_id"] == case["id"]


async def test_an_analyst_may_export(client):
    """Reading and reporting is the analyst's whole job. Only deciding is
    gated."""
    analyst = (await client.post("/v1/auth/login", json={
        "email": "analyst@ledgergraph.dev", "password": DEMO_PASSWORD,
    })).json()["accessToken"]

    response = await client.get(
        "/v1/exports/exceptions.csv",
        headers={"Authorization": f"Bearer {analyst}"},
    )
    assert response.status_code == 200
