VERSION 5.00
Object = "{831FDD16-0C5C-11D2-A9FC-0000F8754DA1}#2.0#0"; "MSCOMCTL.OCX"
Begin VB.Form frmAidCalc
   Caption         =   "District Aid Calculation"
   ClientHeight    =   5400
   Begin VB.TextBox txtDistrict
      Height          =   315
   End
   Begin VB.CommandButton cmdCalc
      Caption         =   "&Calculate"
   End
End
Attribute VB_Name = "frmAidCalc"
Option Explicit
Private cn As ADODB.Connection
Private Const CONN_STR = "Provider=SQLOLEDB;Data Source=MDESQL01;Initial Catalog=SCHOOLFIN;User ID=aidapp;Password=Winter2009"

Private Sub Form_Load()
    Set cn = New ADODB.Connection
    cn.Open CONN_STR
End Sub

Private Sub cmdCalc_Click()
    Dim rs As ADODB.Recordset
    Dim sql As String
    On Error GoTo ErrHandler
    sql = "SELECT ADM, PUPIL_UNITS FROM DISTRICT_ADM WHERE DISTRICT_ID = '" & txtDistrict.Text & "'"
    Set rs = cn.Execute(sql)
    If Not rs.EOF Then
        Call ComputeAid(rs!ADM)
    End If
    frmResults.Show
    Exit Sub
ErrHandler:
    MsgBox Err.Description
    Resume Next
End Sub

Private Sub ComputeAid(ByVal adm As Double)
    Dim f As Integer
    f = FreeFile
    Open "C:\AID\AUDIT.LOG" For Append As #f
    Print #f, adm
    Close #f
End Sub
