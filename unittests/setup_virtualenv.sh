#!/bin/bash
set -eu

# Create a virtual environment
virtualenv .env

# Activate virtual environment
set +u
. .env/bin/activate
set -u

# Install requirements
pip install -r test-requirements.txt

# Hacks, so that ../exec and ../lib are on the PYTHONPATH
readlink -f ../exec > .env/lib/python2.7/site-packages/xenrt-exec.pth
readlink -f ../lib > .env/lib/python2.7/site-packages/xenrt-lib.pth

# Another hack - so that imports don't fail
touch ../exec/xenrt/ctrl.py

cat << EOF
DONE

Activate your virtual environment by:

    . .env/bin/activate

Run tests:

    nosetests -v

EOF
