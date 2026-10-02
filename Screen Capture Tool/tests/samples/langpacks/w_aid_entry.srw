$PBExportHeader$w_aid_entry.srw
forward
global type w_aid_entry from window
end type
end forward

global type w_aid_entry from window
integer width = 2400
string title = "Aid Entry"
end type

event open;
SQLCA.DBMS = "ODBC"
SQLCA.DBPass = "pbaid99"
CONNECT USING SQLCA;
dw_aid.SetTransObject(SQLCA)
dw_aid.Retrieve()
end event

event clicked;
long ll_count
SELECT count(*) INTO :ll_count FROM aid_payment WHERE district_id = :is_dist USING SQLCA;
IF ll_count = 0 THEN
    Open(w_aid_detail)
END IF
end event
