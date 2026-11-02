
import os

import pandas as pd
import plotly.express as px
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
