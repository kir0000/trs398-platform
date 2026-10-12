-- Equipment can be removed by the application (admin only, enforced in the app) when nothing refers to it.
-- Foreign keys still protect used rows; measurement data keeps its no-DELETE rule (see admin_purge()).
GRANT DELETE ON linacs, beams, spc_baseline, calibrations, chamber_units TO trs_app;
