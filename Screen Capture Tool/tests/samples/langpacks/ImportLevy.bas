Attribute VB_Name = "ImportLevy"
Option Compare Database
Option Explicit

' Imports the county levy file into the LEVY_STAGING table (run from the main switchboard)
Public Sub ImportLevyFile()
    Dim db As DAO.Database
    Dim rs As DAO.Recordset
    On Error GoTo Fail
    Set db = CurrentDb
    DoCmd.SetWarnings False
    DoCmd.RunSQL "DELETE FROM LEVY_STAGING"
    DoCmd.TransferText acImportDelim, "LevySpec", "LEVY_STAGING", "\\mdefs01\levy\levy.csv", True
    Set rs = db.OpenRecordset("LEVY_STAGING")
    Do While Not rs.EOF
        If rs!AMOUNT < 0 Then
            DoCmd.RunSQL "UPDATE LEVY_STAGING SET FLAG = 'NEG' WHERE ID = " & rs!ID
        End If
        rs.MoveNext
    Loop
    DoCmd.OpenForm "frmLevyReview"
    Exit Sub
Fail:
    MsgBox "Import failed: " & Err.Description
End Sub
