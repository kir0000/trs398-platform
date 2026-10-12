-- Parameters of worksheet sections 1-3 live in Equipment, not on the calculation sheet.
ALTER TABLE linacs ADD COLUMN IF NOT EXISTS city text;

ALTER TABLE beams ADD COLUMN IF NOT EXISTS field_size text;          -- reference field (photons) / applicator (electrons)
ALTER TABLE beams ADD COLUMN IF NOT EXISTS phantom text;
ALTER TABLE beams ADD COLUMN IF NOT EXISTS c_pl numeric;             -- plastic phantom: depth scaling
ALTER TABLE beams ADD COLUMN IF NOT EXISTS h_pl numeric;             -- plastic phantom: fluence scaling
ALTER TABLE beams ADD COLUMN IF NOT EXISTS zmax numeric;

ALTER TABLE calibrations ADD COLUMN IF NOT EXISTS r50_q0 numeric;    -- Q0 = electron beam: its R50,w
ALTER TABLE calibrations ADD COLUMN IF NOT EXISTS cal_depth numeric;
ALTER TABLE calibrations ADD COLUMN IF NOT EXISTS p0 numeric;
ALTER TABLE calibrations ADD COLUMN IF NOT EXISTS t0 numeric;
ALTER TABLE calibrations ADD COLUMN IF NOT EXISTS cal_rh numeric;
ALTER TABLE calibrations ADD COLUMN IF NOT EXISTS polarity_cal text;        -- '+', '−' or '+−' (both ticked on the sheet)
ALTER TABLE calibrations ADD COLUMN IF NOT EXISTS cal_pol_corrected boolean NOT NULL DEFAULT false;
ALTER TABLE calibrations ADD COLUMN IF NOT EXISTS polarity_user text;
ALTER TABLE calibrations ADD COLUMN IF NOT EXISTS el_range text;
ALTER TABLE calibrations ADD COLUMN IF NOT EXISTS kelec_lab text;           -- separate electrometer calibration (kelec, section ii)
ALTER TABLE calibrations ADD COLUMN IF NOT EXISTS kelec_date date;
