/* Post aid payments - OpenEdge 10.2B */
DEFINE VARIABLE dTotal AS DECIMAL NO-UNDO.
DEFINE NEW SHARED VARIABLE cPeriod AS CHARACTER NO-UNDO.
{aidcommon.i}
FOR EACH district NO-LOCK:
    FIND FIRST aidpay WHERE aidpay.distid = district.distid NO-ERROR.
    IF NOT AVAILABLE aidpay THEN DO:
        CREATE aidpay.
        aidpay.distid = district.distid.
    END.
    RUN calcaid.p (INPUT district.distid, OUTPUT dTotal).
END.
PROCEDURE logRun:
    DEFINE INPUT PARAMETER pcMsg AS CHARACTER NO-UNDO.
    MESSAGE pcMsg.
END PROCEDURE.
