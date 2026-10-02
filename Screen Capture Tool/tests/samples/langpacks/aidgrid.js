// District aid grid (jQuery 1.4 era)
var AidGrid = function () {};
function loadGrid(district) {
    $.ajax({ url: "/aid/services/AidService.asmx/GetDistrict", data: { id: district }, async: false,
        success: function (data) { document.write("<table>" + data.d + "</table>"); } });
}
function exportGrid() {
    var xhr = new XMLHttpRequest();
    xhr.open("GET", "/aid/export.ashx?id=" + district, false);
    xhr.send();
    eval(xhr.responseText);
}
$(document).ready(function () { loadGrid($("#district").val()); });
