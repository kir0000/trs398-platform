-- A beam entered by mistake that already has records:
--  * archive: the beam disappears from the choices of a new measurement, its records and trends stay;
--  * delete with its drafts: only when every record of the beam is a draft or a returned one (approved, superseded and
--    annulled records are history and are never deleted); imported journal rows are deleted only on request.
ALTER TABLE beams ADD COLUMN IF NOT EXISTS archived boolean NOT NULL DEFAULT false;
ALTER TABLE beams ADD COLUMN IF NOT EXISTS archived_at timestamptz;
ALTER TABLE beams ADD COLUMN IF NOT EXISTS archived_by int REFERENCES users(id);

CREATE OR REPLACE FUNCTION delete_beam_with_drafts(p_beam int, p_actor int, p_legacy boolean DEFAULT false) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    n_locked int; n_drafts int; n_legacy int;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM users WHERE id = p_actor AND role = 'admin' AND is_active) THEN
        RAISE EXCEPTION 'only an active admin may delete a beam';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM beams WHERE id = p_beam) THEN RAISE EXCEPTION 'beam not found'; END IF;
    SELECT count(*) FILTER (WHERE status::text NOT IN ('draft', 'returned')), count(*) INTO n_locked, n_drafts
        FROM measurement_sessions WHERE beam_id = p_beam;
    IF n_locked > 0 THEN
        RAISE EXCEPTION 'the beam has approved, superseded or annulled records: archive it instead';
    END IF;
    SELECT count(*) INTO n_legacy FROM legacy_journal WHERE beam_id = p_beam;
    IF n_legacy > 0 AND NOT p_legacy THEN
        RAISE EXCEPTION 'the beam has imported journal rows: confirm their deletion';
    END IF;
    DELETE FROM results WHERE session_id IN (SELECT id FROM measurement_sessions WHERE beam_id = p_beam);
    DELETE FROM measurement_sessions WHERE beam_id = p_beam;
    DELETE FROM legacy_journal WHERE beam_id = p_beam;
    DELETE FROM spc_baseline WHERE beam_id = p_beam;
    DELETE FROM beam_reference WHERE beam_id = p_beam;
    DELETE FROM beams WHERE id = p_beam;
    INSERT INTO audit_log(user_id, action, entity, entity_id, details)
    VALUES (p_actor, 'delete_beam_with_drafts', 'beams', p_beam::text,
            jsonb_build_object('drafts', n_drafts, 'legacy', n_legacy));
    RETURN jsonb_build_object('drafts', n_drafts, 'legacy', n_legacy);
END $$;
REVOKE ALL ON FUNCTION delete_beam_with_drafts(int, int, boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION delete_beam_with_drafts(int, int, boolean) TO trs_app;
