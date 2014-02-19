#!/bin/sh
#
# process.sh
#
# Usage: process.sh <dir> <stylesheet>
# 
# This script scans all subdirectories of <dir> and converts
# any trace files it finds into a form suitable for display.
#
# <stylesheet> is the XSLT stylesheet to use for the 
# transformation. 
#
TRACEDIR=${1}
STYLESHEET=${2}
SUBNODES=subnodes.tar.bz2

WORKDIR=`mktemp -d`
IFS="$(echo -e "\n\r")"

mkdir ${WORKDIR}/subnodes

for TRACE in `find ${TRACEDIR} -name "*.xml.bz2"`; do
    OUTPUTFILE=`echo ${TRACE} | sed 's/.xml.bz2/.htm/'`    
    if lsof ${TRACE} &> /dev/null; then
        echo "Skipping open file ${TRACE}."
        continue
    elif [ -e ${OUTPUTFILE} ]; then
        echo "Skipping already processed file ${TRACE}."
        continue
    fi
    echo "Processing trace ${TRACE}..."
    bzcat ${TRACE} | xsltproc -o ${WORKDIR}/ ${STYLESHEET} -
    for SUBNODE in `find ${WORKDIR} -maxdepth 1 -name "id*.htm"`; do
        mv "${SUBNODE}" ${WORKDIR}/subnodes
    done
    mv ${WORKDIR}/*.htm ${OUTPUTFILE}
done

tar cjf ${TRACEDIR}/${SUBNODES} -C ${WORKDIR}/subnodes .
rm -rf ${WORKDIR}
