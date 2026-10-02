Imports System.Data.SqlClient
Imports System.Web.UI

Public Class AidService
    Inherits System.Web.UI.Page

    Private Sub btnFind_Click(ByVal sender As Object, ByVal e As EventArgs) Handles btnFind.Click
        Dim cn As New SqlConnection("Data Source=MDESQL01;Initial Catalog=SCHOOLFIN;Integrated Security=SSPI")
        Dim cmd As New SqlCommand("SELECT * FROM AidPayment WHERE DistrictId = '" & txtDistrict.Text & "'", cn)
        On Error GoTo Fail
        cn.Open()
        grid.DataSource = cmd.ExecuteReader()
        Exit Sub
Fail:
        lblError.Text = Err.Description
    End Sub
End Class
