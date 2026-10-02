DATABASE schfin
GLOBALS
  DEFINE g_dist LIKE district.district_id
END GLOBALS
MAIN
  WHENEVER ERROR CONTINUE
  OPEN WINDOW w_aid AT 2,2 WITH FORM "aidform"
  CALL load_district()
  START REPORT aid_rpt
  CLOSE WINDOW w_aid
END MAIN
FUNCTION load_district()
  DEFINE l_amt DECIMAL(11,2)
  SELECT total_aid INTO l_amt FROM district_aid WHERE district_id = g_dist
  UPDATE district_aid SET reviewed = "Y" WHERE district_id = g_dist
END FUNCTION
REPORT aid_rpt(r)
  DEFINE r RECORD LIKE district_aid.*
  FORMAT EVERY ROW
END REPORT
