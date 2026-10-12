-- Historical journal entries imported from the xlsm worksheets. They hold results only (no raw readings),
-- so they cannot live in measurement_sessions. Demo rows are stored but excluded from trends.
-- Safe to re-run: views are dropped and recreated.

CREATE TABLE IF NOT EXISTS legacy_journal (
    id             bigserial PRIMARY KEY,
    beam_id        int NOT NULL REFERENCES beams(id),
    measured_on    date NOT NULL,
    deviation_pct  numeric NOT NULL,
    dw_zmax        numeric NOT NULL,
    mq_nc_per_mu   numeric,
    chamber_text   text,
    note           text,
    source_file    text NOT NULL,
    is_demo        boolean NOT NULL DEFAULT false,
    imported_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (beam_id, measured_on, dw_zmax)
);

DROP VIEW IF EXISTS v_spc;
DROP VIEW IF EXISTS v_trend;

CREATE VIEW v_trend AS
SELECT 'measured'::text AS source, s.id AS record_id, s.measured_on, l.name AS linac, b.modality,
       b.nominal_energy, b.fff, r.dw_zmax, r.deviation_pct,
       r.k_elec, r.k_q, r.k_s, r.k_pol, r.k_tp, r.k_vol
FROM measurement_sessions s
JOIN results r ON r.session_id = s.id
JOIN beams b ON b.id = s.beam_id
JOIN linacs l ON l.id = b.linac_id
WHERE s.status = 'approved'
UNION ALL
SELECT 'legacy', j.id, j.measured_on, l.name, b.modality, b.nominal_energy, b.fff,
       j.dw_zmax, j.deviation_pct, NULL, NULL, NULL, NULL, NULL, NULL
FROM legacy_journal j
JOIN beams b ON b.id = j.beam_id
JOIN linacs l ON l.id = b.linac_id
WHERE NOT j.is_demo;

CREATE VIEW v_spc AS
SELECT t.*,
       abs(t.deviation_pct - lag(t.deviation_pct) OVER w) AS mr,
       avg(t.deviation_pct) OVER (PARTITION BY t.linac, t.modality, t.nominal_energy, t.fff) AS cl
FROM v_trend t
WINDOW w AS (PARTITION BY t.linac, t.modality, t.nominal_energy, t.fff ORDER BY t.measured_on, t.source, t.record_id);

GRANT SELECT, INSERT ON legacy_journal TO trs_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO trs_app;
GRANT SELECT ON v_trend, v_spc TO trs_readonly, trs_app;
