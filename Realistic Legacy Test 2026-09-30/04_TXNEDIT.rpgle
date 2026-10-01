     H DFTACTGRP(*NO) ACTGRP('TAXBATCH') OPTION(*SRCSTMT:*NODEBUGIO)
     H DATFMT(*ISO) TIMFMT(*ISO) BNDDIR('QC2LE')
     FTXNIN     IF   E             DISK    USROPN INFDS(FileInfo)
     FTXNVALID  O    E             DISK    USROPN
     FTXNREJECT O    E             DISK    USROPN
     D TxnEdit         PR                  EXTPGM('TXNEDIT')
     D  ControlDate                   8A   CONST
     D  BranchNumber                  5A   CONST
     D  ReturnCode                   10I 0
     D TxnEdit         PI
     D  ControlDate                   8A   CONST
     D  BranchNumber                  5A   CONST
     D  ReturnCode                   10I 0
     D FileInfo        DS
     D  FileStatus            11     15A
     D  MemberName            83     92A
     D Work            DS                  QUALIFIED
     D  Parcel                       12A
     D  Receipt                      16A
     D  PayDate                        D   DATFMT(*ISO)
     D  Amount                       11P 2
     D  Tender                        1A
     D  Source                        4A
     D  ErrorCode                     4A
     D Totals          DS                  QUALIFIED
     D  ReadCount                    10I 0 INZ(0)
     D  ValidCount                   10I 0 INZ(0)
     D  RejectCount                  10I 0 INZ(0)
     D  ValidAmount                  15P 2 INZ(0)
     D  RejectAmount                 15P 2 INZ(0)
     D ParsedDate      S               D   DATFMT(*ISO)
     D TodayDate       S               D   DATFMT(*ISO)
     D ControlISO      S               D   DATFMT(*ISO)
     D Duplicate       S               N   INZ(*OFF)
     D Message         S             80A   INZ(*BLANKS)
     D LogMessage      PR                  EXTPGM('Qp0lWriteLog')
     D  Text                         80A   CONST
     C                   EVAL      ReturnCode = 0
     C                   MONITOR
     C                   EVAL      ControlISO = %DATE(ControlDate:*ISO0)
     C                   ON-ERROR
     C                   EVAL      ReturnCode = 4
     C                   EVAL      Message = 'TXNEDIT INVALID CONTROL DATE'
     C                   CALLP     LogMessage(Message)
     C                   RETURN
     C                   ENDMON
     C                   OPEN      TXNIN
     C                   OPEN      TXNVALID
     C                   OPEN      TXNREJECT
     C                   IF        FileStatus <> '00000'
     C                   EVAL      ReturnCode = 12
     C                   EVAL      Message = 'TXNEDIT INPUT OPEN FAILED ' +
     C                                      FileStatus
     C                   CALLP     LogMessage(Message)
     C                   RETURN
     C                   ENDIF
     C                   READ      TXNIN                                90
     C                   DOW       NOT *IN90
     C                   ADD       1             Totals.ReadCount
     C                   CLEAR                   Work.ErrorCode
     C                   EXSR      ValidateRecord
     C                   IF        Work.ErrorCode = *BLANKS
     C                   WRITE     TXNVALIDR
     C                   ADD       1             Totals.ValidCount
     C                   ADD       Work.Amount   Totals.ValidAmount
     C                   ELSE
     C                   WRITE     TXNREJECTR
     C                   ADD       1             Totals.RejectCount
     C                   ADD       Work.Amount   Totals.RejectAmount
     C                   ENDIF
     C                   READ      TXNIN                                90
     C                   ENDDO
     C                   EXSR      CheckTotals
     C                   CLOSE     TXNIN
     C                   CLOSE     TXNVALID
     C                   CLOSE     TXNREJECT
     C                   SETON                                        LR
     C                   RETURN
     C     ValidateRecord BEGSR
     C                   IF        %TRIM(Work.Parcel) = *BLANKS
     C                   EVAL      Work.ErrorCode = 'P001'
     C                   ELSEIF    %LEN(%TRIM(Work.Parcel)) <> 12
     C                   EVAL      Work.ErrorCode = 'P002'
     C                   ELSEIF    %TRIM(Work.Receipt) = *BLANKS
     C                   EVAL      Work.ErrorCode = 'R001'
     C                   ELSEIF    Work.Amount <= 0
     C                   EVAL      Work.ErrorCode = 'A001'
     C                   ELSEIF    Work.Amount > 9999999.99
     C                   EVAL      Work.ErrorCode = 'A002'
     C                   ELSEIF    Work.PayDate > ControlISO
     C                   EVAL      Work.ErrorCode = 'D001'
     C                   ELSEIF    Work.PayDate < ControlISO - %DAYS(45)
     C                   EVAL      Work.ErrorCode = 'D002'
     C                   ELSEIF    %SCAN(Work.Tender:'ACW') = 0
     C                   EVAL      Work.ErrorCode = 'T001'
     C                   ELSEIF    Work.Source <> 'BRCH'
     C                   EVAL      Work.ErrorCode = 'S001'
     C                   ELSE
     C                   EXSR      CheckDuplicate
     C                   IF        Duplicate
     C                   EVAL      Work.ErrorCode = 'R002'
     C                   ENDIF
     C                   ENDIF
     C                   ENDSR
     C     CheckDuplicate BEGSR
     C                   SETOFF                                       91
     C     Work.Receipt  CHAIN     TXNVALIDR                            91
     C                   EVAL      Duplicate = NOT *IN91
     C                   ENDSR
     C     CheckTotals   BEGSR
     C                   IF        Totals.ReadCount <>
     C                             Totals.ValidCount + Totals.RejectCount
     C                   EVAL      ReturnCode = 20
     C                   EVAL      Message = 'TXNEDIT CONTROL TOTAL MISMATCH'
     C                   CALLP     LogMessage(Message)
     C                   ELSEIF    Totals.RejectCount > 0
     C                   EVAL      ReturnCode = 4
     C                   ENDIF
     C                   ENDSR
      * END OF TXNEDIT PROGRAM SOURCE
