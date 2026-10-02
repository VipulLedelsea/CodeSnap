* Post levy adjustments (FoxPro 9)
SET PROCEDURE TO aidlib
USE levyadj IN 0 SHARED
SELECT levyadj
SCAN FOR !DELETED()
   DO calcadj WITH levyadj.distid
ENDSCAN
lnConn = SQLCONNECT("SCHOOLFIN", "fox", "fox99")
lcSql = "UPDATE AID_PAYMENT SET ADJ = 1 WHERE DISTRICT_ID = " + levyadj.distid
= SQLEXEC(lnConn, lcSql)
DO FORM levyreview
PROCEDURE calcadj
   PARAMETERS tcDist
   REPLACE amount WITH amount * 1.02 IN levyadj
ENDPROC
