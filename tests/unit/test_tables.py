"""The Core tables must not drift from `db/schema.sql`.

`tables.py` declares a deliberate *subset* of the schema's columns — only
what the repository reads or writes. A subset is fine; fiction is not. A
column renamed in the schema and not here produces an `UndefinedColumn`
at runtime, on the one code path that has no test coverage without a
database.

So both directions are checked against the parsed schema:

* every table named in `tables.py` exists in `db/schema.sql`;
* every column named in `tables.py` exists on that table;
* every enum type named in `tables.py` is declared by a `CREATE TYPE`.

And every statement the repository builds is compiled against the
PostgreSQL dialect, which is the closest thing to executing it that is
available without a server.
"""

from __future__ import annotations

from pathlib import Path

import pglast
import pytest
from ledgergraph_api import tables as t
from pglast import ast
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import ENUM

SCHEMA = Path(__file__).resolve().parents[2] / "db" / "schema.sql"


@pytest.fixture(scope="module")
def schema() -> tuple[dict[str, set[str]], set[str]]:
    """(table -> columns, enum type names), parsed from the SQL."""
    statements = pglast.parse_sql(SCHEMA.read_text(encoding="utf-8"))

    tables: dict[str, set[str]] = {}
    enums: set[str] = set()
    for wrapper in statements:
        stmt = wrapper.stmt
        if isinstance(stmt, ast.CreateStmt):
            tables[stmt.relation.relname] = {
                element.colname
                for element in (stmt.tableElts or ())
                if isinstance(element, ast.ColumnDef)
            }
        elif isinstance(stmt, ast.CreateEnumStmt):
            enums.add(stmt.typeName[-1].sval)
    return tables, enums


def _declared_tables() -> list:
    return list(t.metadata.tables.values())


@pytest.mark.parametrize("table", _declared_tables(), ids=lambda tb: tb.name)
def test_every_declared_table_and_column_exists_in_the_schema(table, schema):
    schema_tables, _ = schema

    assert table.name in schema_tables, (
        f"tables.py declares {table.name!r}, which db/schema.sql does not create"
    )

    missing = {c.name for c in table.columns} - schema_tables[table.name]
    assert not missing, (
        f"{table.name}: tables.py declares columns the schema does not have: "
        f"{sorted(missing)}"
    )


def test_every_declared_enum_type_is_created_by_the_schema(schema):
    _, schema_enums = schema

    problems: list[str] = []
    for table in _declared_tables():
        for column in table.columns:
            type_ = column.type
            # ARRAY(ENUM(...)) - reach through to the element type.
            inner = getattr(type_, "item_type", None)
            for candidate in (type_, inner):
                if isinstance(candidate, ENUM) and candidate.name not in schema_enums:
                    problems.append(
                        f"{table.name}.{column.name} uses enum {candidate.name!r}, "
                        f"which db/schema.sql never creates"
                    )
    assert not problems, "\n".join(problems)


def test_no_table_is_configured_to_create_its_own_enum_types():
    """`create_type=True` (the default) makes every insert attempt a
    `CREATE TYPE` the schema already ran, and fail."""
    offenders = [
        f"{table.name}.{column.name}"
        for table in _declared_tables()
        for column in table.columns
        if isinstance(column.type, ENUM) and column.type.create_type
    ]
    assert not offenders, (
        "these enum columns would try to re-create their type: " + ", ".join(offenders)
    )


def test_the_metadata_is_never_used_to_create_tables():
    """`db/schema.sql` is the source of truth.

    `metadata.create_all()` would produce tables *without* the triggers,
    partial indexes and CHECK expressions the SQL file carries - the same
    table names holding none of the guarantees, which is worse than no
    tables at all.
    """
    import ast

    source = (
        Path(__file__).resolve().parents[2]
        / "backend" / "src" / "ledgergraph_api"
    )
    # Parsed, not grepped. A substring search matches the sentence above
    # explaining that this is never called, so it would fail on its own
    # documentation - a test that cannot distinguish a call from a
    # comment is not checking what it claims to.
    for path in source.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"create_all", "drop_all"}
        ]
        assert not calls, f"{path.name} calls {calls[0].func.attr}() at line {calls[0].lineno}"


# --------------------------------------------------------------------------
# The queries themselves
# --------------------------------------------------------------------------

def test_every_repository_statement_compiles_against_postgres():
    """Compilation is the closest thing to execution available here.

    It resolves every column reference against the table definitions
    above - which the tests above tie to the real schema - so a typo in a
    column name fails here rather than as an `UndefinedColumn` on the one
    path no test can otherwise reach.
    """
    from ledgergraph_api.store_postgres import statements_for_compilation

    dialect = postgresql.dialect()
    for label, statement in statements_for_compilation().items():
        try:
            compiled = str(statement.compile(dialect=dialect))
        except Exception as exc:  # noqa: BLE001 - the failure is the result
            pytest.fail(f"{label} does not compile: {type(exc).__name__}: {exc}")
        assert compiled.strip(), f"{label} compiled to nothing"


def test_the_queue_query_orders_by_money_descending():
    """The queue's contract with the analyst, asserted against the SQL.

    A default that put cheap problems first would waste the scarcest
    thing in the system, and it is the kind of change that looks harmless
    in a diff.
    """
    from ledgergraph_api.store_postgres import statements_for_compilation

    sql = str(
        statements_for_compilation()["cases_for_run"]
        .compile(dialect=postgresql.dialect())
    )
    assert "amount_at_risk_minor DESC" in sql


def test_the_postgres_repository_satisfies_the_protocol():
    """Both implementations must offer the same surface.

    `Repository` is a `Protocol`, so nothing at import time checks that
    `PostgresRepository` actually implements it - a missing method
    surfaces as an `AttributeError` on whichever endpoint calls it first,
    in the deployment that is using Postgres and nowhere else.

    Signatures are compared too, not just names. A method that exists but
    takes different arguments is the same bug wearing a disguise.
    """
    import inspect

    from ledgergraph_api.store import InMemoryRepository, Repository
    from ledgergraph_api.store_postgres import PostgresRepository

    expected = {
        name for name in dir(Repository)
        if not name.startswith("_") and callable(getattr(Repository, name, None))
    }
    assert expected, "the protocol appears to declare no methods"

    missing = [n for n in sorted(expected) if not hasattr(PostgresRepository, n)]
    assert not missing, f"PostgresRepository is missing: {missing}"

    mismatched: list[str] = []
    for name in sorted(expected):
        reference = inspect.signature(getattr(InMemoryRepository, name))
        actual = inspect.signature(getattr(PostgresRepository, name))
        if list(reference.parameters) != list(actual.parameters):
            mismatched.append(
                f"{name}: in-memory{reference} vs postgres{actual}"
            )
    assert not mismatched, "\n".join(mismatched)


def test_both_implementations_are_async_throughout():
    """A synchronous database call inside an async handler blocks the
    event loop for every other request, which is invisible in
    development and fatal under load."""
    import inspect

    from ledgergraph_api.store import InMemoryRepository, Repository
    from ledgergraph_api.store_postgres import PostgresRepository

    names = {
        name for name in dir(Repository)
        if not name.startswith("_") and callable(getattr(Repository, name, None))
    }
    for implementation in (InMemoryRepository, PostgresRepository):
        blocking = [
            name for name in sorted(names)
            if not inspect.iscoroutinefunction(getattr(implementation, name))
        ]
        assert not blocking, (
            f"{implementation.__name__} has synchronous methods: {blocking}"
        )
