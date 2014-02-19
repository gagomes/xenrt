#!/bin/bash
#
# Perform a database backup if DATABASE_BACKUP_TARGET is configured.
#

if DBBACKUP=`xrt --lookup DATABASE_BACKUP_TARGET 2>/dev/null`; then
    IP=`xrt --lookup XENRT_SERVER_ADDRESS`
    FILENAME=/tmp/${IP}-xenrt-`date +%Y%m%d`.gz
    pg_dump xenrt | gzip -c > ${FILENAME}
    scp ${FILENAME} ${DBBACKUP}
    rm -f ${FILENAME}
fi
