#!/bin/bash

# Wraps a XenRT execution in a virtual environment
# Usage: venvwrapper.sh <venvpath> <logpath> <jobid> <xenrt executable> <parameters>

# First we get the first 3 parameters and shift

venvpath=$1
logpath=$2
jobid=$3

shift 3

# Error handler
cleanup() {
    # Remove the trap
    trap '' ERR
    set +x
    set +e
    # Print out the error for information
    cat $logpath/setup.log
    # NoJob is what xrt the xrt calls this script with. If a job is present, we want to complete it
    if [ "$jobid" != "NoJob" ]
    then
        echo "Job $jobid Exiting with error"
        set -x
        xenrt update $jobid PREPARE_FAILED "Setup exited with error"
        # If we've got a log, then upload it
        if [ -e "$logpath/setup.log" ]
        then
            if [ -e "$logpath/harness.out" ]
            then
                cat $logpath/harness.out >> $logpath/setup.log
            fi
            
            if [ -e "$logpath/harness.err" ]
            then
                cat $logpath/harness.err >> $logpath/setup.log
            fi

            tar -C $logpath -cvjf $venvpath/setup.tar.bz2 ./setup.log
            xenrt upload $jobid -f $venvpath/setup.tar.bz2
            xenrt update $jobid UPLOADED yes
            xenrt update $jobid PREPARE_FAILED_LOG "setup.log"
        fi
        # Set various parameters on the job, then complete and email
        xenrt update $jobid RETURN ERROR
        xenrt update $jobid CHECK ERROR
        xenrt update $jobid REGRESSION ERROR
        xenrt complete $jobid
        xenrt email $jobid
    fi
    # Remove the virtual env
    rm -rf $venvpath
    exit
}

# Install the trap handler
trap cleanup ERR

set -ex
PATH=/usr/local/bin:$PATH

# If they don't exist, create the virtualenv and log dirs
mkdir -p $venvpath
mkdir -p $logpath

# Create the virtualenv and activate it
virtualenv --system-site-packages $venvpath

source $venvpath/bin/activate

# Copy the exec dir to the virtualenv, so we get better stack traces
path=`dirname $1`

cmd=`basename $1`

shift

# Run install-packages. This also acts as a handy syntax check
python $venvpath/exec/$cmd --install-packages "$@" > $logpath/setup.log 2>&1

# Now actually run XenRT. We don't want the trap handler any more
trap '' ERR
set +e
python $venvpath/exec/$cmd "$@"

# And cleanup
rm -rf $venvpath
