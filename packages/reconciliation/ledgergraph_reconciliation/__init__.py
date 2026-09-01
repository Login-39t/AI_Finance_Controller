"""Matching rules, grouping, bridge arithmetic, exception detection, and
the auto-resolution gate.

Framework-free by construction: imports nothing from `backend/` or
`frontend/`, so the evaluation harness can run the real engine without an
HTTP server, a database, or an event loop. That constraint is what keeps
the held-out metrics honest.
"""

from .engine import RULESET_VERSION, execute
from .models import Bridge, Evidence, ExceptionCase, MatchGroup, RunResult
from .policy import Policy, apply_gate, evaluate_gate, requires_controller

__all__ = [
    "RULESET_VERSION",
    "Bridge",
    "Evidence",
    "ExceptionCase",
    "MatchGroup",
    "Policy",
    "RunResult",
    "apply_gate",
    "evaluate_gate",
    "execute",
    "requires_controller",
]
