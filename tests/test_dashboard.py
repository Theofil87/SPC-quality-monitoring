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
        "baseline_id": baseline_id,
        "baseline_version": baseline_id,
        "baseline_current_status": "ACTIVE" if baseline_id is not None else None,
        "baseline_effective_from": pd.Timestamp("2026-03-01", tz="UTC") if baseline_id is not None else None,
        "baseline_effective_to": None,
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
    assert pd.notna(provenance["Effective to (exclusive; blank means open)"].iloc[0])
    assert pd.isna(provenance["Effective to (exclusive; blank means open)"].iloc[1])
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
