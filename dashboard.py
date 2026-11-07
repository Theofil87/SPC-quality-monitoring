
import os

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError

st.set_page_config(
    page_title="SPC & Quality Monitoring",
    page_icon="📊",
    layout="wide",
)

st.title("SPC & Quality Monitoring")
st.caption("Manufacturing quality analytics | Powder coating process")


@st.cache_data(ttl=3600)
def load_spc_results():
    """Read baseline-based SPC results for BOOTH_01 / A-L1."""
    query = text("""
        SELECT
            spc.measurement_timestamp,
            spc.measurement_id,
            measurement.specification_id,
            specification.characteristic,
            specification.unit AS specification_unit,
            CAST(spc.baseline_id AS TEXT) AS baseline_id,
            baseline.version AS baseline_version,
            baseline.status AS baseline_current_status,
            baseline.effective_from AS baseline_effective_from,
            baseline.effective_to AS baseline_effective_to,
            spc.booth,
            spc.measurement_point,
            spc.shift_id,
            spc.shift_name,
            spc.shift_instance,
            spc.measured_value,
            spc.moving_range,
            spc.center_line,
            spc.sigma,
            spc.i_lcl,
            spc.i_ucl,
            spc.mr_center,
            spc.mr_ucl,
            spc.rule_1,
            spc.rule_2,
            spc.rule_3,
            spc.rule_4,
            spc.spc_signal
        FROM v_spc_rule_results AS spc
        LEFT JOIN v_measurement_enriched AS measurement
            ON measurement.measurement_id = spc.measurement_id
        LEFT JOIN dim_specification AS specification
            ON specification.specification_id = measurement.specification_id
        LEFT JOIN spc_baseline AS baseline
            ON baseline.baseline_id = spc.baseline_id
        WHERE spc.booth = 'BOOTH_01'
          AND spc.measurement_point = 'A-L1'
        ORDER BY spc.measurement_timestamp, spc.measurement_id
    """)

    engine = get_engine()

    with engine.connect() as connection:
        return pd.read_sql_query(query, connection)


@st.cache_resource
def get_engine():
    """Create a PostgreSQL connection using environment settings."""
    url = URL.create(
        drivername="postgresql+psycopg2",
        username=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD") or None,
        host=os.getenv("PGHOST", "localhost"),
        port=int(os.getenv("PGPORT", "5432")),
        database=os.getenv("PGDATABASE", "spc_quality_monitoring"),
    )
    return create_engine(url, pool_pre_ping=True)


dashboard_section = st.sidebar.radio(
    "Dashboard section",
    options=["Quality dashboard", "SPC monitoring"],
    key="dashboard_section",
)

if dashboard_section == "SPC monitoring":
    st.header("SPC monitoring")
    st.info(
        "Current scope: BOOTH_01 / A-L1 only. Other booths and "
        "measurement points are not yet supported."
    )

    try:
        with st.spinner("Loading SPC results from PostgreSQL..."):
            spc_df = load_spc_results()
    except (SQLAlchemyError, OSError, ValueError) as exc:
        st.error("Could not load SPC results from PostgreSQL.")
        st.caption(
            "Check the PostgreSQL service, connection settings, "
            "database permissions and whether the SPC results view exists."
        )
        with st.expander("Technical details"):
            st.code(str(exc))
        st.stop()

    if spc_df.empty:
        if "spc_specification" in st.session_state:
            del st.session_state["spc_specification"]
        st.warning("The BOOTH_01 / A-L1 SPC results view contains no records.")
        st.stop()

    specification_columns = ["specification_id", "characteristic", "specification_unit"]
    if spc_df[specification_columns].isna().any().any():
        st.error("Some SPC results have missing specification information; analysis cannot continue.")
        st.stop()

    specifications = spc_df[specification_columns].drop_duplicates()
    if specifications["specification_id"].duplicated().any():
        st.error("Inconsistent specification information; analysis cannot continue.")
        st.stop()
    specifications = specifications.sort_values("specification_id")
    specification_labels = {
        row.specification_id: (
            f"{row.characteristic} ({row.specification_unit}) — ID {row.specification_id}"
        )
        for row in specifications.itertuples(index=False)
    }
    if (
        st.session_state.get("spc_specification") is not None
        and st.session_state["spc_specification"] not in specification_labels
    ):
        del st.session_state["spc_specification"]
    if len(specification_labels) == 1:
        selected_specification = next(iter(specification_labels))
        st.sidebar.caption(f"Specification: {specification_labels[selected_specification]}")
    else:
        selected_specification = st.sidebar.selectbox(
            "Specification",
            options=list(specification_labels),
            index=None,
            placeholder="Select a specification",
            format_func=specification_labels.get,
            key="spc_specification",
        )
        if selected_specification is None:
            st.info("Select a specification to view SPC results.")
            st.stop()
    spc_df = spc_df.loc[spc_df["specification_id"] == selected_specification].copy()
    if spc_df.empty:
        st.warning("No SPC results match the selected specification.")
        st.stop()

    spc_df["measurement_timestamp"] = pd.to_datetime(
        spc_df["measurement_timestamp"]
    )
    spc_df = spc_df.sort_values(
        ["measurement_timestamp", "measurement_id"], kind="mergesort"
    ).reset_index(drop=True)

    rule_columns = ["rule_1", "rule_2", "rule_3", "rule_4"]
    rule_labels = {
        "rule_1": "Rule 1",
        "rule_2": "Rule 2",
        "rule_3": "Rule 3",
        "rule_4": "Rule 4",
    }
    for column in rule_columns + ["spc_signal"]:
        spc_df[column] = spc_df[column].fillna(False).astype(bool)

    baseline_covered = spc_df["baseline_id"].notna()
    limit_columns = ["center_line", "sigma", "i_ucl", "i_lcl", "mr_center", "mr_ucl"]
    for column in ["moving_range", *limit_columns]:
        spc_df[column] = pd.to_numeric(spc_df[column], errors="coerce")
    if (spc_df[rule_columns + ["spc_signal"]].any(axis=1) & ~baseline_covered).any():
        st.error("SPC rule flags or signals were returned for measurements without a baseline.")
        st.stop()
    if not np.isfinite(spc_df.loc[baseline_covered, limit_columns]).all().all():
        st.error("Some assigned baselines have missing or invalid control limits; SPC analysis cannot continue.")
        st.stop()
    spc_df.loc[~baseline_covered, limit_columns] = np.nan
    spc_df["mr_lcl"] = np.where(baseline_covered, 0.0, np.nan)
    baseline_covered_count = int(baseline_covered.sum())
    baseline_coverage_pct = baseline_covered_count / len(spc_df) * 100

    if baseline_covered_count == 0:
        st.info(
            "No approved baseline is available. Measurements are displayed for "
            "descriptive purposes only; SPC evaluation is not available."
        )
    elif baseline_covered_count < len(spc_df):
        st.info(
            "Only baseline-covered observations are evaluated in both charts. "
            "Uncovered measurements are displayed for descriptive purposes only."
        )

    def display_value(value):
        return "Unavailable" if pd.isna(value) else str(value)

    spc_df["baseline_label"] = [
        (
            f"Baseline ID {display_value(baseline_id)}, version {display_value(version)}"
            if pd.notna(baseline_id)
            else "No applicable baseline — not assessed"
        )
        for baseline_id, version in zip(spc_df["baseline_id"], spc_df["baseline_version"])
    ]
    spc_df["i_hover"] = [
        f"{label}<br>Center line: {display_value(center)}"
        f"<br>I LCL: {display_value(lcl)}<br>I UCL: {display_value(ucl)}"
        for label, center, lcl, ucl in zip(
            spc_df["baseline_label"], spc_df["center_line"], spc_df["i_lcl"], spc_df["i_ucl"]
        )
    ]
    spc_df["mr_hover"] = [
        f"{label}<br>MR center: {display_value(center)}"
        f"<br>MR LCL: {display_value(lcl)}<br>MR UCL: {display_value(ucl)}"
        for label, center, lcl, ucl in zip(
            spc_df["baseline_label"], spc_df["mr_center"], spc_df["mr_lcl"], spc_df["mr_ucl"]
        )
    ]

    previous_baseline = spc_df["baseline_id"].shift()
    same_baseline = (
        spc_df["baseline_id"].eq(previous_baseline).fillna(False)
        | (spc_df["baseline_id"].isna() & previous_baseline.isna())
    )
    transitions = ~same_baseline
    transitions.iloc[0] = False
    limit_columns = ["center_line", "i_ucl", "i_lcl", "mr_center", "mr_ucl", "mr_lcl"]
    plot_columns = ["measurement_timestamp", *limit_columns, "i_hover", "mr_hover"]
    limit_gaps = spc_df.loc[transitions, plot_columns].copy()
    limit_gaps[limit_columns] = np.nan
    limit_plot = pd.concat(
        [limit_gaps, spc_df[plot_columns]]
    ).sort_index(kind="stable")

    spc_df["triggered_rules"] = spc_df[rule_columns].apply(
        lambda row: " + ".join(
            rule_labels[column] for column in rule_columns if row[column]
        ),
        axis=1,
    )

    st.subheader("I-Chart")
    st.caption(
        "SQL-supplied Rule 1–4 signals are highlighted by their triggered "
        "rule combination. The plotted rule flags are not recalculated here."
    )

    i_chart = go.Figure()
    i_chart.add_trace(
        go.Scatter(
            x=spc_df["measurement_timestamp"],
            y=spc_df["measured_value"],
            mode="lines+markers",
            name="Measured value",
            line={"color": "#2b6cb0", "width": 1.5},
            text=spc_df["i_hover"],
            hovertemplate="%{x}<br>Measured value: %{y}<br>%{text}<extra></extra>",
        )
    )
    for column, label, color, dash in (
        ("center_line", "Center line", "#2f855a", "solid"),
        ("i_ucl", "UCL", "#c53030", "dash"),
        ("i_lcl", "LCL", "#c53030", "dash"),
    ):
        if not limit_plot[column].notna().any():
            continue
        i_chart.add_trace(
            go.Scatter(
                x=limit_plot["measurement_timestamp"],
                y=limit_plot[column],
                mode="lines+markers",
                name=label,
                line={"color": color, "dash": dash, "width": 1.5},
                marker={"size": 4},
                connectgaps=False,
                text=limit_plot["i_hover"],
                hovertemplate="%{x}<br>%{text}<extra></extra>",
            )
        )

    signal_rows = spc_df.loc[baseline_covered & spc_df["spc_signal"]]
    signal_combinations = sorted(signal_rows["triggered_rules"].unique())
    marker_colors = [
        "#d62728", "#ff7f0e", "#9467bd", "#8c564b", "#e377c2",
        "#17becf", "#bcbd22", "#393b79", "#637939", "#8c6d31",
        "#843c39", "#7b4173", "#3182bd", "#31a354", "#756bb1",
    ]
    marker_symbols = [
        "circle", "square", "diamond", "cross", "x", "triangle-up",
        "triangle-down", "star", "hexagon", "pentagon", "hourglass",
        "bowtie", "hexagram", "triangle-left", "triangle-right",
    ]
    for index, combination in enumerate(signal_combinations):
        points = signal_rows.loc[signal_rows["triggered_rules"] == combination]
        i_chart.add_trace(
            go.Scatter(
                x=points["measurement_timestamp"],
                y=points["measured_value"],
                mode="markers",
                name=combination,
                marker={
                    "color": marker_colors[index],
                    "symbol": marker_symbols[index],
                    "size": 10,
                    "line": {"width": 1, "color": "white"},
                },
                customdata=points[["measurement_id"]],
                text=points["i_hover"],
                hovertemplate=(
                    "%{x}<br>Measured value: %{y}<br>"
                    "Measurement ID: %{customdata[0]}<br>"
                    f"Triggered: {combination}<br>%{{text}}<extra></extra>"
                ),
            )
        )
    for timestamp in spc_df.loc[transitions, "measurement_timestamp"]:
        i_chart.add_shape(
            type="line", x0=timestamp, x1=timestamp, y0=0, y1=1, yref="paper",
            line={"color": "#777777", "dash": "dot", "width": 1},
        )
    i_chart.update_layout(
        xaxis_title="Measurement timestamp",
        yaxis_title="Measured value",
        hovermode="x unified",
        legend_title="I-chart series and triggered rules",
    )
    st.plotly_chart(
        i_chart,
        width="stretch",
        alt="I-chart showing measured values, center line, control limits and SPC rule signals.",
    )

    st.divider()
    st.subheader("MR-Chart")
    valid_mr = (
        baseline_covered
        & spc_df["moving_range"].notna()
        & np.isfinite(spc_df["moving_range"])
        & spc_df["mr_ucl"].notna()
    )
    spc_df["mr_violation"] = (
        valid_mr & spc_df["moving_range"].gt(spc_df["mr_ucl"])
    )

    valid_mr_count = int(valid_mr.sum())
    mr_violation_count = int(spc_df["mr_violation"].sum())
    mr_violation_rate = (
        mr_violation_count / valid_mr_count * 100
        if valid_mr_count
        else None
    )
    maximum_mr = (
        float(spc_df.loc[valid_mr, "moving_range"].max())
        if valid_mr_count
        else None
    )
    mr_chart = go.Figure()
    mr_chart.add_trace(
        go.Scatter(
            x=spc_df["measurement_timestamp"],
            y=spc_df["moving_range"],
            mode="lines+markers",
            name="Moving range",
            line={"color": "#2b6cb0", "width": 1.5},
            connectgaps=False,
            text=spc_df["mr_hover"],
            hovertemplate="%{x}<br>Moving range: %{y}<br>%{text}<extra></extra>",
        )
    )
    for column, label, color, dash in (
        ("mr_center", "MR center line", "#2f855a", "solid"),
        ("mr_ucl", "MR UCL", "#c53030", "dash"),
        ("mr_lcl", "MR LCL (D3 = 0)", "#c53030", "dash"),
    ):
        if not limit_plot[column].notna().any():
            continue
        mr_chart.add_trace(
            go.Scatter(
                x=limit_plot["measurement_timestamp"],
                y=limit_plot[column],
                mode="lines+markers",
                name=label,
                line={"color": color, "dash": dash, "width": 1.5},
                marker={"size": 4},
                connectgaps=False,
                text=limit_plot["mr_hover"],
                hovertemplate="%{x}<br>%{text}<extra></extra>",
            )
        )

    violation_rows = spc_df.loc[spc_df["mr_violation"]]
    mr_chart.add_trace(
        go.Scatter(
            x=violation_rows["measurement_timestamp"],
            y=violation_rows["moving_range"],
            mode="markers",
            name="MR violations (> UCL)",
            showlegend=bool(valid_mr_count),
            marker={
                "color": "#d62728",
                "symbol": "triangle-up",
                "size": 10,
                "line": {"width": 1, "color": "white"},
            },
            customdata=violation_rows[["measurement_id"]],
            text=violation_rows["mr_hover"],
            hovertemplate=(
                "%{x}<br>Moving range: %{y}<br>"
                "Measurement ID: %{customdata[0]}<br>"
                "MR violation: above UCL<br>%{text}<extra></extra>"
            ),
        )
    )
    for timestamp in spc_df.loc[transitions, "measurement_timestamp"]:
        mr_chart.add_shape(
            type="line", x0=timestamp, x1=timestamp, y0=0, y1=1, yref="paper",
            line={"color": "#777777", "dash": "dot", "width": 1},
        )
    mr_chart.update_layout(
        xaxis_title="Measurement timestamp",
        yaxis_title="Moving range (2 observations)",
        hovermode="x unified",
        legend_title="MR-chart series",
    )
    st.plotly_chart(
        mr_chart,
        width="stretch",
        alt="Moving-range chart with stored baseline control limits and violations.",
    )
    st.caption(
        "An MR violation is a moving range above its UCL, indicating unusually "
        "large change between consecutive observations. These are separate "
        "from the I-chart SPC rule flags. Uncovered moving ranges are descriptive only."
    )
    mr_kpis = st.columns(3)
    mr_kpis[0].metric(
        "MR violations", f"{mr_violation_count:,}" if valid_mr_count else "N/A"
    )
    mr_kpis[1].metric(
        "Valid baseline-covered MRs above UCL",
        (
            f"{mr_violation_rate:.2f}% ({valid_mr_count:,} valid MRs)"
            if mr_violation_rate is not None
            else "N/A"
        ),
    )
    mr_kpis[2].metric(
        "Maximum moving range",
        f"{maximum_mr:.3f}" if maximum_mr is not None else "N/A",
    )
    coverage_column, total_column = st.columns(2)
    coverage_column.metric(
        "Baseline coverage",
        f"{baseline_coverage_pct:.2f}%",
        help="Baseline-covered observations divided by all filtered observations.",
    )
    total_column.metric(
        "Baseline-covered observations",
        f"{baseline_covered_count:,} / {len(spc_df):,} total",
    )
    counts = st.columns(2)
    counts[0].metric("Total measurements", f"{len(spc_df):,}")
    counts[1].metric("Not assessed (no applicable baseline)", f"{len(spc_df) - baseline_covered_count:,}")
    if baseline_covered_count < len(spc_df):
        st.warning(
            "Measurements without an applicable baseline are not assessed; "
            "they must not be interpreted as in-control."
        )

    st.subheader("Baseline provenance")
    st.caption(
        "Current status is shown at the last data load, not at measurement time. "
        "Results and status may be cached for up to one hour. "
        "Dotted lines mark changes in the assigned baseline."
    )
    provenance_columns = [
        "baseline_id", "baseline_version", "baseline_current_status",
        "baseline_effective_from", "baseline_effective_to",
    ]
    provenance = spc_df.loc[baseline_covered, provenance_columns].drop_duplicates()
    if provenance.empty:
        st.info("No applicable baseline was assigned to these measurements.")
    else:
        if provenance[["baseline_version", "baseline_current_status", "baseline_effective_from"]].isna().any().any():
            st.warning("Some assigned baseline metadata is unavailable.")
        st.table(
            provenance.rename(columns={
                "baseline_id": "Baseline ID",
                "baseline_version": "Version",
                "baseline_current_status": "Current status",
                "baseline_effective_from": "Effective from (inclusive)",
                "baseline_effective_to": "Effective to (exclusive; blank means open)",
            }).reset_index(drop=True),
            alt="Baselines assigned to the selected specification",
        )

    st.divider()
    st.subheader("SPC rule summary")
    rule_counts = {
        rule_labels[column]: int(spc_df.loc[baseline_covered, column].sum())
        for column in rule_columns
    }
    covered_signal_count = len(signal_rows)
    covered_signal_rate = (
        covered_signal_count / baseline_covered_count * 100 if baseline_covered_count else None
    )
    summary_columns = st.columns(5)
    for column, (label, count) in zip(
        summary_columns,
        [
            *rule_counts.items(),
            ("Observations with signal", covered_signal_count),
        ],
    ):
        column.metric(label, f"{count:,}" if baseline_covered_count else "N/A")
    st.metric(
        "Baseline-covered signal rate",
        f"{covered_signal_rate:.2f}%" if covered_signal_rate is not None else "N/A",
        help="Measurements with an SPC signal divided by baseline-covered measurements.",
    )
    st.caption("Signal rate denominator: baseline-covered measurements only.")
    st.metric(
        "Assessed with no SPC signal",
        f"{baseline_covered_count - covered_signal_count:,}",
        help="No SPC signal does not establish that the process is in control.",
    )

    st.divider()
    st.subheader("Signal details")
    if signal_rows.empty:
        st.info(
            "No baseline-covered observations have an SPC signal."
            if baseline_covered_count
            else "No observations were assessed for SPC signals."
        )
    else:
        signal_details = signal_rows[
            [
                "measurement_timestamp",
                "measurement_id",
                "measured_value",
                "triggered_rules",
                "spc_signal",
            ]
        ].rename(
            columns={
                "measurement_timestamp": "Timestamp",
                "measurement_id": "Measurement ID",
                "measured_value": "Measured value",
                "triggered_rules": "Triggered SPC rules",
                "spc_signal": "SPC signal status",
            }
        )
        st.dataframe(
            signal_details,
            width="stretch",
            hide_index=True,
        )

    st.caption(
        "Data sources: PostgreSQL views v_spc_rule_results and v_measurement_enriched, "
        "and tables dim_specification and spc_baseline."
    )
    st.stop()


@st.cache_data(ttl=3600)
def load_measurements():
    """Read the existing validated measurement view."""
    query = text("""
        SELECT
            measurement_id,
            cabin_id,
            production_date,
            production_timestamp,
            booth_name,
            shift_name,
            point_code,
            characteristic,
            measured_value,
            unit,
            lsl,
            target,
            usl,
            is_oos,
            compliance_status
        FROM v_measurement_enriched
        ORDER BY production_timestamp, measurement_id
    """)

    engine = get_engine()

    with engine.connect() as connection:
        return pd.read_sql_query(query, connection)


try:
    with st.spinner("Loading measurements from PostgreSQL..."):
        df = load_measurements()

except (SQLAlchemyError, OSError, ValueError) as exc:
    st.error("Could not connect to PostgreSQL or load the measurements.")
    st.caption(
        "Check the PostgreSQL service, connection settings, "
        "database permissions and whether the SQL views exist."
    )
    with st.expander("Technical details"):
        st.code(str(exc))
    st.stop()


if df.empty:
    st.warning("The measurement view contains no records.")
    st.stop()


# Normalize data types.
df["production_date"] = pd.to_datetime(df["production_date"]).dt.date
df["production_timestamp"] = pd.to_datetime(df["production_timestamp"])
df["measured_value"] = pd.to_numeric(df["measured_value"])
df["is_oos"] = df["is_oos"].fillna(False).astype(bool)

# Sidebar filters.
st.sidebar.header("Filters")

available_booths = sorted(df["booth_name"].dropna().unique().tolist())
selected_booths = st.sidebar.multiselect(
    "Paint booth",
    options=available_booths,
    default=available_booths,
)

available_shifts = sorted(df["shift_name"].dropna().unique().tolist())
selected_shifts = st.sidebar.multiselect(
    "Shift",
    options=available_shifts,
    default=available_shifts,
)

available_points = sorted(df["point_code"].dropna().unique().tolist())
selected_points = st.sidebar.multiselect(
    "Measurement point",
    options=available_points,
    default=available_points,
)

min_date = min(df["production_date"])
max_date = max(df["production_date"])

selected_dates = st.sidebar.date_input(
    "Production date range",
    value=(min_date, max_date),
    min_value=min_date,
    max_value=max_date,
)

if isinstance(selected_dates, (tuple, list)) and len(selected_dates) == 2:
    start_date, end_date = selected_dates
elif isinstance(selected_dates, (tuple, list)) and len(selected_dates) == 1:
    start_date = end_date = selected_dates[0]
else:
    start_date = end_date = selected_dates

filtered = df[
    df["booth_name"].isin(selected_booths)
    & df["shift_name"].isin(selected_shifts)
    & df["point_code"].isin(selected_points)
    & df["production_date"].between(start_date, end_date)
].copy()

st.sidebar.caption(f"{len(filtered):,} measurements selected")

if filtered.empty:
    st.warning("No measurements match the selected filters.")
    st.stop()


# KPI overview.
total_measurements = len(filtered)
total_cabins = filtered["cabin_id"].nunique()
oos_count = int(filtered["is_oos"].sum())
oos_rate = oos_count / total_measurements * 100
average_value = filtered["measured_value"].mean()

col1, col2, col3, col4 = st.columns(4)

col1.metric("Produced cabins", f"{total_cabins:,}")
col2.metric("Measurements", f"{total_measurements:,}")
col3.metric("Out-of-spec measurements", f"{oos_count:,}")
col4.metric("Out-of-spec rate", f"{oos_rate:.2f}%")

st.divider()

# Quality trend.
st.subheader("Quality trend")

daily = (
    filtered.groupby("production_date", as_index=False)
    .agg(
        mean_value=("measured_value", "mean"),
        oos_count=("is_oos", "sum"),
        measurement_count=("measurement_id", "count"),
    )
)

daily["oos_rate_pct"] = (
    daily["oos_count"] / daily["measurement_count"] * 100
)

left, right = st.columns(2)

with left:
    fig_mean = px.line(
        daily,
        x="production_date",
        y="mean_value",
        markers=True,
        title="Daily mean measured value",
        labels={
            "production_date": "Production date",
            "mean_value": "Mean measured value",
        },
    )
    st.plotly_chart(fig_mean, width="stretch")

with right:
    fig_oos = px.bar(
        daily,
        x="production_date",
        y="oos_rate_pct",
        title="Daily out-of-spec rate",
        labels={
            "production_date": "Production date",
            "oos_rate_pct": "Out-of-spec (%)",
        },
    )
    st.plotly_chart(fig_oos, width="stretch")

# Booth comparison.
st.subheader("Paint booth comparison")

booth_summary = (
    filtered.groupby("booth_name", as_index=False)
    .agg(
        cabins=("cabin_id", "nunique"),
        measurements=("measurement_id", "count"),
        oos_count=("is_oos", "sum"),
        mean_value=("measured_value", "mean"),
    )
)

booth_summary["oos_rate_pct"] = (
    booth_summary["oos_count"] / booth_summary["measurements"] * 100
)

st.dataframe(
    booth_summary.round(3),
    width="stretch",
    hide_index=True,
)

# Detailed measurements.
DETAIL_ROW_LIMIT = 1000

with st.expander("View filtered measurements"):
    st.caption(
        f"Showing the latest {min(DETAIL_ROW_LIMIT, len(filtered)):,} "
        f"of {len(filtered):,} filtered measurements. "
        "KPIs and charts use all filtered records."
    )
    st.dataframe(
        filtered.sort_values(
            "production_timestamp", ascending=False
        ).head(DETAIL_ROW_LIMIT),
        width="stretch",
        hide_index=True,
    )

st.caption(
    "Data source: PostgreSQL view v_measurement_enriched. "
    "SPC rule calculations remain in the existing SQL layer."
)
