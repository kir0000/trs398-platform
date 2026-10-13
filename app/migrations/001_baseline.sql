-- Baseline schema of the SQLite edition (the final state of the PostgreSQL migrations 001-017 of the Docker edition).
-- Types: dates and times are ISO text read back as date / datetime (declared DATE, TIMESTAMP), booleans are 0/1 (BOOLEAN),
-- arrays of readings and JSON documents are JSON text (NUMARR, JSON). The protections that the PostgreSQL edition had in
-- roles and functions are triggers here: an approved record is immutable, the audit log is append-only, protocol numbers are
-- assigned by the database and never change, history is never deleted outside the maintenance functions.

CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    login         TEXT NOT NULL UNIQUE,
    full_name     TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'viewer' CHECK (role IN ('viewer', 'physicist', 'reviewer', 'admin')),
    password_hash TEXT NOT NULL,
    is_active     BOOLEAN NOT NULL DEFAULT 1,
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE linacs (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL UNIQUE,
    site      TEXT,
    model     TEXT,
    serial_no TEXT,
    city      TEXT
);

CREATE TABLE beams (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    linac_id         INTEGER NOT NULL REFERENCES linacs(id),
    modality         TEXT NOT NULL CHECK (modality IN ('photon', 'electron')),
    nominal_energy   NUMERIC NOT NULL,
    fff              BOOLEAN NOT NULL DEFAULT 0,
    dose_rate_mu     NUMERIC,
    field_size       TEXT,
    phantom          TEXT,
    c_pl             NUMERIC,
    h_pl             NUMERIC,
    zmax             NUMERIC,
    window_material  TEXT,
    window_thickness NUMERIC,
    pdd_zref         NUMERIC CHECK (pdd_zref IS NULL OR (pdd_zref > 0 AND pdd_zref <= 120)),
    tmr_zref         NUMERIC CHECK (tmr_zref IS NULL OR (tmr_zref > 0 AND tmr_zref <= 1.5)),
    exp_cgy_mu       NUMERIC CHECK (exp_cgy_mu IS NULL OR (exp_cgy_mu > 0 AND exp_cgy_mu <= 300)),
    exp_zref         NUMERIC CHECK (exp_zref IS NULL OR (exp_zref > 0 AND exp_zref <= 30)),
    exp_source       TEXT,
    cal_mu           NUMERIC CHECK (cal_mu IS NULL OR (cal_mu >= 1 AND cal_mu <= 100000)),
    ref_depth        NUMERIC CHECK (ref_depth IS NULL OR (ref_depth > 0 AND ref_depth <= 30)),
    archived         BOOLEAN NOT NULL DEFAULT 0,
    archived_at      TIMESTAMP,
    archived_by      INTEGER REFERENCES users(id),
    UNIQUE (linac_id, modality, nominal_energy, fff)
);

CREATE TABLE chambers (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    wall_material    TEXT,
    wall_thickness   NUMERIC,
    cavity_length_cm NUMERIC,
    table_version    TEXT NOT NULL,
    UNIQUE (name, table_version)
);

CREATE TABLE chamber_units (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chamber_id INTEGER NOT NULL REFERENCES chambers(id),
    serial_no  TEXT NOT NULL,
    UNIQUE (chamber_id, serial_no)
);

CREATE TABLE electrometers (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    model     TEXT NOT NULL,
    serial_no TEXT NOT NULL,
    UNIQUE (model, serial_no)
);

CREATE TABLE chamber_kq_photon (
    chamber_id INTEGER NOT NULL REFERENCES chambers(id),
    tpr        NUMERIC NOT NULL,
    kq         NUMERIC NOT NULL,
    PRIMARY KEY (chamber_id, tpr)
);

CREATE TABLE chamber_kq_electron (
    chamber_id INTEGER NOT NULL REFERENCES chambers(id),
    table_no   INTEGER NOT NULL CHECK (table_no IN (20, 21)),
    r50        NUMERIC NOT NULL,
    kq         NUMERIC NOT NULL,
    PRIMARY KEY (chamber_id, table_no, r50)
);

CREATE TABLE table10_ks (
    beam_type TEXT NOT NULL CHECK (beam_type IN ('pulsed', 'pulsed_scanned')),
    v_ratio   NUMERIC NOT NULL,
    a0        NUMERIC NOT NULL,
    a1        NUMERIC NOT NULL,
    a2        NUMERIC NOT NULL,
    PRIMARY KEY (beam_type, v_ratio)
);

CREATE TABLE calibrations (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    chamber_unit_id   INTEGER NOT NULL REFERENCES chamber_units(id),
    electrometer_id   INTEGER REFERENCES electrometers(id),
    nd_w              NUMERIC NOT NULL,
    q0                TEXT NOT NULL DEFAULT 'Co-60',
    k_elec            NUMERIC NOT NULL DEFAULT 1,
    voltage_v         NUMERIC,
    polarity_calib    TEXT,
    lab               TEXT,
    calibrated_on     DATE NOT NULL,
    valid_until       DATE,
    kelec_separate    BOOLEAN NOT NULL DEFAULT 0,
    r50_q0            NUMERIC,
    cal_depth         NUMERIC,
    p0                NUMERIC,
    t0                NUMERIC,
    cal_rh            NUMERIC,
    polarity_cal      TEXT,
    cal_pol_corrected BOOLEAN NOT NULL DEFAULT 0,
    polarity_user     TEXT,
    el_range          TEXT,
    kelec_lab         TEXT,
    kelec_date        DATE
);

CREATE TABLE measurement_sessions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    measured_on      DATE NOT NULL,
    beam_id          INTEGER NOT NULL REFERENCES beams(id),
    calibration_id   INTEGER NOT NULL REFERENCES calibrations(id),
    geometry         TEXT NOT NULL CHECK (geometry IN ('SSD', 'SAD')),
    mu               NUMERIC NOT NULL,
    pressure_kpa     NUMERIC NOT NULL,
    temp_c           NUMERIC NOT NULL,
    humidity_pct     NUMERIC,
    v1               NUMERIC NOT NULL,
    v2               NUMERIC NOT NULL,
    m1_readings      NUMARR NOT NULL,
    m2_readings      NUMARR NOT NULL,
    m_plus_readings  NUMARR,
    m_minus_readings NUMARR,
    beam_quality     NUMERIC NOT NULL,
    pdd_zref         NUMERIC,
    tmr_zref         NUMERIC,
    note             TEXT,
    status           TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'submitted', 'approved', 'returned', 'superseded', 'voided')),
    created_by       INTEGER NOT NULL REFERENCES users(id),
    created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    approved_by      INTEGER REFERENCES users(id),
    approved_at      TIMESTAMP,
    supersedes_id    INTEGER REFERENCES measurement_sessions(id),
    supersede_reason TEXT,
    extra            JSON NOT NULL DEFAULT '{}',
    review_comment   TEXT,
    protocol_no      TEXT,
    void_reason      TEXT,
    voided_by        INTEGER REFERENCES users(id),
    voided_at        TIMESTAMP,
    ref_key          TEXT,
    CONSTRAINT approver_differs CHECK (approved_by IS NULL OR approved_by <> created_by),
    CONSTRAINT approved_needs_approver CHECK (status <> 'approved' OR approved_by IS NOT NULL),
    CONSTRAINT supersede_needs_reason CHECK (supersedes_id IS NULL OR supersede_reason IS NOT NULL),
    CONSTRAINT void_needs_reason CHECK (status <> 'voided' OR (void_reason IS NOT NULL AND length(trim(void_reason)) >= 5 AND voided_by IS NOT NULL))
);
CREATE INDEX measurement_sessions_beam_id_measured_on_idx ON measurement_sessions (beam_id, measured_on);
CREATE UNIQUE INDEX measurement_sessions_protocol_no_key ON measurement_sessions (protocol_no);

CREATE TABLE results (
    session_id      INTEGER PRIMARY KEY REFERENCES measurement_sessions(id),
    k_tp            NUMERIC NOT NULL,
    k_elec          NUMERIC NOT NULL,
    k_pol           NUMERIC NOT NULL,
    k_s             NUMERIC NOT NULL,
    k_vol           NUMERIC NOT NULL,
    k_q             NUMERIC NOT NULL,
    m_corrected     NUMERIC NOT NULL,
    dw_zref         NUMERIC NOT NULL,
    dw_zmax         NUMERIC,
    deviation_pct   NUMERIC NOT NULL,
    formula_version TEXT NOT NULL,
    tables_version  TEXT NOT NULL,
    computed_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE protocol_counters (
    year INTEGER PRIMARY KEY,
    last INTEGER NOT NULL
);

CREATE TABLE legacy_journal (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    beam_id       INTEGER NOT NULL REFERENCES beams(id),
    measured_on   DATE NOT NULL,
    deviation_pct NUMERIC NOT NULL,
    dw_zmax       NUMERIC NOT NULL,
    mq_nc_per_mu  NUMERIC,
    chamber_text  TEXT,
    note          TEXT,
    source_file   TEXT NOT NULL,
    is_demo       BOOLEAN NOT NULL DEFAULT 0,
    imported_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (beam_id, measured_on, dw_zmax)
);

CREATE TABLE spc_baseline (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    beam_id   INTEGER NOT NULL REFERENCES beams(id),
    from_date DATE NOT NULL,
    to_date   DATE NOT NULL,
    set_by    INTEGER NOT NULL REFERENCES users(id),
    set_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (to_date >= from_date),
    UNIQUE (beam_id, from_date)
);

CREATE TABLE beam_reference (
    beam_id         INTEGER NOT NULL REFERENCES beams(id) ON DELETE CASCADE,
    chamber_unit_id INTEGER NOT NULL REFERENCES chamber_units(id) ON DELETE CASCADE,
    data            JSON NOT NULL,
    set_by          INTEGER NOT NULL REFERENCES users(id),
    set_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (beam_id, chamber_unit_id)
);

CREATE TABLE uncertainty_settings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    modality   TEXT NOT NULL CHECK (modality IN ('photon', 'electron')),
    code       TEXT NOT NULL,
    is_extra   BOOLEAN NOT NULL DEFAULT 0,
    stage      INTEGER CHECK (stage IN (1, 2)),
    name       TEXT,
    u_pct      NUMERIC NOT NULL CHECK (u_pct >= 0 AND u_pct <= 10),
    note       TEXT,
    active     BOOLEAN NOT NULL DEFAULT 1,
    updated_by INTEGER REFERENCES users(id),
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dist       TEXT CHECK (dist IS NULL OR dist IN ('normal', 'uniform', 'triangular', 'ushaped')),
    how        TEXT,
    UNIQUE (modality, code),
    CHECK (NOT is_extra OR (stage IS NOT NULL AND name IS NOT NULL AND length(trim(name)) >= 3))
);

CREATE TABLE audit_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_id   INTEGER REFERENCES users(id),
    action    TEXT NOT NULL,
    entity    TEXT NOT NULL,
    entity_id TEXT,
    details   JSON
);

-- the flag that the maintenance functions set while they remove history (purge, deleting a beam with its drafts)
CREATE TABLE _maintenance (k TEXT PRIMARY KEY);

-- ---------------------------------------------------------------------------------------------- protections
CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;

CREATE TRIGGER session_lock_voided BEFORE UPDATE ON measurement_sessions
WHEN OLD.status = 'voided'
BEGIN SELECT RAISE(ABORT, 'a voided record cannot be changed'); END;

CREATE TRIGGER session_lock_status BEFORE UPDATE ON measurement_sessions
WHEN OLD.status = 'approved' AND NEW.status NOT IN ('approved', 'superseded', 'voided')
BEGIN SELECT RAISE(ABORT, 'approved record can only be superseded or voided'); END;

CREATE TRIGGER session_lock_data BEFORE UPDATE ON measurement_sessions
WHEN OLD.status = 'approved' AND NEW.status = 'approved'
 AND (NEW.m1_readings IS NOT OLD.m1_readings OR NEW.m2_readings IS NOT OLD.m2_readings OR NEW.beam_quality IS NOT OLD.beam_quality
      OR NEW.pressure_kpa IS NOT OLD.pressure_kpa OR NEW.temp_c IS NOT OLD.temp_c)
BEGIN SELECT RAISE(ABORT, 'approved record is immutable'); END;

CREATE TRIGGER session_keep_protocol_no BEFORE UPDATE OF protocol_no ON measurement_sessions
WHEN OLD.protocol_no IS NOT NULL AND NEW.protocol_no IS NOT OLD.protocol_no
BEGIN SELECT RAISE(ABORT, 'the protocol number cannot be changed'); END;

-- the number is assigned by the database, sequential within the year of the measurement, never reused
CREATE TRIGGER session_assign_protocol_no AFTER INSERT ON measurement_sessions
WHEN NEW.protocol_no IS NULL
BEGIN
    INSERT INTO protocol_counters(year, last) VALUES (CAST(strftime('%Y', NEW.measured_on) AS INTEGER), 1)
        ON CONFLICT(year) DO UPDATE SET last = last + 1;
    UPDATE measurement_sessions
       SET protocol_no = strftime('%Y', NEW.measured_on) || '-' ||
           printf('%04d', (SELECT last FROM protocol_counters WHERE year = CAST(strftime('%Y', NEW.measured_on) AS INTEGER)))
     WHERE id = NEW.id;
END;

-- history is not deleted by the program except through the maintenance functions
CREATE TRIGGER session_no_delete BEFORE DELETE ON measurement_sessions
WHEN OLD.status NOT IN ('draft', 'returned') AND NOT EXISTS (SELECT 1 FROM _maintenance WHERE k = 'purge')
BEGIN SELECT RAISE(ABORT, 'approved, superseded and annulled records cannot be deleted'); END;

-- results, the imported journals and users are history as well: removed only by the maintenance functions (users are deactivated, never deleted)
CREATE TRIGGER results_no_delete BEFORE DELETE ON results
WHEN NOT EXISTS (SELECT 1 FROM _maintenance WHERE k = 'purge')
 AND (SELECT status FROM measurement_sessions WHERE id = OLD.session_id) NOT IN ('draft', 'returned')
BEGIN SELECT RAISE(ABORT, 'results of an approved record cannot be deleted'); END;

CREATE TRIGGER legacy_journal_no_delete BEFORE DELETE ON legacy_journal
WHEN NOT EXISTS (SELECT 1 FROM _maintenance WHERE k = 'purge')
BEGIN SELECT RAISE(ABORT, 'imported journal rows are removed only by the maintenance functions'); END;

CREATE TRIGGER users_no_delete BEFORE DELETE ON users
WHEN NOT EXISTS (SELECT 1 FROM _maintenance WHERE k = 'purge')
BEGIN SELECT RAISE(ABORT, 'users are deactivated, never deleted'); END;

-- ---------------------------------------------------------------------------------------------- views
CREATE VIEW v_trend AS
SELECT 'measured' AS source, s.id AS record_id, s.measured_on, l.name AS linac, b.modality, b.nominal_energy, b.fff,
       r.dw_zmax, r.deviation_pct, r.k_elec, r.k_q, r.k_s, r.k_pol, r.k_tp, r.k_vol, COALESCE(s.ref_key, 'SSD') AS ref_key
FROM measurement_sessions s
JOIN results r ON r.session_id = s.id
JOIN beams b ON b.id = s.beam_id
JOIN linacs l ON l.id = b.linac_id
WHERE s.status = 'approved'
UNION ALL
SELECT 'legacy', j.id, j.measured_on, l.name, b.modality, b.nominal_energy, b.fff,
       j.dw_zmax, j.deviation_pct, NULL, NULL, NULL, NULL, NULL, NULL, 'SSD'
FROM legacy_journal j
JOIN beams b ON b.id = j.beam_id
JOIN linacs l ON l.id = b.linac_id
WHERE NOT j.is_demo;

CREATE VIEW v_spc AS
SELECT t.*,
       abs(t.deviation_pct - lag(t.deviation_pct) OVER w) AS mr,
       avg(t.deviation_pct) OVER (PARTITION BY t.linac, t.modality, t.nominal_energy, t.fff, t.ref_key) AS cl
FROM v_trend t
WINDOW w AS (PARTITION BY t.linac, t.modality, t.nominal_energy, t.fff, t.ref_key ORDER BY t.measured_on, t.source, t.record_id);
