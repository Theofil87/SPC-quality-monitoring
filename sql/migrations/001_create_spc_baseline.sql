-- ============================================================
-- SPC & Quality Monitoring
-- Migration 001: versioned SPC baseline records
--
-- Review only until approved for deployment. Not idempotent by design:
-- it fails if spc_baseline already exists instead of altering it.
-- Contains no sample data.
-- ============================================================

BEGIN;

-- ------------------------------------------------------------
-- SPC BASELINES
--
-- One row is one versioned set of fixed control limits for a
-- booth / measurement point / specification scope. Limits are stored
-- as frozen values, so later measurements do not change them.
-- ------------------------------------------------------------

CREATE TABLE spc_baseline (
    baseline_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- Scope. Types match dim_booth, dim_measurement_point and
    -- dim_specification (all INTEGER identity keys).
    booth_id INTEGER NOT NULL,
    measurement_point_id INTEGER NOT NULL,
    specification_id INTEGER NOT NULL,

    -- Version number within the scope, starting at 1.
    version INTEGER NOT NULL,

    -- Measurement window used to fit the limits; window_end is exclusive.
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,

    status VARCHAR(20) NOT NULL DEFAULT 'DRAFT',

    -- Period in which the limits are used for monitoring.
    -- effective_from may be NULL for DRAFT; effective_to NULL means open-ended.
    effective_from TIMESTAMPTZ,
    effective_to TIMESTAMPTZ,

    -- Approval metadata; optional for DRAFT.
    approved_by TEXT,
    approved_at TIMESTAMPTZ,
    rationale TEXT,

    -- Size of the fitting set. n_valid_mr counts within-shift moving ranges.
    n_observations INTEGER NOT NULL,
    n_valid_mr INTEGER NOT NULL,

    -- Fixed I-chart limits: center_line is the mean of the fitting
    -- window and sigma = MR-bar / 1.128; i_lcl / i_ucl = center_line -/+ 3 * sigma.
    center_line NUMERIC(14, 6) NOT NULL,
    sigma NUMERIC(14, 6) NOT NULL,
    i_lcl NUMERIC(14, 6) NOT NULL,
    i_ucl NUMERIC(14, 6) NOT NULL,

    -- Fixed MR-chart limits: mr_center is MR-bar; mr_ucl = 3.267 * mr_center.
    mr_center NUMERIC(14, 6) NOT NULL,
    mr_ucl NUMERIC(14, 6) NOT NULL,

    -- Optional fingerprint of the query / data used to fit the limits.
    source_query_hash TEXT,

    -- Previous baseline version replaced by this one, if any.
    supersedes_baseline_id BIGINT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT fk_spc_baseline_booth
        FOREIGN KEY (booth_id)
        REFERENCES dim_booth (booth_id),

    CONSTRAINT fk_spc_baseline_measurement_point
        FOREIGN KEY (measurement_point_id)
        REFERENCES dim_measurement_point (measurement_point_id),

    CONSTRAINT fk_spc_baseline_specification
        FOREIGN KEY (specification_id)
        REFERENCES dim_specification (specification_id),

    -- Include the scope in the self-reference so a successor cannot point
    -- to a baseline belonging to another booth / point / specification.
    CONSTRAINT fk_spc_baseline_supersedes_same_scope
        FOREIGN KEY (
            booth_id,
            measurement_point_id,
            specification_id,
            supersedes_baseline_id
        )
        REFERENCES spc_baseline (
            booth_id,
            measurement_point_id,
            specification_id,
            baseline_id
        ),

    CONSTRAINT uq_spc_baseline_scope_version
        UNIQUE (booth_id, measurement_point_id, specification_id, version),

    CONSTRAINT uq_spc_baseline_scope_id
        UNIQUE (
            booth_id,
            measurement_point_id,
            specification_id,
            baseline_id
        ),

    CONSTRAINT chk_spc_baseline_version
        CHECK (version >= 1),

    CONSTRAINT chk_spc_baseline_status
        CHECK (status IN ('DRAFT', 'ACTIVE', 'RETIRED')),

    CONSTRAINT chk_spc_baseline_window
        CHECK (window_end > window_start),

    CONSTRAINT chk_spc_baseline_effective_period
        CHECK (
            (
                (
                    effective_from IS NOT NULL
                    AND effective_from >= window_end
                )
                OR (
                    effective_from IS NULL
                    AND effective_to IS NULL
                )
            )
            AND (
                effective_to IS NULL
                OR effective_to > effective_from
            )
        ),

    -- DRAFT may omit effective_from and approval metadata.
    CONSTRAINT chk_spc_baseline_active_effective_from
        CHECK (status <> 'ACTIVE' OR effective_from IS NOT NULL),

    CONSTRAINT chk_spc_baseline_retired_effective_to
        CHECK (status <> 'RETIRED' OR effective_to IS NOT NULL),

    CONSTRAINT chk_spc_baseline_active_approval
        CHECK (
            status NOT IN ('ACTIVE', 'RETIRED')
            OR (
                approved_by IS NOT NULL
                AND btrim(approved_by) <> ''
                AND approved_at IS NOT NULL
            )
        ),

    CONSTRAINT chk_spc_baseline_counts
        CHECK (
            n_observations >= 2
            AND n_valid_mr >= 1
            AND n_valid_mr < n_observations
        ),

    CONSTRAINT chk_spc_baseline_i_chart_limits
        CHECK (
            sigma >= 0
            AND abs(sigma - mr_center / 1.128) <= 0.000003
            AND i_lcl <= center_line
            AND center_line <= i_ucl
            AND abs(i_lcl - (center_line - 3 * sigma)) <= 0.000003
            AND abs(i_ucl - (center_line + 3 * sigma)) <= 0.000003
        ),

    CONSTRAINT chk_spc_baseline_mr_limits
        CHECK (
            mr_center >= 0
            AND abs(mr_ucl - 3.267 * mr_center) <= 0.000003
        ),

    CONSTRAINT chk_spc_baseline_not_self_superseding
        CHECK (
            supersedes_baseline_id IS NULL
            OR supersedes_baseline_id <> baseline_id
        )
);

CREATE FUNCTION enforce_spc_baseline_immutability()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status IN ('ACTIVE', 'RETIRED') THEN
            RAISE EXCEPTION 'Approved baselines cannot be deleted'
                USING ERRCODE = '23514',
                      CONSTRAINT = 'chk_spc_baseline_immutable_approved';
        END IF;
        RETURN OLD;
    END IF;

    IF (
           OLD.baseline_id IS DISTINCT FROM NEW.baseline_id
           OR OLD.booth_id IS DISTINCT FROM NEW.booth_id
           OR OLD.measurement_point_id IS DISTINCT FROM NEW.measurement_point_id
           OR OLD.specification_id IS DISTINCT FROM NEW.specification_id
           OR OLD.version IS DISTINCT FROM NEW.version
       ) THEN
        RAISE EXCEPTION 'Baseline identity, scope, and version are immutable'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'chk_spc_baseline_immutable_version';
    END IF;

    IF OLD.status IN ('ACTIVE', 'RETIRED') THEN
        IF ROW(
            OLD.window_start, OLD.window_end, OLD.n_observations, OLD.n_valid_mr,
            OLD.center_line, OLD.sigma, OLD.i_lcl, OLD.i_ucl, OLD.mr_center,
            OLD.mr_ucl, OLD.source_query_hash, OLD.approved_by, OLD.approved_at,
            OLD.supersedes_baseline_id, OLD.effective_from, OLD.rationale,
            OLD.created_at
        ) IS DISTINCT FROM ROW(
            NEW.window_start, NEW.window_end, NEW.n_observations, NEW.n_valid_mr,
            NEW.center_line, NEW.sigma, NEW.i_lcl, NEW.i_ucl, NEW.mr_center,
            NEW.mr_ucl, NEW.source_query_hash, NEW.approved_by, NEW.approved_at,
            NEW.supersedes_baseline_id, NEW.effective_from, NEW.rationale,
            NEW.created_at
        ) THEN
            RAISE EXCEPTION 'Approved baseline data are immutable'
                USING ERRCODE = '23514',
                      CONSTRAINT = 'chk_spc_baseline_immutable_approved';
        END IF;
        IF (OLD.status = 'ACTIVE' AND NEW.status NOT IN ('ACTIVE', 'RETIRED'))
           OR (OLD.status = 'RETIRED' AND NEW.status <> 'RETIRED')
           OR (
               OLD.effective_to IS DISTINCT FROM NEW.effective_to
               AND (OLD.status = 'RETIRED' OR OLD.effective_to IS NOT NULL)
           ) THEN
            RAISE EXCEPTION 'Invalid approved baseline lifecycle change'
                USING ERRCODE = '23514',
                      CONSTRAINT = 'chk_spc_baseline_lifecycle';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_spc_baseline_immutability
    BEFORE UPDATE OR DELETE ON spc_baseline
    FOR EACH ROW
    EXECUTE FUNCTION enforce_spc_baseline_immutability();

CREATE FUNCTION enforce_spc_baseline_supersession()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    invalid_order BOOLEAN;
BEGIN
    EXECUTE
        'SELECT predecessor.version >= current.version FROM '
        || quote_ident(TG_TABLE_SCHEMA)
        || '.spc_baseline AS current JOIN '
        || quote_ident(TG_TABLE_SCHEMA)
        || '.spc_baseline AS predecessor'
        || ' ON predecessor.baseline_id = current.supersedes_baseline_id'
        || ' WHERE current.baseline_id = $1'
    INTO invalid_order
    USING NEW.baseline_id;

    IF invalid_order THEN
        RAISE EXCEPTION 'A baseline must supersede a lower version'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'chk_spc_baseline_supersedes_lower_version';
    END IF;

    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER trg_spc_baseline_supersession
    AFTER INSERT OR UPDATE
    ON spc_baseline
    DEFERRABLE INITIALLY IMMEDIATE
    FOR EACH ROW
    EXECUTE FUNCTION enforce_spc_baseline_supersession();

-- At most one ACTIVE baseline per scope.
CREATE UNIQUE INDEX uq_spc_baseline_one_active_per_scope
    ON spc_baseline (booth_id, measurement_point_id, specification_id)
    WHERE status = 'ACTIVE';

-- Lookup of the baseline effective for a scope at a given time.
CREATE INDEX idx_spc_baseline_scope_effective
    ON spc_baseline (
        booth_id,
        measurement_point_id,
        specification_id,
        effective_from,
        effective_to
    );

-- Foreign-key support for the remaining referenced keys.
CREATE INDEX idx_spc_baseline_measurement_point
    ON spc_baseline (measurement_point_id);

CREATE INDEX idx_spc_baseline_specification
    ON spc_baseline (specification_id);

CREATE INDEX idx_spc_baseline_supersedes
    ON spc_baseline (supersedes_baseline_id)
    WHERE supersedes_baseline_id IS NOT NULL;

COMMENT ON TABLE spc_baseline IS
    'Versioned fixed SPC control limits per booth, measurement point and specification.';
COMMENT ON COLUMN spc_baseline.window_end IS
    'Exclusive end of the measurement window used to fit the limits.';
COMMENT ON COLUMN spc_baseline.status IS
    'DRAFT (under review), ACTIVE (used for monitoring) or RETIRED.';
COMMENT ON COLUMN spc_baseline.effective_from IS
    'Start of use for monitoring; required when status is ACTIVE.';
COMMENT ON COLUMN spc_baseline.effective_to IS
    'Exclusive end of use for monitoring; NULL means open-ended.';
COMMENT ON COLUMN spc_baseline.n_valid_mr IS
    'Number of valid within-shift moving ranges in the fitting window.';
COMMENT ON COLUMN spc_baseline.sigma IS
    'Estimated sigma = MR-bar / 1.128.';
COMMENT ON COLUMN spc_baseline.mr_ucl IS
    'MR-chart upper control limit = 3.267 * mr_center.';
COMMENT ON COLUMN spc_baseline.supersedes_baseline_id IS
    'Earlier baseline version replaced by this baseline, if any.';

COMMIT;
