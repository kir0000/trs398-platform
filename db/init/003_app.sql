-- Application support: extra input fields, review comment, and the controlled admin purge.
-- The application role has no DELETE privilege. Purging goes through admin_purge(), a SECURITY DEFINER
-- function that checks the actor is an active admin, requires a reason, and writes the audit record
-- (audit_log itself is never purged).

ALTER TABLE measurement_sessions ADD COLUMN IF NOT EXISTS extra jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE measurement_sessions ADD COLUMN IF NOT EXISTS review_comment text;

CREATE OR REPLACE FUNCTION admin_purge(p_scope text, p_actor int, p_reason text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    n_res bigint := 0;
    n_ses bigint := 0;
    n_leg bigint := 0;
BEGIN
    IF p_reason IS NULL OR length(trim(p_reason)) < 5 THEN
        RAISE EXCEPTION 'a reason of at least 5 characters is required';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM users WHERE id = p_actor AND role = 'admin' AND is_active) THEN
        RAISE EXCEPTION 'only an active admin may purge data';
    END IF;
    IF p_scope NOT IN ('measurements', 'legacy', 'all') THEN
        RAISE EXCEPTION 'unknown purge scope: %', p_scope;
    END IF;

    IF p_scope IN ('measurements', 'all') THEN
        DELETE FROM results;
        GET DIAGNOSTICS n_res = ROW_COUNT;
        DELETE FROM measurement_sessions;
        GET DIAGNOSTICS n_ses = ROW_COUNT;
    END IF;
    IF p_scope IN ('legacy', 'all') THEN
        DELETE FROM legacy_journal;
        GET DIAGNOSTICS n_leg = ROW_COUNT;
    END IF;

    INSERT INTO audit_log(user_id, action, entity, details)
    VALUES (p_actor, 'purge', p_scope,
            jsonb_build_object('reason', p_reason, 'sessions', n_ses, 'results', n_res, 'legacy', n_leg));
    RETURN jsonb_build_object('sessions', n_ses, 'results', n_res, 'legacy', n_leg);
END $$;

REVOKE ALL ON FUNCTION admin_purge(text, int, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admin_purge(text, int, text) TO trs_app;
