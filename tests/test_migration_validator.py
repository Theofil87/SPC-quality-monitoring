from __future__ import annotations

from datetime import datetime, time, timedelta, timezone, tzinfo
from decimal import Decimal
import tracemalloc

import pytest

from src.migration_validator import compare_record_streams, compare_records


def test_equal_records_are_order_independent_and_reported():
    source = [{"id": 2, "value": "b"}, {"id": 1, "value": "a"}]
    target = [{"value": "a", "id": 1}, {"value": "b", "id": 2}]

    report = compare_records(source, target, "id")

    assert report.status == "PASS"
    assert (report.source_count, report.target_count) == (2, 2)
    assert [record.primary_key for record in report.matched] == [(1,), (2,)]
    assert report.matched[0].values == {"id": 1, "value": "a"}
    assert not report.source_only and not report.target_only and not report.different
    assert report == compare_records(list(reversed(source)), list(reversed(target)), "id")


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
    assert report.matched[0].primary_key == (2,)


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
    assert report.matched[0].primary_key == (1, 3)
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
    assert len(report.matched) == 1


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
    assert not report.matched and not report.source_only and not report.target_only


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


@pytest.mark.parametrize(
    ("source", "target", "key"),
    [
        ([], [], "id"),
        ([{"id": 2}, {"id": 10}], [{"id": 2}, {"id": 10}], "id"),
        (
            [{"id": 1, "value": "source"}, {"id": 2, "value": "before"},
             {"id": 4, "value": "same"}],
            [{"id": 2, "value": "after"}, {"id": 3, "value": "target"},
             {"id": 4, "value": "same"}],
            "id",
        ),
        (
            [{"a": 1, "b": 2}, {"a": 2, "b": 1}],
            [{"a": 1, "b": 3}, {"a": 2, "b": 1}],
            ("a", "b"),
        ),
    ],
)
def test_streaming_matches_existing_comparison(source, target, key):
    old = compare_records(source, target, key)
    events = []
    report = compare_record_streams(
        iter(source), iter(target), key, batch_size=1, max_samples=10,
        on_difference=events.append,
    )

    assert report.complete and report.error is None
    assert report.status == old.status
    assert (report.source_count, report.target_count) == (old.source_count, old.target_count)
    assert report.matched_count == len(old.matched)
    assert report.source_only_count == len(old.source_only)
    assert report.target_only_count == len(old.target_only)
    assert report.different_count == len(old.different)
    assert {event.primary_key: event.source for event in events if event.kind == "source_only"} == {
        record.primary_key: record for record in old.source_only
    }
    assert {event.primary_key: event.target for event in events if event.kind == "target_only"} == {
        record.primary_key: record for record in old.target_only
    }
    assert {event.primary_key: event.fields for event in events if event.kind == "different"} == {
        record.primary_key: record.fields for record in old.different
    }
    assert report.samples == tuple(events)


def test_streaming_exact_decimal_null_and_datetime():
    instant = datetime(2026, 1, 19, 5, tzinfo=timezone.utc)
    local = datetime(2026, 1, 19, 6, tzinfo=timezone(timedelta(hours=1)))
    source = [
        {"id": 1, "value": Decimal("10000000000000000000.0000001"), "dt": instant, "null": None},
        {"id": 2, "value": Decimal("1.0"), "dt": datetime(2026, 1, 19, 6), "null": None},
    ]
    target = [
        {"id": 1, "value": Decimal("10000000000000000000.0000002"), "dt": local, "null": None},
        {"id": 2, "value": Decimal("1.00"), "dt": local, "null": None},
    ]
    old = compare_records(source, target, "id")
    report = compare_record_streams(source, target, "id")

    assert report.status == "FAIL"
    assert report.different_count == 2
    assert {event.primary_key: event.fields for event in report.samples} == {
        record.primary_key: record.fields for record in old.different
    }
    assert [field.field for field in report.samples[0].fields] == ["value"]
    assert [field.field for field in report.samples[1].fields] == ["dt"]


def test_streaming_aware_datetime_keys_are_normalized_before_ordering():
    utc = timezone.utc
    plus_one = timezone(timedelta(hours=1))
    source = [{"id": datetime(2026, 1, 1, hour, tzinfo=utc)} for hour in (5, 6)]
    target = [{"id": datetime(2026, 1, 1, hour, tzinfo=plus_one)} for hour in (6, 7)]
    report = compare_record_streams(source, target, "id", batch_size=1)
    assert report.status == "PASS"
    assert report.matched_count == 2


@pytest.mark.parametrize("side", ["source", "target"])
@pytest.mark.parametrize(
    ("keys", "message"),
    [([1, 2, 2], "duplicate"), ([1, 10, 2], "increasing order")],
)
def test_streaming_rejects_bad_order_even_after_other_stream_is_exhausted(side, keys, message):
    rows = [{"id": key} for key in keys]
    source, target = (rows, []) if side == "source" else ([], rows)
    report = compare_record_streams(source, target, "id", batch_size=2)
    assert report.status == "FAIL"
    assert not report.complete
    assert report.error is not None
    assert side in report.error and message in report.error
    assert report.source_count + report.target_count == 2


def test_streaming_detects_differences_across_batch_boundaries():
    source = [{"id": i, "value": i} for i in range(8)]
    target = [{"id": i, "value": -i if i in (3, 4) else i} for i in range(8)]
    report = compare_record_streams(source, target, "id", batch_size=4)
    assert report.status == "FAIL"
    assert report.matched_count == 6
    assert [item.primary_key for item in report.samples] == [(3,), (4,)]


def test_streaming_batch_size_does_not_change_results():
    source = [{"id": i, "value": i} for i in (1, 2, 4, 10, 11)]
    target = [{"id": i, "value": 0} for i in (1, 3, 4, 10, 12)]
    reports = [
        compare_record_streams(iter(source), iter(target), "id", batch_size=size)
        for size in (1, 2, 3, 128)
    ]
    assert all(report == reports[0] for report in reports)


def test_streaming_samples_are_bounded_but_callback_receives_every_difference():
    source = ({"id": i, "value": i} for i in range(20))
    target = ({"id": i, "value": -1} for i in range(20))
    events = []
    report = compare_record_streams(source, target, "id", max_samples=2, on_difference=events.append)
    assert report.different_count == 20
    assert len(report.samples) == 2
    assert len(events) == 20
    assert report.samples == tuple(events[:2])
    assert compare_record_streams([{"id": 1}], [], "id", max_samples=0).samples == ()


@pytest.mark.parametrize(
    ("source", "target", "key", "error"),
    [
        ([{"value": 1}], [], "id", ValueError),
        ([{"id": 1}], [{"id": 1, "extra": 2}], "id", ValueError),
        ([{"id": 1}, {"id": 2, "extra": 2}], [], "id", ValueError),
        ([None], [], "id", TypeError),
        ({"id": 1}, [], "id", TypeError),
        ([], [], [], ValueError),
        ([{"id": None}], [], "id", ValueError),
        ([{"id": 1, "value": []}], [], "id", TypeError),
        ([{"id": 1, "value": Decimal("NaN")}], [], "id", ValueError),
        ([{"id": 1}], [{"id": 1.0}], "id", ValueError),
    ],
)
def test_streaming_invalid_input_raises_without_pass(source, target, key, error):
    with pytest.raises(error):
        compare_record_streams(source, target, key, batch_size=1)


@pytest.mark.parametrize("options", [
    {"batch_size": 0}, {"batch_size": True}, {"batch_size": 1.5},
    {"max_samples": -1}, {"max_samples": True}, {"on_difference": 1},
])
def test_streaming_invalid_options_are_rejected(options):
    with pytest.raises((TypeError, ValueError)):
        compare_record_streams([], [], "id", **options)


@pytest.mark.parametrize("side", ["source", "target"])
def test_streaming_iterator_error_propagates(side):
    def broken():
        yield {"id": 1}
        raise RuntimeError("interrupted iterator")

    source, target = (broken(), []) if side == "source" else ([], broken())
    with pytest.raises(RuntimeError, match="interrupted iterator"):
        compare_record_streams(source, target, "id", batch_size=1)


def test_streaming_callback_error_propagates_without_draining_streams():
    consumed = []

    def source():
        for i in range(1000):
            consumed.append(i)
            yield {"id": i}

    def fail(_):
        raise OSError("output failed")

    with pytest.raises(OSError, match="output failed"):
        compare_record_streams(source(), [], "id", batch_size=4, on_difference=fail)
    assert len(consumed) == 4


def test_streaming_copies_reused_generator_rows_at_batch_read():
    def rows():
        row = {"id": 0}
        for i in range(5):
            row["id"] = i
            yield row

    assert compare_record_streams(rows(), rows(), "id", batch_size=3).matched_count == 5


def test_streaming_large_generator_memory_is_bounded():
    def peak(count):
        tracemalloc.start()
        try:
            report = compare_record_streams(
                ({"id": i, "value": i} for i in range(count)),
                ({"id": i, "value": -1} for i in range(count)),
                "id", batch_size=16, max_samples=3,
            )
            _, maximum = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert report.different_count == count
        assert len(report.samples) == 3
        return maximum

    small_peak = peak(1000)
    large_peak = peak(40000)
    assert large_peak < small_peak + 500_000
