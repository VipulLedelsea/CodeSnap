<%@ Language=VBScript %>
<!--#include file="inc/dbconn.asp"-->
<html>
<head><title>District Aid Lookup</title></head>
<body>
<%
Option Explicit
Dim conn, rs, strSQL, districtId
On Error Resume Next
districtId = Request.QueryString("id")
Set conn = Server.CreateObject("ADODB.Connection")
conn.Open "Provider=SQLOLEDB;Data Source=MDESQL01;Initial Catalog=SCHOOLFIN;User ID=web;Password=web123"
strSQL = "SELECT NAME, TOTAL_AID FROM DISTRICT WHERE DISTRICT_ID = " & districtId
Set rs = conn.Execute(strSQL)
Response.Write "<h1>" & Request.QueryString("id") & "</h1>"
Sub ShowRow(r)
    Response.Write "<p>" & r("NAME") & ": " & r("TOTAL_AID") & "</p>"
End Sub
Do While Not rs.EOF
    Call ShowRow(rs)
    rs.MoveNext
Loop
If Session("admin") = "" Then Response.Redirect "login.asp"
%>
<form method="post" action="aidlookup.asp"><input type="text" name="id"><input type="submit" value="Find"></form>
</body>
</html>
