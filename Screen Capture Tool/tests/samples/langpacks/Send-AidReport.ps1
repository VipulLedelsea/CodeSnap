#requires -version 3
param([string]$Period)
Import-Module SqlServer
$pw = ConvertTo-SecureString "Rpt2016!" -AsPlainText -Force
function Get-AidRows {
    param($p)
    Invoke-Sqlcmd -ServerInstance MDESQL01 -Database SCHOOLFIN -Query "SELECT * FROM AidPayment WHERE Period = '$p'"
}
$rows = Get-AidRows $Period
$rows | Export-Csv "C:\reports\aid_$Period.csv"
Invoke-Expression "C:\tools\mailer.exe $Period"
