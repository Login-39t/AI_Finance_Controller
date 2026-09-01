"""Settings validation.

The rule these tests protect: a misconfigured AI provider must stop the
process at startup, not surface as a failed call in front of an audience.
The inverse matters just as much - AI is optional, so a missing key with
`AI_ENABLED=false` must boot cleanly.
"""

from __future__ import annotations

import pytest
from ledgergraph_api.config import Settings

SECRET = "x" * 40


def _settings(**overrides) -> Settings:
    base = {"jwt_secret": SECRET}
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# AI is optional
# --------------------------------------------------------------------------

def test_boots_without_any_ai_key_when_ai_is_disabled():
    """Today's default state. The engine is fully functional without a
    model, and every deterministic finding stands on its own."""
    s = _settings(ai_enabled=False, ai_api_key=None)
    assert s.ai_enabled is False


def test_default_provider_is_a_free_tier_one():
    s = _settings()
    assert s.ai_provider == "gemini"
    assert s.ai_model.startswith("gemini-")


# --------------------------------------------------------------------------
# A hosted provider without a key must fail at startup
# --------------------------------------------------------------------------

@pytest.mark.parametrize("provider", ["gemini", "groq", "openai_compatible"])
def test_hosted_provider_requires_a_key_when_enabled(provider):
    with pytest.raises(ValueError) as exc:
        _settings(ai_enabled=True, ai_provider=provider, ai_api_key=None)
    assert "AI_API_KEY" in str(exc.value)


@pytest.mark.parametrize("provider", ["gemini", "groq", "openai_compatible"])
def test_hosted_provider_accepts_a_key(provider):
    s = _settings(ai_enabled=True, ai_provider=provider, ai_api_key="sk-test")
    assert s.ai_provider == provider


def test_ollama_needs_no_key_because_it_runs_locally():
    s = _settings(ai_enabled=True, ai_provider="ollama", ai_api_key=None)
    assert s.ai_provider == "ollama"


# --------------------------------------------------------------------------
# Typos fail loudly rather than silently selecting a default
# --------------------------------------------------------------------------

@pytest.mark.parametrize("provider", ["bedrock", "anthropic", "grok", "openai", ""])
def test_unknown_provider_is_rejected(provider):
    """A Literal, not a free-text string. `grok` (xAI) and `groq` are
    different companies and one character apart, so a typo here must be a
    startup error rather than a silent fallback."""
    with pytest.raises(ValueError):
        _settings(ai_provider=provider)


# --------------------------------------------------------------------------
# Non-AI invariants worth pinning
# --------------------------------------------------------------------------

def test_jwt_secret_has_a_minimum_length():
    with pytest.raises(ValueError):
        Settings(jwt_secret="short")  # type: ignore[arg-type]


def test_cors_origin_defaults_to_the_local_frontend():
    assert _settings().frontend_origin == "http://localhost:3000"


def test_business_defaults_are_indian():
    s = _settings()
    assert s.business_timezone == "Asia/Kolkata"
    assert s.base_currency == "INR"
