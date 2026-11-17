"""Integration tests of the PostgreSQL adapter against a disposable PostgreSQL 17.

Skipped unless SPC_ADAPTER_IT_URL is set. The URL is accepted only for the
dedicated throwaway container (127.0.0.1:55417, database spc_adapter_integration).
All tables live in temporary schemas that are dropped even when a test fails.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from decimal import Decimal
import os
import time
import tracemalloc
import uuid

import pytest

sa = pytest.importorskip("sqlalchemy")
psycopg2 = pytest.importorskip("psycopg2")
from sqlalchemy import event, make_url  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from src.migration_validator import compare_records  # noqa: E402
from src.postgres_adapter import compare_tables, iter_table_records  # noqa: E402

DATABASE_URL = os.environ.get("SPC_ADAPTER_IT_URL")
ALLOWED_DATABASE = "spc_adapter_integration"
ALLOWED_PORT = 55417
ADAPTER_APP = "spc_adapter_it"
ADMIN_APP = "spc_adapter_it_admin"

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="SPC_ADAPTER_IT_URL is not set")

TEXT_KEYS = [
    "B", "a", "A", "Ab", "a-b", "ab", "ab ", " lead", "a b", "Z", "z", "_x", "-", "~",
    "Éa", "ea", "éa", "őr", "я", "日本", "😀",
]


def _url_error(url: str) -> str | None:
    parsed = make_url(url)
    if parsed.drivername != "postgresql+psycopg2" or parsed.query:
        return "must use plain postgresql+psycopg2 without query parameters"
    if parsed.host != "127.0.0.1" or parsed.port != ALLOWED_PORT:
        return f"must target 127.0.0.1:{ALLOWED_PORT}"
    if parsed.database != ALLOWED_DATABASE:
        return f"must target database {ALLOWED_DATABASE}"
    return None


def _engine(application_name: str, **extra_options):
    error = _url_error(DATABASE_URL)
    if error:
        pytest.fail(f"SPC_ADAPTER_IT_URL {error}; refusing to connect")
    options = "".join(f" -c {key}={value}" for key, value in extra_options.items())
    connect_args = {"hostaddr": "127.0.0.1", "application_name": application_name}
    if options:
        connect_args["options"] = options.strip()
    return sa.create_engine(DATABASE_URL, poolclass=NullPool, connect_args=connect_args)


@pytest.fixture(scope="module")
def admin():
    engine = _engine(ADMIN_APP).execution_options(isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        version = connection.exec_driver_sql("SHOW server_version_num").scalar()
        assert version.startswith("17"), f"expected PostgreSQL 17, got {version}"
        assert connection.exec_driver_sql("SHOW server_encoding").scalar() == "UTF8"
    yield engine
    engine.dispose()


@pytest.fixture
def schema(admin) -> Iterator[str]:
    name = f"it_{uuid.uuid4().hex[:10]}"
    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{name}"')
    try:
        yield name
    finally:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')


class Adapter:
    """Adapter-side engine that records every raw psycopg2 connection."""

    def __init__(self, **session_options):
        self.engine = _engine(ADAPTER_APP, **session_options)
        self.raw = []
        event.listen(self.engine, "connect", lambda dbapi, _: self.raw.append(dbapi))


@pytest.fixture
def adapter():
    instance = Adapter()
    yield instance
    instance.engine.dispose()


def run(admin, sql, params=None):
    with admin.connect() as connection:
        if params:
            connection.execute(sa.text(sql), params)
        else:
            connection.execute(sa.text(sql))


def scalar(admin, sql):
    with admin.connect() as connection:
        return connection.exec_driver_sql(sql).scalar()


def adapter_backends(admin, timeout=10.0) -> int:
    deadline = time.monotonic() + timeout
    while True:
        count = scalar(
            admin,
            f"SELECT count(*) FROM pg_stat_activity WHERE application_name = '{ADAPTER_APP}'",
        )
        if count == 0 or time.monotonic() > deadline:
            return count
        time.sleep(0.1)


def test_text_keys_use_c_order_equal_to_python_while_default_collation_differs(admin, schema, adapter):
    run(admin, f'CREATE TABLE "{schema}".t (code text PRIMARY KEY, v int)')
    run(admin, f'INSERT INTO "{schema}".t VALUES (:k, 1)', [{"k": key} for key in reversed(TEXT_KEYS)])

    rows = list(iter_table_records(adapter.engine, "t", "code", schema=schema))

    assert [row["code"] for row in rows] == sorted(TEXT_KEYS)
    with admin.connect() as connection:
        locale_order = [r[0] for r in connection.exec_driver_sql(
            f'SELECT code FROM "{schema}".t ORDER BY code'
        )]
    assert locale_order != sorted(TEXT_KEYS), "default collation unexpectedly equals C order"
    assert adapter_backends(admin) == 0


def test_composite_primary_key_order_matches_python_tuple_order(admin, schema, adapter):
    run(admin, f'CREATE TABLE "{schema}".t (code text, n int, d date, ts timestamptz, '
               'PRIMARY KEY (code, n, d, ts))')
    keys = []
    for code in ("b", "B", "é", "a", "日本"):
        for n in (10, 2):
            for day in (2, 1):
                for hour in (6, 5):
                    keys.append((code, n, datetime(2026, 1, day).date(),
                                 datetime(2026, 1, 19, hour, tzinfo=timezone.utc)))
    run(admin, f'INSERT INTO "{schema}".t VALUES (:c, :n, :d, :ts)',
        [dict(c=c, n=n, d=d, ts=ts) for c, n, d, ts in reversed(keys)])

    rows = list(iter_table_records(adapter.engine, "t", ("code", "n", "d", "ts"), schema=schema))

    assert [(r["code"], r["n"], r["d"], r["ts"]) for r in rows] == sorted(keys)


def test_bytea_keys_order_and_values_are_bytes(admin, schema, adapter):
    keys = [b"\xff", b"\x00", b"a", b"", b"ab", b"\x00\x00"]
    run(admin, f'CREATE TABLE "{schema}".t (k bytea PRIMARY KEY, v int)')
    run(admin, f'INSERT INTO "{schema}".t VALUES (:k, 1)', [{"k": k} for k in keys])

    rows = list(iter_table_records(adapter.engine, "t", "k", schema=schema))

    assert [row["k"] for row in rows] == sorted(keys)
    assert all(type(row["k"]) is bytes for row in rows)


def test_server_side_cursor_exists_during_iteration_and_not_for_plain_fetch(admin, schema, adapter):
    run(admin, f'CREATE TABLE "{schema}".t AS SELECT g AS id FROM generate_series(1, 500) g')
    run(admin, f'ALTER TABLE "{schema}".t ADD PRIMARY KEY (id)')

    rows = iter_table_records(adapter.engine, "t", "id", schema=schema, fetch_size=10)
    assert next(rows) == {"id": 1}
    cursor = adapter.raw[-1].cursor()
    cursor.execute("SELECT name FROM pg_cursors")
    assert len(cursor.fetchall()) == 1
    cursor.close()
    rows.close()

    with adapter.engine.connect() as connection:
        connection.execute(sa.text(f'SELECT id FROM "{schema}".t'))
        cursor = adapter.raw[-1].cursor()
        cursor.execute("SELECT name FROM pg_cursors")
        assert cursor.fetchall() == []
        cursor.close()


def test_streaming_uses_far_less_python_memory_than_fetchall(admin, schema, adapter):
    run(admin, f'CREATE TABLE "{schema}".t AS SELECT g AS id, g * 2 AS v, repeat(\'x\', 20) AS s '
               'FROM generate_series(1, 100000) g')
    run(admin, f'ALTER TABLE "{schema}".t ADD PRIMARY KEY (id)')

    def streamed_peak():
        tracemalloc.start()
        try:
            count, previous = 0, 0
            for row in iter_table_records(adapter.engine, "t", "id", schema=schema, fetch_size=1000):
                assert row["id"] > previous
                previous = row["id"]
                count += 1
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert count == 100000
        return peak

    def fetchall_peak():
        tracemalloc.start()
        try:
            with adapter.engine.connect() as connection:
                rows = connection.execute(sa.text(f'SELECT * FROM "{schema}".t ORDER BY id')).fetchall()
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert len(rows) == 100000
        return peak

    streaming, everything = streamed_peak(), fetchall_peak()
    assert streaming * 5 < everything, (streaming, everything)


def test_read_only_transaction_is_enforced_and_does_not_leak(admin, schema, adapter):
    run(admin, f'CREATE TABLE "{schema}".t (id int PRIMARY KEY)')
    run(admin, f'INSERT INTO "{schema}".t SELECT g FROM generate_series(1, 50) g')

    rows = iter_table_records(adapter.engine, "t", "id", schema=schema, fetch_size=5)
    next(rows)
    cursor = adapter.raw[-1].cursor()
    cursor.execute("SHOW transaction_read_only")
    assert cursor.fetchone()[0] == "on"
    with pytest.raises(psycopg2.errors.ReadOnlySqlTransaction):
        cursor.execute(f'INSERT INTO "{schema}".t VALUES (999)')
    cursor.close()
    rows.close()

    assert scalar(admin, f'SELECT count(*) FROM "{schema}".t') == 50
    with adapter.engine.connect() as connection:
        assert connection.exec_driver_sql("SHOW transaction_read_only").scalar() == "off"
    assert adapter_backends(admin) == 0


def test_connections_and_cursors_are_released_on_every_path(admin, schema, adapter):
    run(admin, f'CREATE TABLE "{schema}".t AS SELECT g AS id FROM generate_series(1, 300) g')
    run(admin, f'ALTER TABLE "{schema}".t ADD PRIMARY KEY (id)')

    assert len(list(iter_table_records(adapter.engine, "t", "id", schema=schema, fetch_size=7))) == 300
    assert adapter_backends(admin) == 0

    rows = iter_table_records(adapter.engine, "t", "id", schema=schema, fetch_size=7)
    next(rows)
    assert scalar(admin, f"SELECT count(*) FROM pg_stat_activity WHERE application_name = '{ADAPTER_APP}'") == 1
    rows.close()
    assert adapter_backends(admin) == 0

    run(admin, f'CREATE TABLE "{schema}".u (id uuid PRIMARY KEY)')
    with pytest.raises(ValueError, match="unsupported type"):
        list(iter_table_records(adapter.engine, "u", "id", schema=schema))
    assert adapter_backends(admin) == 0


def test_server_error_during_fetch_releases_connection(admin, schema, adapter):
    run(admin, f'CREATE TABLE "{schema}".base AS SELECT g AS id FROM generate_series(1, 100) g')
    run(admin, f'CREATE VIEW "{schema}".v AS SELECT id, 10 / (id - 50) AS bad FROM "{schema}".base')

    with pytest.raises(sa.exc.DBAPIError, match="division by zero"):
        list(iter_table_records(adapter.engine, "v", "id", schema=schema, fetch_size=10))
    assert adapter_backends(admin) == 0


@pytest.mark.parametrize("column_type", ["char(5)", "uuid", "interval", "timetz"])
def test_unsupported_real_column_types_are_rejected(admin, schema, adapter, column_type):
    run(admin, f'CREATE TABLE "{schema}".t (k {column_type} PRIMARY KEY)')
    with pytest.raises(ValueError, match="unsupported type"):
        list(iter_table_records(adapter.engine, "t", "k", schema=schema))
    assert adapter_backends(admin) == 0


@pytest.mark.parametrize(
    ("column_type", "value"),
    [
        ("time", "TIME '24:00:00'"),
        ("date", "DATE 'infinity'"),
        ("date", "DATE '-infinity'"),
        ("timestamp", "TIMESTAMP 'infinity'"),
        ("timestamp", "TIMESTAMP '-infinity'"),
        ("timestamptz", "TIMESTAMPTZ 'infinity'"),
        ("timestamptz", "TIMESTAMPTZ '-infinity'"),
    ],
)
def test_lossy_temporal_primary_keys_are_rejected(
    admin, schema, adapter, column_type, value
):
    run(admin, f'CREATE TABLE "{schema}".t (k {column_type} PRIMARY KEY)')
    run(admin, f'INSERT INTO "{schema}".t VALUES ({value})')

    with pytest.raises(ValueError, match="cannot represent without loss"):
        list(iter_table_records(adapter.engine, "t", "k", schema=schema))

    assert adapter_backends(admin) == 0


def test_enum_and_citext_keys_are_rejected(admin, schema, adapter):
    run(admin, f'CREATE EXTENSION citext SCHEMA "{schema}"')
    run(admin, f'CREATE TYPE "{schema}".kind AS ENUM (\'a\', \'b\')')
    run(admin, f'CREATE TABLE "{schema}".e (k "{schema}".kind PRIMARY KEY)')
    run(admin, f'CREATE TABLE "{schema}".c (k "{schema}".citext PRIMARY KEY)')
    for table in ("e", "c"):
        with pytest.raises(ValueError, match="unsupported type"):
            list(iter_table_records(adapter.engine, table, "k", schema=schema))
    assert adapter_backends(admin) == 0


def test_text_key_in_non_utf8_database_is_refused(admin):
    name = f"spc_adapter_it_ascii_{uuid.uuid4().hex[:8]}"
    ascii_url = make_url(DATABASE_URL).set(database=name)
    try:
        run(admin, f'CREATE DATABASE "{name}" TEMPLATE template0 ENCODING \'SQL_ASCII\' '
                   "LC_COLLATE 'C' LC_CTYPE 'C'")
        engine = sa.create_engine(
            ascii_url, poolclass=NullPool,
            connect_args={"hostaddr": "127.0.0.1", "application_name": ADAPTER_APP},
        )
        try:
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
                connection.exec_driver_sql("CREATE TABLE t (code text PRIMARY KEY, n int)")
            with pytest.raises(ValueError, match="UTF8"):
                list(iter_table_records(engine, "t", "code"))
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
                connection.exec_driver_sql("CREATE TABLE s (n int PRIMARY KEY, code text)")
            assert list(iter_table_records(engine, "s", "n")) == []
        finally:
            engine.dispose()
    finally:
        run(admin, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    assert adapter_backends(admin) == 0


def test_decimal_null_and_datetime_values_are_exact(admin, schema, adapter):
    run(admin, f'CREATE TABLE "{schema}".t (id int PRIMARY KEY, amount numeric, ts timestamptz, '
               'local_ts timestamp, d date, tm time, note text, f boolean, '
               'nullable_d date, nullable_tm time, nullable_ts timestamptz)')
    run(admin, f'INSERT INTO "{schema}".t VALUES (1, 10000000000000000000.0000001, '
               "'2026-01-19 06:00:00+01', '2026-01-19 06:00:00', '2026-01-19', "
               "'06:30:15.123456', NULL, true, NULL, NULL, NULL)")

    [row] = iter_table_records(adapter.engine, "t", "id", schema=schema)

    assert row["amount"] == Decimal("10000000000000000000.0000001") and type(row["amount"]) is Decimal
    assert row["ts"].utcoffset() is not None
    assert row["ts"].astimezone(timezone.utc) == datetime(2026, 1, 19, 5, tzinfo=timezone.utc)
    assert row["local_ts"] == datetime(2026, 1, 19, 6) and row["local_ts"].tzinfo is None
    assert row["d"] == date(2026, 1, 19)
    assert row["tm"] == datetime_time(6, 30, 15, 123456)
    assert row["nullable_d"] is row["nullable_tm"] is row["nullable_ts"] is None
    assert row["note"] is None and row["f"] is True


def _populate_pair(admin, source_schema, target_schema):
    for schema in (source_schema, target_schema):
        run(admin, f'CREATE SCHEMA "{schema}"')
        run(admin, f'CREATE TABLE "{schema}".m (code text, n int, amount numeric, ts timestamptz, '
                   'note text, PRIMARY KEY (code, n))')
    source = [(f"k{index:05d}é", index % 7, Decimal(index) / 4, datetime(2026, 1, 1, tzinfo=timezone.utc)
               + timedelta(minutes=index), None if index % 5 else "x") for index in range(3000)]
    source.append(("日本", 1, Decimal("10000000000000000000.0000001"), datetime(2026, 1, 1, tzinfo=timezone.utc), None))
    target = [list(row) for row in source]
    target[10][2] = target[10][2] + Decimal("0.0000001")
    target[20][3] = target[20][3] + timedelta(microseconds=1)
    target[30][4] = "changed"
    target[40][4] = None if target[40][4] else "now set"
    del target[50]
    target.append(["ünique-target", 1, Decimal(1), datetime(2026, 1, 1, tzinfo=timezone.utc), None])
    insert = 'INSERT INTO "{}".m VALUES (:c, :n, :a, :t, :note)'
    for schema, rows in ((source_schema, source), (target_schema, target)):
        run(admin, insert.format(schema),
            [dict(c=c, n=n, a=a, t=t, note=note) for c, n, a, t, note in rows])


@pytest.fixture
def schema_pair(admin):
    source_schema = f"it_src_{uuid.uuid4().hex[:8]}"
    target_schema = f"it_dst_{uuid.uuid4().hex[:8]}"
    try:
        _populate_pair(admin, source_schema, target_schema)
        yield source_schema, target_schema
    finally:
        for name in (source_schema, target_schema):
            run(admin, f'DROP SCHEMA IF EXISTS "{name}" CASCADE')


def _load(admin, schema):
    with admin.connect() as connection:
        return [dict(r._mapping) for r in connection.execute(sa.text(f'SELECT * FROM "{schema}".m'))]


def test_compare_tables_matches_in_memory_comparison_across_separate_tables(admin, schema_pair):
    source_schema, target_schema = schema_pair
    source = Adapter(timezone="UTC")
    target = Adapter(timezone="Asia/Tokyo")
    try:
        events = []
        report = compare_tables(
            source.engine, target.engine, "m", ("code", "n"),
            schema=source_schema, target_schema=target_schema,
            batch_size=250, max_samples=100, on_difference=events.append,
        )
        reference = compare_records(_load(admin, source_schema), _load(admin, target_schema), ("code", "n"))
    finally:
        source.engine.dispose()
        target.engine.dispose()

    assert report.complete and report.status == "FAIL"
    assert (report.source_count, report.target_count) == (reference.source_count, reference.target_count)
    assert report.matched_count == len(reference.matched)
    assert report.source_only_count == len(reference.source_only) == 1
    assert report.target_only_count == len(reference.target_only) == 1
    assert report.different_count == len(reference.different) == 4
    assert {e.primary_key: e.fields for e in events if e.kind == "different"} == {
        d.primary_key: d.fields for d in reference.different
    }
    assert adapter_backends(admin) == 0


def test_compare_tables_identical_tables_pass_across_session_time_zones(admin, schema):
    run(admin, f'CREATE TABLE "{schema}".a (id int PRIMARY KEY, amount numeric, ts timestamptz, note text)')
    run(admin, f'CREATE TABLE "{schema}".b (LIKE "{schema}".a INCLUDING ALL)')
    for table, amount, ts in (("a", "1.10", "2026-01-19 05:00:00+00"), ("b", "1.1", "2026-01-19 06:00:00+01")):
        run(admin, f"INSERT INTO \"{schema}\".{table} VALUES (1, {amount}, '{ts}', NULL)")
    source, target = Adapter(timezone="UTC"), Adapter(timezone="Asia/Tokyo")
    try:
        report = compare_tables(source.engine, target.engine, "a", "id", schema=schema,
                                target_table="b", target_schema=schema)
    finally:
        source.engine.dispose()
        target.engine.dispose()

    assert report.status == "PASS" and report.matched_count == 1
    assert adapter_backends(admin) == 0


def test_compare_tables_releases_both_connections_when_comparison_fails(admin, schema):
    for table in ("a", "b"):
        run(admin, f'CREATE TABLE "{schema}".{table} (id int PRIMARY KEY, doc jsonb)')
        run(admin, f"INSERT INTO \"{schema}\".{table} VALUES (1, '{{\"x\": 1}}')")
    source, target = Adapter(), Adapter()
    try:
        with pytest.raises(TypeError, match="unsupported value type"):
            compare_tables(source.engine, target.engine, "a", "id", schema=schema,
                           target_table="b", target_schema=schema)
    finally:
        source.engine.dispose()
        target.engine.dispose()
    assert adapter_backends(admin) == 0
