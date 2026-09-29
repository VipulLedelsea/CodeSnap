     H DFTACTGRP(*NO) ACTGRP(*CALLER)
     FDISTMST   IF   E           K DISK
     FAIDPAY    UF A E           K DISK
     FAIDDSP    CF   E             WORKSTN
     D WKAMT           S             11P 2
     D CMD             S            200A
      * Post monthly aid payments for each district
     C     *ENTRY        PLIST
     C                   PARM                    PERIOD            6
     C     *LOVAL        SETLL     DISTMST
     C                   READ      DISTMST
     C                   DOW       NOT %EOF(DISTMST)
     C                   EXSR      CALCAID
     C                   READ      DISTMST
     C                   ENDDO
     C                   EXFMT     AIDSCR
     C                   EVAL      CMD = 'SBMJOB CMD(CALL AIDRPT) JOB(' + %TRIM(PERIOD) + ')'
     C                   CALL      'QCMDEXC'
     C                   SETON                                        LR
     C     CALCAID       BEGSR
     C     DISTID        CHAIN     AIDPAY
     C                   IF        %FOUND(AIDPAY)
     C                   EVAL      WKAMT = ADM * RATE
     C                   UPDATE    AIDPAY
     C                   ELSE
     C                   WRITE     AIDPAY
     C                   ENDIF
     C                   ENDSR
