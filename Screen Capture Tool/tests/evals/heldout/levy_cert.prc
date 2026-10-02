CREATE OR REPLACE PROCEDURE certify_levy(p_dist IN VARCHAR2) IS
  v_total NUMBER;
BEGIN
  SELECT SUM(amount) INTO v_total FROM levy_cert WHERE district_id = p_dist;
  IF v_total > 0 THEN
    UPDATE levy_total SET total = v_total WHERE district_id = p_dist;
  END IF;
  INSERT INTO levy_audit (district_id, action) VALUES (p_dist, 'CERT');
  notify_pkg.send_mail(p_dist);
END certify_levy;
/
