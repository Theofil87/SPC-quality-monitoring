"""Mock-based tests of the PostgreSQL adapter; no database is contacted.

These tests do not prove server-side cursor behaviour of a real PostgreSQL
server. That needs a separate integration test against a disposable database.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import uuid

import pytest

sa = pytest.importorskip("sqlalchemy")
from sqlalchemy.dialects import postgresql  # noqa: E402
from sqlalchemy.exc import NoSuchTableError  # noqa: E402

from src import postgres_adapter as adapter  # noqa: E402
from src.migration_validator import compare_record_streams  # noqa: E402
from src.postgres_adapter import compare_tables, iter_table_records  # noqa: E402


class FakeResult:
    def __init__(self, rows, fail_after=None, close_error=None):
        self._rows = rows
        self._fail_after = fail_after
        self._close_error = close_error
        self.closed = False
        self.consumed = 0

    def mappings(self):
        for index, row in enumerate(self._rows):
            if self._fail_after is not None and index >= self._fail_after:
                raise RuntimeError("cursor failure")
            self.consumed += 1
            yield dict(row)

    def close(self):
        self.closed = True
        if self._close_error is not None:
            raise self._close_error


class FakeConnection:
    def __init__(self, rows, fail_after=None, encoding="UTF8", read_only="on",
                 close_result_error=None):
        self.rows = rows
        self.fail_after = fail_after
        self.encoding = encoding
        self.read_only = read_only
        self.close_result_error = close_result_error
        self.options = {}
        self.statements = []
        self.driver_sql = []
        self.results = []
        self.close_count = 0

    def execution_options(self, **options):
        self.options.update(options)
        return self

    def exec_driver_sql(self, sql):
        self.driver_sql.append(sql)
        return type("Row", (), {"one": lambda _: (self.encoding, self.read_only)})()

    def execute(self, statement):
        self.statements.append(statement)
        rows = []
        for row in self.rows:
            mapped = dict(row)
            for name in statement.selected_columns.keys():
                if name.startswith(adapter._TEMPORAL_VALUES_SAFE_LABEL):
                    mapped.setdefault(name, True)
            rows.append(mapped)
        result = FakeResult(rows, self.fail_after, self.close_result_error)
        self.results.append(result)
        return result

    def close(self):
        self.close_count += 1


class FakeEngine:
    def __init__(self, rows=(), fail_after=None, connect_error=None, **connection_options):
        self.rows = list(rows)
        self.fail_after = fail_after
        self.connect_error = connect_error
        self.connection_options = connection_options
        self.connections = []

    def connect(self):
        if self.connect_error is not None:
            raise self.connect_error
        connection = FakeConnection(self.rows, self.fail_after, **self.connection_options)
        self.connections.append(connection)
        return connection


def make_table(name="measurements", **types):
    columns = {
        "id": sa.Integer(),
        "code": sa.Text(),
        "ts": sa.DateTime(timezone=True),
        "val": sa.Numeric(30, 10),
        "payload": sa.LargeBinary(),
        "note": sa.Text(),
    }
    columns.update(types)
    return sa.Table(
        name, sa.MetaData(), *(sa.Column(n, t) for n, t in columns.items())
    )


@pytest.fixture
def table(monkeypatch):
    fake = make_table()
    monkeypatch.setattr(adapter, "Table", lambda *args, **kwargs: fake)
    return fake


def sql_of(connection):
    return str(connection.statements[0].compile(dialect=postgresql.dialect()))


def assert_all_closed(engine):
    assert engine.connections
    for connection in engine.connections:
        assert connection.close_count == 1
        assert all(result.closed for result in connection.results)


def test_text_key_is_ordered_with_collate_c_and_numeric_key_is_plain(table):
    engine = FakeEngine([{"id": 1, "code": "a"}])
    list(iter_table_records(engine, "measurements", ("code", "id"), columns=["id", "code"]))

    assert 'ORDER BY measurements.code COLLATE "C" ASC, measurements.id ASC' in sql_of(
        engine.connections[0]
    )


def test_composite_key_follows_key_order_not_column_order(table):
    engine = FakeEngine([])
    list(iter_table_records(engine, "measurements", ("id", "code", "ts")))

    ordering = sql_of(engine.connections[0]).split("ORDER BY")[1]
    assert ordering.split(",")[0].strip() == "measurements.id ASC"
    assert 'measurements.code COLLATE "C" ASC' in ordering.split(",")[1]
    assert ordering.split(",")[2].strip() == "measurements.ts ASC"


def test_statement_requests_streaming_and_connection_is_read_only(table):
    engine = FakeEngine([])
    list(iter_table_records(engine, "measurements", "id", fetch_size=250))

    connection = engine.connections[0]
    assert connection.options == {"postgresql_readonly": True}
    options = connection.statements[0].get_execution_options()
    assert options["stream_results"] is True
    assert options["yield_per"] == 250


def test_rows_are_streamed_lazily_not_fetched_all_at_once(table):
    engine = FakeEngine([{"id": i} for i in range(100)])
    rows = iter_table_records(engine, "measurements", "id", columns=["id"])

    assert next(rows) == {"id": 0}
    assert engine.connections[0].results[0].consumed == 1
    rows.close()


def test_connection_is_opened_only_when_iteration_starts(table):
    engine = FakeEngine([])
    rows = iter_table_records(engine, "measurements", "id")
    assert engine.connections == []
    rows.close()
    assert engine.connections == []


def test_connection_closed_after_exhaustion_and_early_close(table):
    engine = FakeEngine([{"id": i} for i in range(5)])
    list(iter_table_records(engine, "measurements", "id"))
    assert_all_closed(engine)

    early = FakeEngine([{"id": i} for i in range(5)])
    rows = iter_table_records(early, "measurements", "id")
    next(rows)
    assert early.connections[0].close_count == 0
    rows.close()
    assert_all_closed(early)


def test_connection_closed_when_cursor_fails_midway(table):
    engine = FakeEngine([{"id": i} for i in range(5)], fail_after=2)
    with pytest.raises(RuntimeError, match="cursor failure"):
        list(iter_table_records(engine, "measurements", "id"))
    assert_all_closed(engine)


@pytest.mark.parametrize(
    ("key", "kwargs", "message"),
    [
        ("missing", {}, "not found"),
        ("id", {"columns": ["id", "nope"]}, "columns not found"),
    ],
)
def test_connection_closed_when_schema_validation_fails(table, key, kwargs, message):
    engine = FakeEngine([])
    with pytest.raises(ValueError, match=message):
        list(iter_table_records(engine, "measurements", key, **kwargs))
    assert_all_closed(engine)


def test_missing_table_is_reported_and_connection_closed(monkeypatch):
    def no_table(*args, **kwargs):
        raise NoSuchTableError("measurements")

    monkeypatch.setattr(adapter, "Table", no_table)
    engine = FakeEngine([])
    with pytest.raises(ValueError, match="was not found"):
        list(iter_table_records(engine, "measurements", "id"))
    assert_all_closed(engine)


@pytest.mark.parametrize(
    "column_type",
    [
        sa.Enum("a", "b", name="kind"), postgresql.UUID(), sa.JSON(), sa.types.NullType(),
        sa.CHAR(5), sa.String(), postgresql.CITEXT(), sa.Interval(), sa.Time(timezone=True),
    ],
)
def test_key_types_without_proven_ordering_are_rejected(monkeypatch, column_type):
    fake = make_table(id=column_type)
    monkeypatch.setattr(adapter, "Table", lambda *args, **kwargs: fake)
    engine = FakeEngine([])
    with pytest.raises(ValueError, match="unsupported type"):
        list(iter_table_records(engine, "measurements", "id"))
    assert_all_closed(engine)


@pytest.mark.parametrize("column_type", [sa.VARCHAR(20), sa.TEXT(), postgresql.TIMESTAMP()])
def test_varchar_text_and_timestamp_keys_are_accepted(monkeypatch, column_type):
    fake = make_table(id=column_type)
    monkeypatch.setattr(adapter, "Table", lambda *args, **kwargs: fake)
    engine = FakeEngine([])
    assert list(iter_table_records(engine, "measurements", "id")) == []
    assert_all_closed(engine)


@pytest.mark.parametrize("encoding", ["SQL_ASCII", "LATIN1", "EUC_JP"])
def test_text_key_requires_utf8_database_and_connection_is_closed(table, encoding):
    engine = FakeEngine([{"id": 1, "code": "a"}], encoding=encoding)
    with pytest.raises(ValueError, match="UTF8"):
        list(iter_table_records(engine, "measurements", "code"))
    assert engine.connections[0].statements == []
    assert_all_closed(engine)


def test_non_text_key_does_not_depend_on_database_encoding(table):
    engine = FakeEngine([{"id": 1}], encoding="LATIN1")
    assert list(iter_table_records(engine, "measurements", "id", columns=["id"])) == [{"id": 1}]


def test_composite_key_with_text_component_requires_utf8(table):
    engine = FakeEngine([], encoding="LATIN1")
    with pytest.raises(ValueError, match="UTF8"):
        list(iter_table_records(engine, "measurements", ("id", "code")))
    assert_all_closed(engine)


@pytest.mark.parametrize("read_only", ["off", ""])
def test_connection_that_is_not_read_only_is_refused_before_reading(table, read_only):
    engine = FakeEngine([{"id": 1}], read_only=read_only)
    with pytest.raises(RuntimeError, match="read-only"):
        list(iter_table_records(engine, "measurements", "id"))
    assert engine.connections[0].statements == []
    assert_all_closed(engine)


def test_connection_closed_even_when_result_close_fails(table):
    engine = FakeEngine([{"id": 1}], close_result_error=OSError("close failed"))
    with pytest.raises(OSError, match="close failed"):
        list(iter_table_records(engine, "measurements", "id"))
    assert engine.connections[0].close_count == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"table": ""}, {"schema": ""}, {"primary_key": []}, {"fetch_size": 0},
        {"fetch_size": True}, {"columns": []}, {"columns": ["code"]},
        {"columns": ["id", "id"]},
    ],
)
def test_invalid_arguments_fail_before_any_connection(kwargs):
    engine = FakeEngine([])
    arguments = {"table": "t", "primary_key": "id"}
    arguments.update(kwargs)
    call = {key: arguments.pop(key) for key in ("table", "primary_key")}
    with pytest.raises(ValueError):
        iter_table_records(engine, call["table"], call["primary_key"], **arguments)
    assert engine.connections == []


def test_memoryview_bytea_is_converted_and_other_values_pass_through(table):
    moment = datetime(2026, 1, 19, 5, tzinfo=timezone.utc)
    row = {
        "id": 1, "payload": memoryview(b"\x00\xff"), "val": Decimal("1.0000000001"),
        "ts": moment, "note": None,
    }
    engine = FakeEngine([row])
    [converted] = iter_table_records(engine, "measurements", "id")

    assert converted["payload"] == b"\x00\xff" and type(converted["payload"]) is bytes
    assert converted["val"] == Decimal("1.0000000001")
    assert converted["ts"] is moment
    assert converted["note"] is None


@pytest.mark.parametrize(
    ("column_type", "unsafe_sql"),
    [
        (sa.Time(), "TIME '24:00:00'"),
        (sa.Date(), "isfinite("),
        (sa.DateTime(), "isfinite("),
        (sa.DateTime(timezone=True), "isfinite("),
    ],
)
def test_temporal_special_values_are_rejected_before_driver_conversion(
    monkeypatch, column_type, unsafe_sql
):
    fake = make_table(id=column_type)
    monkeypatch.setattr(adapter, "Table", lambda *args, **kwargs: fake)
    engine = FakeEngine([{
        "id": None,
        adapter._TEMPORAL_VALUES_SAFE_LABEL: False,
    }])

    with pytest.raises(ValueError, match="cannot represent without loss"):
        list(iter_table_records(engine, "measurements", "id"))

    assert unsafe_sql in sql_of(engine.connections[0])
    assert_all_closed(engine)


def test_temporal_special_values_in_non_key_columns_are_rejected(monkeypatch):
    fake = make_table(ts=sa.DateTime(timezone=True))
    monkeypatch.setattr(adapter, "Table", lambda *args, **kwargs: fake)
    engine = FakeEngine([{
        "id": 1,
        "ts": datetime.max.replace(tzinfo=timezone.utc),
        adapter._TEMPORAL_VALUES_SAFE_LABEL: False,
    }])

    with pytest.raises(ValueError, match="cannot represent without loss"):
        list(iter_table_records(engine, "measurements", "id", columns=["id", "ts"]))

    assert_all_closed(engine)


def test_normal_temporal_values_and_nulls_are_unchanged(monkeypatch):
    fake = make_table(
        day=sa.Date(),
        clock=sa.Time(),
        nullable_day=sa.Date(),
    )
    monkeypatch.setattr(adapter, "Table", lambda *args, **kwargs: fake)
    moment = datetime(2026, 1, 19, 5, tzinfo=timezone.utc)
    record = {
        "id": 1,
        "ts": moment,
        "day": date(2026, 1, 19),
        "clock": time(6, 30, 15, 123456),
        "nullable_day": None,
    }

    [converted] = iter_table_records(
        FakeEngine([record]),
        "measurements",
        "id",
        columns=["id", "ts", "day", "clock", "nullable_day"],
    )

    assert converted == record
    assert converted["ts"] is moment


# Python orders strings by code point. COLLATE "C" makes PostgreSQL do the same;
# a locale collation would not, and the comparator would misreport.
TEXT_KEYS = ["B", "a", "a-b", "ab", "Z", "z", "_x", "Éa", "ea", "éa", "őr", "я", "日本", "😀"]
LOCALE_LIKE_ORDER = ["_x", "a", "a-b", "ab", "B", "ea", "éa", "Éa", "őr", "z", "Z", "я", "日本", "😀"]


def test_python_code_point_order_of_mixed_text_keys_is_accepted():
    ordered = sorted(TEXT_KEYS)
    assert ordered == sorted(TEXT_KEYS, key=lambda value: value.encode("utf-8"))
    rows = [{"id": key, "v": 1} for key in ordered]

    report = compare_record_streams(rows, rows, "id", batch_size=3)

    assert report.status == "PASS" and report.matched_count == len(TEXT_KEYS)


def test_locale_like_order_is_rejected_which_is_why_collate_c_is_required():
    rows = [{"id": key} for key in LOCALE_LIKE_ORDER]

    report = compare_record_streams(rows, [], "id")

    assert not report.complete and "increasing order" in report.error


def test_composite_key_with_text_component_matches_python_tuple_order(table):
    keys = [(text, number) for text in sorted(TEXT_KEYS) for number in (2, 10)]
    assert keys == sorted(keys)
    rows = [{"code": text, "id": number, "v": 0} for text, number in keys]
    source, target = FakeEngine(rows), FakeEngine(rows)

    report = compare_tables(source, target, "measurements", ("code", "id"),
                            columns=["code", "id", "val"])

    assert report.status == "PASS" and report.matched_count == len(keys)
    assert 'COLLATE "C"' in sql_of(source.connections[0])


def test_compare_tables_reports_differences_with_null_decimal_and_datetime(table):
    instant = datetime(2026, 1, 19, 5, tzinfo=timezone.utc)
    shifted = datetime(2026, 1, 19, 6, tzinfo=timezone(timedelta(hours=1)))
    source = FakeEngine([
        {"id": 1, "val": Decimal("1.10"), "ts": instant, "note": None},
        {"id": 2, "val": Decimal("2"), "ts": instant, "note": "x"},
    ])
    target = FakeEngine([
        {"id": 1, "val": Decimal("1.1"), "ts": shifted, "note": None},
        {"id": 2, "val": Decimal("2.0000000001"), "ts": instant, "note": None},
        {"id": 3, "val": Decimal("3"), "ts": instant, "note": None},
    ])
    target.rows = [dict(row) for row in target.rows]

    report = compare_tables(source, target, "measurements", "id",
                            columns=["id", "val", "ts", "note"])

    assert (report.matched_count, report.different_count, report.target_only_count) == (1, 1, 1)
    [different] = [s for s in report.samples if s.kind == "different"]
    assert {f.field for f in different.fields} == {"val", "note"}
    assert_all_closed(source)
    assert_all_closed(target)


def test_compare_tables_uses_separate_target_name_and_schema(monkeypatch):
    seen = []

    def fake_table(name, metadata, **kwargs):
        seen.append((name, kwargs.get("schema")))
        return make_table(name)

    monkeypatch.setattr(adapter, "Table", fake_table)
    compare_tables(FakeEngine([]), FakeEngine([]), "src_t", "id", schema="s1",
                   target_table="dst_t", target_schema="s2")

    assert seen == [("src_t", "s1"), ("dst_t", "s2")]


def test_compare_tables_inherits_source_schema_when_target_schema_is_none(monkeypatch):
    seen = []

    def fake_table(name, metadata, **kwargs):
        seen.append((name, kwargs.get("schema")))
        return make_table(name)

    monkeypatch.setattr(adapter, "Table", fake_table)
    compare_tables(FakeEngine([]), FakeEngine([]), "t", "id", schema="source_schema")

    assert seen == [("t", "source_schema"), ("t", "source_schema")]


def test_both_connections_closed_when_comparison_stops_on_order_error(table):
    source = FakeEngine([{"id": i} for i in (1, 3, 2, 4)])
    target = FakeEngine([{"id": i} for i in range(1, 100)])

    report = compare_tables(source, target, "measurements", "id", columns=["id"], batch_size=2)

    assert not report.complete
    assert_all_closed(source)
    assert_all_closed(target)


def test_both_connections_closed_when_callback_raises(table):
    source = FakeEngine([{"id": i, "note": "a"} for i in range(10)])
    target = FakeEngine([{"id": i, "note": "b"} for i in range(10)])

    def fail(_):
        raise OSError("output failed")

    with pytest.raises(OSError, match="output failed"):
        compare_tables(source, target, "measurements", "id",
                       columns=["id", "note"], on_difference=fail)
    assert_all_closed(source)
    assert_all_closed(target)


@pytest.mark.parametrize("failing", ["source", "target"])
def test_both_connections_closed_when_one_cursor_fails(table, failing):
    good = [{"id": i} for i in range(10)]
    source = FakeEngine(good, fail_after=3 if failing == "source" else None)
    target = FakeEngine(good, fail_after=3 if failing == "target" else None)

    with pytest.raises(RuntimeError, match="cursor failure"):
        compare_tables(source, target, "measurements", "id", columns=["id"], batch_size=2)
    assert_all_closed(source)
    assert_all_closed(target)


def test_source_connection_closed_when_target_cannot_connect(table):
    source = FakeEngine([{"id": 1}])
    target = FakeEngine(connect_error=ConnectionError("target down"))

    with pytest.raises(ConnectionError, match="target down"):
        compare_tables(source, target, "measurements", "id", columns=["id"])
    assert_all_closed(source)


def test_sqlalchemy_psycopg2_dialect_requests_named_cursor_for_streaming():
    """Checks dialect wiring with a fake DBAPI connection, not a PostgreSQL server."""
    pytest.importorskip("psycopg2")
    from unittest.mock import MagicMock, patch

    dbapi_connection = MagicMock()
    with patch("psycopg2.extras.register_uuid"):
        engine = sa.create_engine(
            "postgresql+psycopg2://",
            creator=lambda: dbapi_connection,
            use_native_hstore=False,
        )
        statement = sa.select(sa.column("id")).select_from(sa.table("t")).execution_options(
            stream_results=True, yield_per=10
        )
        try:
            with patch.object(engine.dialect, "initialize", return_value=None):
                engine.dialect.server_version_info = (16, 0)
                with engine.connect() as connection:
                    connection.execute(statement)

                [call] = dbapi_connection.cursor.call_args_list
                assert call.args and isinstance(call.args[0], str)
                unnamed = sa.select(sa.column("id")).select_from(sa.table("t"))
                dbapi_connection.reset_mock()
                with engine.connect() as connection:
                    connection.execute(unnamed)
                assert dbapi_connection.cursor.call_args.args == ()
        finally:
            engine.dispose()
