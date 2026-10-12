-- Regression test for schema rules. Run as owner; everything is rolled back at the end.
-- Usage: docker exec -i -e PGPASSWORD=... trs398_db psql -h 127.0.0.1 -U trs_owner -d trs398 -tA < tests/db_constraints.sql
-- Each "expect fail" line must be followed by an ERROR, each "expect ok" by no ERROR.
BEGIN;
INSERT INTO users(login,full_name,role,password_hash) VALUES ('a','A','physicist','x'),('b','B','reviewer','x');
INSERT INTO linacs(name) VALUES ('L1');
INSERT INTO beams(linac_id,modality,nominal_energy,fff) SELECT id,'photon',6,true FROM linacs WHERE name='L1';
INSERT INTO chambers(name,table_version) VALUES ('C','t');
INSERT INTO chamber_units(chamber_id,serial_no) SELECT id,'1' FROM chambers WHERE name='C';
INSERT INTO calibrations(chamber_unit_id,nd_w,calibrated_on) SELECT id,0.05,'2026-01-01' FROM chamber_units WHERE serial_no='1';
INSERT INTO measurement_sessions(measured_on,beam_id,calibration_id,geometry,mu,pressure_kpa,temp_c,v1,v2,m1_readings,m2_readings,beam_quality,created_by)
 SELECT '2026-09-19',b.id,c.id,'SSD',200,100.6,23,-300,-100,'{24.36}','{24.21}',0.6276,u.id
 FROM beams b, calibrations c, users u WHERE u.login='a';
SELECT id AS sid FROM measurement_sessions LIMIT 1 \gset
SELECT id AS ua FROM users WHERE login='a' \gset
SELECT id AS ub FROM users WHERE login='b' \gset

SELECT 'T1 self-approve (expect fail)';
SAVEPOINT sp; UPDATE measurement_sessions SET status='approved', approved_by=:ua WHERE id=:sid; ROLLBACK TO sp;

SELECT 'T2 approved without approver (expect fail)';
SAVEPOINT sp; UPDATE measurement_sessions SET status='approved' WHERE id=:sid; ROLLBACK TO sp;

SELECT 'T3 approve by another user (expect ok)';
UPDATE measurement_sessions SET status='approved', approved_by=:ub, approved_at=now() WHERE id=:sid;

SELECT 'T4 edit approved readings (expect fail)';
SAVEPOINT sp; UPDATE measurement_sessions SET m1_readings='{25}' WHERE id=:sid; ROLLBACK TO sp;

SELECT 'T5 approved back to draft (expect fail)';
SAVEPOINT sp; UPDATE measurement_sessions SET status='draft' WHERE id=:sid; ROLLBACK TO sp;

SELECT 'T6 supersede without reason (expect fail)';
SAVEPOINT sp;
INSERT INTO measurement_sessions(measured_on,beam_id,calibration_id,geometry,mu,pressure_kpa,temp_c,v1,v2,m1_readings,m2_readings,beam_quality,created_by,supersedes_id)
 SELECT '2026-09-19',beam_id,calibration_id,'SSD',200,100.6,23,-300,-100,'{24.4}','{24.2}',0.6276,:ua,:sid FROM measurement_sessions WHERE id=:sid;
ROLLBACK TO sp;

SELECT 'T7 supersede with reason, mark old record superseded (expect ok)';
INSERT INTO measurement_sessions(measured_on,beam_id,calibration_id,geometry,mu,pressure_kpa,temp_c,v1,v2,m1_readings,m2_readings,beam_quality,created_by,supersedes_id,supersede_reason)
 SELECT '2026-09-19',beam_id,calibration_id,'SSD',200,100.6,23,-300,-100,'{24.4}','{24.2}',0.6276,:ua,:sid,'typo in reading' FROM measurement_sessions WHERE id=:sid;
UPDATE measurement_sessions SET status='superseded' WHERE id=:sid;

SELECT 'T8 audit_log update (expect fail)';
INSERT INTO audit_log(action,entity) VALUES ('x','y');
SAVEPOINT sp; UPDATE audit_log SET action='z'; ROLLBACK TO sp;

SELECT 'T9 audit_log delete (expect fail)';
SAVEPOINT sp; DELETE FROM audit_log; ROLLBACK TO sp;

ROLLBACK;
