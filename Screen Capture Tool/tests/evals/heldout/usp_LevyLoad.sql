CREATE PROCEDURE dbo.usp_LevyLoad
AS
BEGIN
    SET NOCOUNT ON
    TRUNCATE TABLE dbo.LevyStage
    INSERT INTO dbo.LevyStage SELECT * FROM OPENQUERY(MAINFRAME, 'SELECT * FROM MDE.LEVY_CERT')
    UPDATE t SET t.Amount = s.Amount FROM dbo.LevyTotal t JOIN dbo.LevyStage s ON s.DistrictId = t.DistrictId
    EXEC dbo.usp_LevyAudit 'LOAD'
END
GO
