-- Water phantom window (electron worksheet, section 3): lives in Equipment like the other section 1-3 parameters.
ALTER TABLE beams ADD COLUMN IF NOT EXISTS window_material text;
ALTER TABLE beams ADD COLUMN IF NOT EXISTS window_thickness numeric;      -- g cm-2
