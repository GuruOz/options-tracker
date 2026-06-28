"""Idempotency helpers for Alembic migrations.

The baseline migration (``0001_initial``) builds the *entire current* schema
from SQLAlchemy metadata via ``create_all``. That means a fresh database already
has every table/column/constraint the models define, so the later incremental
migrations (which exist to upgrade *old* databases) would otherwise collide with
objects that already exist (e.g. ``DuplicateColumnError``).

These helpers let each incremental migration apply its change only when it is
actually missing, so the same migration chain works for both a brand-new clone
and a long-lived database. Future incremental migrations should use them too.
"""
from alembic import op
import sqlalchemy as sa


def _inspector() -> sa.engine.reflection.Inspector:
    return sa.inspect(op.get_bind())


def has_table(table: str) -> bool:
    return table in _inspector().get_table_names()


def has_column(table: str, column: str) -> bool:
    if not has_table(table):
        return False
    return any(c["name"] == column for c in _inspector().get_columns(table))


def has_constraint(table: str, name: str) -> bool:
    if not has_table(table):
        return False
    insp = _inspector()
    names: set[str] = set()
    names.update(c["name"] for c in insp.get_unique_constraints(table))
    names.update(c["name"] for c in insp.get_foreign_keys(table) if c.get("name"))
    try:
        names.update(c["name"] for c in insp.get_check_constraints(table))
    except NotImplementedError:  # pragma: no cover - dialect dependent
        pass
    pk = insp.get_pk_constraint(table).get("name")
    if pk:
        names.add(pk)
    return name in names


def has_index(table: str, name: str) -> bool:
    if not has_table(table):
        return False
    return any(i["name"] == name for i in _inspector().get_indexes(table))
