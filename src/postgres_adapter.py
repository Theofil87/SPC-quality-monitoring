"""PostgreSQL adapter feeding ordered table streams to the streaming comparator."""

from __future__ import annotations

from collections.abc import Callable, Generator, Sequence
from contextlib import ExitStack, closing
from typing import Any

from sqlalchemy import MetaData, Table, and_, collate, func, literal_column, or_, select
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.engine import Engine
from sqlalchemy.exc import NoSuchTableError
from sqlalchemy.sql import sqltypes

from src.migration_validator import (
    StreamComparisonReport,
    StreamDifference,
    _primary_key_columns,
    compare_record_streams,
)

# Key types whose PostgreSQL ordering and equality match Python's for the
# values the comparator normalizes. Anything else (CHAR(n), CITEXT, "char",
# name, enums, UUID, intervals, timetz, ...) is rejected.
_ORDERABLE_KEY_TYPES = (
    sqltypes.Boolean,
    sqltypes.Integer,
    sqltypes.Numeric,  # includes Float
    sqltypes.Date,
    sqltypes.DateTime,
    sqltypes.Time,
    sqltypes.LargeBinary,
)
# Text keys are ordered with COLLATE "C" (byte order). That equals Python's
# code point order only when the database encoding is UTF8, which is verified
# before reading. CHAR(n) ignores trailing spaces in comparisons and CITEXT is
# case-insensitive, so neither is accepted.
_TEXT_KEY_TYPES = (sqltypes.VARCHAR, sqltypes.Text)
_TEMPORAL_VALUES_SAFE_LABEL = "_spc_adapter_temporal_values_safe"
_PREFLIGHT_SQL = (
    "SELECT current_setting('server_encoding'), current_setting('transaction_read_only')"
)


def _is_text_key(column_type: object) -> bool:
    return isinstance(column_type, _TEXT_KEY_TYPES) and not isinstance(
        column_type, CITEXT
    )


def _is_supported_key(column_type: object) -> bool:
    if _is_text_key(column_type):
        return True
    if isinstance(column_type, sqltypes.Time) and column_type.timezone:
        return False
    return isinstance(column_type, _ORDERABLE_KEY_TYPES)


def _verify_session(connection: Any, has_text_key: bool) -> None:
    encoding, read_only = connection.exec_driver_sql(_PREFLIGHT_SQL).one()
    if str(read_only).lower() != "on":
        raise RuntimeError("connection is not in a read-only transaction")
    if has_text_key and str(encoding).upper().replace("-", "") != "UTF8":
        raise ValueError(
            f"text primary keys require a UTF8 database (server_encoding is {encoding!r}): "
            'COLLATE "C" order is not guaranteed to match Python ordering'
        )


def _validate_name(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _validate_positive_int(value: object, label: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _convert_value(value: object) -> object:
    # psycopg2 returns bytea as memoryview, which the comparator rejects.
    return bytes(value) if isinstance(value, memoryview) else value


def _temporal_value_is_lossless(column: Any) -> Any | None:
    if isinstance(column.type, (sqltypes.Date, sqltypes.DateTime)):
        return or_(column.is_(None), func.isfinite(column))
    if isinstance(column.type, sqltypes.Time) and not column.type.timezone:
        return or_(
            column.is_(None),
            column != literal_column("TIME '24:00:00'"),
        )
    return None


def _key_ordering(
    table: Table, key_columns: tuple[str, ...]
) -> tuple[list[Any], bool]:
    ordering: list[Any] = []
    has_text_key = False
    for name in key_columns:
        if name not in table.c:
            raise ValueError(f"primary key column {name!r} not found in {table.name!r}")
        column = table.c[name]
        if not _is_supported_key(column.type):
            raise ValueError(
                f"primary key column {name!r} has unsupported type {column.type!r}: "
                "its database ordering or equality may not match Python's"
            )
        if _is_text_key(column.type):
            has_text_key = True
            ordering.append(collate(column, "C").asc())
        else:
            ordering.append(column.asc())
    return ordering, has_text_key


def iter_table_records(
    engine: Engine,
    table: str,
    primary_key: str | Sequence[str],
    *,
    schema: str | None = None,
    columns: Sequence[str] | None = None,
    fetch_size: int = 1000,
) -> Generator[dict[str, object], None, None]:
    """Return a generator of table rows ordered by primary key.

    Arguments are validated eagerly; the connection opens on the first
    ``next()`` and is always released when the generator is exhausted, closed
    early or fails. Rows are fetched through a server-side cursor in chunks of
    ``fetch_size``. The read-only transaction is rolled back, never committed.
    Before reading, the session must be read-only; text keys additionally
    require ``server_encoding`` UTF8 (the only case where ``COLLATE "C"``
    matches Python ordering).
    """
    table_name = _validate_name(table, "table")
    if schema is not None:
        _validate_name(schema, "schema")
    key_columns = _primary_key_columns(primary_key)
    _validate_positive_int(fetch_size, "fetch_size")
    selected: tuple[str, ...] | None = None
    if columns is not None:
        selected = tuple(columns)
        if not selected or any(not isinstance(name, str) or not name for name in selected):
            raise ValueError("columns must contain non-empty column names")
        if len(set(selected)) != len(selected):
            raise ValueError("columns must be unique")
        if not set(key_columns).issubset(selected):
            raise ValueError("columns must include every primary key column")
    return _stream_rows(engine, table_name, key_columns, schema, selected, fetch_size)


def _stream_rows(
    engine: Engine,
    table_name: str,
    key_columns: tuple[str, ...],
    schema: str | None,
    selected: tuple[str, ...] | None,
    fetch_size: int,
) -> Generator[dict[str, object], None, None]:
    connection = engine.connect()
    try:
        connection = connection.execution_options(postgresql_readonly=True)
        try:
            reflected = Table(
                table_name, MetaData(), schema=schema, autoload_with=connection
            )
        except NoSuchTableError:
            raise ValueError(f"table {table_name!r} was not found") from None
        names = selected if selected is not None else tuple(reflected.c.keys())
        selected_names = frozenset(names)
        missing = [name for name in names if name not in reflected.c]
        if missing:
            raise ValueError(f"columns not found in {table_name!r}: {missing}")
        ordering, has_text_key = _key_ordering(reflected, key_columns)
        temporal_checks = [
            check
            for name in names
            if (check := _temporal_value_is_lossless(reflected.c[name])) is not None
        ]
        safe_label = _TEMPORAL_VALUES_SAFE_LABEL
        while safe_label in reflected.c:
            safe_label += "_"
        selected_columns = [reflected.c[name] for name in names]
        if temporal_checks:
            selected_columns.append(and_(*temporal_checks).label(safe_label))
        statement = (
            select(*selected_columns)
            .order_by(*ordering)
            .execution_options(stream_results=True, yield_per=fetch_size)
        )
        _verify_session(connection, has_text_key)
        result = connection.execute(statement)
        try:
            for row in result.mappings():
                if temporal_checks and row[safe_label] is not True:
                    raise ValueError(
                        f"table {table_name!r} contains a temporal value that "
                        "psycopg2 cannot represent without loss"
                    )
                yield {
                    name: _convert_value(value)
                    for name, value in row.items()
                    if name in selected_names
                }
        finally:
            result.close()
    finally:
        connection.close()


def compare_tables(
    source_engine: Engine,
    target_engine: Engine,
    table: str,
    primary_key: str | Sequence[str],
    *,
    schema: str | None = None,
    target_table: str | None = None,
    target_schema: str | None = None,
    columns: Sequence[str] | None = None,
    batch_size: int = 1000,
    max_samples: int = 10,
    on_difference: Callable[[StreamDifference], None] | None = None,
) -> StreamComparisonReport:
    """Compare a table of two PostgreSQL databases with bounded memory.

    ``batch_size`` is used both as the server-side fetch size and as the
    comparator batch size. Both row streams are closed on every exit path.
    ``target_schema=None`` inherits ``schema``; it does not select the target
    connection's default schema when ``schema`` is set.
    """
    source_rows = iter_table_records(
        source_engine, table, primary_key,
        schema=schema, columns=columns, fetch_size=batch_size,
    )
    target_rows = iter_table_records(
        target_engine, target_table if target_table is not None else table, primary_key,
        schema=target_schema if target_schema is not None else schema,
        columns=columns, fetch_size=batch_size,
    )
    with ExitStack() as stack:
        stack.enter_context(closing(source_rows))
        stack.enter_context(closing(target_rows))
        return compare_record_streams(
            source_rows, target_rows, primary_key,
            batch_size=batch_size, max_samples=max_samples, on_difference=on_difference,
        )
