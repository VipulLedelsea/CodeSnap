<%@ page import="mn.mde.finance.aid.AidCalculator, java.util.Vector" %>
<%@ include file="header.jsp" %>
<html>
<head><title>Aid Lookup</title><script src="js/prototype-1.6.0.js"></script></head>
<body>
<form action="/aid/lookup" method="get">
  District: <input type="text" name="district" required>
  <input type="submit" value="Search">
</form>
<object classid="clsid:D27CDB6E-AE6D-11cf-96B8-444553540000"><param name="movie" value="chart.swf"></object>
</body>
</html>
