#!/bin/ksh
# Nightly aid batch driver
PERIOD=$1
LOG=/var/log/aid/nightly_$PERIOD.log
run_extract() {
    sqlplus -s aidbatch/Batch2012@SCHFINP @/opt/aid/sql/extract.sql $PERIOD >> $LOG
}
if [ $PERIOD = "" ]; then
    echo "usage: aid_nightly.ksh period"
    exit 1
fi
run_extract
. /opt/aid/bin/common.ksh
ftp -n county-ftp <<END_FTP
user aid aidpw
put /data/aid/feed.txt
END_FTP
eval "$POST_CMD"
