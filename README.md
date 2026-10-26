# SPC Quality Monitoring

Manufacturing-focused **Statistical Process Control (SPC)** project built around a synthetic powder-coating process for tractor cabins.

Production measurements are generated in Python, loaded into PostgreSQL, checked against I-MR SPC rules in SQL, and analysed in Python for process capability and drift / shift-to-shift variation.

> **Synthetic data.** No real production data is used. The dataset is generated with a fixed random seed, and several special-cause periods (drift, shift, increased variation, specification violations, outliers) are **deliberately injected** with a known answer key. Results demonstrate a reproducible method, not the performance of a real paintshop. See [docs/data_generation.md](docs/data_generation.md).

## 🎯 Objective

The practical question is:

> **Is the process stable and capable of meeting specification requirements?**

For the analysed stream the answer is: **stability is not demonstrated** (SPC signals are present), so the capability indices below are **exploratory Phase I** values and not a capability certification.

## 🔧 What Is Implemented

- Reproducible synthetic data generator with automated tests (`src/data_generation/`)
- PostgreSQL schema, clean CSV load, analytical views and SQL validation scripts (`sql/`)
- dbt staging model and measurement, quality, and SPC marts (`models/`; scaffolded, pending first authenticated `dbt build`)
- I-MR SPC rule detection and signal summaries in SQL
- Process capability (Cp / Cpk / Pp / Ppk) in Python with a hand-checked fixture
- Drift and shift-to-shift variation analysis on actual shift instances
- 44 Python tests plus SQL regression fixtures

Not implemented: a dashboard or Streamlit app, and root-cause analysis. The `fact_process_event` ground truth is not used by the analysis notebooks or dbt models.

## 🏭 Manufacturing Context

The generator models a **tractor-cabin powder-coating paintshop**:

- Two booths with four robots each
- 18 coating-thickness measurement points per cabin
- Three shifts per day (one overnight), six production days per week, about six months
- About 167,400 measurements overall

The analysis focuses on one stream: **BOOTH_01 / measurement point A-L1 / Coating Thickness**, LSL 70 µm, target 75 µm, USL 80 µm.

## 📊 Analytics Workflow

```text
Synthetic data generator (Python, fixed seed)
            │  CSV files in data/raw/
            ▼
   PostgreSQL (schema.sql, load.sql, views.sql)
            │
            ▼
 dbt: staging + measurement / quality / SPC marts
            │
            ▼
   SQL: I-MR SPC rules, signal summary, validation
            │
            ▼
   Python: capability  ──►  drift / shift-to-shift variation
            │
            ▼
   Notebooks and tests
```

## 📈 Results (BOOTH_01 / A-L1, synthetic)

From the saved output of `notebooks/drift_shift_variation_analysis.ipynb`:

| Item | Result |
|---|---|
| Measurements | 4,650 |
| Actual shift instances | 465 (10 measurements each; overnight shifts kept whole) |
| Out-of-specification measurements | 56 |
| SPC-signal measurements | 174 |
| Cp / Cpk (within sigma 1.384 µm) | 1.204 / 1.139 |
| Pp / Ppk (overall sigma 1.545 µm) | 1.078 / 1.020 |
| Within-shift / between-shift sum of squares | 79.4% / 20.6% |
| Trend slope of shift-instance means | −0.000424 µm/day, 95% CI [−0.001648, 0.000800] |

**Conclusion:** there is insufficient evidence to describe sustained drift under the predefined framework. The slope interval includes zero, and the other predeclared conditions are not all met. This is not proof that no drift exists. The analysis is observational and does not establish causes.

Cp and Cpk exceed Pp and Ppk, which is compatible with overall spread being larger than the short-term estimate. About a fifth of the total variation lies between shifts. Signals and out-of-specification values are concentrated in some months (for example April), as the notebook's monthly table shows.

## 📐 Key Concepts

### SPC signals versus out-of-specification

- An **SPC signal** is a pattern flagged by an I-MR rule. It indicates the process may have changed and is an **investigation prompt**, not proof of a special cause.
- An **out-of-specification (OOS)** measurement is strictly below LSL or strictly above USL. A value equal to a limit is in specification.
- The two sets are different: a measurement can signal while within specification. Control limits describe process behaviour; specification limits define acceptance. All signal-bearing observations are retained in every analysis.

### Cp / Cpk versus Pp / Ppk

- **Cp / Cpk** use a short-term **within sigma**, estimated from shift-bounded moving ranges (mean moving range / 1.128). Cp ignores centering; Cpk uses the distance to the nearer limit.
- **Pp / Ppk** use the **overall sample standard deviation**, which also contains between-shift and time-related variation.
- Pooled within-shift SD (1.451 µm) is a different quantity from the I-MR within sigma (1.384 µm).
- Because SPC signals are present, all indices are exploratory Phase I values. Classical indices also assume approximate normality and a stable process.

More detail: [docs/methodology_and_data_model.md](docs/methodology_and_data_model.md).

## ⚠️ Limitations

- Synthetic data with injected special causes; no real-process conclusions.
- Confidence intervals are normal-approximation and not adjusted for autocorrelation.
- Shift type may be confounded with time or unmeasured conditions; multiple descriptive comparisons can show chance patterns.
- Phase I exploratory analysis; no causal claims.

## 🛠️ Technology Stack

- Python (pandas, NumPy, Matplotlib)
- SQL / PostgreSQL (`psql` client)
- Jupyter Notebook
- pytest
- Git / GitHub

## 🚀 Start Here

1. This README, then `docs/methodology_and_data_model.md`.
2. `notebooks/process_capability_analysis.ipynb` for SPC stability versus capability.
3. `notebooks/drift_shift_variation_analysis.ipynb` for the drift and variation decomposition.
4. `sql/` (schema, load, views, `analysis/`), `src/` and `tests/` for the implementation.

## ⚙️ Setup and Run

Prerequisites: Python 3 (tested with 3.13), PostgreSQL with the `psql` client on `PATH`, and a database user that can create tables and views.

```bash
python -m venv .venv
# activate the environment, then:
pip install -r requirements.txt

# 1. Generate the CSV files (data/raw/*.csv is git-ignored)
python -m src.data_generation.generate_data

# 2. Create the database and schema
createdb spc_quality_monitoring
psql -X -v ON_ERROR_STOP=1 -d spc_quality_monitoring -f sql/schema.sql

# 3. Load the CSVs (psql must run inside data/raw; do not run sql/seed.sql in this database)
cd data/raw
psql -X -v ON_ERROR_STOP=1 -d spc_quality_monitoring -f ../../sql/load.sql
cd ../..

# 4. Create the analytical views
psql -X -v ON_ERROR_STOP=1 -d spc_quality_monitoring -f sql/views.sql

# 5. Tests
python -m pytest tests/ -q

# 6. dbt (create ~/.dbt/profiles.yml from profiles.yml.example; keep credentials outside Git)
dbt debug
dbt build
```

Optional SQL checks: run `sql/analysis/test_*.sql` (regression fixtures) and `sql/analysis/validate_*.sql` (live reconciliation) with `psql` in the same way.

**Authentication.** The notebooks call `psql` with `-w`, so they never prompt for a password and never store one. Supply credentials outside the notebook through a `pgpass` file or `PGPASSWORD`. The notebooks default to database `spc_quality_monitoring` and user `postgres` and honour `PGDATABASE`, `PGUSER`, `PGHOST` and `PGPORT`; on Windows they also point `PGPASSFILE` at `%APPDATA%\postgresql\pgpass.conf` if it is unset. If the database cannot be reached, the notebooks print `LIVE ANALYSIS NOT EXECUTED` and skip the data-dependent cells.

The notebooks assert the exact counts produced by the default generator seed (for example 4,650 measurements), so regenerate with the default configuration.

## 📁 Project Structure

```text
SPC-quality-monitoring/
├── data/raw/        generated CSVs (git-ignored)
├── docs/            data generation and methodology / data model
├── notebooks/       capability and drift / shift analyses
├── models/           dbt staging and mart models
├── sql/             schema, load, views, analysis and validation scripts
├── src/             data generator, capability and drift / shift code
├── tests/           pytest suite
├── requirements.txt
└── README.md
```

## 🔍 Why This Project Matters

This project demonstrates the combination of:

**Manufacturing domain knowledge + statistical quality methods + data analytics**

Rather than treating SPC as a purely theoretical topic, the project applies it to a manufacturing scenario and connects the results to practical quality monitoring.

## 🚧 Project Status

Completed: synthetic dataset, PostgreSQL schema and load, SQL analytics and validation, I-MR rule detection, capability analysis, drift / shift-to-shift analysis, automated tests.

## 🔮 Possible Next Steps

- Extend capability reporting beyond BOOTH_01 / A-L1 to other booths and measurement points
- Add control-chart figures to the documentation
- Compare SPC signals with the injected event ground truth as a separate, clearly labelled evaluation
- Add an interactive dashboard (not started)

## 👤 Author

**Béla Páger**

Materials Engineer · Data Analyst · Manufacturing & Quality Analytics

GitHub: https://github.com/Theofil87
