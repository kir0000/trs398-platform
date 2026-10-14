-- the audit log stays append-only; only the controlled clearing of the administrator (app/dbops.py: prune_audit) may delete records,
-- after the archive and a safety copy of the database are made, and the clearing itself is written to the log
DROP TRIGGER audit_no_delete;
CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_log
WHEN NOT EXISTS (SELECT 1 FROM _maintenance WHERE k = 'audit_prune')
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
