from __future__ import annotations

import base64
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.io as pio
import pytest
import sqlalchemy
import streamlit as st
from streamlit.testing.v1 import AppTest


DASHBOARD = Path(__file__).resolve().parents[1] / "dashboard.py"


def _row(measurement_id, baseline_id=1, **overrides):
    row = {
        "measurement_timestamp": pd.Timestamp("2026-03-01") + pd.Timedelta(
            minutes=measurement_id
        ),
        "measurement_id": measurement_id,
        "specification_id": 1,
        "characteristic": "Thickness",
        "specification_unit": "um",
        "batch_id": 1,
        "robot_names": ["ROBOT_01"],
        "baseline_id": baseline_id,
        "baseline_version": baseline_id,
        "baseline_current_status": "ACTIVE" if baseline_id is not None else None,
        "baseline_window_start": pd.Timestamp("2026-02-01", tz="UTC") if baseline_id is not None else None,
        "baseline_window_end": pd.Timestamp("2026-03-01", tz="UTC") if baseline_id is not None else None,
        "baseline_effective_from": pd.Timestamp("2026-03-01", tz="UTC") if baseline_id is not None else None,
        "baseline_effective_to": None,
        "baseline_approved_by": "Reviewer" if baseline_id is not None else None,
        "baseline_approved_at": pd.Timestamp("2026-03-01", tz="UTC") if baseline_id is not None else None,
        "active_baseline": None,
        "booth": "BOOTH_01",
        "measurement_point": "A-L1",
        "shift_id": 1,
        "shift_name": "SHIFT_01",
        "shift_instance": pd.Timestamp("2026-03-01"),
        "measured_value": 75.0,
        "moving_range": None,
        "center_line": 75.0 if baseline_id is not None else None,
        "sigma": 1.0 if baseline_id is not None else None,
        "i_lcl": 72.0 if baseline_id is not None else None,
        "i_ucl": 78.0 if baseline_id is not None else None,
        "mr_center": 1.0 if baseline_id is not None else None,
        "mr_ucl": 3.0 if baseline_id is not None else None,
        "rule_1": False,
        "rule_2": False,
        "rule_3": False,
        "rule_4": False,
        "spc_signal": False,
    }
    return row | overrides


@pytest.fixture
def run_dashboard(monkeypatch):
    class FakeEngine:
        @contextmanager
        def connect(self):
            yield object()

    st.cache_data.clear()
    st.cache_resource.clear()
    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *args, **kwargs: FakeEngine())

    def run(rows):
        monkeypatch.setattr(
            pd, "read_sql_query", lambda *args, **kwargs: pd.DataFrame(rows).copy()
        )
        app = AppTest.from_file(str(DASHBOARD), default_timeout=30)
        app.session_state["dashboard_section"] = "SPC monitoring"
        app.run()
        assert not app.exception
        return app

    yield run
    st.cache_data.clear()
    st.cache_resource.clear()


def _metrics(app):
    return {metric.label: metric.value for metric in app.metric}


def _charts(app):
    return [pio.from_json(chart.proto.spec) for chart in app.get("plotly_chart")]


def _trace(chart, name):
    return next(trace for trace in chart.data if trace.name == name)


def _values(values):
    if isinstance(values, dict) and "bdata" in values:
        return np.frombuffer(
            base64.b64decode(values["bdata"]), dtype=values["dtype"]
        ).tolist()
    return list(values)


def test_empty_spc_results_stop_before_kpis(run_dashboard):
    app = run_dashboard([])

    assert any("contains no records" in warning.value for warning in app.warning)
    assert not app.metric
    assert not app.get("plotly_chart")


def test_spc_query_joins_specification_by_measurement_id(monkeypatch):
    class FakeEngine:
        @contextmanager
        def connect(self):
            yield object()

    queries = []

    def fake_read_sql(query, connection):
        queries.append(" ".join(str(query).lower().split()))
        return pd.DataFrame([_row(1, None)])

    st.cache_data.clear()
    st.cache_resource.clear()
    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *args, **kwargs: FakeEngine())
    monkeypatch.setattr(pd, "read_sql_query", fake_read_sql)
    app = AppTest.from_file(str(DASHBOARD), default_timeout=30)
    app.session_state["dashboard_section"] = "SPC monitoring"
    try:
        app.run()
        assert not app.exception
        assert len(queries) == 1
        assert "measurement.specification_id" in queries[0]
        assert "left join v_measurement_enriched as measurement" in queries[0]
        assert "measurement.measurement_id = spc.measurement_id" in queries[0]
        assert "left join dim_specification as specification" in queries[0]
        assert "specification.specification_id = measurement.specification_id" in queries[0]
        assert "left join spc_baseline as baseline" in queries[0]
        assert "baseline.baseline_id = spc.baseline_id" in queries[0]
        assert "cast(spc.baseline_id as text) as baseline_id" in queries[0]
        assert "baseline.version as baseline_version" in queries[0]
        assert "baseline.status as baseline_current_status" in queries[0]
        assert "baseline.effective_from as baseline_effective_from" in queries[0]
        assert "baseline.effective_to as baseline_effective_to" in queries[0]
        assert "baseline.approved_by as baseline_approved_by" in queries[0]
        assert "baseline.approved_at as baseline_approved_at" in queries[0]
        assert "measurement.batch_id" in queries[0]
        assert "bridge_measurement_robot" in queries[0]
        assert "array_agg(robot.robot_name" in queries[0]
        assert "baseline.window_start as baseline_window_start" in queries[0]
        assert "baseline.window_end as baseline_window_end" in queries[0]
        assert "left join spc_baseline as active" in queries[0]
        assert "active.status = 'active'" in queries[0]
    finally:
        st.cache_data.clear()
        st.cache_resource.clear()


def test_single_specification_is_selected_automatically(run_dashboard):
    app = run_dashboard([_row(1, rule_1=True, spc_signal=True)])

    assert not app.selectbox
    assert any("Specification: Thickness (um) — ID 1" in item.value for item in app.caption)
    assert _metrics(app)["Baseline-covered observations"] == "1 / 1 total"
    assert _values(_trace(_charts(app)[0], "Measured value").y) == [75.0]


def test_switching_specifications_updates_all_spc_outputs(run_dashboard):
    app = run_dashboard([
        _row(1, 1, measured_value=10.0, moving_range=None),
        _row(2, 1, measured_value=12.0, moving_range=4.0, rule_1=True, spc_signal=True),
        _row(
            3, 2, specification_id=2, characteristic="Weight",
            specification_unit="kg", measured_value=100.0, moving_range=2.0,
            center_line=100.0, i_lcl=95.0, i_ucl=105.0,
            mr_center=1.5, mr_ucl=6.0, rule_2=True, rule_3=True,
            rule_4=True, spc_signal=True,
        ),
        _row(
            4, None, specification_id=2, characteristic="Weight",
            specification_unit="kg", measured_value=110.0, moving_range=None,
        ),
    ])
    assert app.selectbox[0].value is None
    assert any("Select a specification" in message.value for message in app.info)
    assert not app.metric
    assert not app.get("plotly_chart")
    assert not app.dataframe

    app.selectbox[0].select(2).run()
    assert not app.exception
    assert app.selectbox[0].value == 2
    assert _metrics(app)["Baseline coverage"] == "50.00%"
    assert _metrics(app)["Baseline-covered observations"] == "1 / 2 total"
    assert _metrics(app)["MR violations"] == "0"
    assert _metrics(app)["Valid baseline-covered MRs above UCL"] == "0.00% (1 valid MRs)"
    assert _metrics(app)["Rule 1"] == "0"
    assert _metrics(app)["Rule 2"] == "1"
    assert _metrics(app)["Rule 3"] == "1"
    assert _metrics(app)["Rule 4"] == "1"
    assert _metrics(app)["Observations with signal"] == "1"
    assert _metrics(app)["Baseline-covered signal rate"] == "100.00%"
    i_chart, mr_chart = _charts(app)
    assert _values(_trace(i_chart, "Measured value").y) == [100.0, 110.0]
    assert _values(_trace(i_chart, "Rule 2 + Rule 3 + Rule 4").y) == [100.0]
    assert _values(_trace(i_chart, "UCL").y)[0] == 105.0
    assert _values(_trace(mr_chart, "MR UCL").y)[0] == 6.0
    assert _values(_trace(mr_chart, "Moving range").y)[0] == 2.0
    assert _values(_trace(mr_chart, "MR violations (> UCL)").y) == []
    assert app.dataframe[0].value["Measurement ID"].tolist() == [3]

    app.selectbox[0].select(1).run()
    assert not app.exception
    assert _metrics(app)["Baseline coverage"] == "100.00%"
    assert _metrics(app)["MR violations"] == "1"
    assert _metrics(app)["Valid baseline-covered MRs above UCL"] == "100.00% (1 valid MRs)"
    assert _metrics(app)["Rule 1"] == "1"
    assert _metrics(app)["Rule 2"] == "0"
    assert _metrics(app)["Rule 3"] == "0"
    assert _metrics(app)["Rule 4"] == "0"
    assert _metrics(app)["Baseline-covered signal rate"] == "50.00%"
    assert _values(_trace(_charts(app)[0], "Measured value").y) == [10.0, 12.0]
    assert _values(_trace(_charts(app)[0], "UCL").y) == [78.0, 78.0]
    assert _values(_trace(_charts(app)[1], "Moving range").y)[1] == 4.0
    assert _values(_trace(_charts(app)[1], "MR UCL").y) == [3.0, 3.0]
    assert app.dataframe[0].value["Measurement ID"].tolist() == [2]

    app.selectbox[0].select(2).run()
    assert not app.exception
    assert _metrics(app)["Baseline coverage"] == "50.00%"
    assert _metrics(app)["Rule 3"] == "1"
    assert _metrics(app)["Rule 4"] == "1"
    assert _values(_trace(_charts(app)[0], "Measured value").y) == [100.0, 110.0]
    assert app.dataframe[0].value["Measurement ID"].tolist() == [3]


def _refresh_dashboard(app, rows, replacement):
    rows[:] = replacement
    st.cache_data.clear()
    app.run()
    assert not app.exception


def test_disappearing_selection_requires_new_explicit_choice(run_dashboard):
    rows = [
        _row(1),
        _row(2, specification_id=2, characteristic="Weight", rule_1=True, spc_signal=True),
        _row(3, specification_id=3, characteristic="Density"),
    ]
    app = run_dashboard(rows)
    app.selectbox[0].select(2).run()
    assert app.dataframe[0].value["Measurement ID"].tolist() == [2]

    _refresh_dashboard(app, rows, [rows[0], rows[2]])
    assert app.selectbox[0].value is None
    assert any("Select a specification" in message.value for message in app.info)
    assert not app.metric
    assert not app.get("plotly_chart")
    assert not app.dataframe
    app.selectbox[0].select(3).run()
    assert not app.exception
    assert _values(_trace(_charts(app)[0], "Measured value").y) == [75.0]
    assert not app.dataframe


def test_refresh_to_one_specification_auto_selects_remaining_scope(run_dashboard):
    rows = [_row(1), _row(2, specification_id=2, characteristic="Weight")]
    app = run_dashboard(rows)
    app.selectbox[0].select(2).run()
    assert app.selectbox[0].value == 2
    _refresh_dashboard(app, rows, [rows[0]])
    assert not app.selectbox
    assert any("Specification: Thickness" in item.value for item in app.caption)
    assert _metrics(app)["Baseline-covered observations"] == "1 / 1 total"

    rows.append(_row(3, specification_id=2, characteristic="Weight"))
    st.cache_data.clear()
    app.run()
    assert not app.exception
    assert app.selectbox[0].value is None
    assert not app.metric
    assert not app.get("plotly_chart")


def test_refresh_to_no_specifications_clears_previous_analysis(run_dashboard):
    rows = [_row(1), _row(2, specification_id=2, characteristic="Weight")]
    app = run_dashboard(rows)
    app.selectbox[0].select(2).run()
    assert app.metric
    _refresh_dashboard(app, rows, [])
    assert any("contains no records" in warning.value for warning in app.warning)
    assert not app.selectbox
    assert not app.metric
    assert not app.get("plotly_chart")
    assert not app.dataframe

    rows.extend([_row(1), _row(2, specification_id=2, characteristic="Weight")])
    st.cache_data.clear()
    app.run()
    assert not app.exception
    assert app.selectbox[0].value is None
    assert not app.metric


@pytest.mark.parametrize("column", ["specification_id", "characteristic", "specification_unit"])
def test_missing_specification_information_stops_analysis(run_dashboard, column):
    app = run_dashboard([_row(1), _row(2, **{column: None})])

    assert any("missing specification information" in error.value for error in app.error)
    assert not app.metric
    assert not app.get("plotly_chart")


def test_inconsistent_specification_metadata_stops_analysis(run_dashboard):
    app = run_dashboard([_row(1), _row(2, characteristic="Other")])

    assert any("Inconsistent specification information" in error.value for error in app.error)
    assert not app.metric
    assert not app.get("plotly_chart")


def test_missing_assigned_baseline_limits_stop_analysis(run_dashboard):
    app = run_dashboard(
        [
            _row(1, None, moving_range=4.0),
            _row(
                2, 1, center_line=None, i_lcl=None, i_ucl=None,
                mr_center=None, mr_ucl=None, moving_range=5.0,
                rule_1=True, spc_signal=True,
            ),
        ]
    )
    assert any("missing or invalid control limits" in error.value for error in app.error)
    assert not app.metric
    assert not app.get("plotly_chart")


def test_zero_valid_moving_ranges_preserves_coverage_and_signals(run_dashboard):
    app = run_dashboard([_row(1, 1, rule_1=True, spc_signal=True)])

    metrics = _metrics(app)
    assert metrics["Baseline coverage"] == "100.00%"
    assert metrics["MR violations"] == "N/A"
    assert metrics["Valid baseline-covered MRs above UCL"] == "N/A"
    assert metrics["Maximum moving range"] == "N/A"
    assert metrics["Observations with signal"] == "1"
    i_chart, mr_chart = _charts(app)
    assert len(_trace(i_chart, "Rule 1").x) == 1
    assert _values(_trace(mr_chart, "MR UCL").y) == [3.0]


def test_coverage_and_mr_violations_use_baseline_covered_ranges(run_dashboard):
    app = run_dashboard(
        [
            _row(1, 1, moving_range=None),
            _row(2, 1, moving_range=4.0, rule_1=True, spc_signal=True),
            _row(3, 1, moving_range=2.0),
            _row(4, None, moving_range=9.0),
        ]
    )
    metrics = _metrics(app)
    assert metrics["Baseline coverage"] == "75.00%"
    assert metrics["Baseline-covered observations"] == "3 / 4 total"
    assert metrics["MR violations"] == "1"
    assert metrics["Valid baseline-covered MRs above UCL"] == (
        "50.00% (2 valid MRs)"
    )
    assert metrics["Maximum moving range"] == "4.000"
    assert metrics["Observations with signal"] == "1"
    assert any(
        caption.value == (
            "Data sources: PostgreSQL views v_spc_rule_results and v_measurement_enriched, "
            "and tables dim_specification and spc_baseline."
        )
        for caption in app.caption
    )
    i_chart, mr_chart = _charts(app)
    assert len(_trace(i_chart, "Rule 1").x) == 1
    assert _values(_trace(mr_chart, "MR violations (> UCL)").y) == [4.0]


def test_control_limits_break_at_baseline_transitions(run_dashboard):
    rows = [
        _row(1, 1, moving_range=None),
        _row(2, 1, moving_range=2.0),
        _row(
            3, 2, moving_range=4.0, center_line=85.0, i_lcl=82.0,
            i_ucl=88.0, mr_center=2.0, mr_ucl=6.0,
            rule_1=True, spc_signal=True,
        ),
        _row(
            4, 2, moving_range=1.0, center_line=85.0, i_lcl=82.0,
            i_ucl=88.0, mr_center=2.0, mr_ucl=6.0,
        ),
        _row(5, None, moving_range=9.0),
    ]
    app = run_dashboard(rows)
    i_chart, mr_chart = _charts(app)

    for chart, names in (
        (i_chart, ["Center line", "LCL", "UCL"]),
        (mr_chart, ["MR center line", "MR UCL", "MR LCL (D3 = 0)"]),
    ):
        for name in names:
            trace = _trace(chart, name)
            assert trace.connectgaps is False
            values = _values(trace.y)
            assert len(values) == 7
            assert pd.isna(values[2])
            assert pd.isna(values[5])
            assert all(not pd.isna(values[i]) for i in [0, 1, 3, 4])
    assert _values(_trace(i_chart, "Measured value").y) == [75.0] * 5
    assert len(_trace(i_chart, "Rule 1").x) == 1
    assert len(_values(_trace(mr_chart, "Moving range").y)) == 5
    assert [_values(_trace(i_chart, "UCL").y)[i] for i in [0, 1, 3, 4]] == [
        78.0, 78.0, 88.0, 88.0,
    ]
    assert [_values(_trace(mr_chart, "MR UCL").y)[i] for i in [0, 1, 3, 4]] == [
        3.0, 3.0, 6.0, 6.0,
    ]


@pytest.mark.parametrize(
    ("rows", "coverage", "covered", "uncovered", "covered_rate", "no_signal"),
    [
        ([_row(1, None), _row(2, None)], "0.00%", "0 / 2 total", "2", "N/A", "0"),
        (
            [_row(1, 1, rule_1=True, spc_signal=True), _row(2, 1), _row(3, None)],
            "66.67%", "2 / 3 total", "1", "50.00%", "1",
        ),
        (
            [_row(1, 1, rule_1=True, spc_signal=True), _row(2, 1)],
            "100.00%", "2 / 2 total", "0", "50.00%", "1",
        ),
    ],
)
def test_coverage_and_signal_denominators(
    run_dashboard, rows, coverage, covered, uncovered, covered_rate, no_signal
):
    app = run_dashboard(rows)
    metrics = _metrics(app)
    assert metrics["Total measurements"] == str(len(rows))
    assert metrics["Baseline coverage"] == coverage
    assert metrics["Baseline-covered observations"] == covered
    assert metrics["Not assessed (no applicable baseline)"] == uncovered
    assert "Overall signal rate" not in metrics
    assert metrics["Baseline-covered signal rate"] == covered_rate
    assert metrics["Assessed with no SPC signal"] == no_signal
    if int(uncovered):
        assert any("not assessed" in warning.value for warning in app.warning)
    if not int(covered.split()[0]):
        assert any("No observations were assessed" in info.value for info in app.info)
        assert not app.table
        assert "not assessed" in _trace(_charts(app)[0], "Measured value").text[0]


def test_provenance_and_hover_preserve_historical_baseline_segments(run_dashboard):
    retired = {
        "baseline_current_status": "RETIRED",
        "baseline_effective_to": pd.Timestamp("2026-04-01", tz="UTC"),
    }
    app = run_dashboard([
        _row(1, 1, **retired),
        _row(2, 2, center_line=85.0, i_lcl=82.0, i_ucl=88.0, mr_center=2.0, mr_ucl=6.0),
        _row(3, 1, **retired),
        _row(4, None),
    ])
    provenance = app.table[0].value
    assert provenance["Baseline ID"].tolist() == [1, 2]
    assert provenance["Version"].tolist() == [1, 2]
    assert provenance["Current status"].tolist() == ["RETIRED", "ACTIVE"]
    assert pd.notna(provenance["Effective to (exclusive, Europe/Budapest; blank means open)"].iloc[0])
    assert pd.isna(provenance["Effective to (exclusive, Europe/Budapest; blank means open)"].iloc[1])
    assert provenance["Approved by"].tolist() == ["Reviewer", "Reviewer"]
    assert str(provenance["Approved at (Europe/Budapest)"].iloc[0]) == "2026-03-01 01:00:00+01:00"
    assert any("not at measurement time" in caption.value for caption in app.caption)
    for chart, limit, center in (
        (_charts(app)[0], "UCL", "I UCL"),
        (_charts(app)[1], "MR UCL", "MR UCL"),
    ):
        trace = _trace(chart, limit)
        assert trace.connectgaps is False
        assert [i for i, value in enumerate(_values(trace.y)) if pd.isna(value)] == [1, 3, 5, 6]
        assert "Baseline ID 1" in trace.text[0]
        assert "Baseline ID 2" in trace.text[2]
        assert "version 2" in trace.text[2]
        assert center in trace.text[2]
        assert len(chart.layout.shapes) == 3


def test_provenance_is_filtered_with_selected_specification(run_dashboard):
    app = run_dashboard([
        _row(1, 1),
        _row(2, 2, specification_id=2, characteristic="Weight"),
    ])
    app.selectbox[0].select(2).run()
    assert not app.exception
    assert app.table[0].value["Baseline ID"].tolist() == [2]
    app.selectbox[0].select(1).run()
    assert not app.exception
    assert app.table[0].value["Baseline ID"].tolist() == [1]


def test_missing_assigned_baseline_metadata_is_explicit(run_dashboard):
    app = run_dashboard([_row(1, 1, baseline_version=None, baseline_current_status=None)])
    assert any("baseline metadata is unavailable" in warning.value for warning in app.warning)
    assert "version Unavailable" in _trace(_charts(app)[0], "Measured value").text[0]


def test_january_baseline_values_and_approval_are_shown_without_refitting(run_dashboard):
    january_limits = {
        "center_line": 74.540491,
        "sigma": 1.197419,
        "i_lcl": 70.948233,
        "i_ucl": 78.132749,
        "mr_center": 1.350689,
        "mr_ucl": 4.412701,
        "baseline_approved_by": "Bela Pager",
        "baseline_approved_at": pd.Timestamp("2026-11-07 19:56:53", tz="UTC"),
        "baseline_effective_from": pd.Timestamp("2026-01-19 05:00:00", tz="UTC"),
    }
    app = run_dashboard([
        _row(1, None, measurement_timestamp=pd.Timestamp("2026-01-19 05:59")),
        _row(
            2, 1, measurement_timestamp=pd.Timestamp("2026-01-19 06:00"),
            measured_value=80.0, rule_1=True, rule_3=True, spc_signal=True,
            **january_limits,
        ),
        _row(
            3, 1, measurement_timestamp=pd.Timestamp("2026-01-19 06:01"),
            measured_value=70.0, moving_range=5.0, **january_limits,
        ),
    ])
    i_chart, mr_chart = _charts(app)
    for chart, trace_name, value in (
        (i_chart, "Center line", 74.540491),
        (i_chart, "LCL", 70.948233),
        (i_chart, "UCL", 78.132749),
        (mr_chart, "MR center line", 1.350689),
        (mr_chart, "MR UCL", 4.412701),
    ):
        values = _values(_trace(chart, trace_name).y)
        assert pd.isna(values[0])
        assert values[-2:] == [value, value]
    assert _metrics(app)["Baseline-covered observations"] == "2 / 3 total"
    assert _metrics(app)["Rule 1"] == "1"
    assert _metrics(app)["Rule 3"] == "1"
    assert _metrics(app)["MR violations"] == "1"
    provenance = app.table[0].value
    assert provenance["Approved by"].tolist() == ["Bela Pager"]
    assert str(provenance["Approved at (Europe/Budapest)"].iloc[0]) == "2026-11-07 20:56:53+01:00"
    assert str(provenance["Effective from (inclusive, Europe/Budapest)"].iloc[0]) == "2026-01-19 06:00:00+01:00"
    assert provenance["I center line"].tolist() == [74.540491]
    assert provenance["MR UCL"].tolist() == [4.412701]
    assert "Fitting start (inclusive, Europe/Budapest)" in provenance.columns


def test_spc_filters_keep_rule_context_and_break_chart_lines(run_dashboard):
    rows = [
        _row(1, 1, batch_id=10, robot_names=["R1", "R2"], measured_value=10.0),
        _row(2, None, batch_id=20, robot_names=["R2"], measured_value=20.0),
        _row(3, 1, batch_id=10, robot_names=["R1"], measured_value=30.0,
             moving_range=4.0, rule_3=True, spc_signal=True),
        _row(4, 1, batch_id=10, robot_names=["R1"], shift_name="SHIFT_02",
             measured_value=40.0, moving_range=5.0),
    ]
    app = run_dashboard(rows)
    app.multiselect(key="spc_batches_1").set_value([10]).run()
    assert not app.exception
    assert _metrics(app)["Total measurements"] == "3"
    assert _metrics(app)["Rule 3"] == "1"
    assert _metrics(app)["MR violations"] == "2"
    i_chart, mr_chart = _charts(app)
    for chart, name in ((i_chart, "Measured value"), (i_chart, "UCL"),
                        (mr_chart, "Moving range"), (mr_chart, "MR UCL")):
        assert pd.isna(_values(_trace(chart, name).y)[1])
        assert _trace(chart, name).connectgaps is False
    assert any("original within-shift context" in caption.value for caption in app.caption)
    assert app.dataframe[0].value["Measurement ID"].tolist() == [3]
    assert app.dataframe[1].value["Measurement ID"].tolist() == [3, 4]

    app.multiselect(key="spc_shifts_1").set_value(["SHIFT_01"]).run()
    app.multiselect(key="spc_robots_1").set_value(["R2"]).run()
    assert not app.exception
    assert _metrics(app)["Total measurements"] == "1"
    assert _values(_trace(_charts(app)[0], "Measured value").y) == [10.0]
    assert _metrics(app)["MR violations"] == "N/A"


def test_date_filter_and_empty_selection(run_dashboard):
    app = run_dashboard([
        _row(1, measurement_timestamp=pd.Timestamp("2026-03-01 06:00"),
             robot_names=["R2"]),
        _row(2, measurement_timestamp=pd.Timestamp("2026-03-02 06:00"),
             robot_names=["R1"], rule_4=True, spc_signal=True),
    ])
    app.date_input(key="spc_dates_1").set_value(
        (pd.Timestamp("2026-03-02").date(), pd.Timestamp("2026-03-02").date())
    ).run()
    assert not app.exception
    assert _metrics(app)["Total measurements"] == "1"
    assert _metrics(app)["Rule 4"] == "1"
    app.multiselect(key="spc_robots_1").set_value(["R2"]).run()
    assert any("No SPC measurements match" in item.value for item in app.warning)
    assert not app.metric
    assert not app.get("plotly_chart")


def test_spc_filters_are_scoped_to_specification(run_dashboard):
    app = run_dashboard([
        _row(1, batch_id=10),
        _row(2, batch_id=20, specification_id=2, characteristic="Weight"),
    ])
    app.selectbox[0].select(1).run()
    app.multiselect(key="spc_batches_1").set_value([10]).run()
    app.selectbox[0].select(2).run()
    assert not app.exception
    assert _metrics(app)["Total measurements"] == "1"
    assert app.multiselect(key="spc_batches_2").value == []


@pytest.mark.parametrize(
    ("key", "field", "selected", "other"),
    [
        ("spc_batches_1", "batch_id", 10, 20),
        ("spc_shifts_1", "shift_name", "SHIFT_01", "SHIFT_02"),
        ("spc_robots_1", "robot_names", "R1", "R2"),
    ],
)
def test_unavailable_filter_requires_explicit_clear(run_dashboard, key, field, selected, other):
    values = lambda value: [value] if field == "robot_names" else value
    rows = [_row(1, **{field: values(selected)}), _row(2, **{field: values(other)})]
    app = run_dashboard(rows)
    app.multiselect(key=key).set_value([selected]).run()
    assert _metrics(app)["Total measurements"] == "1"

    _refresh_dashboard(app, rows, [rows[1]])
    assert not app.exception
    assert app.multiselect(key=key).value == [selected]
    assert any("unavailable" in item.value for item in app.warning)
    assert not app.metric
    assert not app.get("plotly_chart")
    app.run()
    assert app.multiselect(key=key).value == [selected]
    assert not app.metric

    app.multiselect(key=key).set_value([]).run()
    assert not app.exception
    assert _metrics(app)["Total measurements"] == "1"


@pytest.mark.parametrize(
    ("key", "field", "missing", "remaining"),
    [
        ("spc_batches_1", "batch_id", 10, 20),
        ("spc_shifts_1", "shift_name", "SHIFT_01", "SHIFT_02"),
        ("spc_robots_1", "robot_names", "R1", "R2"),
    ],
)
def test_partially_unavailable_filter_preserves_selection(run_dashboard, key, field, missing, remaining):
    values = lambda value: [value] if field == "robot_names" else value
    rows = [_row(1, **{field: values(missing)}), _row(2, **{field: values(remaining)})]
    app = run_dashboard(rows)
    app.multiselect(key=key).set_value([missing, remaining]).run()
    _refresh_dashboard(app, rows, [rows[1]])
    assert not app.exception
    assert set(app.multiselect(key=key).value) == {missing, remaining}
    assert any("unavailable" in item.value for item in app.warning)
    assert _metrics(app)["Total measurements"] == "1"
    assert _values(_trace(_charts(app)[0], "Measured value").y) == [75.0]
    app.multiselect(key=key).set_value([remaining]).run()
    assert not any("unavailable" in item.value for item in app.warning)
    assert _metrics(app)["Total measurements"] == "1"


@pytest.mark.parametrize(
    ("key", "field", "selected", "other"),
    [
        ("spc_batches_1", "batch_id", 10, 20),
        ("spc_shifts_1", "shift_name", "SHIFT_01", "SHIFT_02"),
        ("spc_robots_1", "robot_names", "R1", "R2"),
    ],
)
def test_unavailable_filter_selection_recovers_when_value_returns(run_dashboard, key, field, selected, other):
    values = lambda value: [value] if field == "robot_names" else value
    selected_row = _row(1, **{field: values(selected)})
    other_row = _row(2, **{field: values(other)})
    rows = [selected_row, other_row]
    app = run_dashboard(rows)
    app.multiselect(key=key).set_value([selected]).run()
    _refresh_dashboard(app, rows, [other_row])
    assert not app.metric
    _refresh_dashboard(app, rows, [selected_row, other_row])
    assert not app.exception
    assert app.multiselect(key=key).value == [selected]
    assert not any("unavailable" in item.value for item in app.warning)
    assert _metrics(app)["Total measurements"] == "1"


def test_missing_batch_or_shift_information_stops_analysis(run_dashboard):
    app = run_dashboard([_row(1, batch_id=None)])
    assert any("missing batch or shift" in item.value for item in app.error)
    assert not app.metric


def test_active_baseline_is_visible_when_selected_measurements_are_uncovered(run_dashboard):
    active = {
        "id": 1, "version": 1, "status": "ACTIVE",
        "approved_by": "Reviewer", "approved_at": "2026-03-01T00:00:00+00:00",
        "window_start": "2026-01-01T05:00:00+00:00",
        "window_end": "2026-01-19T05:00:00+00:00",
        "effective_from": "2026-01-19T05:00:00+00:00", "effective_to": None,
        "center_line": 74.540491, "sigma": 1.197419, "i_lcl": 70.948233,
        "i_ucl": 78.132749, "mr_center": 1.350689, "mr_ucl": 4.412701,
    }
    app = run_dashboard([_row(1, None, active_baseline=active)])
    assert _metrics(app)["Baseline coverage"] == "0.00%"
    assert _metrics(app)["Rule 1"] == "N/A"
    assert any("not assigned to the selected measurements" in item.value for item in app.caption)
    summary = app.dataframe[0].value
    assert summary["Baseline ID"].tolist() == [1]
    assert summary["I UCL"].tolist() == [78.132749]
    assert summary["Approved by"].tolist() == ["Reviewer"]
    assert str(summary["Effective from (inclusive, Europe/Budapest)"].iloc[0]) == "2026-01-19 06:00:00+01:00"


@pytest.mark.parametrize(
    "flags", [
        {"spc_signal": True}, {"rule_1": True}, {"rule_2": True},
        {"rule_3": True}, {"rule_4": True},
    ]
)
def test_uncovered_spc_signal_is_rejected(run_dashboard, flags):
    app = run_dashboard([_row(1, None, **flags)])
    assert any("signals were returned" in error.value for error in app.error)
    assert not app.metric
    assert not app.get("plotly_chart")


def test_zero_coverage_shows_raw_values_without_control_legends(run_dashboard):
    app = run_dashboard([
        _row(1, None, measured_value=70.0, moving_range=None),
        _row(2, None, measured_value=90.0, moving_range=20.0),
    ])
    i_chart, mr_chart = _charts(app)
    assert _values(_trace(i_chart, "Measured value").y) == [70.0, 90.0]
    assert _values(_trace(mr_chart, "Moving range").y)[1] == 20.0
    assert _trace(i_chart, "Measured value").mode == "lines+markers"
    assert _trace(mr_chart, "Moving range").mode == "lines+markers"
    assert _trace(mr_chart, "MR violations (> UCL)").showlegend is False
    assert not {"Center line", "LCL", "UCL"} & {t.name for t in i_chart.data}
    assert not {"MR center line", "MR UCL", "MR LCL (D3 = 0)"} & {
        t.name for t in mr_chart.data
    }
    assert "not assessed" in _trace(i_chart, "Measured value").text[1]
    assert "not assessed" in _trace(mr_chart, "Moving range").text[1]
    metrics = _metrics(app)
    for label in [
        "MR violations", "Valid baseline-covered MRs above UCL",
        "Maximum moving range", "Baseline-covered signal rate",
        "Rule 1", "Rule 2", "Rule 3", "Rule 4", "Observations with signal",
    ]:
        assert metrics[label] == "N/A"
    assert any(
        info.value == (
            "No approved baseline is available. Measurements are displayed for "
            "descriptive purposes only; SPC evaluation is not available."
        )
        for info in app.info
    )


def test_partial_coverage_masks_stray_limits_and_excludes_uncovered_mrs(run_dashboard):
    app = run_dashboard([
        _row(1, None, measured_value=10.0, moving_range=99.0, center_line=42.0,
             i_lcl=40.0, i_ucl=44.0, mr_center=1.0, mr_ucl=3.0),
        _row(2, 1, measured_value=11.0, moving_range=2.0, rule_1=True,
             rule_2=True, rule_3=True, rule_4=True, spc_signal=True),
        _row(3, None, measured_value=12.0, moving_range=100.0),
        _row(4, 1, measured_value=13.0, moving_range=4.0),
    ])
    metrics = _metrics(app)
    assert metrics["Baseline coverage"] == "50.00%"
    assert metrics["MR violations"] == "1"
    assert metrics["Valid baseline-covered MRs above UCL"] == "50.00% (2 valid MRs)"
    assert metrics["Maximum moving range"] == "4.000"
    assert metrics["Baseline-covered signal rate"] == "50.00%"
    assert [metrics[f"Rule {i}"] for i in range(1, 5)] == ["1"] * 4
    assert any("Only baseline-covered observations" in item.value for item in app.info)
    i_chart, mr_chart = _charts(app)
    assert _values(_trace(i_chart, "Measured value").y) == [10.0, 11.0, 12.0, 13.0]
    assert _values(_trace(mr_chart, "Moving range").y) == [99.0, 2.0, 100.0, 4.0]
    for chart, names in (
        (i_chart, ["Center line", "LCL", "UCL"]),
        (mr_chart, ["MR center line", "MR UCL", "MR LCL (D3 = 0)"]),
    ):
        for name in names:
            values = _values(_trace(chart, name).y)
            assert pd.isna(values[0]) and pd.isna(values[3])
            assert pd.notna(values[2]) and pd.notna(values[6])
        assert len(chart.layout.shapes) == 3
    assert _values(_trace(mr_chart, "MR violations (> UCL)").y) == [4.0]
    assert "Baseline ID 1" in _trace(i_chart, "Measured value").text[1]
    assert "Baseline ID 1" in _trace(mr_chart, "Moving range").text[1]
    assert "not assessed" in _trace(i_chart, "Measured value").text[0]
    assert "not assessed" in _trace(mr_chart, "Moving range").text[0]


@pytest.mark.parametrize("column", ["center_line", "sigma", "i_lcl", "i_ucl", "mr_center", "mr_ucl"])
def test_invalid_assigned_limits_stop_both_chart_evaluations(run_dashboard, column):
    app = run_dashboard([_row(1, **{column: float("inf")})])
    assert any("missing or invalid control limits" in error.value for error in app.error)
    assert not app.get("plotly_chart")
