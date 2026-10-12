-- Reference values of a beam (worksheet sections 1, 3, (iii), (iv)) and the depth data that belong to the beam itself.
--  * beams.pdd_zref / beams.tmr_zref: PDD(zref), % and TMR(zref) of the beam are Equipment data and fill the sheet automatically;
--  * beam_reference: the readings that a physicist declared as the reference of a beam with a given chamber unit
--    (quality inputs, the series M, MU, M+, M-, M1, M2, V1, V2, pulse type); they are offered to every new measurement.
ALTER TABLE beams ADD COLUMN IF NOT EXISTS pdd_zref numeric CHECK (pdd_zref IS NULL OR (pdd_zref > 0 AND pdd_zref <= 120));
ALTER TABLE beams ADD COLUMN IF NOT EXISTS tmr_zref numeric CHECK (tmr_zref IS NULL OR (tmr_zref > 0 AND tmr_zref <= 1.5));

CREATE TABLE IF NOT EXISTS beam_reference (
    beam_id          int NOT NULL REFERENCES beams(id) ON DELETE CASCADE,
    chamber_unit_id  int NOT NULL REFERENCES chamber_units(id) ON DELETE CASCADE,
    data             jsonb NOT NULL,
    set_by           int NOT NULL REFERENCES users(id),
    set_at           timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (beam_id, chamber_unit_id)
);
GRANT SELECT, INSERT, UPDATE ON beam_reference TO trs_app;
