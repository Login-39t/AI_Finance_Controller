"""Browsing match groups.

The point of exposing cleared groups at all is that auto-resolution
precision should be spot-checkable rather than taken on trust. So the
tests here are mostly about that: an auto-resolved group must be
reachable, and it must carry the six conditions that let it through.
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
    out = tmp_path_factory.mktemp("match_data")
    world = generate_world(400, seed=29, lookback_days=30)
    inject_anomalies(world, random.Random(29 ^ 0x5EED))
    write_world(world, out)
    return out


@pytest.fixture
async def client(dataset):
    reset_repository()
    await seed_demo_users()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        token = (await c.post("/v1/auth/login", json={
            "email": "analyst@tallyproof.dev", "password": DEMO_PASSWORD,
        })).json()["accessToken"]
        c.headers["Authorization"] = f"Bearer {token}"

        for name, filename in DATASETS.items():
            assert (await c.post(
                "/v1/imports",
                data={"dataset": name},
                files={"file": (filename, (dataset / filename).read_bytes(), "text/csv")},
            )).status_code == 201

        run_id = (await c.post("/v1/reconciliation-runs")).json()["id"]
        for _ in range(200):
            state = (await c.get(f"/v1/reconciliation-runs/{run_id}")).json()
            if state["status"] in ("completed", "failed"):
                break
            await asyncio.sleep(0.05)
        assert state["status"] == "completed", state

        yield c
    reset_repository()


async def test_browsing_groups_requires_a_signed_in_caller(dataset):
    reset_repository()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        assert (await c.get("/v1/match-groups")).status_code == 401
        assert (await c.get("/v1/match-groups/grp_nope")).status_code == 401
    reset_repository()


async def test_groups_are_sorted_by_matched_value(client):
    page = (await client.get("/v1/match-groups", params={"limit": 200})).json()
    amounts = [int(g["matchedAmountMinor"]) for g in page["items"]]
    assert amounts == sorted(amounts, reverse=True)


async def test_auto_resolved_groups_are_visible_not_hidden(client):
    """The half a reconciliation tool usually hides."""
    page = (await client.get("/v1/match-groups",
                             params={"status": "auto_resolved", "limit": 200})).json()
    assert page["total"] > 0, "no cleared group is reachable, so precision cannot be checked"
    assert all(g["status"] == "auto_resolved" for g in page["items"])


async def test_status_counts_cover_every_group_and_do_not_move_when_filtered(client):
    """A tab bar whose numbers change as you filter is worse than none."""
    everything = (await client.get("/v1/match-groups", params={"limit": 200})).json()
    filtered = (await client.get("/v1/match-groups",
                                 params={"status": "auto_resolved", "limit": 200})).json()

    assert filtered["statusCounts"] == everything["statusCounts"]
    assert sum(everything["statusCounts"].values()) == everything["total"]


async def test_a_cleared_group_carries_the_conditions_that_cleared_it(client):
    page = (await client.get("/v1/match-groups",
                             params={"status": "auto_resolved", "limit": 1})).json()
    group_id = page["items"][0]["id"]

    detail = (await client.get(f"/v1/match-groups/{group_id}")).json()
    assert detail["status"] == "auto_resolved"
    assert len(detail["gate"]) == 6, "the gate has six conditions; all must be reported"
    assert all(c["passed"] for c in detail["gate"]), (
        "a group was auto-resolved with a failing gate condition"
    )
    assert detail["gatePassed"] == detail["gateTotal"] == 6


async def test_a_group_routed_to_review_says_which_condition_failed(client):
    page = (await client.get("/v1/match-groups",
                             params={"status": "pending_review", "limit": 1})).json()
    if page["total"] == 0:
        pytest.fail("this dataset produced no group needing review; the test is vacuous")

    detail = (await client.get(f"/v1/match-groups/{page['items'][0]['id']}")).json()
    failed = [c for c in detail["gate"] if not c["passed"]]
    assert failed, "a group was routed to review with every condition passing"
    assert all(c["detail"] for c in failed), (
        "a failed condition with no detail tells the analyst nothing"
    )


async def test_confidence_never_overrides_a_failed_condition(client):
    """The claim the whole system rests on, checked against the data.

    A high-confidence group with a failing condition must still be
    pending review. If this ever passes vacuously - no such group in the
    data - it fails loudly rather than reporting success.
    """
    page = (await client.get("/v1/match-groups", params={"limit": 200})).json()

    checked = 0
    for summary in page["items"]:
        if summary["confidence"] < 0.95 or summary["gateTotal"] == 0:
            continue
        if summary["gatePassed"] == summary["gateTotal"]:
            continue
        checked += 1
        assert summary["status"] != "auto_resolved", (
            f"{summary['id']} cleared with {summary['gatePassed']}/"
            f"{summary['gateTotal']} conditions at confidence {summary['confidence']}"
        )

    assert checked > 0, (
        "no high-confidence group with a failed condition exists in this run, "
        "so this test proved nothing"
    )


async def test_group_detail_reuses_the_same_bridge_shape_as_a_case(client):
    """One renderer, one meaning of 'balances'."""
    page = (await client.get("/v1/match-groups", params={"limit": 200})).json()
    with_bridge = [g for g in page["items"] if g["bridgeBalances"] is not None]
    assert with_bridge, "no group carries a bridge"

    detail = (await client.get(f"/v1/match-groups/{with_bridge[0]['id']}")).json()
    bridge = detail["bridge"]
    assert bridge is not None
    assert {"expectedNetMinor", "observedNetMinor", "differenceMinor", "balances"} <= set(bridge)

    # The difference is exactly observed minus expected. Integer identity,
    # not an approximation.
    assert (
        int(bridge["differenceMinor"])
        == int(bridge["observedNetMinor"]) - int(bridge["expectedNetMinor"])
    )


async def test_an_unknown_group_is_404(client):
    assert (await client.get("/v1/match-groups/grp_nope")).status_code == 404


async def test_a_bad_cursor_is_a_client_error(client):
    response = await client.get("/v1/match-groups", params={"cursor": "not-base64"})
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_CURSOR"


async def test_paging_covers_every_group_exactly_once(client):
    seen: list[str] = []
    cursor = None
    for _ in range(50):
        params = {"limit": 20}
        if cursor:
            params["cursor"] = cursor
        page = (await client.get("/v1/match-groups", params=params)).json()
        seen.extend(g["id"] for g in page["items"])
        cursor = page["nextCursor"]
        if not cursor:
            break

    assert len(seen) == len(set(seen)), "paging returned a group twice"
    everything = (await client.get("/v1/match-groups", params={"limit": 200})).json()
    assert len(seen) == everything["total"]
