param([string]$Year)
function Get-LevyData {
    param($y)
    Invoke-Sqlcmd -ServerInstance MDESQL03 -Database Levy -Query "SELECT * FROM dbo.LevyCert WHERE Year = $y"
}
function Send-LevyFile {
    param($path)
    Copy-Item $path \\mdefs01\levy\outbound
}
$data = Get-LevyData $Year
$data | Export-Csv "C:\levy\levy_$Year.csv"
Send-LevyFile "C:\levy\levy_$Year.csv"
