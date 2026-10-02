<?php
include("config.php");
$conn = mysql_connect("mdedb01", "aid", "aidpass2011");
mysql_select_db("schoolfin", $conn);
$district = $_GET['district'];
function saveUpload($file) {
    move_uploaded_file($file['tmp_name'], "/var/aid/" . $file['name']);
    system("gzip /var/aid/" . $file['name']);
}
$result = mysql_query("SELECT * FROM district_aid WHERE district_id = '$district'");
while ($row = mysql_fetch_assoc($result)) {
    echo "<tr><td>" . $row['name'] . "</td></tr>";
}
echo "Searched for " . $_GET['district'];
if (isset($_FILES['levy'])) { saveUpload($_FILES['levy']); }
header("Location: done.php");
?>
<html><body><form method="post" enctype="multipart/form-data"><input type="file" name="levy"></form></body></html>
