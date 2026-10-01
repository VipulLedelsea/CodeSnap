//TXNNIGHT JOB (REV,ACCT),'TAX PMT NIGHTLY',CLASS=A,MSGCLASS=H,
//             MSGLEVEL=(1,1),NOTIFY=&SYSUID,REGION=0M
//*------------------------------------------------------------------*
//* COUNTY PROPERTY TAX PAYMENT CYCLE                                *
//* SCHEDULE: TUESDAY-SATURDAY 01:15 AFTER BANK FILE ARRIVAL         *
//* RESTART: USE TXNRECOV REXX TO IDENTIFY THE SAFE RESTART STEP      *
//*------------------------------------------------------------------*
//JCLLIB   ORDER=(COUNTY.TAX.PROCLIB)
//SETVARS  SET RUNDATE=&LYYMMDD,ENV=PROD,HLQ=COUNTY.TAX
//*------------------------------------------------------------------*
//* VERIFY THE SETTLEMENT FEED IS PRESENT AND NONEMPTY                *
//*------------------------------------------------------------------*
//CHECKIN  EXEC PGM=IDCAMS
//SYSPRINT DD SYSOUT=*
//SYSIN    DD *,SYMBOLS=JCLONLY
  LISTCAT ENT('&HLQ..BANK.SETTLE.D&RUNDATE') ALL
  IF LASTCC GT 0 THEN SET MAXCC = 12
/*
//*------------------------------------------------------------------*
//* NORMALIZE BANK RECORDS AND SPLIT VALID/REJECTED ITEMS             *
//*------------------------------------------------------------------*
//INTAKE   EXEC PGM=TXNPAYB,COND=(0,NE,CHECKIN)
//STEPLIB  DD DISP=SHR,DSN=&HLQ..LOAD
//BANKIN   DD DISP=SHR,DSN=&HLQ..BANK.SETTLE.D&RUNDATE
//POSTOUT  DD DSN=&HLQ..POST.INPUT.D&RUNDATE,
//            DISP=(NEW,CATLG,DELETE),UNIT=SYSDA,
//            SPACE=(CYL,(20,10),RLSE),DCB=(RECFM=FB,LRECL=47)
//REJOUT   DD DSN=&HLQ..REJECT.D&RUNDATE,
//            DISP=(NEW,CATLG,DELETE),UNIT=SYSDA,
//            SPACE=(CYL,(5,2),RLSE),DCB=(RECFM=FB,LRECL=78)
//SYSOUT   DD SYSOUT=*
//SYSUDUMP DD SYSOUT=H
//*------------------------------------------------------------------*
//* SORT BY PARCEL AND RECEIPT FOR DB2 LOCK ORDER AND RESTARTABILITY *
//*------------------------------------------------------------------*
//SORTPAY  EXEC PGM=SORT,COND=(4,LT,INTAKE)
//SYSOUT   DD SYSOUT=*
//SORTIN   DD DISP=SHR,DSN=&HLQ..POST.INPUT.D&RUNDATE
//SORTOUT  DD DSN=&HLQ..POST.SORTED.D&RUNDATE,
//            DISP=(NEW,CATLG,DELETE),UNIT=SYSDA,
//            SPACE=(CYL,(20,10),RLSE),DCB=(RECFM=FB,LRECL=47)
//SYSIN    DD *
  SORT FIELDS=(1,12,CH,A,13,16,CH,A)
  SUM FIELDS=NONE
/*
//*------------------------------------------------------------------*
//* POST PAYMENTS. TXNPOST COMMITS ONE RECEIPT AT A TIME.             *
//* RC 4 = BUSINESS REJECTIONS; RC 8 = ONE OR MORE DB2 FAILURES.     *
//*------------------------------------------------------------------*
//POSTDB2  EXEC PGM=IKJEFT01,DYNAMNBR=30,COND=(4,LT,SORTPAY)
//STEPLIB  DD DISP=SHR,DSN=&HLQ..LOAD
//SYSTSPRT DD SYSOUT=*
//SYSPRINT DD SYSOUT=*
//INFILE   DD DISP=SHR,DSN=&HLQ..POST.SORTED.D&RUNDATE
//AUDITF   DD DSN=&HLQ..POST.AUDIT.D&RUNDATE,
//            DISP=(NEW,CATLG,DELETE),UNIT=SYSDA,
//            SPACE=(CYL,(10,5),RLSE),DCB=(RECFM=FB,LRECL=58)
//SYSTSIN  DD *,SYMBOLS=JCLONLY
  DSN SYSTEM(TXP1)
  RUN PROGRAM(TXNPOST) PLAN(TXNPOSTP) LIB('&HLQ..LOAD')
  END
/*
//*------------------------------------------------------------------*
//* RECONCILE BANK, POSTING, AND DB2 TOTALS                           *
//*------------------------------------------------------------------*
//RECON    EXEC PGM=TXNRECON,COND=(8,LT,POSTDB2)
//STEPLIB  DD DISP=SHR,DSN=&HLQ..LOAD
//BANKIN   DD DISP=SHR,DSN=&HLQ..BANK.SETTLE.D&RUNDATE
//AUDITIN  DD DISP=SHR,DSN=&HLQ..POST.AUDIT.D&RUNDATE
//REJECTIN DD DISP=SHR,DSN=&HLQ..REJECT.D&RUNDATE
//REPORT   DD SYSOUT=R,DEST=FINANCE
//EXCEPT   DD DSN=&HLQ..RECON.EXCEPT.D&RUNDATE,
//            DISP=(NEW,CATLG,DELETE),UNIT=SYSDA,
//            SPACE=(TRK,(15,5),RLSE),DCB=(RECFM=FB,LRECL=133)
//SYSOUT   DD SYSOUT=*
//*------------------------------------------------------------------*
//* CREATE A GENERATION FOR DOWNSTREAM GENERAL LEDGER INTERFACE      *
//*------------------------------------------------------------------*
//GLFEED   EXEC PGM=TXNGLXTR,COND=(4,LT,RECON)
//STEPLIB  DD DISP=SHR,DSN=&HLQ..LOAD
//AUDITIN  DD DISP=SHR,DSN=&HLQ..POST.AUDIT.D&RUNDATE
//GLOUT    DD DSN=&HLQ..GL.PAYMENTS(+1),
//            DISP=(NEW,CATLG,DELETE),UNIT=SYSDA,
//            SPACE=(CYL,(5,2),RLSE),DCB=(RECFM=FB,LRECL=120)
//CONTROL  DD DSN=&HLQ..GL.CONTROL(+1),
//            DISP=(NEW,CATLG,DELETE),UNIT=SYSDA,
//            SPACE=(TRK,(1,1),RLSE),DCB=(RECFM=FB,LRECL=80)
//SYSOUT   DD SYSOUT=*
//*------------------------------------------------------------------*
//* RETAIN AUDIT DATA FOR SEVEN YEARS; WORK DATA EXPIRES IN 30 DAYS  *
//*------------------------------------------------------------------*
//MIGRATE  EXEC PGM=IDCAMS,COND=(4,LT,GLFEED)
//SYSPRINT DD SYSOUT=*
//SYSIN    DD *,SYMBOLS=JCLONLY
  ALTER '&HLQ..POST.AUDIT.D&RUNDATE' MANAGEMENTCLASS(TAX7YEAR)
  ALTER '&HLQ..POST.SORTED.D&RUNDATE' MANAGEMENTCLASS(WORK30DY)
  ALTER '&HLQ..REJECT.D&RUNDATE' MANAGEMENTCLASS(TAX7YEAR)
/*
//*------------------------------------------------------------------*
//* SEND COMPLETION EVENT TO ENTERPRISE SCHEDULER                     *
//*------------------------------------------------------------------*
//NOTIFY   EXEC PGM=IEFBR14,COND=EVEN
//COMPLETE DD DSN=&HLQ..CONTROL.TXNNIGHT.D&RUNDATE,
//            DISP=(NEW,CATLG,DELETE),UNIT=SYSDA,
//            SPACE=(TRK,(1,1)),DCB=(RECFM=FB,LRECL=80)
//* END TXNNIGHT
