/* REXX - extract district aid file and hand off to the state system */
ARG period
ADDRESS TSO "ALLOC F(AIDIN) DA('SCHFIN.AID.MONTHLY') SHR REUSE"
"EXECIO * DISKR AIDIN (STEM rec. FINIS"
DO i = 1 TO rec.0
  PARSE VAR rec.i distid 5 amount 16 .
  CALL CHECKAMT amount
END
"EXECIO * DISKW AIDOUT (STEM rec. FINIS"
ADDRESS ISPEXEC "DISPLAY PANEL(AIDPNL1)"
cmd = "SUBMIT 'SCHFIN.JCL(AIDSEND" || period || ")'"
INTERPRET cmd
EXIT 0
CHECKAMT: PROCEDURE
  ARG amt
  IF amt < 0 THEN SIGNAL BADAMT
  RETURN
BADAMT:
  SAY 'Negative amount'
  EXIT 8
