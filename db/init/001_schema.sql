-- TRS-398 Rev.1 absolute dose platform: initial schema.
-- Executed once by the postgres image on first start of an empty data volume.
-- Role passwords come from environment variables via 000_roles.sh.

CREATE TYPE app_role AS ENUM ('viewer', 'physicist', 'reviewer', 'admin');
CREATE TYPE modality AS ENUM ('photon', 'electron');
CREATE TYPE record_status AS ENUM ('draft', 'submitted', 'approved', 'returned', 'superseded');
CREATE TYPE geometry AS ENUM ('SSD', 'SAD');

-- users of the application (not database roles)
CREATE TABLE users (
    id            serial PRIMARY KEY,
    login         text NOT NULL UNIQUE,
    full_name     text NOT NULL,
    role          app_role NOT NULL DEFAULT 'viewer',
    password_hash text NOT NULL,
    is_active     boolean NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- reference data (versioned by table_version)
CREATE TABLE chambers (
    id               serial PRIMARY KEY,
    name             text NOT NULL,
    wall_material    text,
    wall_thickness   numeric,          -- g/cm2
    cavity_length_cm numeric,          -- L, used for kvol (photons, FFF)
    table_version    text NOT NULL,    -- e.g. 'TRS398-Rev1-2024'
    UNIQUE (name, table_version)
);

CREATE TABLE chamber_kq_photon (        -- Table 16: kQ vs TPR20,10
    chamber_id int NOT NULL REFERENCES chambers(id),
    tpr        numeric NOT NULL,
    kq         numeric NOT NULL,
    PRIMARY KEY (chamber_id, tpr)
);

CREATE TABLE chamber_kq_electron (      -- Tables 20 (Co-60 cal) and 21 (electron cal): kQ vs R50
    chamber_id int NOT NULL REFERENCES chambers(id),
    table_no   int NOT NULL CHECK (table_no IN (20, 21)),
    r50        numeric NOT NULL,
    kq         numeric NOT NULL,
    PRIMARY KEY (chamber_id, table_no, r50)
);

CREATE TABLE table10_ks (               -- Table 10: ks coefficients vs V1/V2
    beam_type text NOT NULL CHECK (beam_type IN ('pulsed', 'pulsed_scanned')),
    v_ratio   numeric NOT NULL,
    a0 numeric NOT NULL, a1 numeric NOT NULL, a2 numeric NOT NULL,
    PRIMARY KEY (beam_type, v_ratio)
);

-- equipment
CREATE TABLE linacs (
    id   serial PRIMARY KEY,
    name text NOT NULL UNIQUE,
    site text
);

CREATE TABLE beams (
    id             serial PRIMARY KEY,
    linac_id       int NOT NULL REFERENCES linacs(id),
    modality       modality NOT NULL,
    nominal_energy numeric NOT NULL,         -- MV or MeV
    fff            boolean NOT NULL DEFAULT false,
    dose_rate_mu   numeric,                  -- MU/min
    UNIQUE (linac_id, modality, nominal_energy, fff)
);

CREATE TABLE chamber_units (
    id         serial PRIMARY KEY,
    chamber_id int NOT NULL REFERENCES chambers(id),
    serial_no  text NOT NULL,
    UNIQUE (chamber_id, serial_no)
);

CREATE TABLE electrometers (
    id        serial PRIMARY KEY,
    model     text NOT NULL,
    serial_no text NOT NULL,
    UNIQUE (model, serial_no)
);

CREATE TABLE calibrations (             -- calibration certificates, including kelec history
    id                 serial PRIMARY KEY,
    chamber_unit_id    int NOT NULL REFERENCES chamber_units(id),
    electrometer_id    int REFERENCES electrometers(id),
    nd_w               numeric NOT NULL,      -- ND,w
    q0                 text NOT NULL DEFAULT 'Co-60',
    k_elec             numeric NOT NULL DEFAULT 1,
    voltage_v          numeric,
    polarity_calib     text,
    lab                text,
    calibrated_on      date NOT NULL,
    valid_until        date
);

-- measurements
CREATE TABLE measurement_sessions (
    id              bigserial PRIMARY KEY,
    measured_on     date NOT NULL,
    beam_id         int NOT NULL REFERENCES beams(id),
    calibration_id  int NOT NULL REFERENCES calibrations(id),
    geometry        geometry NOT NULL,
    mu              numeric NOT NULL,
    pressure_kpa    numeric NOT NULL,
    temp_c          numeric NOT NULL,
    humidity_pct    numeric,
    v1              numeric NOT NULL,
    v2              numeric NOT NULL,
    m1_readings     numeric[] NOT NULL,    -- raw readings at V1
    m2_readings     numeric[] NOT NULL,    -- raw readings at V2
    m_plus_readings numeric[],
    m_minus_readings numeric[],
    beam_quality    numeric NOT NULL,      -- TPR20,10 or R50
    pdd_zref        numeric,               -- percent
    tmr_zref        numeric,
    note            text,
    status          record_status NOT NULL DEFAULT 'draft',
    created_by      int NOT NULL REFERENCES users(id),
    created_at      timestamptz NOT NULL DEFAULT now(),
    approved_by     int REFERENCES users(id),
    approved_at     timestamptz,
    supersedes_id   bigint REFERENCES measurement_sessions(id),
    supersede_reason text,
    -- two-person rule
    CONSTRAINT approver_differs CHECK (approved_by IS NULL OR approved_by <> created_by),
    CONSTRAINT approved_needs_approver CHECK (status <> 'approved' OR approved_by IS NOT NULL),
    CONSTRAINT supersede_needs_reason CHECK (supersedes_id IS NULL OR supersede_reason IS NOT NULL)
);
CREATE INDEX ON measurement_sessions (beam_id, measured_on);

CREATE TABLE results (
    session_id      bigint PRIMARY KEY REFERENCES measurement_sessions(id),
    k_tp            numeric NOT NULL,
    k_elec          numeric NOT NULL,
    k_pol           numeric NOT NULL,
    k_s             numeric NOT NULL,
    k_vol           numeric NOT NULL,
    k_q             numeric NOT NULL,
    m_corrected     numeric NOT NULL,
    dw_zref         numeric NOT NULL,      -- Gy/MU
    dw_zmax         numeric NOT NULL,      -- Gy/MU
    deviation_pct   numeric NOT NULL,      -- vs 1 cGy/MU
    formula_version text NOT NULL,
    tables_version  text NOT NULL,
    computed_at     timestamptz NOT NULL DEFAULT now()
);

-- SPC settings: fixed baseline per beam (optional)
CREATE TABLE spc_baseline (
    beam_id    int PRIMARY KEY REFERENCES beams(id),
    from_date  date NOT NULL,
    to_date    date NOT NULL,
    set_by     int NOT NULL REFERENCES users(id),
    set_at     timestamptz NOT NULL DEFAULT now(),
    CHECK (to_date >= from_date)
);

-- append-only audit trail
CREATE TABLE audit_log (
    id         bigserial PRIMARY KEY,
    at         timestamptz NOT NULL DEFAULT now(),
    user_id    int REFERENCES users(id),
    action     text NOT NULL,
    entity     text NOT NULL,
    entity_id  text,
    details    jsonb
);

CREATE FUNCTION audit_log_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only';
END $$;
CREATE TRIGGER audit_no_update BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();

-- approved measurements cannot be edited, only superseded
CREATE FUNCTION session_lock() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status = 'approved' AND NEW.status NOT IN ('approved', 'superseded') THEN
        RAISE EXCEPTION 'approved record can only be superseded';
    END IF;
    IF OLD.status = 'approved' AND NEW.status = 'approved' AND
       (NEW.m1_readings, NEW.m2_readings, NEW.beam_quality, NEW.pressure_kpa, NEW.temp_c)
       IS DISTINCT FROM
       (OLD.m1_readings, OLD.m2_readings, OLD.beam_quality, OLD.pressure_kpa, OLD.temp_c) THEN
        RAISE EXCEPTION 'approved record is immutable';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER session_lock BEFORE UPDATE ON measurement_sessions
    FOR EACH ROW EXECUTE FUNCTION session_lock();

-- views for trends (approved records only); Grafana reads these
CREATE VIEW v_trend AS
SELECT s.id AS session_id, s.measured_on, l.name AS linac, b.modality, b.nominal_energy, b.fff,
       r.dw_zmax, r.deviation_pct, r.k_elec, r.k_q, r.k_s, r.k_pol, r.k_tp, r.k_vol
FROM measurement_sessions s
JOIN results r ON r.session_id = s.id
JOIN beams b ON b.id = s.beam_id
JOIN linacs l ON l.id = b.linac_id
WHERE s.status = 'approved';

CREATE VIEW v_spc AS
SELECT t.*,
       abs(t.deviation_pct - lag(t.deviation_pct) OVER w) AS mr,
       avg(t.deviation_pct) OVER (PARTITION BY t.linac, t.modality, t.nominal_energy, t.fff) AS cl
FROM v_trend t
WINDOW w AS (PARTITION BY t.linac, t.modality, t.nominal_energy, t.fff ORDER BY t.measured_on, t.session_id);

-- grants (roles created in 000_roles.sh)
GRANT USAGE ON SCHEMA public TO trs_app, trs_readonly;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO trs_app;
REVOKE UPDATE ON audit_log FROM trs_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO trs_app;
GRANT SELECT ON v_trend, v_spc TO trs_readonly;
