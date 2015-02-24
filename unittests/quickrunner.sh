#!/bin/bash

set -ex

pushd $1/unittests

export PYTHONPATH=../exec:../server

dir=`mktemp -d`

virtualenv --system-site-packages $dir
source $dir/bin/activate

pip install /usr/share/xenrt/unittests/marvin.tar.gz

nosetests -v --with-xunit

popd
rm -r $dir
