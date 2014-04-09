#!/bin/bash
set -eux

# Snapshot created with: xenrt-integrator-snapshot-guest virtualbox:guesttest/test
# Do not forget to forward the execdaemon ports

THIS_DIR="$(dirname "$(readlink -f $0)")"
OPSYS_DIR="$(readlink -f "$THIS_DIR/../exec/xenrt/lib/opsys")"
#GUEST="virtualbox:wendows/test"
GUEST="virtualbox-pfwd:127.0.0.1:guesttest/test"
GUEST="xenserver:root@butterfish.xenrt.xs.citrite.net:xenroot:Windows 7/test"

coverage run $(which nosetests) \
  -v \
  --with-guest-launcher="$GUEST" --with-xenrt="$THIS_DIR/.."

coverage report --include "$OPSYS_DIR/*"