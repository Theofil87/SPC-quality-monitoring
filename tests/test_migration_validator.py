from __future__ import annotations

from datetime import datetime, time, timedelta, timezone, tzinfo
from decimal import Decimal

import pytest

from src.migration_validator import compare_records


def test_equal_sorted_records_are_reported():
    source = [{"id": 1, "value": "a"}, {"id": 2, "value": "b"}]
    target = [{"value": "a", "id": 1}, {"value": "b", "id": 2}]

    report = compare_records(source, target, "id")

    assert report.status == "PASS"
    assert (report.source_count, report.target_count) == (2, 2)
    assert report.matched_count == 2
    assert not report.source_only and not report.target_only and not report.different


def test_unsorted_records_are_rejected():
    with pytest.raises(ValueError, match="ordered by primary key"):
        compare_records([{"id": 2}, {"id": 1}], [{"id": 1}, {"id": 2}], "id")


def test_missing_source_and_target_records_are_reported_with_values():
    report = compare_records(
        [{"id": 1, "value": "source"}, {"id": 2, "value": "same"}],
        [{"id": 2, "value": "same"}, {"id": 3, "value": "target"}],
        "id",
    )

    assert report.status == "FAIL"
    assert (report.source_count, report.target_count) == (2, 2)
    assert report.source_only[0].primary_key == (1,)
    assert report.source_only[0].values["value"] == "source"
    assert report.target_only[0].primary_key == (3,)
    assert report.target_only[0].values["value"] == "target"
    assert report.matched_count == 1


def test_different_fields_include_both_values():
    report = compare_records(
        [{"id": 1, "a": None, "b": 3}],
        [{"id": 1, "a": "changed", "b": 4}],
        "id",
    )

    assert report.status == "FAIL"
    assert report.different[0].primary_key == (1,)
    assert [(field.field, field.source, field.target) for field in report.different[0].fields] == [
        ("a", None, "changed"),
        ("b", 3, 4),
    ]


def test_composite_primary_key_distinguishes_records():
    report = compare_records(
        [{"measurement_id": 1, "robot_id": 2}, {"measurement_id": 1, "robot_id": 3}],
        [{"measurement_id": 1, "robot_id": 3}, {"measurement_id": 1, "robot_id": 4}],
        ("measurement_id", "robot_id"),
    )

    assert report.status == "FAIL"
    assert report.matched_count == 1
    assert report.source_only[0].primary_key == (1, 2)
    assert report.target_only[0].primary_key == (1, 4)


def test_null_values_compare_equal_but_null_primary_key_is_invalid():
    assert compare_records([{"id": 1, "value": None}], [{"id": 1, "value": None}], "id").status == "PASS"
    with pytest.raises(ValueError, match="primary key.*NULL"):
        compare_records([{"id": None}], [], "id")


def test_decimal_values_are_exact_and_never_coerced_to_float():
    source = Decimal("10000000000000000000.0000001")
    target = Decimal("10000000000000000000.0000002")
    report = compare_records([{"id": 1, "value": source}], [{"id": 1, "value": target}], "id")

    assert report.status == "FAIL"
    assert report.different[0].fields[0].source == source
    assert report.different[0].fields[0].target == target
    assert compare_records(
        [{"id": 1, "value": Decimal("1.0")}],
        [{"id": 1, "value": Decimal("1.00")}],
        "id",
    ).status == "PASS"
    assert compare_records(
        [{"id": 1, "value": Decimal("1.0")}],
        [{"id": 1, "value": 1.0}],
        "id",
    ).status == "FAIL"


def test_aware_datetimes_compare_by_instant_and_naive_datetimes_by_wall_time():
    instant = datetime(2026, 1, 19, 5, tzinfo=timezone.utc)
    local = datetime(2026, 1, 19, 6, tzinfo=timezone(timedelta(hours=1)))
    source = [{"id": 1, "timestamp": instant, "local": datetime(2026, 1, 19, 6)}]
    target = [{"id": 1, "timestamp": local, "local": datetime(2026, 1, 19, 6)}]

    assert compare_records(source, target, "id").status == "PASS"
    target[0]["local"] = local
    report = compare_records(source, target, "id")
    assert report.status == "FAIL"
    assert report.different[0].fields[0].field == "local"


def test_aware_datetime_primary_keys_match_across_timezones():
    source_key = datetime(2026, 1, 19, 5, tzinfo=timezone.utc)
    target_key = datetime(2026, 1, 19, 6, tzinfo=timezone(timedelta(hours=1)))

    report = compare_records(iter([{"id": source_key}]), iter([{"id": target_key}]), "id")

    assert report.status == "PASS"
    assert report.matched_count == 1


def test_ambiguous_aware_datetimes_with_same_timezone_use_real_instants():
    class FoldTimezone(tzinfo):
        def utcoffset(self, value):
            return timedelta(hours=1 if value.fold else 2)

    zone = FoldTimezone()
    source = datetime(2026, 10, 25, 2, 30, tzinfo=zone, fold=0)
    target = datetime(2026, 10, 25, 2, 30, tzinfo=zone, fold=1)

    assert compare_records([{"id": 1, "value": source}], [{"id": 1, "value": target}], "id").status == "FAIL"


def test_empty_tables_are_equal():
    report = compare_records([], [], "id")

    assert report.status == "PASS"
    assert (report.source_count, report.target_count) == (0, 0)
    assert report.matched_count == 0
    assert not report.source_only and not report.target_only


@pytest.mark.parametrize(
    ("source", "target", "side"),
    [
        ([{"id": 1}, {"id": 1}], [], "source"),
        ([], [{"id": 1}, {"id": 1}], "target"),
    ],
)
def test_duplicate_primary_keys_are_rejected(source, target, side):
    with pytest.raises(ValueError, match=f"{side}.*duplicate primary key"):
        compare_records(source, target, "id")


@pytest.mark.parametrize(
    ("source", "target", "primary_key", "error"),
    [
        ([{"value": 1}], [], "id", ValueError),
        ([{"id": 1}], [{"id": 1, "extra": 2}], "id", ValueError),
        ([{"id": 1}, {"id": 2, "extra": 2}], [], "id", ValueError),
        ([1], [], "id", TypeError),
        ({"id": 1}, [], "id", TypeError),
        ([], [], [], ValueError),
        ([], [], ["id", "id"], ValueError),
        ([{"id": 1, "value": []}], [], "id", TypeError),
        ([{"id": 1, "value": float("nan")}], [], "id", ValueError),
        ([{"id": 1, "value": Decimal("NaN")}], [], "id", ValueError),
        ([{"id": 1, "value": time(1, tzinfo=timezone.utc)}], [], "id", ValueError),
        ([{"id": 1}, {"id": 1.0}], [{"id": 1}, {"id": 1.0}], "id", ValueError),
        ([{"id": 1}], [{"id": 1.0}], "id", ValueError),
    ],
)
def test_invalid_inputs_raise_instead_of_passing(source, target, primary_key, error):
    with pytest.raises(error):
        compare_records(source, target, primary_key)
