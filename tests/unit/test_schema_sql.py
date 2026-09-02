"""`db/schema.sql` is checked without a database.

There is no Postgres on this machine, so the schema has never been
executed. That is a real gap and it is stated plainly in the README - but
"unexecuted" does not have to mean "unverified".

`pglast` wraps `libpg_query`, which is **PostgreSQL's own parser** lifted
out of the server. Parsing with it is not an approximation of what
Postgres would say about this file; it is what Postgres says about this
file, minus execution. That catches every syntax error.

Syntax is not the whole risk, though. The errors that actually bite in a
hand-written schema are name errors: a foreign key pointing at a column
that was renamed, an index on a column that does not exist, a trigger
calling a function nobody defined. Those parse perfectly and fail at
`CREATE`. So the checks below resolve names across the file as well.

What this still cannot prove: that the file applies cleanly in order,
that the constraint triggers behave, and that the partial indexes are
usable. Only a real `make migrate` shows that. This narrows the gap; it
does not close it.
"""

from __future__ import annotations

from pathlib import Path

import pglast
import pytest
from pglast import ast

SCHEMA = Path(__file__).resolve().parents[2] / "db" / "schema.sql"


@pytest.fixture(scope="module")
def statements() -> tuple:
    return pglast.parse_sql(SCHEMA.read_text(encoding="utf-8"))


def _stmts_of(statements, kind) -> list:
    return [s.stmt for s in statements if isinstance(s.stmt, kind)]


def _table_name(relation) -> str:
    return relation.relname


@pytest.fixture(scope="module")
def tables(statements) -> dict[str, set[str]]:
    """table name -> its column names."""
    out: dict[str, set[str]] = {}
    for stmt in _stmts_of(statements, ast.CreateStmt):
        columns = {
            element.colname
            for element in (stmt.tableElts or ())
            if isinstance(element, ast.ColumnDef)
        }
        out[_table_name(stmt.relation)] = columns
    return out


@pytest.fixture(scope="module")
def enums(statements) -> set[str]:
    return {
        stmt.typeName[-1].sval
        for stmt in _stmts_of(statements, ast.CreateEnumStmt)
    }


# --------------------------------------------------------------------------
# Syntax
# --------------------------------------------------------------------------

def test_the_schema_parses_with_postgres_own_parser(statements):
    """If this fails, `make migrate` fails - there is no daylight between
    libpg_query and the server on syntax."""
    assert len(statements) >= 90, f"only {len(statements)} statements parsed"


def test_the_expected_objects_are_all_declared(tables, enums, statements):
    assert len(tables) >= 23, f"expected 23+ tables, found {len(tables)}: {sorted(tables)}"
    assert len(enums) >= 19, f"expected 19+ enum types, found {len(enums)}"
    views = _stmts_of(statements, ast.ViewStmt)
    assert views, "the schema declares no views"


# --------------------------------------------------------------------------
# Name resolution - the errors that parse fine and fail at CREATE
# --------------------------------------------------------------------------

def _column_constraints(stmt) -> list[tuple[str | None, ast.Constraint]]:
    """Every constraint in a CREATE TABLE, column-level and table-level."""
    found: list[tuple[str | None, ast.Constraint]] = []
    for element in stmt.tableElts or ():
        if isinstance(element, ast.ColumnDef):
            for constraint in element.constraints or ():
                found.append((element.colname, constraint))
        elif isinstance(element, ast.Constraint):
            found.append((None, element))
    return found


def test_every_foreign_key_points_at_a_table_and_column_that_exist(statements, tables):
    """A FK naming a renamed column parses and then fails at CREATE."""
    problems: list[str] = []

    for stmt in _stmts_of(statements, ast.CreateStmt):
        source = _table_name(stmt.relation)
        for _, constraint in _column_constraints(stmt):
            if constraint.contype != enum_fk():
                continue
            target = constraint.pktable.relname
            if target not in tables:
                problems.append(f"{source}: FK references unknown table {target!r}")
                continue
            referenced = [a.sval for a in (constraint.pk_attrs or ())]
            missing = [c for c in referenced if c not in tables[target]]
            if missing:
                problems.append(
                    f"{source}: FK references {target}({', '.join(missing)}) "
                    f"which does not exist"
                )

    assert not problems, "\n".join(problems)


def test_every_enum_typed_column_uses_a_declared_type(statements, enums):
    """A column typed with an enum nobody created is a CREATE-time failure."""
    builtin_prefixes = {
        "pg_catalog", "text", "int4", "int8", "bool", "timestamptz", "date",
        "numeric", "jsonb", "uuid", "bytea", "varchar", "bpchar", "float8",
        "int2", "time", "interval", "inet", "citext",
    }
    problems: list[str] = []

    for stmt in _stmts_of(statements, ast.CreateStmt):
        table = _table_name(stmt.relation)
        for element in stmt.tableElts or ():
            if not isinstance(element, ast.ColumnDef):
                continue
            names = [n.sval for n in element.typeName.names]
            leaf = names[-1]
            if leaf in builtin_prefixes or names[0] == "pg_catalog":
                continue
            if leaf not in enums:
                problems.append(
                    f"{table}.{element.colname} is typed {leaf!r}, "
                    f"which is neither a builtin nor a declared enum"
                )

    assert not problems, "\n".join(problems)


def test_every_index_is_on_a_table_and_columns_that_exist(statements, tables):
    problems: list[str] = []

    for stmt in _stmts_of(statements, ast.IndexStmt):
        table = _table_name(stmt.relation)
        if table not in tables:
            problems.append(f"index {stmt.idxname!r} is on unknown table {table!r}")
            continue
        for element in stmt.indexParams or ():
            # An expression index has no plain column name; skip those.
            if element.name is None:
                continue
            if element.name not in tables[table]:
                problems.append(
                    f"index {stmt.idxname!r} references {table}.{element.name}, "
                    f"which does not exist"
                )

    assert not problems, "\n".join(problems)


def test_every_trigger_calls_a_function_the_file_defines(statements):
    """A trigger naming a function that was never created fails at CREATE."""
    defined = {
        stmt.funcname[-1].sval
        for stmt in _stmts_of(statements, ast.CreateFunctionStmt)
    }
    problems = [
        f"trigger {stmt.trigname!r} calls {stmt.funcname[-1].sval}(), which is not defined here"
        for stmt in _stmts_of(statements, ast.CreateTrigStmt)
        if stmt.funcname[-1].sval not in defined
    ]
    assert not problems, "\n".join(problems)


# --------------------------------------------------------------------------
# The money rule, enforced against the schema itself
# --------------------------------------------------------------------------

def test_no_money_column_is_a_floating_point_type(statements):
    """The whole system's claim is that no float touches money.

    `money.py` enforces it in Python. This enforces it in the place that
    would silently undo it: a `double precision` column would convert
    every exact integer the API writes into an approximation, and nothing
    downstream would notice until a reconciliation was off by a paise.
    """
    float_types = {"float4", "float8", "real", "double"}
    problems: list[str] = []

    for stmt in _stmts_of(statements, ast.CreateStmt):
        table = _table_name(stmt.relation)
        for element in stmt.tableElts or ():
            if not isinstance(element, ast.ColumnDef):
                continue
            leaf = element.typeName.names[-1].sval
            if leaf in float_types:
                problems.append(f"{table}.{element.colname} is {leaf}")

    assert not problems, (
        "floating-point columns found:\n" + "\n".join(problems)
    )


def test_amount_columns_are_bigint_minor_units(statements):
    """Every `*_minor` column must be BIGINT.

    The naming convention is the contract - a column called `_minor` that
    is not an integer type is a lie the rest of the codebase believes.
    """
    problems: list[str] = []

    for stmt in _stmts_of(statements, ast.CreateStmt):
        table = _table_name(stmt.relation)
        for element in stmt.tableElts or ():
            if not isinstance(element, ast.ColumnDef):
                continue
            if not element.colname.endswith("_minor"):
                continue
            leaf = element.typeName.names[-1].sval
            if leaf not in {"int8", "int4"}:
                problems.append(f"{table}.{element.colname} is {leaf}, not an integer")

    assert not problems, "\n".join(problems)


def enum_fk():
    """`CONSTR_FOREIGN`, without importing the enum by a name that has
    moved between pglast versions."""
    from pglast.enums.parsenodes import ConstrType

    return ConstrType.CONSTR_FOREIGN
