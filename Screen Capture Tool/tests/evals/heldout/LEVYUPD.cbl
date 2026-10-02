       IDENTIFICATION DIVISION.
       PROGRAM-ID. LEVYUPD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
           EXEC SQL INCLUDE LEVYREC END-EXEC.
       01  WS-DIST                   PIC X(6).
       01  WS-AMT                    PIC S9(9)V99 COMP-3.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM OPEN-CURSOR
           PERFORM FETCH-LEVY UNTIL SQLCODE = 100
           CALL 'LEVYLOG' USING WS-DIST
           STOP RUN.
       OPEN-CURSOR.
           EXEC SQL
               DECLARE C1 CURSOR FOR
               SELECT DISTRICT_ID, LEVY_AMT FROM MDE.LEVY_CERT
           END-EXEC
           EXEC SQL OPEN C1 END-EXEC.
       FETCH-LEVY.
           EXEC SQL FETCH C1 INTO :WS-DIST, :WS-AMT END-EXEC
           IF SQLCODE = 0
               EXEC SQL
                   UPDATE MDE.LEVY_TOTAL SET AMT = AMT + :WS-AMT
                   WHERE DISTRICT_ID = :WS-DIST
               END-EXEC
           END-IF.
