-- Several baseline periods per beam (statistics restart after a re-adjustment): spc_baseline is keyed by (beam_id, from_date).
ALTER TABLE spc_baseline ADD COLUMN IF NOT EXISTS id serial;
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'spc_baseline_pkey' AND conrelid = 'spc_baseline'::regclass
               AND pg_get_constraintdef(oid) = 'PRIMARY KEY (beam_id)') THEN
        ALTER TABLE spc_baseline DROP CONSTRAINT spc_baseline_pkey;
        ALTER TABLE spc_baseline ADD PRIMARY KEY (id);
    END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS spc_baseline_beam_from_key ON spc_baseline (beam_id, from_date);
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO trs_app;
