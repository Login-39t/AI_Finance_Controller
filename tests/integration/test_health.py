"""Health and error-contract tests.

These run against the real ASGI app with no network and no database, so
they stay fast and they verify the thing that actually matters at this
stage: the service boots, reports its own state honestly, and speaks
problem+json when something goes wrong.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from ledgergraph_api.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_liveness_does_not_touch_the_database(client):
    """A database outage must not make the platform kill a healthy process."""
    r = await client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["environment"] == "local"
    assert body["rulesetVersion"].startswith("rules@")


@pytest.mark.asyncio
async def test_readiness_reports_degraded_when_the_database_is_unreachable(client):
    """There is no Postgres in this environment, so readiness must say so.

    The point of the endpoint is to name the failing dependency, not to
    hide it behind a 500 or, worse, report ready anyway.
    """
    r = await client.get("/readyz")
    assert r.status_code in (200, 503)
    body = r.json()
    db = body["checks"]["database"]

    if db["reachable"]:
        assert r.status_code == 200
        assert body["status"] == "ready"
    else:
        assert r.status_code == 503
        assert body["status"] == "degraded"
        assert db["error"], "an unreachable database must explain why"


@pytest.mark.asyncio
async def test_readyz_reports_whether_ai_is_configured(client, monkeypatch):
    """Both states, forced - not whichever one `.env` happens to hold.

    This test used to assert `enabled is False`, which passed only while
    the developer's own `.env` had AI switched off. Turning it on broke a
    test that had nothing to do with the change: the suite was reading
    ambient configuration, so it was reporting the machine's state rather
    than the code's behaviour.
    """
    from ledgergraph_api.config import get_settings

    for enabled in (False, True):
        get_settings.cache_clear()
        monkeypatch.setenv("AI_ENABLED", "true" if enabled else "false")
        monkeypatch.setenv("AI_API_KEY", "test-key-not-used")
        try:
            r = await client.get("/readyz")
            assert r.json()["checks"]["ai"]["enabled"] is enabled
        finally:
            get_settings.cache_clear()


@pytest.mark.asyncio
async def test_unknown_route_returns_problem_json_with_a_stable_code(client):
    r = await client.get("/v1/does-not-exist")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["code"] == "NOT_FOUND"
    assert body["status"] == 404
    assert body["instance"] == "/v1/does-not-exist"


@pytest.mark.asyncio
async def test_openapi_is_served(client):
    """The frontend generates its types from this document."""
    r = await client.get("/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    assert spec["info"]["title"] == "TallyProof API"
    assert "/healthz" in spec["paths"]


@pytest.mark.asyncio
async def test_cors_allows_the_configured_origin_with_credentials(client):
    """Cross-site cookies need an exact origin; a wildcard is ignored."""
    r = await client.options(
        "/healthz",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.status_code in (200, 204)
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert r.headers["access-control-allow-credentials"] == "true"


@pytest.mark.asyncio
async def test_cors_rejects_an_unconfigured_origin(client):
    r = await client.options(
        "/healthz",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.headers.get("access-control-allow-origin") != "https://evil.example"
