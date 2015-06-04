#!/bin/bash

set -ex

pushd $1/unittests

export PYTHONPATH=../exec:../server

nosetests -v --with-xunit

popd
