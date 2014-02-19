#!/bin/sh

ROOTDIR=`pwd`

CACHEMAXSIZE=500
CACHE=${ROOTDIR}/cache

TARFILE=${ROOTDIR}`echo ${1} | sed 's/ .*'//`
TARHASH=`sha1sum ${TARFILE} | awk '{print $1}'`
PAGE=`echo ${1} | sed 's/.* //'`

echo Content-type: text/plain
echo ""

if [ ! -e ${CACHE}/${TARHASH} ]; then
    while lsof ${CACHE}/${TARHASH} &> /dev/null; do
        sleep 1
    done
    mkdir -p ${CACHE}
    bzcat ${TARFILE} > ${CACHE}/${TARHASH}
    CURRENTSIZE=`du -m ${CACHE} | awk '{print $1}'`
    while [ ${CURRENTSIZE} -gt ${CACHEMAXSIZE} ]; do
        OLDEST=`ls -t1 --color=none ${CACHE} | tail -n 1`
        rm -f ${CACHE}/${OLDEST}
        CURRENTSIZE=`du -m ${CACHE} | awk '{print $1}'`
    done
fi

if [ ! -z "${PAGE}" ]; then 
    SUBNODES=${CACHE}/${TARHASH}
    tar xOf ${SUBNODES} ./${PAGE}
fi
