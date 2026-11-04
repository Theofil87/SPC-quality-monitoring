
import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError

from src.spc_monitoring import summarize_mr_violations


st.set_page_config(
    page_title="SPC & Quality Monitoring",
    page_icon="📊",
    layout="wide",
)

st.title("SPC & Quality Monitoring")
st.caption("Manufacturing quality analytics | Powder coating process")


@st.cache_data(ttl=3600)
def load_spc_results():
    """Read the existing BOOTH_01 / A-L1 SPC results view."""
    query = text("""
        SELECT
            measurement_timestamp,
            measurement_id,
            booth,
            measurement_point,
            shift_id,
            shift_name,
            shift_instance,
            measured_value,
            moving_range,
            center_line,
            sigma,
            lcl,
            ucl,
            rule_1,
            rule_2,
            rule_3,
            rule_4,
            spc_signal
        FROM v_spc_rule_results_booth01_a_l1
        ORDER BY measurement_timestamp, measurement_id
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
        st.warning("The BOOTH_01 / A-L1 SPC results view contains no records.")
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
            mode="lines",
            name="Measured value",
            line={"color": "#2b6cb0", "width": 1.5},
        )
    )
    for column, label, color, dash in (
        ("center_line", "Center line", "#2f855a", "solid"),
        ("ucl", "UCL", "#c53030", "dash"),
        ("lcl", "LCL", "#c53030", "dash"),
    ):
        i_chart.add_trace(
            go.Scatter(
                x=spc_df["measurement_timestamp"],
                y=spc_df[column],
                mode="lines",
                name=label,
                line={"color": color, "dash": dash, "width": 1.5},
            )
        )

    signal_rows = spc_df.loc[spc_df["spc_signal"]]
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
                hovertemplate=(
                    "%{x}<br>Measured value: %{y}<br>"
                    "Measurement ID: %{customdata[0]}<br>"
                    f"Triggered: {combination}<extra></extra>"
                ),
            )
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
    mr_summary = summarize_mr_violations(spc_df["moving_range"])
    spc_df["mr_violation"] = mr_summary.violations
    if mr_summary.valid_count == 0:
        st.info("No valid moving-range values are available to calculate MR limits.")

    mr_chart = go.Figure()
    mr_chart.add_trace(
        go.Scatter(
            x=spc_df["measurement_timestamp"],
            y=mr_summary.values,
            mode="lines",
            name="Moving range",
            line={"color": "#2b6cb0", "width": 1.5},
            connectgaps=False,
        )
    )
    violation_rows = spc_df.loc[spc_df["mr_violation"]]
    mr_chart.add_trace(
        go.Scatter(
            x=violation_rows["measurement_timestamp"],
            y=mr_summary.values.loc[violation_rows.index],
            mode="markers",
            name="MR violations (> UCL)",
            marker={
                "color": "#d62728",
                "symbol": "triangle-up",
                "size": 10,
                "line": {"width": 1, "color": "white"},
            },
            customdata=violation_rows[["measurement_id"]],
            hovertemplate=(
                "%{x}<br>Moving range: %{y}<br>"
                "Measurement ID: %{customdata[0]}<br>"
                "MR violation: above UCL<extra></extra>"
            ),
        )
    )
    if mr_summary.center_line is not None:
        for label, value, color, dash in (
            ("MR center line (average)", mr_summary.center_line, "#2f855a", "solid"),
            (
                "MR UCL (D4 = 3.267)",
                mr_summary.upper_control_limit,
                "#c53030",
                "dash",
            ),
            (
                "MR LCL (D3 = 0)",
                mr_summary.lower_control_limit,
                "#c53030",
                "dash",
            ),
        ):
            mr_chart.add_hline(
                y=value,
                line_color=color,
                line_dash=dash,
                annotation_text=label,
                annotation_position="top left",
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
        alt="Moving-range chart with the average moving range and calculated MR control limits.",
    )
    st.caption(
        "An MR violation is a moving range above its UCL, indicating unusually "
        "large change between consecutive observations. These are separate "
        "from the I-chart SPC rule flags."
    )
    mr_kpis = st.columns(3)
    mr_kpis[0].metric("MR violations", f"{mr_summary.violation_count:,}")
    mr_kpis[1].metric(
        "Valid MR observations above UCL",
        (
            f"{mr_summary.violation_rate_pct:.2f}%"
            if mr_summary.violation_rate_pct is not None
            else "N/A"
        ),
    )
    mr_kpis[2].metric(
        "Maximum moving range",
        f"{mr_summary.maximum:.3f}" if mr_summary.maximum is not None else "N/A",
    )

    st.divider()
    st.subheader("SPC rule summary")
    rule_counts = {
        rule_labels[column]: int(spc_df[column].sum()) for column in rule_columns
    }
    signal_count = int(spc_df["spc_signal"].sum())
    signal_rate = signal_count / len(spc_df) * 100
    summary_columns = st.columns(6)
    for column, (label, count) in zip(
        summary_columns,
        [
            *rule_counts.items(),
            ("Observations with signal", signal_count),
            ("Overall signal rate", f"{signal_rate:.2f}%"),
        ],
    ):
        column.metric(label, f"{count:,}" if isinstance(count, int) else count)

    st.divider()
    st.subheader("Signal details")
    if signal_rows.empty:
        st.info("No observations in this view have an SPC signal.")
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

    st.caption("Data source: PostgreSQL view v_spc_rule_results_booth01_a_l1.")
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
