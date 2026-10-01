/* REXX: TXNRECOV - ASSESS AND RESTART THE NIGHTLY TAX PAYMENT JOB */
parse upper arg runDate action .
if runDate = '' then runDate = date('S')
if action = '' then action = 'CHECK'
if datatype(runDate, 'W') = 0 | length(runDate) <> 8 then do
  say 'Usage: TXNRECOV yyyymmdd CHECK|RESTART'
  exit 4
end
if action <> 'CHECK' & action <> 'RESTART' then do
  say 'TXNRECOV: action must be CHECK or RESTART'
  exit 4
end
numeric digits 12
address tso
userId = sysvar('SYSUID')
hlq = 'COUNTY.TAX'
jobName = 'TXNNIGHT'
bankDsn = hlq'.BANK.SETTLE.D'substr(runDate,3)
postDsn = hlq'.POST.INPUT.D'substr(runDate,3)
sortDsn = hlq'.POST.SORTED.D'substr(runDate,3)
auditDsn = hlq'.POST.AUDIT.D'substr(runDate,3)
rejectDsn = hlq'.REJECT.D'substr(runDate,3)
glCtlDsn = hlq'.CONTROL.TXNNIGHT.D'substr(runDate,3)
call CheckDataSet bankDsn,  'BANK INPUT'
bankExists = result
call CheckDataSet postDsn,  'INTAKE OUTPUT'
postExists = result
call CheckDataSet sortDsn,  'SORT OUTPUT'
sortExists = result
call CheckDataSet auditDsn, 'POST AUDIT'
auditExists = result
call CheckDataSet rejectDsn,'REJECT FILE'
rejectExists = result
call CheckDataSet glCtlDsn,  'COMPLETION'
completeExists = result
if completeExists then do
  say 'Job is already marked complete; no restart is allowed.'
  exit 0
end
if \bankExists then do
  say 'Bank input is missing. Contact Treasury Operations.'
  exit 8
end
restartStep = 'INTAKE'
if postExists then restartStep = 'SORTPAY'
if sortExists then restartStep = 'POSTDB2'
if auditExists then restartStep = 'RECON'
if auditExists then do
  call ReadAudit auditDsn
  if auditDbErrors > 0 then do
    say 'DB2 errors must be cleared before a restart.'
    exit 12
  end
  if auditPosted > 0 then restartStep = 'RECON'
end
say 'Recommended restart step:' restartStep
if action = 'CHECK' then do
  say 'No job was submitted.'
  exit 0
end
if restartStep = 'POSTDB2' & auditExists then do
  say 'Refusing POSTDB2 restart because an audit file already exists.'
  say 'Use receipt-level recovery procedure TAX-OPS-17.'
  exit 12
end
jclDsn = hlq'.JCL(TXNNIGHT)'
tempDsn = "'"userId'.TXNRECOV.JCL'"
"ALLOC FI(INTJCL) DA("tempDsn") NEW TRACKS SPACE(2,1)",
  "RECFM(F B) LRECL(80) BLKSIZE(0) REUSE"
if rc <> 0 then do
  say 'Unable to allocate temporary JCL; return code' rc
  exit 16
end
queue "//TXNNGHT JOB (REV,ACCT),'TAX RECOVERY',CLASS=A,MSGCLASS=H"
queue "//         SET RUNDATE="substr(runDate,3)
queue "//         SET RESTART="restartStep
queue "//TXNNIGHT JCLLIB ORDER=(COUNTY.TAX.PROCLIB)"
queue "//         INCLUDE MEMBER=TXNNIGHT"
queue "/*"
"EXECIO" queued() "DISKW INTJCL (FINIS"
if rc <> 0 then do
  say 'Unable to write temporary JCL; return code' rc
  "FREE FI(INTJCL)"
  exit 16
end
"SUBMIT" tempDsn
submitRc = rc
"FREE FI(INTJCL)"
if submitRc <> 0 then do
  say 'Job submission failed; return code' submitRc
  exit 16
end
say 'Recovery job submitted. Review JES output before releasing GL feed.'
exit 0
CheckDataSet: procedure
  parse arg dsn, label
  x = outtrap('list.')
  "LISTDSI '"dsn"'"
  listRc = rc
  x = outtrap('OFF')
  if listRc = 0 then do
    say left(label,16) 'FOUND' dsn
    return 1
  end
  say left(label,16) 'MISSING' dsn
  return 0
ReadAudit: procedure expose auditPosted auditDbErrors
  parse arg dsn
  auditPosted = 0
  auditDbErrors = 0
  "ALLOC FI(AUDITIN) DA('"dsn"') SHR REUSE"
  if rc <> 0 then return
  "EXECIO * DISKR AUDITIN (STEM row. FINIS"
  if rc = 0 then do i = 1 to row.0
    status = strip(substr(row.i,43,8))
    if status = 'POSTED' then auditPosted = auditPosted + 1
    if status = 'DBERROR' then auditDbErrors = auditDbErrors + 1
  end
  "FREE FI(AUDITIN)"
  return
