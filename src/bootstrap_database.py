"""Build and validate the canonical SPC database from an empty PostgreSQL database."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.engine import Engine, URL

from src.data_generation.generate_data import (
    build_all_tables,
    validate_generated_data,
    write_tables,
)
from src.spc_monitoring import BaselineLimits, fit_baseline


REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_SCOPE_BOOTH = "BOOTH_01"
BASELINE_SCOPE_POINT = "A-L1"
BASELINE_SCOPE_CHARACTERISTIC = "Coating Thickness"
BASELINE_SCOPE_UNIT = "um"
BASELINE_WINDOW_DAYS = 18
BASELINE_TIMEZONE = "Europe/Budapest"
BASELINE_APPROVER = "Canonical bootstrap"
BASELINE_RATIONALE = (
    "Deterministic synthetic-data baseline created by the canonical database bootstrap."
)

_SCHEMA_SQL = REPO_ROOT / "sql" / "schema.sql"
_MIGRATION_SQL = REPO_ROOT / "sql" / "migrations" / "001_create_spc_baseline.sql"
_LOAD_SQL = REPO_ROOT / "sql" / "load.sql"
_VIEWS_SQL = REPO_ROOT / "sql" / "views.sql"
_BOOTSTRAP_VALIDATION_SQL = REPO_ROOT / "sql" / "validate_bootstrap.sql"
_SPC_RULE_TEST_SQL = REPO_ROOT / "sql" / "analysis" / "test_spc_rules.sql"
_SPC_SUMMARY_TEST_SQL = REPO_ROOT / "sql" / "analysis" / "test_spc_signal_summary.sql"

_DECIMAL_QUANTUM = Decimal("0.000001")


@dataclass(frozen=True)
class BootstrapOptions:
    database_url: URL
    booth: str
    measurement_point: str
    characteristic: str
    unit: str
    baseline_window_days: int
    approved_by: str


@dataclass(frozen=True)
class BootstrapResult:
    baseline_id: int
    source_query_hash: str
    measurement_count: int
    baseline_observation_count: int
    baseline_valid_mr_count: int
    eligible_spc_count: int
    baseline_covered_count: int
    spc_signal_count: int
    limits: BaselineLimits

    def as_dict(self) -> dict[str, Any]:
        return {
            "baseline_id": self.baseline_id,
            "source_query_hash": self.source_query_hash,
            "measurement_count": self.measurement_count,
            "baseline_observation_count": self.baseline_observation_count,
            "baseline_valid_mr_count": self.baseline_valid_mr_count,
            "eligible_spc_count": self.eligible_spc_count,
            "baseline_covered_count": self.baseline_covered_count,
            "spc_signal_count": self.spc_signal_count,
            "center_line": self.limits.center_line,
            "sigma": self.limits.sigma,
            "i_lcl": self.limits.i_lcl,
            "i_ucl": self.limits.i_ucl,
            "mr_center": self.limits.mr_center,
            "mr_ucl": self.limits.mr_ucl,
        }


def execution_plan() -> tuple[str, ...]:
    """Return the canonical bootstrap stages in execution order."""
    return (
        "verify empty database",
        "generate deterministic CSV data",
        "apply database schema",
        "apply SPC baseline migration",
        "load dimensions and measurements",
        "fit baseline with src.spc_monitoring.fit_baseline",
        "persist and activate baseline",
        "create SQL analytical views",
        "run SQL data and SPC regression validations",
    )


def _database_url(value: str | None) -> URL:
    raw_url = value or os.getenv("SPC_BOOTSTRAP_DATABASE_URL")
    if raw_url:
        parsed = make_url(raw_url)
        if parsed.query:
            raise ValueError("database URL must not contain query parameters")
        if parsed.drivername not in {"postgresql", "postgresql+psycopg2"}:
            raise ValueError("database URL must use the psycopg2 PostgreSQL driver")
        parsed = parsed.set(drivername="postgresql+psycopg2")
        if not parsed.database or not parsed.host or parsed.port is None or not parsed.username:
            raise ValueError(
                "database URL must include host, port, database, and username"
            )
        return parsed

    database = os.getenv("PGDATABASE", "spc_quality_monitoring")
    host = os.getenv("PGHOST", "localhost")
    port = int(os.getenv("PGPORT", "5432"))
    username = os.getenv("PGUSER", "postgres")
    return URL.create(
        drivername="postgresql+psycopg2",
        username=username,
        password=os.getenv("PGPASSWORD") or None,
        host=host,
        port=port,
        database=database,
    )


def _run_psql(options: BootstrapOptions, script: Path, *, cwd: Path) -> None:
    executable = shutil.which("psql")
    if executable is None:
        raise RuntimeError("psql must be installed and available on PATH")
    url = options.database_url
    environment = os.environ.copy()
    environment.update(
        {
            "PGHOST": url.host or "",
            "PGPORT": str(url.port or 5432),
            "PGDATABASE": url.database or "",
            "PGUSER": url.username or "",
        }
    )
    if url.password is not None:
        environment["PGPASSWORD"] = url.password
    command = [
        executable,
        "-X",
        "-w",
        "-v",
        "ON_ERROR_STOP=1",
        "-f",
        str(script),
        url.database or "",
    ]
    subprocess.run(command, cwd=cwd, env=environment, check=True)


def _assert_empty_database(engine: Engine) -> None:
    with engine.connect() as connection:
        relation_count = connection.execute(
            text(
                """
                SELECT count(*)
                FROM pg_class AS relation
                JOIN pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'public'
                  AND relation.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
                """
            )
        ).scalar_one()
        function_count = connection.execute(
            text(
                """
                SELECT count(*)
                FROM pg_proc AS function
                JOIN pg_namespace AS namespace
                  ON namespace.oid = function.pronamespace
                WHERE namespace.nspname = 'public'
                """
            )
        ).scalar_one()
    if relation_count or function_count:
        raise RuntimeError(
            "bootstrap requires an empty public schema; "
            f"found {relation_count} relations and {function_count} functions"
        )


def _baseline_records(
    engine: Engine,
    options: BootstrapOptions,
) -> tuple[pd.DataFrame, pd.Timestamp, pd.Timestamp, dict[str, int]]:
    query = text(
        """
        WITH selected_measurements AS (
            SELECT
                measurement.measurement_id,
                measurement.measurement_timestamp,
                measurement.measured_value,
                cabin.booth_id,
                measurement.measurement_point_id,
                measurement.specification_id,
                batch.shift_id,
                (
                    (batch.batch_start::date + shift.start_time)
                    - CASE
                        WHEN shift.end_time <= shift.start_time
                         AND batch.batch_start::time < shift.start_time
                        THEN interval '1 day'
                        ELSE interval '0 day'
                      END
                ) AS shift_instance
            FROM fact_quality_measurement AS measurement
            JOIN dim_cabin AS cabin USING (cabin_id)
            JOIN dim_batch AS batch USING (batch_id)
            JOIN dim_shift AS shift USING (shift_id)
            JOIN dim_booth AS booth USING (booth_id)
            JOIN dim_measurement_point AS point USING (measurement_point_id)
            JOIN dim_specification AS specification USING (specification_id)
            WHERE booth.booth_name = :booth
              AND point.point_code = :measurement_point
              AND specification.characteristic = :characteristic
              AND specification.unit = :unit
        ), window_bounds AS (
            SELECT
                min(shift_instance) AS window_start,
                min(shift_instance) + (:window_days * interval '1 day') AS window_end
            FROM selected_measurements
        )
        SELECT
            selected.measurement_id,
            selected.measurement_timestamp,
            selected.measured_value,
            selected.booth_id,
            selected.measurement_point_id,
            selected.specification_id,
            selected.shift_id,
            selected.shift_instance,
            bounds.window_start,
            bounds.window_end
        FROM selected_measurements AS selected
        CROSS JOIN window_bounds AS bounds
        WHERE selected.measurement_timestamp >= bounds.window_start
          AND selected.measurement_timestamp < bounds.window_end
        ORDER BY selected.measurement_timestamp, selected.measurement_id
        """
    )
    parameters = {
        "booth": options.booth,
        "measurement_point": options.measurement_point,
        "characteristic": options.characteristic,
        "unit": options.unit,
        "window_days": options.baseline_window_days,
    }
    with engine.connect() as connection:
        frame = pd.read_sql_query(query, connection, params=parameters)

    if frame.empty:
        raise RuntimeError(
            "canonical baseline scope contains no measurements in the configured window"
        )
    scope_ids = {
        "booth_id": int(frame["booth_id"].iloc[0]),
        "measurement_point_id": int(frame["measurement_point_id"].iloc[0]),
        "specification_id": int(frame["specification_id"].iloc[0]),
    }
    for column, expected in scope_ids.items():
        if frame[column].nunique() != 1 or int(frame[column].iloc[0]) != expected:
            raise RuntimeError(f"baseline source contains inconsistent {column} values")
    window_start = pd.Timestamp(frame["window_start"].iloc[0])
    window_end = pd.Timestamp(frame["window_end"].iloc[0])
    records = frame[
        [
            "measurement_id",
            "measurement_timestamp",
            "measured_value",
            "booth_id",
            "measurement_point_id",
            "specification_id",
            "shift_id",
            "shift_instance",
        ]
    ].copy()
    records["shift_instance"] = [
        (int(shift_id), pd.Timestamp(shift_instance))
        for shift_id, shift_instance in records[
            ["shift_id", "shift_instance"]
        ].itertuples(index=False, name=None)
    ]
    return records, window_start, window_end, scope_ids


def _source_fingerprint(records: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    digest.update(b"canonical-spc-bootstrap-v1\n")
    ordered = records.sort_values(
        ["measurement_timestamp", "measurement_id"], kind="mergesort"
    )
    for row in ordered.itertuples(index=False):
        shift_id, shift_start = row.shift_instance
        digest.update(
            (
                f"{int(row.measurement_id)}|"
                f"{pd.Timestamp(row.measurement_timestamp).isoformat()}|"
                f"{Decimal(str(row.measured_value))}|"
                f"{shift_id}|{pd.Timestamp(shift_start).isoformat()}\n"
            ).encode("utf-8")
        )
    return digest.hexdigest()


def _six_decimals(value: float) -> Decimal:
    return Decimal(str(value)).quantize(_DECIMAL_QUANTUM, rounding=ROUND_HALF_UP)


def _persist_and_activate_baseline(
    engine: Engine,
    options: BootstrapOptions,
    records: pd.DataFrame,
    limits: BaselineLimits,
    window_start: pd.Timestamp,
    window_end: pd.Timestamp,
    scope_ids: dict[str, int],
) -> tuple[int, str]:
    fingerprint = _source_fingerprint(records)
    local_window_start = window_start.tz_localize(BASELINE_TIMEZONE)
    local_window_end = window_end.tz_localize(BASELINE_TIMEZONE)
    with engine.begin() as connection:
        version = connection.execute(
            text(
                """
                SELECT coalesce(max(version), 0) + 1
                FROM spc_baseline
                WHERE booth_id = :booth_id
                  AND measurement_point_id = :measurement_point_id
                  AND specification_id = :specification_id
                """
            ),
            scope_ids,
        ).scalar_one()
        insert_values = {
            **scope_ids,
            "version": int(version),
            "window_start": local_window_start.to_pydatetime(),
            "window_end": local_window_end.to_pydatetime(),
            "status": "DRAFT",
            "n_observations": limits.n_observations,
            "n_valid_mr": limits.n_valid_mr,
            "center_line": _six_decimals(limits.center_line),
            "sigma": _six_decimals(limits.sigma),
            "i_lcl": _six_decimals(limits.i_lcl),
            "i_ucl": _six_decimals(limits.i_ucl),
            "mr_center": _six_decimals(limits.mr_center),
            "mr_ucl": _six_decimals(limits.mr_ucl),
            "source_query_hash": fingerprint,
        }
        baseline_id = connection.execute(
            text(
                """
                INSERT INTO spc_baseline (
                    booth_id, measurement_point_id, specification_id, version,
                    window_start, window_end, status, n_observations, n_valid_mr,
                    center_line, sigma, i_lcl, i_ucl, mr_center, mr_ucl,
                    source_query_hash
                )
                VALUES (
                    :booth_id, :measurement_point_id, :specification_id, :version,
                    :window_start, :window_end, :status, :n_observations, :n_valid_mr,
                    :center_line, :sigma, :i_lcl, :i_ucl, :mr_center, :mr_ucl,
                    :source_query_hash
                )
                RETURNING baseline_id
                """
            ),
            insert_values,
        ).scalar_one()
        connection.execute(
            text(
                """
                UPDATE spc_baseline
                SET status = 'ACTIVE',
                    effective_from = window_end,
                    approved_by = :approved_by,
                    approved_at = window_end,
                    rationale = :rationale
                WHERE baseline_id = :baseline_id
                  AND status = 'DRAFT'
                """
            ),
            {
                "approved_by": options.approved_by,
                "rationale": BASELINE_RATIONALE,
                "baseline_id": baseline_id,
            },
        )
    return int(baseline_id), fingerprint


def _validate_live_database(
    engine: Engine,
    result: BootstrapResult,
) -> None:
    with engine.connect() as connection:
        active_baseline = connection.execute(
            text(
                """
                SELECT status, approved_by, source_query_hash
                FROM spc_baseline
                WHERE baseline_id = :baseline_id
                """
            ),
            {"baseline_id": result.baseline_id},
        ).mappings().one()
        active_scope_count = connection.execute(
            text(
                """
                SELECT count(*)
                FROM spc_baseline
                WHERE status = 'ACTIVE'
                """
            )
        ).scalar_one()
        counts = connection.execute(
            text(
                """
                SELECT
                    count(*) AS measurement_count,
                    count(*) FILTER (WHERE baseline_id IS NOT NULL) AS baseline_covered_count,
                    count(*) FILTER (WHERE spc_signal) AS spc_signal_count,
                    count(*) FILTER (
                        WHERE baseline_id IS NOT NULL
                          AND spc_signal IS DISTINCT FROM
                              (rule_1 OR rule_2 OR rule_3 OR rule_4)
                    ) AS inconsistent_signal_count,
                    count(*) FILTER (
                        WHERE baseline_id IS NULL
                          AND (rule_1 OR rule_2 OR rule_3 OR rule_4 OR spc_signal IS NOT NULL)
                    ) AS uncovered_signal_count
                FROM v_spc_rule_results
                WHERE booth = 'BOOTH_01'
                  AND measurement_point = 'A-L1'
                """
            )
        ).mappings().one()
        invalid_limits = connection.execute(
            text(
                """
                SELECT count(*) AS invalid_limit_count
                FROM v_spc_rule_results AS result
                JOIN spc_baseline AS baseline USING (baseline_id)
                WHERE result.baseline_id = :baseline_id
                  AND (
                       result.center_line IS DISTINCT FROM baseline.center_line
                    OR result.sigma IS DISTINCT FROM baseline.sigma
                    OR result.i_lcl IS DISTINCT FROM baseline.i_lcl
                    OR result.i_ucl IS DISTINCT FROM baseline.i_ucl
                    OR result.mr_center IS DISTINCT FROM baseline.mr_center
                    OR result.mr_ucl IS DISTINCT FROM baseline.mr_ucl
                  )
                """
            ),
            {"baseline_id": result.baseline_id},
        ).scalar_one()
        total_measurements = connection.execute(
            text("SELECT count(*) FROM fact_quality_measurement")
        ).scalar_one()

    if active_baseline["status"] != "ACTIVE":
        raise RuntimeError("persisted canonical baseline was not activated")
    if active_baseline["source_query_hash"] != result.source_query_hash:
        raise RuntimeError("persisted baseline source fingerprint changed")
    if active_scope_count != 1:
        raise RuntimeError(f"expected one ACTIVE baseline, found {active_scope_count}")
    if counts["measurement_count"] != result.eligible_spc_count:
        raise RuntimeError("SPC result grain does not match the canonical scope")
    if counts["inconsistent_signal_count"]:
        raise RuntimeError("SPC signal flags are inconsistent with Rules 1-4")
    if counts["uncovered_signal_count"]:
        raise RuntimeError("SPC signals were produced for baseline-uncovered rows")
    if invalid_limits:
        raise RuntimeError("SPC results do not preserve the stored baseline limits")
    if total_measurements != result.measurement_count:
        raise RuntimeError("measurement table count changed after bootstrap")
    if counts["baseline_covered_count"] != result.baseline_covered_count:
        raise RuntimeError("baseline coverage changed after bootstrap")
    if counts["spc_signal_count"] != result.spc_signal_count:
        raise RuntimeError("SPC signal count changed after bootstrap")


def bootstrap(options: BootstrapOptions) -> BootstrapResult:
    """Build the canonical SPC pipeline in the configured empty database."""
    engine = create_engine(options.database_url, pool_pre_ping=True)
    try:
        print("Stage 1/9: verify empty database")
        _assert_empty_database(engine)
        with tempfile.TemporaryDirectory(prefix="spc-bootstrap-") as temporary:
            generated_dir = Path(temporary)
            print("Stage 2/9: generate deterministic CSV data")
            tables = build_all_tables()
            validate_generated_data(tables)
            write_tables(tables, str(generated_dir))

            print("Stage 3/9: apply database schema")
            _run_psql(options, _SCHEMA_SQL, cwd=generated_dir)
            print("Stage 4/9: apply SPC baseline migration")
            _run_psql(options, _MIGRATION_SQL, cwd=generated_dir)
            print("Stage 5/9: load dimensions and measurements")
            _run_psql(options, _LOAD_SQL, cwd=generated_dir)

            print("Stage 6/9: fit baseline with src.spc_monitoring.fit_baseline")
            records, window_start, window_end, scope_ids = _baseline_records(
                engine, options
            )
            limits = fit_baseline(records)

            print("Stage 7/9: persist and activate baseline")
            baseline_id, fingerprint = _persist_and_activate_baseline(
                engine,
                options,
                records,
                limits,
                window_start,
                window_end,
                scope_ids,
            )

            print("Stage 8/9: create SQL analytical views")
            _run_psql(options, _VIEWS_SQL, cwd=generated_dir)

            with engine.connect() as connection:
                measurement_count = connection.execute(
                    text("SELECT count(*) FROM fact_quality_measurement")
                ).scalar_one()
                eligible_spc_count = connection.execute(
                    text("SELECT count(*) FROM v_spc_rule_results_booth01_a_l1")
                ).scalar_one()
                covered_count, signal_count = connection.execute(
                    text(
                        """
                        SELECT
                            count(*) FILTER (WHERE baseline_id IS NOT NULL),
                            count(*) FILTER (WHERE spc_signal)
                        FROM v_spc_rule_results
                        WHERE booth = 'BOOTH_01'
                          AND measurement_point = 'A-L1'
                        """
                    )
                ).one()
            result = BootstrapResult(
                baseline_id=baseline_id,
                source_query_hash=fingerprint,
                measurement_count=int(measurement_count),
                baseline_observation_count=limits.n_observations,
                baseline_valid_mr_count=limits.n_valid_mr,
                eligible_spc_count=int(eligible_spc_count),
                baseline_covered_count=int(covered_count),
                spc_signal_count=int(signal_count),
                limits=limits,
            )

            print("Stage 9/9: run SQL data and SPC regression validations")
            _run_psql(options, _SPC_RULE_TEST_SQL, cwd=generated_dir)
            _run_psql(options, _SPC_SUMMARY_TEST_SQL, cwd=generated_dir)
            _run_psql(options, _BOOTSTRAP_VALIDATION_SQL, cwd=generated_dir)
            _validate_live_database(engine, result)
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
        return result
    finally:
        engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build and validate the complete SPC pipeline in an empty PostgreSQL "
            "public schema."
        )
    )
    parser.add_argument(
        "--database-url",
        help=(
            "PostgreSQL URL; otherwise PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD "
            "or SPC_BOOTSTRAP_DATABASE_URL is used."
        ),
    )
    parser.add_argument(
        "--baseline-window-days",
        type=int,
        default=BASELINE_WINDOW_DAYS,
        help="Exclusive baseline window length from the first scheduled shift start.",
    )
    parser.add_argument("--approved-by", default=BASELINE_APPROVER)
    return parser


def main() -> None:
    arguments = build_parser().parse_args()
    if arguments.baseline_window_days < 1:
        raise ValueError("--baseline-window-days must be positive")
    options = BootstrapOptions(
        database_url=_database_url(arguments.database_url),
        booth=BASELINE_SCOPE_BOOTH,
        measurement_point=BASELINE_SCOPE_POINT,
        characteristic=BASELINE_SCOPE_CHARACTERISTIC,
        unit=BASELINE_SCOPE_UNIT,
        baseline_window_days=arguments.baseline_window_days,
        approved_by=arguments.approved_by,
    )
    bootstrap(options)


if __name__ == "__main__":
    main()
