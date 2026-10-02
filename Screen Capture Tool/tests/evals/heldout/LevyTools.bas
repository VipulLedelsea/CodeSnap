Attribute VB_Name = "LevyTools"
Option Explicit

Public Function LevyTotal(ByVal dist As String) As Currency
    Dim rs As ADODB.Recordset
    Set rs = New ADODB.Recordset
    rs.Open "SELECT SUM(AMOUNT) FROM LEVY_CERT WHERE DISTRICT_ID = '" & dist & "'", gConn
    LevyTotal = rs(0)
End Function

Public Sub ExportLevy()
    Dim f As Integer
    f = FreeFile
    Open "C:\LEVY\EXPORT.CSV" For Output As #f
    Print #f, LevyTotal("0001")
    Close #f
    Call LogExport
End Sub
