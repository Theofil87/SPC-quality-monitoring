# Synthetic Data Generation

## Why the dataset is synthetic

This project is a portfolio demonstration of SPC (Statistical Process
Control) and quality monitoring for a tractor-cabin powder-coating
process. No real manufacturing data is available or used. Instead, a
fully synthetic, reproducible dataset is generated in Python
(`src/data_generation/`) that:

- structurally matches the PostgreSQL schema in [`sql/schema.sql`](../sql/schema.sql)
  and the reference rows already inserted by [`sql/seed.sql`](../sql/seed.sql),
- behaves like a realistic, "mostly stable" manufacturing process, and
- contains several deliberately injected special-cause conditions with
  known ground truth, so downstream SPC analysis can be scored against
  a known answer key.

The schema and seed data are treated as fixed inputs and are **not**
modified by the generator. For the canonical clean-load workflow, the
generated CSVs are the dataset source of truth. `sql/seed.sql` is a
separate reference-data workflow and must not be run into the same clean
database as the CSV import.

## Production assumptions

Some details of the process are not fully specified by the task and
required an explicit (documented, configurable) assumption. All of
these live in [`src/data_generation/config.py`](../src/data_generation/config.py),
marked `ASSUMPTION`:

- **Non-production day**: "6 production days per week" is implemented
  as every day except Sunday (`NON_PRODUCTION_WEEKDAY = 6`).
- **Batch-to-booth routing**: a batch of 5 cabins moves through one
  booth as a group. Within a shift, the 4 batches alternate 2/2
  between `BOOTH_01` and `BOOTH_02` (`BATCH_BOOTH_PATTERN`).
- **Side-to-track/robot mapping**: the real robot-to-measurement-point
  mapping is unknown and is intentionally NOT modeled. All 4 robots in
  a booth operate on a cabin simultaneously, and a given measurement
  point may plausibly be influenced by just one robot or by several.
  For the synthetic dataset, each measurement's contributing robot
  **count is variable (1 to 4)**, drawn from
  `ROBOT_CONTRIBUTION_COUNT_DISTRIBUTION` (a configurable probability
  distribution, default weights `{1: 0.15, 2: 0.45, 3: 0.30, 4: 0.10}`),
  and that many unique robots are then drawn at random from the 4
  robots belonging to the cabin's booth — they may come from the same
  or different track axes, and the measurement point's side/component
  never determines the count or the choice of robots. This is a
  synthetic contribution assignment for generating plausible data, not
  a claim about the true physical wiring between robots and
  measurement points, which remains unknown.
- **Batch/shift timing**: each shift is split into 4 equal-length
  batch windows; the 5 cabins in a batch are spread evenly (with a
  small random jitter) across that window. `SHIFT_03` (22:00–06:00)
  correctly crosses midnight.

With 6 months, 6 production days/week, 3 shifts/day, 4 batches/shift
and 5 cabins/batch, the generator produces roughly (not exactly, since
"approximately 9,360" allows for calendar variation) 9,300 cabins and
167,400 measurements — within a few percent of the target figures in
the specification.

## Measurement structure

Every cabin receives exactly 18 coating-thickness measurements, one
per `dim_measurement_point` row (A/B pillar left+right, upper
connecting element, A-B connecting elements) — identical set and order
as `sql/seed.sql`.

## Specification limits

Single characteristic, `Coating Thickness`, unit `um`:

- LSL = 70
- Target = 75
- USL = 80

## Random seed

`RANDOM_SEED = 42` (in `config.py`), used to build a single
`numpy.random.Generator` (`np.random.default_rng(42)`) that drives all
random choices (jitter, structural effects, noise, outlier picks).
Running the generator twice with the same code and config produces
byte-for-byte identical CSVs (see `tests/test_generate_data.py::test_same_seed_produces_reproducible_results`).

## Process model

For a stable measurement, the value is:

```
measured_value = TARGET
                + measurement_point_effect   (~ N(0, 0.3), fixed per point)
                + booth_effect               (small fixed bias per booth)
                + robot_effect                (avg. of that measurement's randomly-selected contributing robots' fixed bias, ~ N(0, 0.25))
                + noise                       (~ N(0, 1.2))
```

All structural effects are small relative to the 70–80 um
specification window, so the *stable* process still looks in-control
most of the time, while giving SPC charts realistic point-to-point and
booth-to-booth structure instead of every measurement being i.i.d.
identical.

## Special-cause event simulation

`config.SPECIAL_CAUSE_EVENTS` defines a handful of hand-placed,
non-overlapping windows spread across the 6-month period (different
months, both booths), covering all 5 special-cause types required by
the task:

| Event type | How it's simulated |
|---|---|
| `PROCESS_DRIFT` | Mean ramps linearly upward over the window (`drift_total_um` reached gradually) |
| `PROCESS_SHIFT` | Mean jumps by a constant offset for the whole window |
| `INCREASED_VARIATION` | Same mean, noise std is replaced with a larger `inflated_std_um` |
| `SPECIFICATION_VIOLATION` | Mean is pushed far enough to produce values below LSL or above USL |
| `OUTLIER` | A handful of individual (cabin, measurement point) pairs get one extreme, isolated offset — not a shift of the surrounding batch |

`STABLE_PROCESS` is *not* a row in `fact_process_event` — it's simply
the absence of any special-cause event, and it is not part of the
`chk_event_type` CHECK constraint in `sql/schema.sql`.

**Ground truth vs. detection**: `fact_process_event` records exactly
which batches/booths were affected by which simulated condition. This
is ground truth for *validating* an SPC detection algorithm — the SPC
analysis itself must only ever look at `fact_quality_measurement` and
must not read `event_type` as an input. The intended workflow is:

```
measurement data -> SPC detection -> detected anomaly -> compare against fact_process_event -> evaluate detection performance
```

## Output files

CSV files are written to `data/raw/`, one per schema table:

`dim_booth.csv`, `dim_track_axis.csv`, `dim_robot.csv`, `dim_shift.csv`,
`dim_batch.csv`, `dim_cabin.csv`, `dim_measurement_point.csv`,
`dim_specification.csv`, `fact_quality_measurement.csv`,
`bridge_measurement_robot.csv`, `fact_process_event.csv`.

Column names match their corresponding table in `sql/schema.sql`.
Primary-key columns (e.g. `booth_id`, `cabin_id`, `measurement_id`) are
included explicitly in the CSVs so foreign keys across files stay
consistent; when loading into Postgres against the `GENERATED ALWAYS`
identity columns, use `INSERT ... OVERRIDING SYSTEM VALUE` (or load in
a way that preserves the given ids). The canonical importer is
[`sql/load.sql`](../sql/load.sql); it imports all 11 CSV files and does
not run `seed.sql`.

## PostgreSQL Phase 4 workflow

The reproducible clean-load order is:

1. Create an empty database.
2. Apply `sql/schema.sql`.
3. Import the generated CSV files with `sql/load.sql`.
4. Run `sql/test.sql` and inspect the reconciliation/invariant results.
5. Create reusable analytics views with `sql/views.sql`.
6. Run the ad-hoc analyses in `sql/analysis/`.

Do not apply `sql/seed.sql` as part of this workflow. It is retained as a
separate reference/seed workflow. `sql/load.sql` refuses to load when
target tables already contain rows, protecting against mixing seed rows
with CSV data and against accidental duplicate imports.

The importer uses `psql` client-side `\copy`, so PostgreSQL does not
need server-side access to the CSV directory. Its CSV paths are relative
to the `psql` working directory, not embedded as machine-specific paths
in SQL. From the repository root in PowerShell, set the connection
environment (for example `PGDATABASE`) and run:

```powershell
psql -X -v ON_ERROR_STOP=1 -d $env:PGDATABASE -f sql/schema.sql
Push-Location data/raw
psql -X -v ON_ERROR_STOP=1 -d $env:PGDATABASE -f ../../sql/load.sql
Pop-Location
psql -X -v ON_ERROR_STOP=1 -d $env:PGDATABASE -f sql/views.sql
```

The connection can be configured with normal PostgreSQL environment
variables or a `psql` service file. Choose an empty database; do not use
the existing seeded/reference database for the canonical CSV import.
The loader stages every CSV, inserts in foreign-key order while
preserving identity IDs, synchronizes identity sequences, runs
`sql/test.sql` against both staging and loaded tables, and commits only
if the checks pass.

## Analytics grains and quality semantics

[`sql/views.sql`](../sql/views.sql) defines `v_measurement_enriched` at
exactly one row per `fact_quality_measurement`, without robot or event
joins. Aggregate views cover production volume, cabin, batch, booth,
shift, measurement point, robot attribution, and retrospective event
evaluation. Ad-hoc analyses are in `sql/analysis/`.

The views distinguish specification compliance from process behavior.
An OOS measurement is strictly below LSL or above USL; the limits
themselves are in specification. OOS rates are measurement-level unless
the query explicitly reports cabin-level OOS. Means and sample standard
deviations are descriptive summaries, not SPC control limits or
detection rules.

Each quality fact row represents one measurement. The robot bridge
represents 1-4 synthetic contributing-robot links per measurement and
may link robots across different track axes within the cabin's booth.
Robot views use distinct linked-measurement and linked-cabin counts and
are attribution summaries only. They do not establish causal robot
performance or physical robot-to-measurement-point mapping. Never join
the bridge into a measurement-level aggregate without first restoring
one row per measurement.

`fact_process_event` is synthetic special-cause ground truth. It may be
used for retrospective validation and event-period comparisons, but
must not be an input to future SPC detection logic. Event-evaluation
queries operate at event/batch grain so event rows do not multiply
measurement counts.

The schema's temporal columns are timezone-naive `timestamp` values.
Shift assignment must come from `dim_batch.shift_id`; do not infer the
overnight `SHIFT_03` from a time-of-day comparison alone. Additional
indexes are not presumed necessary; use `EXPLAIN (ANALYZE, BUFFERS)` on
representative queries before adding any.

## SPC rules (initial Phase I analysis)

[`sql/analysis/spc_rules.sql`](../sql/analysis/spc_rules.sql) applies the
first individual/moving-range (I-MR) analysis to `BOOTH_01` and `A-L1`
using `v_measurement_enriched` as its measurement source. Its process
stream is identified by booth, measurement point, specification, and
actual shift instance. Observations are deterministically ordered by
`measurement_timestamp, measurement_id`.

The batch start timestamp is not itself the shift boundary: each actual
shift contains multiple batches, and `shift_id` recurs on later production
days. The analysis combines `shift_id` with the scheduled shift start
reconstructed from `dim_shift.start_time` / `end_time` and `batch_start`.
For an overnight shift, a post-midnight batch belongs to the shift that
started on the prior date. Moving ranges and every sequential rule
partition by this actual shift-instance key. The first measurement in
each instance has a NULL moving range; subsequent ranges are the absolute
difference from the previous ordered observation in that same instance.

The center line is the mean of the selected observations. The I-chart
sigma estimate is average within-instance moving range divided by 1.128;
limits are `CL +/- 3 * sigma_hat`. The moving-range average pools adjacent
within-shift pairs across the selected history. These limits are SPC
control limits, not specification limits: LSL and USL are not used to
estimate them or generate signals.

The four rules use strict beyond-zone comparisons:

- Rule 1 signals an observation strictly beyond either 3-sigma control limit.
- Rule 2 signals when at least 2 of 3 consecutive observations are strictly
  beyond the same-side 2-sigma zone.
- Rule 3 signals when at least 4 of 5 consecutive observations are strictly
  beyond the same-side 1-sigma zone.
- Rule 4 signals from the eighth consecutive observation on one side of the
  center line. An observation exactly on the center line resets the run.

The output includes one row per measurement, individual rule flags, and an
overall `spc_signal` flag that is true when any rule signals at that
measurement. Rules 2-4 signal on the observation that completes the
threshold and on subsequent observations while the qualifying window/run
continues. `sql/analysis/test_spc_rules.sql` exercises threshold, side,
boundary, reset, moving-range, and deterministic-order behavior with
inline SQL fixtures.

This is an exploratory Phase I baseline estimated from the same full
selected history being assessed. Its center line and sigma can therefore
be influenced by special causes; a reviewed stable reference period and
fixed Phase II limits would be needed for production monitoring. The
detector does not read `fact_process_event`; that synthetic ground truth
is reserved for retrospective validation after signals are produced.

## SPC signal summary and diagnostics

[`sql/views.sql`](../sql/views.sql) exposes the unchanged initial rule
results as `v_spc_rule_results_booth01_a_l1`. It retains one row per
eligible `measurement_id`; [`sql/analysis/spc_rules.sql`](../sql/analysis/spc_rules.sql)
is the ordered detail query over that view. The summary in
[`sql/analysis/spc_signal_summary.sql`](../sql/analysis/spc_signal_summary.sql)
joins those rows to `v_measurement_enriched` by `measurement_id` for OOS
status and production timestamp. No robot bridge or event table is joined.

The summary reports overall stream totals, production-month totals, and
actual shift-instance totals. A month is derived from
`production_timestamp`. Shift results group by the existing reconstructed
`shift_instance` together with `shift_id` and `shift_name`; `shift_id`
alone repeats across production days and is not a concrete shift key.
Rule-specific results are long-form for Rules 1-4 at overall, month, and
shift-instance scope.

All counts use distinct `measurement_id`; rates use the total eligible
measurements in the corresponding scope as their denominator. Overall
signal status is the OR of Rules 1-4, so a measurement triggering multiple
rules counts once in the overall signal count. Individual rule counts
are allowed to overlap and must not be added to estimate the total signal
count. OOS measurements and rates use `is_oos` independently of SPC rule
flags; an OOS result is not required for a signal, nor does an SPC signal
imply an OOS result.

An SPC signal means that one or more configured rules flagged an
observation under the exploratory Phase I limits. It is a diagnostic
prompt for investigation, not proof of a special cause or evidence of a
specific root cause. `fact_process_event` remains reserved for subsequent
retrospective validation and is not an input to detection or aggregation.
[`sql/analysis/test_spc_signal_summary.sql`](../sql/analysis/test_spc_signal_summary.sql)
checks deterministic aggregation fixtures, and
[`sql/analysis/validate_spc_signal_summary.sql`](../sql/analysis/validate_spc_signal_summary.sql)
checks measurement grain and reconciliation on the loaded data.

## Phase 4 owner review

Before relying on or extending the SQL, make sure you can explain:

- Why staging plus `OVERRIDING SYSTEM VALUE` preserves generated IDs,
  why identity sequences need synchronization, and why the seed and CSV
  workflows must remain separate.
- What one row means at measurement, cabin, batch, and bridge grains;
  how `COUNT(DISTINCT ...)` prevents robot-link fanout from inflating
  counts; and which denominator each reported rate uses.
- Why sample standard deviation, mean, min/max, and OOS rate answer
  different questions, and why none of these summaries alone is an SPC
  control rule.
- Why specification compliance differs from process variation, and
  why event ground truth is reserved for retrospective evaluation.
- Why robot-linked results are attribution summaries only, and why
  point-level robot ownership cannot be inferred from this dataset.
- How `EXPLAIN (ANALYZE, BUFFERS)` demonstrates whether an additional
  index is worth its storage and load cost.

## How to run the generator

From the repository root:

```powershell
python -m src.data_generation.generate_data
```

This regenerates every CSV in `data/raw/` and prints the resulting
cabin/measurement counts.

## How reproducibility is ensured

- A single fixed seed (`42`) seeds one `numpy.random.Generator` per
  run; no other source of randomness (e.g. `random`, unseeded numpy
  calls) is used.
- All dates, quantities, and event windows are deterministic
  configuration values, not randomly sampled.
- `tests/test_generate_data.py` calls the generator twice in the same
  process and asserts the resulting measurement values and cabin table
  are identical.
