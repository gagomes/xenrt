#!/bin/bash
set -eu

# Create a virtual environment
virtualenv .env

# Activate virtual environment
set +u
. .env/bin/activate
set -u

BUILDDIR=$(mktemp -d)
(
    cd $BUILDDIR
    wget ftp://xmlsoft.org/libxml2/libxml2-2.9.1.tar.gz
    tar -xzf libxml2-2.9.1.tar.gz
    cd libxml2-2.9.1/python
    python setup.py install
)

rm -rf "$BUILDDIR"

# Install requirements
pip install -r test-requirements.txt

# Install xenrt loader
(
    cd ../xenrt-loader/
    python setup.py install
)

cat << EOF
DONE

Activate your virtual environment by:

    . .env/bin/activate

Run tests:

    nosetests -v --with-xenrt=$(pwd)/..

EOF
