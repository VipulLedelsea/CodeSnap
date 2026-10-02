<%@ Page Language="C#" AutoEventWireup="true" CodeBehind="DistrictAid.aspx.cs" Inherits="MDE.Finance.Web.DistrictAidPage" %>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html>
<head>
  <title>District Aid Lookup</title>
  <script src="/scripts/jquery-1.4.2.min.js"></script>
  <!--[if lt IE 8]><link rel="stylesheet" href="ie7.css" /><![endif]-->
</head>
<body>
  <form id="form1" runat="server" action="DistrictAid.aspx" method="post">
    <label for="txtDistrict">District ID</label>
    <asp:TextBox ID="txtDistrict" runat="server" MaxLength="6" />
    <asp:TextBox ID="txtYear" runat="server" />
    <asp:Button ID="btnLookup" runat="server" Text="Look up" OnClick="btnLookup_Click" />
    <asp:Label ID="lblTotal" runat="server" />
  </form>
  <a href="PaymentHistory.aspx?d=1">Payment history</a>
  <a href="https://education.mn.gov/help">Help</a>
</body>
</html>
