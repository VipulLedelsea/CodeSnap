/* Forecast next-year aid by district */
LIBNAME fin ODBC dsn=SCHOOLFIN user=sasuser password=Sas2014pw;
LIBNAME out 'C:\SASDATA\AID';
%MACRO forecast(yr);
  DATA out.forecast_&yr;
    SET fin.district_adm;
    aid = adm * 6728 * 1.02;
  RUN;
%MEND forecast;
PROC SQL;
  CREATE TABLE out.summary AS
  SELECT district_id, SUM(aid) AS total FROM out.forecast_2027 GROUP BY district_id;
QUIT;
%forecast(2027);
X 'copy C:\SASDATA\AID\*.sas7bdat \\mdefs01\aid';
