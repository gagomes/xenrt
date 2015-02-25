#!/bin/bash

set -ex

pushd $1/unittests

export PYTHONPATH=../exec:../server

dir=`mktemp -d`

virtualenv --system-site-packages $dir
source $dir/bin/activate

pip install /usr/share/xenrt/unittests/marvin.tar.gz
pip install /usr/share/xenrt/unittests/coverage-3.7.1.tar.gz

coverage run `which nosetests` -v --with-xunit

popd
mv $1/unittests/nosetests.xml ./nosetests.xml
mv $1/unittests/.coverage ./
coverage xml --include="$1/*"
sed -ie "s,$1/,,g" coverage.xml
rm -r $dir
