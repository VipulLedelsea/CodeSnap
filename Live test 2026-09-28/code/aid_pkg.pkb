CREATE OR REPLACE PACKAGE BODY AID_PKG AS
  PROCEDURE post_payments(p_period IN VARCHAR2) IS
    CURSOR c_dist IS SELECT district_id, adm FROM district_adm WHERE period = p_period;
    v_sql VARCHAR2(4000);
  BEGIN
    FOR r IN c_dist LOOP
      INSERT INTO aid_payment (district_id, amount) VALUES (r.district_id, r.adm * 6728);
    END LOOP;
    v_sql := 'DELETE FROM aid_staging WHERE period = ''' || p_period || '''';
    EXECUTE IMMEDIATE v_sql || ' AND status = ''X''';
    UPDATE aid_run SET status = 'DONE' WHERE period = p_period;
    audit_pkg.log_event('POST', p_period);
  EXCEPTION
    WHEN OTHERS THEN NULL;
  END post_payments;
END AID_PKG;
/
