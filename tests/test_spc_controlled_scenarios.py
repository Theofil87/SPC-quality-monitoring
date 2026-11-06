from __future__ import annotations

from datetime import datetime, time, timedelta
import os
from pathlib import Path
import re

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine, make_url, text

from src.spc_monitoring import summarize_mr_violations


REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_DATABASE_NAME = "spc_quality_monitoring_test"
LOCAL_DATABASE_HOSTS = {"localhost", "127.0.0.1", "::1"}
BASELINE_SEQUENCE = [74.9, 75.1] * 5
OUTLIER_SEQUENCE = [75.0, 80.0, 75.0]
SHIFT_SEQUENCE = [76.0] * 10
TREND_SEQUENCE = [75.1 + 0.25 * index for index in range(12)]
# With the fixture-fitted limits (center ~75.11, sigma ~0.21), 75.65 lies between
# +2 and +3 sigma and 75.43 lies between +1 and +2 sigma.
RULE_2_SEQUENCE = [75.0, 75.65, 75.65, 75.0, 75.0]
RULE_3_SEQUENCE = [75.0, 75.43, 75.43, 75.43, 75.43, 75.0]


def _baseline_moving_ranges() -> list[float]:
    moving_ranges = []
    for _ in range(30):
        moving_ranges.extend(np.abs(np.diff(BASELINE_SEQUENCE)).tolist())
    return moving_ranges


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
    return records, scenario_ids


@pytest.fixture
def production_spc_results():
    """Run the production SQL view against temporary, controlled records.

    The SQL view intentionally fits I-chart limits over every row supplied
    by this fixture. The separate MR test fits its limits on stable baseline
    moving ranges only and evaluates scenario moving ranges against that UCL.
    """
    database_url = os.getenv("SPC_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip(
            "Set SPC_TEST_DATABASE_URL to the dedicated "
            f"{TEST_DATABASE_NAME} database"
        )

    parsed_url = make_url(database_url)
    if parsed_url.database != TEST_DATABASE_NAME:
        pytest.fail(
            "SPC_TEST_DATABASE_URL must target the dedicated "
            f"'{TEST_DATABASE_NAME}' database; refusing to connect "
            "to any other database"
        )
    if (parsed_url.host or "").lower() not in LOCAL_DATABASE_HOSTS:
        pytest.fail(
            "SPC_TEST_DATABASE_URL must use a local PostgreSQL host "
            "(localhost, 127.0.0.1, or ::1)"
        )

    engine = create_engine(database_url)
    records, scenario_ids = _controlled_records()
    view_source = (REPO_ROOT / "sql" / "views.sql").read_text(encoding="utf-8")
    match = re.search(
        r"CREATE OR REPLACE VIEW v_spc_rule_results_booth01_a_l1 AS.*?;",
        view_source,
        flags=re.DOTALL,
    )
    assert match is not None, "Production SPC view definition was not found"
    production_spc_view_sql = match.group(0).replace(
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
                results = pd.read_sql_query(
                    text(
                        """
                        SELECT measurement_id, measurement_timestamp,
                               measured_value, moving_range,
                               rule_1, rule_2, rule_3, rule_4, spc_signal
                        FROM v_spc_rule_results_booth01_a_l1
                        ORDER BY measurement_timestamp, measurement_id
                        """
                    ),
                    connection,
                )
                yield results, scenario_ids
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


def test_production_spc_view_detects_controlled_patterns(production_spc_results):
    results, scenario_ids = production_spc_results
    indexed = results.set_index("measurement_id")

    outlier_id = scenario_ids["outlier"][1]
    assert bool(indexed.loc[outlier_id, "rule_1"])
    assert bool(indexed.loc[outlier_id, "spc_signal"])

    shift_results = indexed.loc[scenario_ids["shift"]]
    assert shift_results["rule_4"].astype(bool).any()

    trend_results = indexed.loc[scenario_ids["trend"]]
    assert trend_results[["rule_2", "rule_3"]].astype(bool).any(axis=None)


def test_production_spc_view_detects_rule_2_two_of_three_beyond_2_sigma(
    production_spc_results,
):
    results, scenario_ids = production_spc_results
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
    results, scenario_ids = production_spc_results
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
    results, scenario_ids = production_spc_results
    baseline_summary = summarize_mr_violations(
        pd.Series(_baseline_moving_ranges(), dtype="float64")
    )
    outlier_results = results.set_index("measurement_id").loc[
        scenario_ids["outlier"]
    ]
    valid_outlier_mrs = outlier_results["moving_range"].dropna().astype(float)

    assert valid_outlier_mrs.tolist() == pytest.approx([5.0, 5.0])
    assert valid_outlier_mrs.gt(baseline_summary.upper_control_limit).all()
