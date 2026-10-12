-- SAD: the dose is determined at the reference point (isocentre, reference depth) and compared with the value expected by the
-- planning system, without recalculation to zmax. The expected value, its reference depth, its source and the MU used at the
-- calibration belong to the beam (Equipment); a record keeps a snapshot, and its trend series is identified by ref_key so that
-- values from different reference conditions are never mixed.
ALTER TABLE beams ADD COLUMN IF NOT EXISTS exp_cgy_mu numeric CHECK (exp_cgy_mu IS NULL OR (exp_cgy_mu > 0 AND exp_cgy_mu <= 300));
ALTER TABLE beams ADD COLUMN IF NOT EXISTS exp_zref numeric CHECK (exp_zref IS NULL OR (exp_zref > 0 AND exp_zref <= 30));
ALTER TABLE beams ADD COLUMN IF NOT EXISTS exp_source text;
ALTER TABLE beams ADD COLUMN IF NOT EXISTS cal_mu numeric CHECK (cal_mu IS NULL OR (cal_mu >= 1 AND cal_mu <= 100000));
ALTER TABLE measurement_sessions ADD COLUMN IF NOT EXISTS ref_key text;
ALTER TABLE results ALTER COLUMN dw_zmax DROP NOT NULL;           -- SAD with the expected dose at the reference point has no zmax value

UPDATE measurement_sessions SET ref_key = CASE WHEN geometry::text = 'SAD' THEN 'SAD|old' ELSE 'SSD' END WHERE ref_key IS NULL;

DROP VIEW IF EXISTS v_spc;
DROP VIEW IF EXISTS v_trend;
CREATE VIEW v_trend AS
SELECT 'measured'::text AS source, s.id AS record_id, s.measured_on, l.name AS linac, b.modality,
       b.nominal_energy, b.fff, r.dw_zmax, r.deviation_pct,
       r.k_elec, r.k_q, r.k_s, r.k_pol, r.k_tp, r.k_vol, COALESCE(s.ref_key, 'SSD') AS ref_key
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
GRANT SELECT ON v_trend, v_spc TO trs_readonly, trs_app;
