CREATE TABLE [dbo].[PaymentBatch] (
    [BatchId]    INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    [DistrictId] CHAR(6) NOT NULL,
    [Status]     CHAR(1) NULL,
    [Amount]     MONEY NULL
);
GO
CREATE TABLE [dbo].[PaymentHistory] (
    [Id]         INT NOT NULL,
    [BatchId]    INT NOT NULL,
    [PaidOn]     DATETIME NULL,
    CONSTRAINT [FK_Hist_Batch] FOREIGN KEY ([BatchId]) REFERENCES [dbo].[PaymentBatch] ([BatchId])
);
GO
CREATE PROCEDURE dbo.usp_ApproveBatch @BatchId INT AS
BEGIN
    UPDATE dbo.PaymentBatch SET Status = 'A' WHERE BatchId = @BatchId;
    INSERT INTO dbo.PaymentHistory (Id, BatchId, PaidOn)
    SELECT NEXT VALUE FOR dbo.HistSeq, BatchId, GETDATE() FROM dbo.PaymentBatch WHERE BatchId = @BatchId;
    EXEC dbo.usp_AuditWrite @BatchId;
END
GO
CREATE TRIGGER dbo.trg_BatchAudit ON dbo.PaymentBatch AFTER UPDATE AS
    INSERT INTO dbo.AuditLog (Msg) VALUES ('batch changed');
GO
