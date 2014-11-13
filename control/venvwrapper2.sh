#!/bin/bash

venvpath=$1
logpath=$2
jobid=$3

shift 3

cleanup() {
    trap '' ERR
    #set +x
    set +e
    cat $logpath/setup.log
    if [ "$jobid" != "NoJob" ]
    then
        echo "Job $jobid Exiting with error"
        set -x
        xenrt update $jobid PREPARE_FAILED "Setup exited with error"
        if [ -e "$logpath/setup.log" ]
        then
            tar -C $logpath -cvjf $venvpath/setup.tar.bz2 ./setup.log
            xenrt upload $jobid -f $venvpath/setup.tar.bz2
            xenrt update $jobid UPLOADED yes
        fi
        xenrt complete $jobid
        xenrt email $jobid
    fi
    rm -rf $venvpath
    exit
}

trap cleanup ERR

set -ex
PATH=/usr/local/bin:$PATH


mkdir -p $venvpath
mkdir -p $logpath

virtualenv --system-site-packages $venvpath

source $venvpath/bin/activate


path=`dirname $1`

cp -R $path $venvpath/exec

cmd=`basename $1`

shift

python $venvpath/exec/$cmd --install-packages "$@" > $logpath/setup.log 2>&1

set +e
python $venvpath/exec/$cmd "$@"

rm -rf $venvpath
