from __future__ import annotations

from datetime import datetime, time, timedelta
import os
from pathlib import Path
import re
import uuid

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.dialects.postgresql.psycopg2 import dialect as psycopg2_dialect
from sqlalchemy.exc import ArgumentError, IntegrityError

from src.spc_monitoring import summarize_mr_violations


REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_DATABASE_NAME = "spc_quality_monitoring_test"
TEST_DATABASE_PORT = 5432
LOCAL_DATABASE_HOSTS = {"localhost", "127.0.0.1", "::1"}
BASELINE_SEQUENCE = [74.9, 75.1] * 5
OUTLIER_SEQUENCE = [75.0, 80.0, 75.0]
SHIFT_SEQUENCE = [76.0] * 10
TREND_SEQUENCE = [75.1 + 0.25 * index for index in range(12)]
# The fixture baseline has center 75 and sigma = 0.2 / 1.128.
RULE_2_SEQUENCE = [75.0, 75.4, 75.4, 75.0, 75.0]
RULE_3_SEQUENCE = [75.0, 75.25, 75.25, 75.25, 75.25, 75.0]


def _baseline_moving_ranges() -> list[float]:
    moving_ranges = []
    for _ in range(30):
        moving_ranges.extend(np.abs(np.diff(BASELINE_SEQUENCE)).tolist())
    return moving_ranges


def _extract_create_view_statement(sql_source: str, view_name: str) -> str:
    """Extract one CREATE VIEW statement, ignoring semicolons in SQL syntax."""
    header = re.search(
        rf"CREATE OR REPLACE VIEW\s+{re.escape(view_name)}\s+AS\b",
        sql_source,
        flags=re.IGNORECASE,
    )
    assert header is not None, f"View definition {view_name!r} was not found"

    index = header.start()
    line_comment = False
    block_comment_depth = 0
    quote: str | None = None
    dollar_quote: str | None = None

    while index < len(sql_source):
        if line_comment:
            if sql_source[index] in "\r\n":
                line_comment = False
            index += 1
            continue

        if block_comment_depth:
            if sql_source.startswith("/*", index):
                block_comment_depth += 1
                index += 2
            elif sql_source.startswith("*/", index):
                block_comment_depth -= 1
                index += 2
            else:
                index += 1
            continue

        if dollar_quote is not None:
            if sql_source.startswith(dollar_quote, index):
                index += len(dollar_quote)
                dollar_quote = None
            else:
                index += 1
            continue

        if quote is not None:
            if sql_source[index] == quote:
                if index + 1 < len(sql_source) and sql_source[index + 1] == quote:
                    index += 2
                    continue
                quote = None
            elif sql_source[index] == "\\":
                index += 1
            index += 1
            continue

        if sql_source.startswith("--", index):
            line_comment = True
            index += 2
        elif sql_source.startswith("/*", index):
            block_comment_depth = 1
            index += 2
        elif sql_source[index] in ("'", '"'):
            quote = sql_source[index]
            index += 1
        elif sql_source[index] == "$":
            dollar_match = re.match(r"\$(?:[A-Za-z_][A-Za-z_0-9]*)?\$", sql_source[index:])
            if dollar_match is None:
                index += 1
            else:
                dollar_quote = dollar_match.group(0)
                index += len(dollar_quote)
        elif sql_source[index] == ";":
            return sql_source[header.start() : index + 1]
        else:
            index += 1

    raise AssertionError(f"View definition {view_name!r} is not terminated")


def test_isolated_outlier_moving_ranges_exceed_baseline_fitted_ucl():
    baseline_summary = summarize_mr_violations(
        pd.Series(_baseline_moving_ranges(), dtype="float64")
    )
    outlier_moving_ranges = np.abs(np.diff(OUTLIER_SEQUENCE))

    assert baseline_summary.center_line == pytest.approx(0.2)
    assert baseline_summary.upper_control_limit == pytest.approx(0.6534)
    assert baseline_summary.violation_count == 0
    assert outlier_moving_ranges.tolist() == pytest.approx([5.0, 5.0])
    assert (outlier_moving_ranges > baseline_summary.upper_control_limit).all()


def test_view_statement_extraction_ignores_semicolons_in_comments_and_literals():
    sql_source = """CREATE OR REPLACE VIEW test_view AS
    SELECT 'text; still a string' AS value
    -- comment; not the statement terminator
    /* nested comment; /* inner; */ still a comment */
    SELECT $$dollar; quoted$$;
    CREATE OR REPLACE VIEW following_view AS SELECT 1;
    """

    statement = _extract_create_view_statement(sql_source, "test_view")

    assert statement.endswith("SELECT $$dollar; quoted$$;")
    assert "comment; not the statement terminator" in statement
    assert "following_view" not in statement


def _test_database_url_error(database_url: str) -> str | None:
    try:
        parsed_url = make_url(database_url)
    except (ArgumentError, ValueError):
        return "SPC_TEST_DATABASE_URL is not a valid PostgreSQL URL"
    if parsed_url.drivername not in {"postgresql", "postgresql+psycopg2"}:
        return "SPC_TEST_DATABASE_URL must use the psycopg2 PostgreSQL driver"
    if parsed_url.query:
        return "SPC_TEST_DATABASE_URL must not contain connection parameters"
    if parsed_url.database != TEST_DATABASE_NAME:
        return (
            "SPC_TEST_DATABASE_URL must target the dedicated "
            f"'{TEST_DATABASE_NAME}' database"
        )
    if (parsed_url.host or "").lower() not in LOCAL_DATABASE_HOSTS:
        return "SPC_TEST_DATABASE_URL must use a local PostgreSQL host"
    if parsed_url.port != TEST_DATABASE_PORT:
        return f"SPC_TEST_DATABASE_URL must use port {TEST_DATABASE_PORT}"
    if not parsed_url.username:
        return "SPC_TEST_DATABASE_URL must include a username"
    args, kwargs = psycopg2_dialect().create_connect_args(parsed_url)
    if (
        args
        or kwargs.get("host") != parsed_url.host
        or kwargs.get("port") != TEST_DATABASE_PORT
        or kwargs.get("dbname") != TEST_DATABASE_NAME
        or kwargs.get("user") != parsed_url.username
        or kwargs.get("password") != parsed_url.password
        or set(kwargs) - {"host", "port", "dbname", "user", "password"}
    ):
        return "SPC_TEST_DATABASE_URL produces unsafe connection arguments"
    return None


def _create_test_engine(database_url: str):
    url_error = _test_database_url_error(database_url)
    if url_error:
        pytest.fail(f"{url_error}; refusing to connect")
    host = make_url(database_url).host
    hostaddr = "::1" if host == "::1" else "127.0.0.1"
    return create_engine(database_url, connect_args={"hostaddr": hostaddr})


def test_controlled_test_database_url_rejects_nonstandard_port():
    url = "postgresql://test_user@localhost:5433/spc_quality_monitoring_test"

    assert _test_database_url_error(url) == (
        f"SPC_TEST_DATABASE_URL must use port {TEST_DATABASE_PORT}"
    )


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://user@remote.example:5432/spc_quality_monitoring_test",
        "postgresql://user@localhost:5432/spc_quality_monitoring",
        "postgresql://user@localhost/spc_quality_monitoring_test",
        "postgresql://localhost:5432/spc_quality_monitoring_test",
        "postgresql+pg8000://user@localhost:5432/spc_quality_monitoring_test",
    ],
)
def test_controlled_test_database_url_rejects_unsafe_authority(url):
    assert _test_database_url_error(url) is not None


@pytest.mark.parametrize(
    "query",
    [
        "host=remote.example",
        "port=5433",
        "dbname=spc_quality_monitoring",
        "database=spc_quality_monitoring",
        "user=other",
        "password=other",
        "hostaddr=192.0.2.1",
        "service=other",
        "sslmode=require",
        "host=localhost&host=remote.example",
    ],
)
def test_controlled_test_database_url_rejects_query_overrides(query, monkeypatch):
    def reject_connection(*args, **kwargs):
        pytest.fail("Unsafe URL reached engine creation")

    monkeypatch.setitem(_create_test_engine.__globals__, "create_engine", reject_connection)
    url = f"postgresql+psycopg2://user@localhost:5432/{TEST_DATABASE_NAME}?{query}"
    assert _test_database_url_error(url) == (
        "SPC_TEST_DATABASE_URL must not contain connection parameters"
    )
    with pytest.raises(pytest.fail.Exception, match="refusing to connect"):
        _create_test_engine(url)


def test_controlled_test_database_url_validates_dialect_arguments(monkeypatch):
    class UnsafeDialect:
        def create_connect_args(self, url):
            return [], {
                "host": "remote.example", "port": 5432,
                "dbname": TEST_DATABASE_NAME, "user": "user",
            }

    monkeypatch.setitem(_test_database_url_error.__globals__, "psycopg2_dialect", UnsafeDialect)
    assert _test_database_url_error(
        f"postgresql://user@localhost:5432/{TEST_DATABASE_NAME}"
    ) == "SPC_TEST_DATABASE_URL produces unsafe connection arguments"


@pytest.mark.parametrize(
    ("host", "hostaddr"),
    [("localhost", "127.0.0.1"), ("127.0.0.1", "127.0.0.1"), ("[::1]", "::1")],
)
def test_controlled_test_engine_pins_loopback_address(monkeypatch, host, hostaddr):
    captured = {}

    def fake_engine(url, **kwargs):
        captured.update(kwargs)
        return "mock engine"

    monkeypatch.setitem(_create_test_engine.__globals__, "create_engine", fake_engine)
    monkeypatch.setenv("PGHOSTADDR", "192.0.2.1")
    assert _create_test_engine(
        f"postgresql://user@{host}:5432/{TEST_DATABASE_NAME}"
    ) == "mock engine"
    assert captured["connect_args"] == {"hostaddr": hostaddr}


def _controlled_records() -> tuple[list[dict[str, object]], dict[str, list[int]]]:
    records: list[dict[str, object]] = []
    scenario_ids: dict[str, list[int]] = {}
    next_measurement_id = 1

    def add_sequence(
        name: str,
        values: list[float],
        start: datetime,
    ) -> None:
        nonlocal next_measurement_id
        measurement_ids = []
        for index, value in enumerate(values):
            records.append(
                {
                    "measurement_id": next_measurement_id,
                    "booth_id": 1,
                    "booth_name": "BOOTH_01",
                    "measurement_point_id": 1,
                    "point_code": "A-L1",
                    "specification_id": 1,
                    "shift_id": 1,
                    "shift_name": "SHIFT_01",
                    "batch_start": start,
                    "measurement_timestamp": start + timedelta(minutes=24 * index),
                    "measured_value": value,
                }
            )
            measurement_ids.append(next_measurement_id)
            next_measurement_id += 1
        if name:
            scenario_ids[name] = measurement_ids

    baseline_start = datetime(2026, 1, 1, 6)
    for sequence_number in range(30):
        add_sequence(
            "",
            BASELINE_SEQUENCE,
            baseline_start + timedelta(days=sequence_number),
        )

    add_sequence("outlier", OUTLIER_SEQUENCE, datetime(2026, 3, 1, 6))
    add_sequence("shift", SHIFT_SEQUENCE, datetime(2026, 3, 2, 6))
    add_sequence("trend", TREND_SEQUENCE, datetime(2026, 3, 3, 6))
    add_sequence("rule_2", RULE_2_SEQUENCE, datetime(2026, 3, 4, 6))
    add_sequence("rule_3", RULE_3_SEQUENCE, datetime(2026, 3, 5, 6))
    add_sequence("expired", OUTLIER_SEQUENCE, datetime(2026, 3, 6, 6))
    add_sequence("baseline_return", [75.4] * 17, datetime(2026, 3, 7, 6))
    for record in records:
        if record["measurement_id"] in scenario_ids["baseline_return"]:
            record["specification_id"] = 2
    return records, scenario_ids


@pytest.fixture
def production_spc_results():
    """Run the production SQL view against temporary, controlled records.

    The SQL view uses fixed limits from a temporary ACTIVE baseline. Its
    effective dates interpret measurement timestamps in Europe/Budapest.
    """
    database_url = os.getenv("SPC_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip(
            "Set SPC_TEST_DATABASE_URL to the dedicated "
            f"{TEST_DATABASE_NAME} database"
        )

    engine = _create_test_engine(database_url)
    records, scenario_ids = _controlled_records()
    view_source = (REPO_ROOT / "sql" / "views.sql").read_text(encoding="utf-8")
    production_spc_view_sql = _extract_create_view_statement(
        view_source,
        "v_spc_rule_results",
    ).replace(
        "CREATE OR REPLACE VIEW",
        "CREATE TEMP VIEW",
        1,
    )
    compatibility_view_sql = _extract_create_view_statement(
        view_source,
        "v_spc_rule_results_booth01_a_l1",
    ).replace(
        "CREATE OR REPLACE VIEW",
        "CREATE TEMP VIEW",
        1,
    )

    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connected_database = connection.execute(
                    text("SELECT current_database()")
                ).scalar_one()
                assert connected_database == TEST_DATABASE_NAME, (
                    f"Connected to '{connected_database}', expected "
                    f"'{TEST_DATABASE_NAME}'"
                )
                connection.execute(text("SET LOCAL search_path TO pg_temp"))
                connection.execute(
                    text(
                        """
                        CREATE TEMP TABLE dim_shift (
                            shift_id INTEGER PRIMARY KEY,
                            shift_name TEXT NOT NULL,
                            start_time TIME NOT NULL,
                            end_time TIME NOT NULL
                        )
                        """
                    )
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO dim_shift
                            (shift_id, shift_name, start_time, end_time)
                        VALUES (1, 'SHIFT_01', :start_time, :end_time)
                        """
                    ),
                    {"start_time": time(6), "end_time": time(14)},
                )
                connection.execute(
                    text(
                        """
                        CREATE TEMP TABLE spc_baseline (
                            baseline_id BIGINT PRIMARY KEY,
                            booth_id INTEGER NOT NULL,
                            measurement_point_id INTEGER NOT NULL,
                            specification_id INTEGER NOT NULL,
                            version INTEGER NOT NULL,
                            status TEXT NOT NULL,
                            effective_from TIMESTAMPTZ NOT NULL,
                            effective_to TIMESTAMPTZ,
                            center_line NUMERIC(14, 6) NOT NULL,
                            sigma NUMERIC(14, 6) NOT NULL,
                            i_lcl NUMERIC(14, 6) NOT NULL,
                            i_ucl NUMERIC(14, 6) NOT NULL,
                            mr_center NUMERIC(14, 6) NOT NULL,
                            mr_ucl NUMERIC(14, 6) NOT NULL
                        )
                        """
                    )
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO spc_baseline
                        VALUES (
                            1, 1, 1, 1, 1, 'RETIRED',
                            TIMESTAMP '2026-03-01 06:00:00'
                                AT TIME ZONE 'Europe/Budapest',
                            TIMESTAMP '2026-03-05 06:00:00'
                                AT TIME ZONE 'Europe/Budapest',
                            75.0,
                            0.2 / 1.128,
                            75.0 - 3 * (0.2 / 1.128),
                            75.0 + 3 * (0.2 / 1.128),
                            0.2,
                            3.267 * 0.2
                        ), (
                            2, 1, 1, 1, 2, 'ACTIVE',
                            TIMESTAMP '2026-03-04 06:00:00'
                                AT TIME ZONE 'Europe/Budapest',
                            TIMESTAMP '2026-03-06 06:00:00'
                                AT TIME ZONE 'Europe/Budapest',
                            75.0,
                            0.2 / 1.128,
                            75.0 - 3 * (0.2 / 1.128),
                            75.0 + 3 * (0.2 / 1.128),
                            0.2,
                            3.267 * 0.2
                        ), (
                            3, 1, 1, 1, 3, 'DRAFT',
                            TIMESTAMP '2026-03-01 06:00:00'
                                AT TIME ZONE 'Europe/Budapest',
                            TIMESTAMP '2026-03-06 06:00:00'
                                AT TIME ZONE 'Europe/Budapest',
                            90.0,
                            0.2 / 1.128,
                            90.0 - 3 * (0.2 / 1.128),
                            90.0 + 3 * (0.2 / 1.128),
                            0.2,
                            3.267 * 0.2
                        ), (
                            4, 1, 1, 2, 1, 'RETIRED',
                            TIMESTAMP '2026-03-07 06:00:00'
                                AT TIME ZONE 'Europe/Budapest',
                            TIMESTAMP '2026-03-07 14:00:00'
                                AT TIME ZONE 'Europe/Budapest',
                            75.0, 0.2 / 1.128,
                            75.0 - 3 * (0.2 / 1.128),
                            75.0 + 3 * (0.2 / 1.128),
                            0.2, 3.267 * 0.2
                        ), (
                            5, 1, 1, 2, 2, 'ACTIVE',
                            TIMESTAMP '2026-03-07 08:48:00'
                                AT TIME ZONE 'Europe/Budapest',
                            TIMESTAMP '2026-03-07 09:36:00'
                                AT TIME ZONE 'Europe/Budapest',
                            75.0, 0.2 / 1.128,
                            75.0 - 3 * (0.2 / 1.128),
                            75.0 + 3 * (0.2 / 1.128),
                            0.2, 3.267 * 0.2
                        )
                        """
                    )
                )
                connection.execute(
                    text(
                        """
                        CREATE TEMP TABLE controlled_measurements (
                            measurement_id BIGINT PRIMARY KEY,
                            booth_id INTEGER NOT NULL,
                            booth_name TEXT NOT NULL,
                            measurement_point_id INTEGER NOT NULL,
                            point_code TEXT NOT NULL,
                            specification_id INTEGER NOT NULL,
                            shift_id INTEGER NOT NULL,
                            shift_name TEXT NOT NULL,
                            batch_start TIMESTAMP NOT NULL,
                            measurement_timestamp TIMESTAMP NOT NULL,
                            measured_value NUMERIC(10, 3) NOT NULL
                        )
                        """
                    )
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO controlled_measurements
                        VALUES (
                            :measurement_id, :booth_id, :booth_name,
                            :measurement_point_id, :point_code,
                            :specification_id, :shift_id, :shift_name,
                            :batch_start, :measurement_timestamp, :measured_value
                        )
                        """
                    ),
                    records,
                )
                connection.execute(
                    text(
                        """
                        CREATE TEMP VIEW v_measurement_enriched AS
                        SELECT measurement_id, booth_id, booth_name,
                               measurement_point_id, point_code,
                               specification_id, shift_id, shift_name,
                               batch_start, measurement_timestamp, measured_value
                        FROM controlled_measurements
                        """
                    )
                )
                connection.execute(text(production_spc_view_sql))
                connection.execute(text(compatibility_view_sql))
                results = pd.read_sql_query(
                    text(
                        """
                        SELECT measurement_id, measurement_timestamp,
                               baseline_id, measured_value, moving_range,
                               center_line, sigma, i_lcl, i_ucl,
                               mr_center, mr_ucl,
                               rule_1, rule_2, rule_3, rule_4, spc_signal
                        FROM v_spc_rule_results
                        ORDER BY measurement_timestamp, measurement_id
                        """
                    ),
                    connection,
                )
                compatibility_results = pd.read_sql_query(
                    text(
                        """
                        SELECT measurement_timestamp, measurement_id,
                               booth, measurement_point, shift_id,
                               shift_name, shift_instance, measured_value,
                               moving_range, center_line, sigma, lcl, ucl,
                               rule_1, rule_2, rule_3, rule_4, spc_signal
                        FROM v_spc_rule_results_booth01_a_l1
                        ORDER BY measurement_timestamp, measurement_id
                        """
                    ),
                    connection,
                )
                yield results, scenario_ids, compatibility_results
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


def test_production_spc_view_detects_controlled_patterns(production_spc_results):
    results, scenario_ids, _ = production_spc_results
    indexed = results.set_index("measurement_id")

    outlier_id = scenario_ids["outlier"][1]
    assert bool(indexed.loc[outlier_id, "rule_1"])
    assert bool(indexed.loc[outlier_id, "spc_signal"])
    assert indexed.loc[scenario_ids["outlier"][0], "baseline_id"] == 1
    assert indexed.loc[scenario_ids["outlier"][0], "i_lcl"] == pytest.approx(
        75.0 - 3 * (0.2 / 1.128)
    )
    assert indexed.loc[scenario_ids["outlier"][0], "i_ucl"] == pytest.approx(
        75.0 + 3 * (0.2 / 1.128)
    )

    shift_results = indexed.loc[scenario_ids["shift"]]
    assert shift_results["rule_4"].astype(bool).any()

    trend_results = indexed.loc[scenario_ids["trend"]]
    assert trend_results[["rule_2", "rule_3"]].astype(bool).any(axis=None)


def test_retired_baselines_remain_historical_and_measurements_match_once(
    production_spc_results,
):
    results, scenario_ids, _ = production_spc_results

    assert results["measurement_id"].is_unique
    assert results.set_index("measurement_id").loc[
        scenario_ids["outlier"][0], "baseline_id"
    ] == 1
    assert results.set_index("measurement_id").loc[
        scenario_ids["rule_2"][0], "baseline_id"
    ] == 2
    assert pd.isna(results.set_index("measurement_id").loc[
        scenario_ids["expired"][0], "baseline_id"
    ])


def test_applicable_draft_baseline_is_not_selected(production_spc_results):
    results, scenario_ids, _ = production_spc_results
    indexed = results.set_index("measurement_id")

    selected = indexed.loc[scenario_ids["rule_2"][0]]
    assert selected["baseline_id"] == 2
    assert results["measurement_id"].is_unique


def test_overlapping_baseline_return_starts_new_rule_and_mr_segment(
    production_spc_results,
):
    results, scenario_ids, _ = production_spc_results
    scenario = results.set_index("measurement_id").loc[
        scenario_ids["baseline_return"]
    ]

    assert scenario["baseline_id"].tolist() == [4] * 7 + [5] * 2 + [4] * 8
    for start, size in ((0, 7), (7, 2), (9, 8)):
        segment = scenario.iloc[start : start + size]
        assert pd.isna(segment["moving_range"].iloc[0])
        assert segment["moving_range"].iloc[1:].astype(float).tolist() == (
            pytest.approx([0.0] * (size - 1))
        )
        assert segment["rule_1"].astype(bool).tolist() == [False] * size
        assert segment["rule_2"].astype(bool).tolist() == [
            index >= 2 for index in range(size)
        ]
        assert segment["rule_3"].astype(bool).tolist() == [
            index >= 4 for index in range(size)
        ]
        assert segment["rule_4"].astype(bool).tolist() == [
            index >= 7 for index in range(size)
        ]


@pytest.fixture
def migrated_baseline_table():
    database_url = os.getenv("SPC_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip(
            "Set SPC_TEST_DATABASE_URL to the dedicated "
            f"{TEST_DATABASE_NAME} database"
        )

    engine = _create_test_engine(database_url)
    schema_name = f"spc_migration_test_{uuid.uuid4().hex}"
    quoted_schema = engine.dialect.identifier_preparer.quote(schema_name)
    migration_path = REPO_ROOT / "sql" / "migrations" / "001_create_spc_baseline.sql"
    migration_sql = migration_path.read_text(encoding="utf-8")
    migration_sql = re.sub(r"(?im)^\s*BEGIN;\s*$", "", migration_sql)
    migration_sql = re.sub(r"(?im)^\s*COMMIT;\s*$", "", migration_sql)

    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connected_database = connection.execute(
                    text("SELECT current_database()")
                ).scalar_one()
                assert connected_database == TEST_DATABASE_NAME, (
                    f"Connected to '{connected_database}', expected "
                    f"'{TEST_DATABASE_NAME}'"
                )
                connection.exec_driver_sql(f"CREATE SCHEMA {quoted_schema}")
                connection.exec_driver_sql(
                    f"SET LOCAL search_path TO {quoted_schema}"
                )
                connection.exec_driver_sql(
                    """
                    CREATE TABLE dim_booth (booth_id INTEGER PRIMARY KEY);
                    CREATE TABLE dim_measurement_point (
                        measurement_point_id INTEGER PRIMARY KEY
                    );
                    CREATE TABLE dim_specification (
                        specification_id INTEGER PRIMARY KEY
                    );
                    INSERT INTO dim_booth VALUES (1), (2);
                    INSERT INTO dim_measurement_point VALUES (1), (2);
                    INSERT INTO dim_specification VALUES (1), (2);
                    """
                )
                connection.exec_driver_sql(migration_sql)
                yield connection
            finally:
                if transaction.is_active:
                    transaction.rollback()
                schema_exists = connection.execute(
                    text(
                        "SELECT EXISTS ("
                        "SELECT 1 FROM pg_namespace WHERE nspname = :schema_name"
                        ")"
                    ),
                    {"schema_name": schema_name},
                ).scalar_one()
                schema_object_count = connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM pg_class AS relation
                        JOIN pg_namespace AS namespace
                          ON namespace.oid = relation.relnamespace
                        WHERE namespace.nspname = :schema_name
                        """
                    ),
                    {"schema_name": schema_name},
                ).scalar_one()
                function_count = connection.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM pg_proc AS function
                        JOIN pg_namespace AS namespace
                          ON namespace.oid = function.pronamespace
                        WHERE namespace.nspname = :schema_name
                        """
                    ),
                    {"schema_name": schema_name},
                ).scalar_one()
                assert not schema_exists
                assert schema_object_count == 0
                assert function_count == 0
    finally:
        engine.dispose()


def _baseline_values(**overrides):
    values = {
        "booth_id": 1,
        "measurement_point_id": 1,
        "specification_id": 1,
        "version": 1,
        "window_start": "2026-01-01 00:00:00+00",
        "window_end": "2026-02-01 00:00:00+00",
        "status": "ACTIVE",
        "effective_from": "2026-02-01 00:00:00+00",
        "effective_to": None,
        "approved_by": "quality",
        "approved_at": "2026-01-31 00:00:00+00",
        "n_observations": 10,
        "n_valid_mr": 9,
        "center_line": 75.0,
        "sigma": 0.177305,
        "i_lcl": 74.468085,
        "i_ucl": 75.531915,
        "mr_center": 0.2,
        "mr_ucl": 0.6534,
        "supersedes_baseline_id": None,
    }
    return values | overrides


def _insert_baseline(connection, **overrides):
    values = _baseline_values(**overrides)
    columns = ", ".join(values)
    parameters = ", ".join(f":{column}" for column in values)
    return connection.execute(
        text(
            f"INSERT INTO spc_baseline ({columns}) "
            f"VALUES ({parameters}) RETURNING baseline_id"
        ),
        values,
    ).scalar_one()


def _assert_constraint_violation(connection, constraint_name, **overrides):
    with pytest.raises(IntegrityError) as error:
        with connection.begin_nested():
            _insert_baseline(connection, **overrides)
    assert error.value.orig.diag.constraint_name == constraint_name


def test_postgresql_migration_constraints_and_numeric_tolerance(
    migrated_baseline_table,
):
    connection = migrated_baseline_table

    first_id = _insert_baseline(connection)
    assert first_id > 0
    assert connection.execute(
        text(
            "SELECT supersedes_baseline_id IS NULL "
            "FROM spc_baseline WHERE baseline_id = :baseline_id"
        ),
        {"baseline_id": first_id},
    ).scalar_one()

    # The stored six-decimal sigma is within the migration's 0.000003 tolerance.
    accepted_sigma_id = _insert_baseline(
        connection,
        version=2,
        status="DRAFT",
        effective_from=None,
        effective_to=None,
        approved_by=None,
        approved_at=None,
        sigma=0.177307,
        i_lcl=74.468079,
        i_ucl=75.531921,
    )
    assert accepted_sigma_id > first_id
    exact_tolerance_id = _insert_baseline(
        connection,
        version=3,
        status="DRAFT",
        effective_from=None,
        effective_to=None,
        approved_by=None,
        approved_at=None,
        sigma=1.000003,
        mr_center=1.128,
        i_lcl=71.999994,
        i_ucl=78.000012,
        mr_ucl=3.685179,
    )
    assert exact_tolerance_id > accepted_sigma_id
    _insert_baseline(
        connection,
        version=4,
        status="DRAFT",
        effective_from=None,
        effective_to=None,
        approved_by=None,
        approved_at=None,
        i_lcl=74.468087,
    )
    _insert_baseline(
        connection,
        version=5,
        status="DRAFT",
        effective_from=None,
        effective_to=None,
        approved_by=None,
        approved_at=None,
        mr_ucl=0.653402,
    )

    _assert_constraint_violation(
        connection,
        "chk_spc_baseline_i_chart_limits",
        version=6,
        status="DRAFT",
        effective_from=None,
        effective_to=None,
        approved_by=None,
        approved_at=None,
        sigma=1.000004,
        mr_center=1.128,
        i_lcl=71.999992,
        i_ucl=78.000016,
        mr_ucl=3.685180,
    )

    _assert_constraint_violation(
        connection,
        "chk_spc_baseline_version",
        version=0,
    )
    _assert_constraint_violation(
        connection,
        "chk_spc_baseline_status",
        version=10,
        status="PENDING",
    )
    _assert_constraint_violation(
        connection,
        "chk_spc_baseline_window",
        version=11,
        window_end="2026-01-01 00:00:00+00",
    )
    _assert_constraint_violation(
        connection,
        "chk_spc_baseline_effective_period",
        version=12,
        effective_to="2026-02-01 00:00:00+00",
    )
    _assert_constraint_violation(
        connection,
        "chk_spc_baseline_active_effective_from",
        version=13,
        effective_from=None,
        effective_to=None,
    )
    _assert_constraint_violation(
        connection,
        "chk_spc_baseline_retired_effective_to",
        version=14,
        status="RETIRED",
        effective_to=None,
    )
    _assert_constraint_violation(
        connection,
        "chk_spc_baseline_active_approval",
        version=15,
        approved_by="   ",
    )
    _assert_constraint_violation(
        connection,
        "chk_spc_baseline_i_chart_limits",
        version=17,
        status="DRAFT",
        effective_from=None,
        effective_to=None,
        approved_by=None,
        approved_at=None,
        sigma=0.177309,
        i_lcl=74.468073,
        i_ucl=75.531927,
    )
    _assert_constraint_violation(
        connection,
        "chk_spc_baseline_i_chart_limits",
        version=18,
        status="DRAFT",
        effective_from=None,
        effective_to=None,
        approved_by=None,
        approved_at=None,
        i_lcl=74.468089,
    )
    _assert_constraint_violation(
        connection,
        "chk_spc_baseline_mr_limits",
        version=19,
        status="DRAFT",
        effective_from=None,
        effective_to=None,
        approved_by=None,
        approved_at=None,
        mr_ucl=0.653404,
    )

    _assert_constraint_violation(
        connection,
        "chk_spc_baseline_counts",
        version=20,
        n_valid_mr=0,
    )
    _assert_constraint_violation(
        connection,
        "chk_spc_baseline_counts",
        version=20,
        n_valid_mr=10,
    )
    multi_shift_id = _insert_baseline(
        connection, version=20, status="DRAFT", effective_from=None,
        approved_by=None, approved_at=None, n_valid_mr=8,
    )
    assert multi_shift_id > first_id
    _assert_constraint_violation(
        connection,
        "uq_spc_baseline_scope_version",
        version=1,
    )
    _assert_constraint_violation(
        connection,
        "uq_spc_baseline_one_active_per_scope",
        version=21,
    )
    _assert_constraint_violation(
        connection,
        "fk_spc_baseline_booth",
        version=22,
        booth_id=99,
    )
    _assert_constraint_violation(
        connection,
        "fk_spc_baseline_measurement_point",
        version=23,
        measurement_point_id=99,
    )
    _assert_constraint_violation(
        connection,
        "fk_spc_baseline_specification",
        version=24,
        specification_id=99,
    )

    _assert_constraint_violation(
        connection,
        "fk_spc_baseline_supersedes_same_scope",
        booth_id=2,
        measurement_point_id=2,
        specification_id=2,
        version=25,
        status="DRAFT",
        effective_from=None,
        effective_to=None,
        approved_by=None,
        approved_at=None,
        supersedes_baseline_id=first_id,
    )
    higher_id = _insert_baseline(
        connection, version=40, status="DRAFT",
        effective_from=None, effective_to=None,
        approved_by=None, approved_at=None,
    )
    _assert_constraint_violation(
        connection,
        "chk_spc_baseline_supersedes_lower_version",
        version=30,
        status="DRAFT",
        effective_from=None,
        effective_to=None,
        approved_by=None,
        approved_at=None,
        supersedes_baseline_id=higher_id,
    )

    retired_id = connection.execute(
        text(
            "UPDATE spc_baseline SET status = 'RETIRED', "
            "effective_to = '2026-03-01 00:00:00+00' "
            "WHERE baseline_id = :baseline_id "
            "RETURNING baseline_id"
        ),
        {"baseline_id": first_id},
    ).scalar_one()
    assert retired_id == first_id
    successor_id = _insert_baseline(
        connection,
        version=26,
        effective_from="2026-03-01 00:00:00+00",
        supersedes_baseline_id=first_id,
    )
    assert successor_id > retired_id

    # Allow UPDATE to reach the trigger; GENERATED ALWAYS rejects assignment first.
    connection.exec_driver_sql(
        "ALTER TABLE spc_baseline "
        "ALTER COLUMN baseline_id SET GENERATED BY DEFAULT"
    )
    with pytest.raises(IntegrityError) as error:
        with connection.begin_nested():
            connection.execute(
                text(
                    "UPDATE spc_baseline SET baseline_id = baseline_id + 100000 "
                    "WHERE baseline_id = :baseline_id"
                ),
                {"baseline_id": successor_id},
            )
    assert error.value.orig.diag.constraint_name == (
        "chk_spc_baseline_immutable_version"
    )

    with pytest.raises(IntegrityError) as error:
        with connection.begin_nested():
            connection.execute(
                text(
                    "UPDATE spc_baseline SET booth_id = 2 "
                    "WHERE baseline_id = :baseline_id"
                ),
                {"baseline_id": successor_id},
            )
    assert error.value.orig.diag.constraint_name == (
        "chk_spc_baseline_immutable_version"
    )

    with pytest.raises(IntegrityError) as error:
        with connection.begin_nested():
            connection.execute(
                text(
                    "UPDATE spc_baseline "
                    "SET supersedes_baseline_id = baseline_id "
                    "WHERE baseline_id = :baseline_id"
                ),
                {"baseline_id": accepted_sigma_id},
            )
    assert error.value.orig.diag.constraint_name == (
        "chk_spc_baseline_not_self_superseding"
    )

    with pytest.raises(IntegrityError) as error:
        with connection.begin_nested():
            connection.execute(
                text(
                    "UPDATE spc_baseline "
                    "SET supersedes_baseline_id = :successor_id "
                    "WHERE baseline_id = :baseline_id"
                ),
                {"successor_id": successor_id, "baseline_id": first_id},
            )
    assert error.value.orig.diag.constraint_name == (
        "chk_spc_baseline_immutable_approved"
    )

    with pytest.raises(IntegrityError) as error:
        with connection.begin_nested():
            connection.execute(
                text("UPDATE spc_baseline SET version = 0 WHERE baseline_id = :id"),
                {"id": first_id},
            )
    assert error.value.orig.diag.constraint_name == (
        "chk_spc_baseline_immutable_version"
    )


def _insert_forward_baselines(connection, first_version, second_version, cyclic=False):
    connection.execute(
        text(
            """
            INSERT INTO spc_baseline (
                baseline_id, booth_id, measurement_point_id, specification_id,
                version, window_start, window_end, status, n_observations,
                n_valid_mr, center_line, sigma, i_lcl, i_ucl, mr_center, mr_ucl,
                supersedes_baseline_id
            ) OVERRIDING SYSTEM VALUE VALUES
                (10001, 1, 1, 1, :first_version, '2026-01-01', '2026-02-01',
                 'DRAFT', 2, 1, 75, 0, 75, 75, 0, 0, 10002),
                (10002, 1, 1, 1, :second_version, '2026-01-01', '2026-02-01',
                 'DRAFT', 2, 1, 75, 0, 75, 75, 0, 0, :second_predecessor)
            """
        ),
        {
            "first_version": first_version,
            "second_version": second_version,
            "second_predecessor": 10001 if cyclic else None,
        },
    )


def test_supersession_validates_forward_rows_and_deferred_cycles(migrated_baseline_table):
    connection = migrated_baseline_table
    with pytest.raises(IntegrityError) as error:
        with connection.begin_nested():
            _insert_forward_baselines(connection, 1, 2)
    assert error.value.orig.diag.constraint_name == (
        "chk_spc_baseline_supersedes_lower_version"
    )

    with pytest.raises(IntegrityError) as error:
        with connection.begin_nested():
            connection.execute(text("SET CONSTRAINTS trg_spc_baseline_supersession DEFERRED"))
            _insert_forward_baselines(connection, 2, 1, cyclic=True)
            connection.execute(text("SET CONSTRAINTS trg_spc_baseline_supersession IMMEDIATE"))
    assert error.value.orig.diag.constraint_name == (
        "chk_spc_baseline_supersedes_lower_version"
    )

    _insert_forward_baselines(connection, 2, 1)
    assert connection.execute(
        text("SELECT count(*) FROM spc_baseline WHERE baseline_id IN (10001, 10002)")
    ).scalar_one() == 2


def test_supersession_ignores_shadowing_temporary_table(migrated_baseline_table):
    connection = migrated_baseline_table
    schema = connection.execute(text("SELECT current_schema()")).scalar_one()
    quoted_schema = connection.dialect.identifier_preparer.quote(schema)
    predecessor_id = _insert_baseline(
        connection, version=2, status="DRAFT", effective_from=None,
        approved_by=None, approved_at=None,
    )
    connection.execute(
        text("CREATE TEMP TABLE spc_baseline (baseline_id BIGINT, version INTEGER)")
    )
    connection.execute(
        text("INSERT INTO pg_temp.spc_baseline VALUES (:id, 0)"),
        {"id": predecessor_id},
    )
    values = _baseline_values(
        version=1, status="DRAFT", effective_from=None, approved_by=None,
        approved_at=None, supersedes_baseline_id=predecessor_id,
    )
    columns = ", ".join(values)
    parameters = ", ".join(f":{column}" for column in values)
    with pytest.raises(IntegrityError) as error:
        with connection.begin_nested():
            connection.execute(
                text(
                    f"INSERT INTO {quoted_schema}.spc_baseline ({columns}) "
                    f"VALUES ({parameters})"
                ),
                values,
            )
    assert error.value.orig.diag.constraint_name == (
        "chk_spc_baseline_supersedes_lower_version"
    )


def test_approved_baseline_data_are_immutable(migrated_baseline_table):
    connection = migrated_baseline_table
    baseline_id = _insert_baseline(connection)
    with pytest.raises(IntegrityError) as error:
        with connection.begin_nested():
            connection.execute(
                text("DELETE FROM spc_baseline WHERE baseline_id = :id"),
                {"id": baseline_id},
            )
    assert error.value.orig.diag.constraint_name == "chk_spc_baseline_immutable_approved"
    changes = {
        "window_start": "2025-12-01 00:00:00+00",
        "window_end": "2026-01-31 00:00:00+00",
        "n_observations": 11,
        "n_valid_mr": 8,
        "center_line": 76,
        "sigma": 0.2,
        "i_lcl": 73,
        "i_ucl": 79,
        "mr_center": 0.3,
        "mr_ucl": 0.9,
        "source_query_hash": "changed",
        "approved_by": "other",
        "approved_at": "2026-01-30 00:00:00+00",
        "supersedes_baseline_id": 9999,
        "effective_from": "2026-02-02 00:00:00+00",
    }
    for column, value in changes.items():
        with pytest.raises(IntegrityError) as error:
            with connection.begin_nested():
                connection.execute(
                    text(f"UPDATE spc_baseline SET {column} = :value WHERE baseline_id = :id"),
                    {"value": value, "id": baseline_id},
                )
        assert error.value.orig.diag.constraint_name == (
            "chk_spc_baseline_immutable_approved"
        ), column

    connection.execute(
        text(
            "UPDATE spc_baseline SET status = 'RETIRED', "
            "effective_to = '2026-03-01 00:00:00+00' WHERE baseline_id = :id"
        ),
        {"id": baseline_id},
    )
    with pytest.raises(IntegrityError) as error:
        with connection.begin_nested():
            connection.execute(
                text("UPDATE spc_baseline SET center_line = 76 WHERE baseline_id = :id"),
                {"id": baseline_id},
            )
    assert error.value.orig.diag.constraint_name == "chk_spc_baseline_immutable_approved"
    with pytest.raises(IntegrityError) as error:
        with connection.begin_nested():
            connection.execute(
                text("DELETE FROM spc_baseline WHERE baseline_id = :id"),
                {"id": baseline_id},
            )
    assert error.value.orig.diag.constraint_name == "chk_spc_baseline_immutable_approved"
    with pytest.raises(IntegrityError) as error:
        with connection.begin_nested():
            connection.execute(
                text("UPDATE spc_baseline SET status = 'DRAFT' WHERE baseline_id = :id"),
                {"id": baseline_id},
            )
    assert error.value.orig.diag.constraint_name == "chk_spc_baseline_lifecycle"
    with pytest.raises(IntegrityError) as error:
        with connection.begin_nested():
            connection.execute(
                text(
                    "UPDATE spc_baseline SET effective_to = '2026-03-02 00:00:00+00' "
                    "WHERE baseline_id = :id"
                ),
                {"id": baseline_id},
            )
    assert error.value.orig.diag.constraint_name == "chk_spc_baseline_lifecycle"

    _assert_constraint_violation(
        connection, "chk_spc_baseline_active_approval",
        version=2, status="RETIRED", effective_to="2026-03-01 00:00:00+00",
        approved_by=None,
    )
    draft_id = _insert_baseline(
        connection, version=3, status="DRAFT", effective_from=None,
        approved_by=None, approved_at=None,
    )
    connection.execute(
        text(
            "UPDATE spc_baseline SET source_query_hash = 'draft', "
            "window_start = '2025-12-01 00:00:00+00', "
            "center_line = 76, i_lcl = 75.468085, i_ucl = 76.531915 "
            "WHERE baseline_id = :id"
        ),
        {"id": draft_id},
    )
    assert connection.execute(
        text("SELECT source_query_hash FROM spc_baseline WHERE baseline_id = :id"),
        {"id": draft_id},
    ).scalar_one() == "draft"
    connection.execute(
        text("DELETE FROM spc_baseline WHERE baseline_id = :id"), {"id": draft_id}
    )


def test_production_spc_view_detects_rule_2_two_of_three_beyond_2_sigma(
    production_spc_results,
):
    results, scenario_ids, _ = production_spc_results
    scenario = results.set_index("measurement_id").loc[scenario_ids["rule_2"]]

    assert scenario["rule_2"].astype(bool).tolist() == [
        False,
        False,
        True,
        True,
        False,
    ]
    assert not scenario["rule_1"].astype(bool).any()
    assert not scenario["rule_3"].astype(bool).any()
    assert not scenario["rule_4"].astype(bool).any()


def test_production_spc_view_detects_rule_3_four_of_five_beyond_1_sigma(
    production_spc_results,
):
    results, scenario_ids, _ = production_spc_results
    scenario = results.set_index("measurement_id").loc[scenario_ids["rule_3"]]

    assert scenario["rule_3"].astype(bool).tolist() == [
        False,
        False,
        False,
        False,
        True,
        True,
    ]
    assert not scenario["rule_1"].astype(bool).any()
    assert not scenario["rule_2"].astype(bool).any()
    assert not scenario["rule_4"].astype(bool).any()


def test_production_spc_view_mr_matches_baseline_fitted_limit(
    production_spc_results,
):
    results, scenario_ids, _ = production_spc_results
    baseline_summary = summarize_mr_violations(
        pd.Series(_baseline_moving_ranges(), dtype="float64")
    )
    outlier_results = results.set_index("measurement_id").loc[
        scenario_ids["outlier"]
    ]
    valid_outlier_mrs = outlier_results["moving_range"].dropna().astype(float)

    assert valid_outlier_mrs.tolist() == pytest.approx([5.0, 5.0])
    assert valid_outlier_mrs.gt(baseline_summary.upper_control_limit).all()
    assert outlier_results["mr_ucl"].astype(float).tolist() == pytest.approx(
        [0.6534, 0.6534, 0.6534]
    )


def test_unbased_and_expired_measurements_have_no_limits_or_signals(
    production_spc_results,
):
    results, scenario_ids, _ = production_spc_results
    indexed = results.set_index("measurement_id")

    records, _ = _controlled_records()
    unbased_ids = [
        record["measurement_id"]
        for record in records
        if record["measurement_timestamp"] < datetime(2026, 3, 1, 6)
    ]
    unbased = indexed.loc[unbased_ids]
    expired = indexed.loc[scenario_ids["expired"]]
    limit_columns = [
        "baseline_id",
        "center_line",
        "sigma",
        "i_lcl",
        "i_ucl",
        "mr_center",
        "mr_ucl",
    ]
    rule_columns = ["rule_1", "rule_2", "rule_3", "rule_4", "spc_signal"]

    assert unbased[limit_columns].isna().all().all()
    assert not unbased[rule_columns].astype(bool).any().any()
    assert expired[limit_columns].isna().all().all()
    assert not expired[rule_columns].astype(bool).any().any()


def test_compatibility_view_preserves_legacy_columns(production_spc_results):
    results, _, compatibility_results = production_spc_results

    assert compatibility_results.columns.tolist() == [
        "measurement_timestamp",
        "measurement_id",
        "booth",
        "measurement_point",
        "shift_id",
        "shift_name",
        "shift_instance",
        "measured_value",
        "moving_range",
        "center_line",
        "sigma",
        "lcl",
        "ucl",
        "rule_1",
        "rule_2",
        "rule_3",
        "rule_4",
        "spc_signal",
    ]
    assert compatibility_results["measurement_id"].tolist() == (
        results["measurement_id"].tolist()
    )
    assert np.allclose(
        compatibility_results["lcl"].astype(float),
        results["i_lcl"].astype(float),
        equal_nan=True,
    )
    assert np.allclose(
        compatibility_results["ucl"].astype(float),
        results["i_ucl"].astype(float),
        equal_nan=True,
    )
