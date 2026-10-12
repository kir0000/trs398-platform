-- Editable Type B uncertainty values (worksheet "yellow cells") and user-added lines of the uncertainty budget.
-- modality: the budget it belongs to; code: the stable code of a standard component (s1_cal_secondary, s2_kq, ...)
-- or the code of an added line (x + random hex). A standard component with an active row has its value replaced;
-- an added line (is_extra) has a name and a stage (1 or 2). Rows are never deleted: active = false switches them off.
CREATE TABLE IF NOT EXISTS uncertainty_settings (
    id          serial PRIMARY KEY,
    modality    text NOT NULL CHECK (modality IN ('photon', 'electron')),
    code        text NOT NULL,
    is_extra    boolean NOT NULL DEFAULT false,
    stage       smallint CHECK (stage IN (1, 2)),
    name        text,
    u_pct       numeric NOT NULL CHECK (u_pct >= 0 AND u_pct <= 10),
    note        text,
    active      boolean NOT NULL DEFAULT true,
    updated_by  int REFERENCES users(id),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (modality, code),
    CHECK (NOT is_extra OR (stage IS NOT NULL AND name IS NOT NULL AND length(btrim(name)) >= 3))
);
GRANT SELECT, INSERT, UPDATE ON uncertainty_settings TO trs_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO trs_app;
