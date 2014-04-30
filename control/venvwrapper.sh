#!/bin/bash
set -ex
PATH=/usr/local/bin:$PATH
venvpath=$1
mkdir -p $venvpath
virtualenv --system-site-packages $venvpath
source $venvpath/bin/activate
shift
cmd=$1
shift
python $cmd "$@"
rm -rf $venvpath
