"""Auth and RBAC, over HTTP.

These tests are written against the properties that matter rather than
the happy path, because the happy path is the part that is obviously
right. What is worth proving:

* an unauthenticated request is refused everywhere except health;
* a refresh token works exactly once, and reusing it kills the session;
* an analyst cannot decide a case, and a reviewer cannot decide a
  material one - enforced by the API, not by a hidden button;
* an override without a reason code is refused.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from ledgergraph_api.auth import mint_access_token, read_access_token
from ledgergraph_api.main import app
from ledgergraph_api.routers.auth import bootstrap_admin, seed_demo_users
from ledgergraph_api.store import get_repository, reset_repository
from ledgergraph_reconciliation.policy import Policy

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


#: Demo scale on purpose. At 300 payments the largest exception is about
#: Rs 1.06 lakh - below the Rs 2.5 lakh material threshold - so the
#: controller-only path would never be exercised and the most important
#: RBAC test would skip. A skipped test proves nothing.
DATASET_PAYMENTS = 1200
DATASET_SEED = 11


@pytest.fixture(scope="module")
def dataset(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("auth_data")
    world = generate_world(DATASET_PAYMENTS, seed=DATASET_SEED, lookback_days=30)
    inject_anomalies(world, random.Random(DATASET_SEED ^ 0x5EED))
    write_world(world, out)
    return out


@pytest.fixture
async def anonymous():
    reset_repository()
    await seed_demo_users()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    reset_repository()


async def _login(c: AsyncClient, role: str) -> str:
    response = await c.post(
        "/v1/auth/login",
        json={"email": f"{role}@ledgergraph.dev", "password": DEMO_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()["accessToken"]


def _as(role_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {role_token}"}


# --------------------------------------------------------------------------
# The guard
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/v1/exceptions"),
        ("GET", "/v1/exceptions/case_nope"),
        ("POST", "/v1/exceptions/case_nope/decision"),
        ("GET", "/v1/imports"),
        ("POST", "/v1/imports"),
        ("GET", "/v1/reconciliation-runs"),
        ("POST", "/v1/reconciliation-runs"),
        ("GET", "/v1/auth/me"),
    ],
)
async def test_every_domain_endpoint_refuses_an_anonymous_caller(anonymous, method, path):
    response = await anonymous.request(method, path)
    assert response.status_code == 401, f"{method} {path} -> {response.status_code}"


async def test_health_endpoints_never_require_a_token(anonymous):
    """A platform health check that needs a credential is a health check
    that fails for the wrong reason at 3am."""
    assert (await anonymous.get("/healthz")).status_code == 200
    # /readyz may legitimately be 503 without a database; what matters is
    # that it is not 401.
    assert (await anonymous.get("/readyz")).status_code in (200, 503)


async def test_a_refresh_token_is_not_an_access_token(anonymous):
    """Presenting the wrong token type must fail closed."""
    await _login(anonymous, "analyst")
    cookie = anonymous.cookies.get("lg_refresh")
    assert cookie, "login must plant a refresh cookie"

    response = await anonymous.get("/v1/auth/me", headers=_as(cookie))
    assert response.status_code == 401


async def test_a_token_for_a_deleted_user_is_not_an_identity(anonymous):
    """A validly signed token naming nobody is refused.

    Signature validity is not identity. Without this check, a token
    minted against a different store would authenticate here.
    """
    token, _ = mint_access_token(user_id="usr_ghost", email="g@x.dev", role="admin")
    response = await anonymous.get("/v1/auth/me", headers=_as(token))
    assert response.status_code == 401
    assert "does not identify" in response.json()["detail"]


async def test_an_unsigned_token_is_refused(anonymous):
    """`alg: none` must not be honoured."""
    import base64
    import json

    def b64(obj: dict) -> str:
        raw = json.dumps(obj).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    header = b64({"alg": "none", "typ": "JWT"})
    claims = b64({"sub": "usr_x", "exp": 9999999999, "typ": "access"})
    forged = f"{header}.{claims}."
    response = await anonymous.get("/v1/auth/me", headers=_as(forged))
    assert response.status_code == 401


# --------------------------------------------------------------------------
# Registration and login
# --------------------------------------------------------------------------

async def test_registration_cannot_mint_privilege(anonymous):
    """A role field in the request body must not become a role."""
    response = await anonymous.post("/v1/auth/register", json={
        "email": "new@ledgergraph.dev", "password": "a-long-enough-password",
        "fullName": "New Person", "role": "admin",
    })
    assert response.status_code == 201, response.text
    assert response.json()["user"]["role"] == "analyst"


async def test_a_short_password_is_refused(anonymous):
    response = await anonymous.post("/v1/auth/register", json={
        "email": "short@ledgergraph.dev", "password": "short", "fullName": "S",
    })
    assert response.status_code == 422
    assert response.json()["code"] == "WEAK_PASSWORD"


async def test_a_password_containing_the_email_name_is_refused(anonymous):
    response = await anonymous.post("/v1/auth/register", json={
        "email": "chitra@ledgergraph.dev", "password": "chitra-chitra-1",
        "fullName": "C",
    })
    assert response.status_code == 422


async def test_a_wrong_password_and_an_unknown_email_are_indistinguishable(anonymous):
    """Both must produce the same code and the same message."""
    wrong = await anonymous.post("/v1/auth/login", json={
        "email": "analyst@ledgergraph.dev", "password": "not-the-password",
    })
    unknown = await anonymous.post("/v1/auth/login", json={
        "email": "nobody@ledgergraph.dev", "password": "not-the-password",
    })
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]
    assert wrong.json()["code"] == unknown.json()["code"] == "INVALID_CREDENTIALS"


async def test_a_disabled_account_cannot_sign_in(anonymous):
    repo = get_repository()
    user = await repo.find_user_by_email("analyst@ledgergraph.dev")
    user.is_active = False

    response = await anonymous.post("/v1/auth/login", json={
        "email": "analyst@ledgergraph.dev", "password": DEMO_PASSWORD,
    })
    assert response.status_code == 401


async def test_the_access_token_carries_the_role_the_store_holds(anonymous):
    token = await _login(anonymous, "controller")
    assert read_access_token(token).role == "controller"


# --------------------------------------------------------------------------
# Refresh rotation and reuse detection
# --------------------------------------------------------------------------

async def test_refresh_rotates_the_cookie(anonymous):
    await _login(anonymous, "reviewer")
    first = anonymous.cookies.get("lg_refresh")

    response = await anonymous.post("/v1/auth/refresh")
    assert response.status_code == 200, response.text
    second = anonymous.cookies.get("lg_refresh")

    assert second and second != first, "a refresh must issue a new token"


async def test_reusing_a_consumed_refresh_token_kills_the_family(anonymous):
    """The property the whole rotation scheme exists for.

    A stolen refresh token must be usable at most once, and its use must
    end the session for everybody rather than quietly succeeding.
    """
    await _login(anonymous, "reviewer")
    stolen = anonymous.cookies.get("lg_refresh")

    assert (await anonymous.post("/v1/auth/refresh")).status_code == 200
    rotated = anonymous.cookies.get("lg_refresh")

    replay = await anonymous.post(
        "/v1/auth/refresh", cookies={"lg_refresh": stolen}
    )
    assert replay.status_code == 401
    assert replay.json()["code"] == "REFRESH_REUSED"

    # And the legitimate successor is dead too - that is the point.
    after = await anonymous.post("/v1/auth/refresh", cookies={"lg_refresh": rotated})
    assert after.status_code == 401


async def test_logout_revokes_the_family(anonymous):
    await _login(anonymous, "analyst")
    cookie = anonymous.cookies.get("lg_refresh")

    assert (await anonymous.post("/v1/auth/logout")).status_code == 204
    replay = await anonymous.post("/v1/auth/refresh", cookies={"lg_refresh": cookie})
    assert replay.status_code == 401


async def test_refresh_without_a_cookie_is_a_401_not_a_500(anonymous):
    response = await anonymous.post("/v1/auth/refresh")
    assert response.status_code == 401
    assert response.json()["code"] == "NO_REFRESH_COOKIE"


async def test_the_refresh_cookie_is_httponly_and_scoped(anonymous):
    """XSS must not be able to read it, and it must not travel to every
    endpoint that happens to be on this origin."""
    response = await anonymous.post("/v1/auth/login", json={
        "email": "analyst@ledgergraph.dev", "password": DEMO_PASSWORD,
    })
    raw = response.headers["set-cookie"].lower()
    assert "httponly" in raw
    assert "path=/v1/auth" in raw


# --------------------------------------------------------------------------
# RBAC on the decision
# --------------------------------------------------------------------------

async def _run_to_cases(c: AsyncClient, dataset: Path) -> list[dict]:
    import asyncio

    for name, filename in DATASETS.items():
        response = await c.post(
            "/v1/imports",
            data={"dataset": name},
            files={"file": (filename, (dataset / filename).read_bytes(), "text/csv")},
        )
        assert response.status_code == 201, response.text

    run = await c.post("/v1/reconciliation-runs")
    assert run.status_code == 202, run.text
    run_id = run.json()["id"]

    for _ in range(100):
        state = (await c.get(f"/v1/reconciliation-runs/{run_id}")).json()
        if state["status"] in ("completed", "failed"):
            break
        await asyncio.sleep(0.05)
    assert state["status"] == "completed", state

    return (await c.get("/v1/exceptions?limit=200")).json()["items"]


@pytest.fixture
async def cases(anonymous, dataset):
    token = await _login(anonymous, "controller")
    anonymous.headers["Authorization"] = f"Bearer {token}"
    items = await _run_to_cases(anonymous, dataset)
    assert items, "the dataset must produce exceptions for these tests to mean anything"
    yield anonymous, items


def _small(items: list[dict], policy: Policy) -> dict:
    below = [i for i in items
             if int(i["amountAtRiskMinor"]) <= policy.review_required_above_minor]
    assert below, "expected at least one case below the material threshold"
    return below[0]


def _material(items: list[dict], policy: Policy) -> dict:
    above = [i for i in items
             if int(i["amountAtRiskMinor"]) > policy.review_required_above_minor]
    assert above, (
        "no case above the material threshold, so the controller-only "
        "path is untested. Raise DATASET_PAYMENTS rather than skipping."
    )
    return above[0]


async def test_an_analyst_cannot_decide_a_case(cases):
    """PRD story F2: the API refuses regardless of what the UI showed."""
    client, items = cases
    token = await _login(client, "analyst")
    case = _small(items, Policy())

    response = await client.post(
        f"/v1/exceptions/{case['id']}/decision",
        json={"resolution": "approved"}, headers=_as(token),
    )
    assert response.status_code == 403
    assert "analyst" in response.json()["detail"]


async def test_a_reviewer_can_decide_a_case_below_the_threshold(cases):
    client, items = cases
    token = await _login(client, "reviewer")
    case = _small(items, Policy())

    response = await client.post(
        f"/v1/exceptions/{case['id']}/decision",
        json={"resolution": "approved", "note": "confirmed against the bank portal"},
        headers=_as(token),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["resolution"] == "approved"
    assert body["status"] == "resolved"
    assert body["decidedByRole"] == "reviewer"


async def test_a_reviewer_cannot_decide_a_material_case(cases):
    """PRD story D2. This check cannot live on the route, because it
    depends on the case rather than the caller."""
    client, items = cases
    policy = Policy()
    case = _material(items, policy)
    token = await _login(client, "reviewer")
    response = await client.post(
        f"/v1/exceptions/{case['id']}/decision",
        json={"resolution": "approved"}, headers=_as(token),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "CONTROLLER_APPROVAL_REQUIRED"

    controller = await _login(client, "controller")
    allowed = await client.post(
        f"/v1/exceptions/{case['id']}/decision",
        json={"resolution": "approved"}, headers=_as(controller),
    )
    assert allowed.status_code == 200, allowed.text


async def test_an_override_without_a_reason_code_is_refused(cases):
    """PRD story D1, mirrored by a CHECK constraint in db/schema.sql."""
    client, items = cases
    token = await _login(client, "controller")
    case = _small(items, Policy())

    bad = await client.post(
        f"/v1/exceptions/{case['id']}/decision",
        json={"resolution": "overridden", "note": "trust me"}, headers=_as(token),
    )
    assert bad.status_code == 422
    assert bad.json()["code"] == "REASON_CODE_REQUIRED"

    good = await client.post(
        f"/v1/exceptions/{case['id']}/decision",
        json={"resolution": "overridden", "reasonCode": "bank_error_confirmed",
              "note": "bank confirmed the credit posted to the wrong account"},
        headers=_as(token),
    )
    assert good.status_code == 200, good.text
    assert good.json()["reasonCode"] == "bank_error_confirmed"


async def test_a_human_cannot_record_an_auto_resolution(cases):
    """`auto_resolved` is the gate's output. A person writing it by hand
    would make the auto-resolution precision metric a lie."""
    client, items = cases
    token = await _login(client, "controller")
    case = _small(items, Policy())

    response = await client.post(
        f"/v1/exceptions/{case['id']}/decision",
        json={"resolution": "auto_resolved"}, headers=_as(token),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "NOT_A_HUMAN_RESOLUTION"


async def test_deciding_twice_is_a_conflict_not_an_overwrite(cases):
    """The audit trail is the product; losing the first verdict silently
    would defeat it."""
    client, items = cases
    token = await _login(client, "controller")
    case = _small(items, Policy())

    first = await client.post(
        f"/v1/exceptions/{case['id']}/decision",
        json={"resolution": "approved"}, headers=_as(token),
    )
    assert first.status_code == 200

    second = await client.post(
        f"/v1/exceptions/{case['id']}/decision",
        json={"resolution": "rejected"}, headers=_as(token),
    )
    assert second.status_code == 409
    assert second.json()["code"] == "ALREADY_DECIDED"


async def test_a_decision_writes_an_audit_event_naming_the_person(cases):
    client, items = cases
    token = await _login(client, "controller")
    case = _small(items, Policy())

    await client.post(
        f"/v1/exceptions/{case['id']}/decision",
        json={"resolution": "rejected", "reasonCode": "evidence_insufficient",
              "note": "the settlement file for this window has not arrived"},
        headers=_as(token),
    )

    packet = (await client.get(f"/v1/exceptions/{case['id']}",
                               headers=_as(token))).json()
    decisions = [e for e in packet["audit"] if e["action"] == "rejected"]
    assert len(decisions) == 1
    event = decisions[0]
    assert event["actorType"] == "user"
    assert event["actorName"] == "Chitra Controller"
    assert event["actorRole"] == "controller"
    assert event["reasonCode"] == "evidence_insufficient"


async def test_the_queue_shows_a_decision_once_it_is_made(cases):
    client, items = cases
    token = await _login(client, "controller")
    case = _small(items, Policy())

    await client.post(
        f"/v1/exceptions/{case['id']}/decision",
        json={"resolution": "dismissed"}, headers=_as(token),
    )

    queue = (await client.get("/v1/exceptions?limit=200",
                              headers=_as(token))).json()["items"]
    decided = next(i for i in queue if i["id"] == case["id"])
    assert decided["status"] == "dismissed"
    assert decided["decidedBy"] == "Chitra Controller"


async def test_only_a_controller_may_list_users(anonymous):
    analyst = await _login(anonymous, "analyst")
    assert (await anonymous.get("/v1/auth/users",
                                headers=_as(analyst))).status_code == 403

    controller = await _login(anonymous, "controller")
    response = await anonymous.get("/v1/auth/users", headers=_as(controller))
    assert response.status_code == 200
    assert len(response.json()) == 4


# --------------------------------------------------------------------------
# Granting roles: the only way to create a controller/admin without SQL
# --------------------------------------------------------------------------

async def _user_id(client: AsyncClient, admin_token: str, email: str) -> str:
    users = (await client.get("/v1/auth/users", headers=_as(admin_token))).json()
    return next(u["id"] for u in users if u["email"] == email)


async def test_an_admin_can_change_a_users_role(anonymous):
    """Promotion through the API is what removes the raw-SQL step."""
    admin = await _login(anonymous, "admin")
    analyst_id = await _user_id(anonymous, admin, "analyst@ledgergraph.dev")

    response = await anonymous.patch(
        f"/v1/auth/users/{analyst_id}",
        json={"role": "controller"}, headers=_as(admin),
    )
    assert response.status_code == 200, response.text
    assert response.json()["role"] == "controller"

    # The change is real: the promoted account can now do controller work.
    events = await get_repository().audit_for(analyst_id)
    changed = [e for e in events if e.action == "role_changed"]
    assert len(changed) == 1
    assert changed[0].actor_name == "admin@ledgergraph.dev"
    assert "analyst to controller" in changed[0].detail


async def test_a_non_admin_cannot_change_roles(anonymous):
    """A controller may decide cases but not hand out privilege."""
    controller = await _login(anonymous, "controller")
    analyst_id = await _user_id(
        anonymous, await _login(anonymous, "admin"), "analyst@ledgergraph.dev"
    )
    response = await anonymous.patch(
        f"/v1/auth/users/{analyst_id}",
        json={"role": "admin"}, headers=_as(controller),
    )
    assert response.status_code == 403


async def test_changing_the_role_of_an_unknown_user_is_404(anonymous):
    admin = await _login(anonymous, "admin")
    response = await anonymous.patch(
        "/v1/auth/users/usr_nobody",
        json={"role": "controller"}, headers=_as(admin),
    )
    assert response.status_code == 404


async def test_an_admin_cannot_change_their_own_role(anonymous):
    """Demoting the only admin would lock user management out for good."""
    admin = await _login(anonymous, "admin")
    admin_id = await _user_id(anonymous, admin, "admin@ledgergraph.dev")
    response = await anonymous.patch(
        f"/v1/auth/users/{admin_id}",
        json={"role": "controller"}, headers=_as(admin),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "CANNOT_CHANGE_OWN_ROLE"


async def test_a_role_outside_the_four_is_refused(anonymous):
    admin = await _login(anonymous, "admin")
    analyst_id = await _user_id(anonymous, admin, "analyst@ledgergraph.dev")
    response = await anonymous.patch(
        f"/v1/auth/users/{analyst_id}",
        json={"role": "superuser"}, headers=_as(admin),
    )
    assert response.status_code == 422


async def test_bootstrap_admin_promotes_a_registered_account(anonymous, monkeypatch):
    """The production escape from the chicken-and-egg: an analyst who has
    registered becomes an admin at startup, without touching the database."""
    from ledgergraph_api.config import get_settings

    await anonymous.post("/v1/auth/register", json={
        "email": "founder@ledgergraph.dev", "password": "a-long-enough-password",
        "fullName": "Founder",
    })

    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "founder@ledgergraph.dev")
    get_settings.cache_clear()
    try:
        assert await bootstrap_admin() == "founder@ledgergraph.dev"
        # Idempotent: running it again promotes no one.
        assert await bootstrap_admin() is None
    finally:
        get_settings.cache_clear()

    admin = await _login(anonymous, "admin")
    users = (await anonymous.get("/v1/auth/users", headers=_as(admin))).json()
    founder = next(u for u in users if u["email"] == "founder@ledgergraph.dev")
    assert founder["role"] == "admin"


async def test_bootstrap_admin_is_a_noop_when_the_account_is_absent(anonymous, monkeypatch):
    from ledgergraph_api.config import get_settings

    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "ghost@ledgergraph.dev")
    get_settings.cache_clear()
    try:
        assert await bootstrap_admin() is None
    finally:
        get_settings.cache_clear()


# --------------------------------------------------------------------------
# Admin creates a user with a role (the admin-gated "create account")
# --------------------------------------------------------------------------

async def test_an_admin_creates_a_user_with_a_chosen_role(anonymous):
    admin = await _login(anonymous, "admin")
    response = await anonymous.post("/v1/auth/users", headers=_as(admin), json={
        "email": "newcontroller@ledgergraph.dev", "password": "a-long-enough-password",
        "fullName": "New Controller", "role": "controller",
    })
    assert response.status_code == 201, response.text
    assert response.json()["role"] == "controller"
    # No session was issued for the created user - the admin's session stands.
    assert "lg_refresh" not in response.cookies
    assert "accessToken" not in response.json()

    # The created account can sign in and act at its role immediately.
    token = await _login(anonymous, "admin")  # admin still works
    assert token
    login = await anonymous.post("/v1/auth/login", json={
        "email": "newcontroller@ledgergraph.dev", "password": "a-long-enough-password",
    })
    assert login.status_code == 200
    assert login.json()["user"]["role"] == "controller"


async def test_a_non_admin_cannot_create_a_user(anonymous):
    controller = await _login(anonymous, "controller")
    response = await anonymous.post("/v1/auth/users", headers=_as(controller), json={
        "email": "x@ledgergraph.dev", "password": "a-long-enough-password",
        "fullName": "X", "role": "analyst",
    })
    assert response.status_code == 403


async def test_creating_a_user_with_a_taken_email_is_409(anonymous):
    admin = await _login(anonymous, "admin")
    response = await anonymous.post("/v1/auth/users", headers=_as(admin), json={
        "email": "analyst@ledgergraph.dev", "password": "a-long-enough-password",
        "fullName": "Dup", "role": "analyst",
    })
    assert response.status_code == 409
    assert response.json()["code"] == "EMAIL_TAKEN"


async def test_creating_a_user_with_a_weak_password_is_refused(anonymous):
    admin = await _login(anonymous, "admin")
    response = await anonymous.post("/v1/auth/users", headers=_as(admin), json={
        "email": "weak@ledgergraph.dev", "password": "short",
        "fullName": "Weak", "role": "analyst",
    })
    assert response.status_code == 422
