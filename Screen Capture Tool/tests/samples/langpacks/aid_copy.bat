@echo off
REM Copy aid exports to the share and load staging
set PERIOD=%1
net use Z: \\mdefs01\aid Summer2015 /user:MDE\aidsvc
call :load
xcopy C:\export\*.csv Z:\incoming /Y
if errorlevel 1 goto fail
goto :eof
:load
sqlcmd -S MDESQL01 -U aidload -P Load2015! -i C:\aid\load.sql
goto :eof
:fail
echo Copy failed
