from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pandas as pd

from src.bootstrap_database import (
    _six_decimals,
    _source_fingerprint,
    execution_plan,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _records() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "measurement_id": [1, 2],
            "measurement_timestamp": [
                pd.Timestamp("2026-01-01 06:30:00"),
                pd.Timestamp("2026-01-01 07:30:00"),
            ],
            "measured_value": [Decimal("74.123"), Decimal("75.456")],
            "shift_instance": [
                (1, pd.Timestamp("2026-01-01 06:00:00")),
                (1, pd.Timestamp("2026-01-01 06:00:00")),
            ],
        }
    )


def test_execution_plan_uses_required_bootstrap_order():
    assert execution_plan() == (
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


def test_source_fingerprint_is_order_independent_for_deterministic_records():
    records = _records()

    assert _source_fingerprint(records) == _source_fingerprint(
        records.iloc[[1, 0]]
    )


def test_source_fingerprint_changes_with_measurement_values():
    records = _records()
    changed = records.copy()
    changed.loc[1, "measured_value"] = Decimal("75.457")

    assert _source_fingerprint(records) != _source_fingerprint(changed)


def test_baseline_storage_rounding_uses_half_up_six_decimals():
    assert _six_decimals(1.2345675) == Decimal("1.234568")


def test_bootstrap_validation_is_transactional_and_fails_explicitly():
    source = (REPO_ROOT / "sql" / "validate_bootstrap.sql").read_text(
        encoding="utf-8"
    )

    assert "\\set ON_ERROR_STOP on" in source
    assert "BEGIN;" in source
    assert "RAISE EXCEPTION" in source
    assert "COMMIT;" in source
