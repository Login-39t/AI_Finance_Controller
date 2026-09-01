"""Python enums must match db/schema.sql exactly.

This is the test that earns its place. The Python enums and the SQL
`CREATE TYPE` declarations are two copies of the same vocabulary, and
nothing at runtime forces them to agree - a value added to one and not
the other surfaces as a failed INSERT deep inside a reconciliation run,
which is a terrible place to discover a typo.

Parsing the actual SQL file rather than restating the values here is the
point: a duplicated list would drift the same way.
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path

import pytest
from ledgergraph_domain.enums import SQL_TYPE_NAMES

SCHEMA = Path(__file__).resolve().parents[2] / "db" / "schema.sql"

_CREATE_TYPE = re.compile(
    r"CREATE\s+TYPE\s+(\w+)\s+AS\s+ENUM\s*\((.*?)\);",
    re.IGNORECASE | re.DOTALL,
)
_VALUE = re.compile(r"'([^']+)'")


def _sql_enums() -> dict[str, list[str]]:
    sql = SCHEMA.read_text(encoding="utf-8")
    return {
        name.lower(): _VALUE.findall(body)
        for name, body in _CREATE_TYPE.findall(sql)
    }


def test_schema_file_is_present_and_parseable():
    assert SCHEMA.exists(), f"db/schema.sql not found at {SCHEMA}"
    parsed = _sql_enums()
    assert len(parsed) >= 19, f"only parsed {len(parsed)} enum types, expected 19+"


@pytest.mark.parametrize(
    ("py_enum", "sql_name"),
    list(SQL_TYPE_NAMES.items()),
    ids=[name for name in SQL_TYPE_NAMES.values()],
)
def test_python_enum_matches_sql_type(py_enum: type[Enum], sql_name: str):
    sql_values = _sql_enums().get(sql_name)
    assert sql_values is not None, f"db/schema.sql has no CREATE TYPE {sql_name}"

    py_values = [m.value for m in py_enum]

    missing_in_python = set(sql_values) - set(py_values)
    missing_in_sql = set(py_values) - set(sql_values)

    assert not missing_in_python, (
        f"{sql_name}: in SQL but not in {py_enum.__name__}: {sorted(missing_in_python)}"
    )
    assert not missing_in_sql, (
        f"{sql_name}: in {py_enum.__name__} but not in SQL: {sorted(missing_in_sql)}"
    )
    # Order matters for a Postgres enum (it defines sort order), so pin it.
    assert py_values == sql_values, (
        f"{sql_name}: same values, different order.\n  SQL: {sql_values}\n  Py:  {py_values}"
    )


def test_every_sql_enum_has_a_python_counterpart():
    """Catches the other direction: a type added to the schema and never
    mirrored into Python."""
    mapped = set(SQL_TYPE_NAMES.values())
    unmapped = set(_sql_enums()) - mapped
    assert not unmapped, (
        f"db/schema.sql declares enum types with no Python counterpart: {sorted(unmapped)}"
    )


def test_exception_type_has_exactly_the_eight_from_the_taxonomy():
    """The AI's classification field validates against this set, so its
    size is a load-bearing fact rather than an incidental one."""
    from ledgergraph_domain.enums import ExceptionType

    assert len(list(ExceptionType)) == 8


def test_enum_members_compare_equal_to_plain_strings():
    """Normalisers, CSV cells, and JSON bodies all traffic in `str`."""
    from ledgergraph_domain.enums import TxnStatus

    assert TxnStatus.CAPTURED == "captured"
    # Reversed on purpose: the point is that comparison works from either
    # side, so this is not a redundant restatement of the line above.
    assert "captured" == TxnStatus.CAPTURED  # noqa: SIM300
    assert TxnStatus("captured") is TxnStatus.CAPTURED
    # StrEnum also makes str() return the value, which is what keeps log
    # lines and CSV writes from emitting "TxnStatus.CAPTURED".
    assert str(TxnStatus.CAPTURED) == "captured"
    assert f"{TxnStatus.CAPTURED}" == "captured"
