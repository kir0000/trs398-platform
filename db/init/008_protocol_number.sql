-- Protocol number: assigned by the database when a record is created, sequential within the year of the measurement
-- (2026-0001, 2026-0002, ...). Nobody types it; it cannot be changed afterwards. Numbers are never reused.
ALTER TABLE measurement_sessions ADD COLUMN IF NOT EXISTS protocol_no text;
CREATE TABLE IF NOT EXISTS protocol_counters (year int PRIMARY KEY, last int NOT NULL);

-- records that exist already: numbered in chronological order
WITH numbered AS (
    SELECT id, extract(year FROM measured_on)::int AS y,
           row_number() OVER (PARTITION BY extract(year FROM measured_on) ORDER BY measured_on, id) AS n
    FROM measurement_sessions WHERE protocol_no IS NULL)
UPDATE measurement_sessions s SET protocol_no = n.y || '-' || lpad(n.n::text, 4, '0') FROM numbered n WHERE s.id = n.id;

INSERT INTO protocol_counters(year, last)
SELECT split_part(protocol_no, '-', 1)::int, max(split_part(protocol_no, '-', 2)::int)
FROM measurement_sessions GROUP BY 1
ON CONFLICT (year) DO UPDATE SET last = GREATEST(protocol_counters.last, EXCLUDED.last);

ALTER TABLE measurement_sessions ALTER COLUMN protocol_no SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS measurement_sessions_protocol_no_key ON measurement_sessions (protocol_no);

-- runs with the rights of the owner: the application role has no access to the counter table
CREATE OR REPLACE FUNCTION assign_protocol_no() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    y int := extract(year FROM NEW.measured_on)::int;
    n int;
BEGIN
    IF NEW.protocol_no IS NULL THEN
        INSERT INTO protocol_counters(year, last) VALUES (y, 1)
        ON CONFLICT (year) DO UPDATE SET last = protocol_counters.last + 1
        RETURNING last INTO n;
        NEW.protocol_no := y || '-' || lpad(n::text, 4, '0');
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_protocol_no ON measurement_sessions;
CREATE TRIGGER trg_protocol_no BEFORE INSERT ON measurement_sessions
    FOR EACH ROW EXECUTE FUNCTION assign_protocol_no();

CREATE OR REPLACE FUNCTION keep_protocol_no() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.protocol_no := OLD.protocol_no;
    RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_keep_protocol_no ON measurement_sessions;
CREATE TRIGGER trg_keep_protocol_no BEFORE UPDATE ON measurement_sessions
    FOR EACH ROW EXECUTE FUNCTION keep_protocol_no();

REVOKE ALL ON protocol_counters FROM PUBLIC;
