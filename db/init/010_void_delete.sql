-- Removing a wrong record without losing the history.
--  * a draft or returned record may be deleted (delete_draft): its protocol number is not reused, the audit log keeps who/what;
--  * an approved record is never deleted: an admin voids it ("annulled") with a reason; it leaves trends and budgets,
--    the protocol prints "ANNULLED", the row stays in the database.
ALTER TYPE record_status ADD VALUE IF NOT EXISTS 'voided';
ALTER TABLE measurement_sessions ADD COLUMN IF NOT EXISTS void_reason text;
ALTER TABLE measurement_sessions ADD COLUMN IF NOT EXISTS voided_by int REFERENCES users(id);
ALTER TABLE measurement_sessions ADD COLUMN IF NOT EXISTS voided_at timestamptz;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'void_needs_reason') THEN
        ALTER TABLE measurement_sessions ADD CONSTRAINT void_needs_reason
            CHECK (status::text <> 'voided' OR (void_reason IS NOT NULL AND length(btrim(void_reason)) >= 5 AND voided_by IS NOT NULL));
    END IF;
END $$;

CREATE OR REPLACE FUNCTION session_lock() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status::text = 'voided' THEN
        RAISE EXCEPTION 'a voided record cannot be changed';
    END IF;
    IF OLD.status = 'approved' AND NEW.status::text NOT IN ('approved', 'superseded', 'voided') THEN
        RAISE EXCEPTION 'approved record can only be superseded or voided';
    END IF;
    IF OLD.status = 'approved' AND NEW.status = 'approved' AND
       (NEW.m1_readings, NEW.m2_readings, NEW.beam_quality, NEW.pressure_kpa, NEW.temp_c)
       IS DISTINCT FROM
       (OLD.m1_readings, OLD.m2_readings, OLD.beam_quality, OLD.pressure_kpa, OLD.temp_c) THEN
        RAISE EXCEPTION 'approved record is immutable';
    END IF;
    RETURN NEW;
END $$;

-- the application role has no DELETE on measurements; this function is the only way and only for unapproved records
CREATE OR REPLACE FUNCTION delete_draft(p_session bigint, p_actor int) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    s measurement_sessions%ROWTYPE;
    a users%ROWTYPE;
BEGIN
    SELECT * INTO a FROM users WHERE id = p_actor AND is_active;
    IF NOT FOUND THEN RAISE EXCEPTION 'unknown or inactive user'; END IF;
    SELECT * INTO s FROM measurement_sessions WHERE id = p_session FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'record not found'; END IF;
    IF s.status::text NOT IN ('draft', 'returned') THEN
        RAISE EXCEPTION 'only a draft or a returned record can be deleted';
    END IF;
    IF s.created_by <> p_actor AND a.role <> 'admin' THEN
        RAISE EXCEPTION 'only the author or an admin can delete a record';
    END IF;
    DELETE FROM results WHERE session_id = p_session;
    DELETE FROM measurement_sessions WHERE id = p_session;
    INSERT INTO audit_log(user_id, action, entity, entity_id, details)
    VALUES (p_actor, 'delete_draft', 'measurement', p_session::text,
            jsonb_build_object('protocol_no', s.protocol_no, 'status', s.status, 'beam_id', s.beam_id,
                               'measured_on', s.measured_on, 'author_id', s.created_by));
    RETURN s.protocol_no;
END $$;
REVOKE ALL ON FUNCTION delete_draft(bigint, int) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION delete_draft(bigint, int) TO trs_app;
