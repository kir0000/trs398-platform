-- the address of the computer an action came from (version 2.2.0); old records keep NULL
ALTER TABLE audit_log ADD COLUMN ip TEXT;
