CREATE PROCEDURE dbo.usp_AidReport @DistrictId varchar(10), @Sort varchar(50)
AS
BEGIN
    SET NOCOUNT ON
    DECLARE @sql nvarchar(4000)
    DECLARE cur CURSOR FOR SELECT DistrictId FROM dbo.District
    SET @sql = 'SELECT * FROM dbo.AidPayment WHERE DistrictId = ''' + @DistrictId + ''' ORDER BY ' + @Sort
    EXEC(@sql)
    IF @@ERROR <> 0 RETURN 1
    INSERT INTO dbo.AuditLog (Event) VALUES ('AidReport')
    EXEC master..xp_cmdshell 'bcp SCHOOLFIN.dbo.AidPayment out C:\export\aid.csv -c -T'
    EXEC dbo.usp_LogRun @DistrictId
END
GO
