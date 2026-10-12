-- Reference depth of the chamber for a beam (g/cm2): photons 10 by default, electrons: the nominal depth for this energy.
ALTER TABLE beams ADD COLUMN IF NOT EXISTS ref_depth numeric CHECK (ref_depth IS NULL OR (ref_depth > 0 AND ref_depth <= 30));
UPDATE beams SET ref_depth = 10 WHERE ref_depth IS NULL AND modality::text = 'photon';
