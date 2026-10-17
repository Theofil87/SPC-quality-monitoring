# Methodology and Data Model

All data are synthetic (see [data_generation.md](data_generation.md)). The results demonstrate a reproducible
method, not the performance of a real paintshop. This page summarises how the pieces fit together and links to
the code that defines them; it does not repeat that code.

## Data model

The PostgreSQL schema is in [`sql/schema.sql`](../sql/schema.sql); generated CSVs are loaded with
[`sql/load.sql`](../sql/load.sql).

| Layer | Objects |
|---|---|
| Dimensions | `dim_booth`, `dim_track_axis`, `dim_robot`, `dim_shift`, `dim_batch`, `dim_cabin`, `dim_measurement_point`, `dim_specification` |
| Facts | `fact_quality_measurement` (one coating-thickness value per cabin and measurement point), `bridge_measurement_robot` (contributing robots), `fact_process_event` (injected special-cause ground truth) |
| Views | [`sql/views.sql`](../sql/views.sql): `v_measurement_enriched`, `v_spc_rule_results_booth01_a_l1`, `v_capability_measurements_booth01_a_l1`, `v_drift_shift_measurements_booth01_a_l1`, plus volume and quality summary views |

`fact_process_event` is the answer key for the generator. The SPC, capability and drift analyses do not read it.

## Analysed stream

BOOTH_01, measurement point A-L1, Coating Thickness (µm): LSL 70, target 75, USL 80. The drift input view
exposes 4,650 measurements, each tagged with its actual `shift_instance` (a concrete scheduled shift; the
overnight 22:00 shift is anchored to its start time, so it is not split at midnight).

## SPC signals

Rules are implemented in [`sql/analysis/spc_rules.sql`](../sql/analysis/spc_rules.sql) on an individuals /
moving-range (I-MR) basis, with moving ranges computed inside a shift instance only. Signal summaries are in
[`sql/analysis/spc_signal_summary.sql`](../sql/analysis/spc_signal_summary.sql). A signal is an investigation
prompt. It is not an out-of-specification measurement and it is not proof of a special cause.

## Out-of-specification

A value is out of specification only if it is strictly below LSL or strictly above USL. Equality with a limit is
in specification. See [`sql/analysis/compliance.sql`](../sql/analysis/compliance.sql) and
[`src/capability.py`](../src/capability.py).

## Capability

[`src/capability.py`](../src/capability.py) (`calculate_capability`) computes:

- within sigma = mean moving range / 1.128, using shift-bounded moving ranges (used for Cp, Cpk);
- overall sigma = sample standard deviation, `ddof=1` (used for Pp, Ppk).

Because SPC signals are present, the indices are exploratory Phase I values, not a capability certification.
Details and a hand-checked fixture are in
[`notebooks/process_capability_analysis.ipynb`](../notebooks/process_capability_analysis.ipynb).

## Drift and shift-to-shift variation

[`src/drift_shift_analysis.py`](../src/drift_shift_analysis.py) and
[`notebooks/drift_shift_variation_analysis.ipynb`](../notebooks/drift_shift_variation_analysis.ipynb):

- Total SS = within-shift SS + between-shift SS, using actual shift instances as groups.
- Pooled within-shift SD is a different quantity from the I-MR within sigma.
- Trend: OLS slope of shift-instance means against time, with a normal-approximation 95% confidence interval
  (not adjusted for autocorrelation), plus rolling means, a first-half/second-half comparison and a
  leave-one-shift-out check.
- Sustained drift is described as supported only if every predeclared condition holds (CI excludes zero,
  practically meaningful fitted change, compatible half comparison, compatible 7/14/21 rolling patterns, stable
  under leave-one-out). Even then the result is observational, not causal.

## Validation

- Python tests: `python -m pytest tests/ -q`.
- SQL regression fixtures: [`sql/analysis/test_spc_rules.sql`](../sql/analysis/test_spc_rules.sql) and
  [`test_spc_signal_summary.sql`](../sql/analysis/test_spc_signal_summary.sql).
- Live reconciliation against the loaded database: the `sql/analysis/validate_*.sql` scripts.
