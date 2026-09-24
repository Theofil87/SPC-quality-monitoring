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
modified by the generator.

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
a way that preserves the given ids).

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
