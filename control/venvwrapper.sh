#!/bin/bash
set -ex
PATH=/usr/local/bin:$PATH

venvpath=$1

mkdir -p $venvpath

virtualenv --system-site-packages $venvpath

source $venvpath/bin/activate

shift

path=`dirname $1`

cp -R $path $venvpath/exec

cmd=`basename $1`

shift

set +e
python $venvpath/exec/$cmd --install-packages "$@"
python $venvpath/exec/$cmd "$@"

rm -rf $venvpath
