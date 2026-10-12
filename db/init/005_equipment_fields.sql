-- Linac model and serial number, and the electrometer data of the worksheet (model, SN, "calibrated separately").
ALTER TABLE linacs ADD COLUMN IF NOT EXISTS model text;
ALTER TABLE linacs ADD COLUMN IF NOT EXISTS serial_no text;
ALTER TABLE calibrations ADD COLUMN IF NOT EXISTS kelec_separate boolean NOT NULL DEFAULT false;
GRANT DELETE ON electrometers TO trs_app;
