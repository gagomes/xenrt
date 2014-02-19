#!/bin/bash
#
# XenRT: suite installation configuration
#
# James Bulpin, March 2007
#
# Copyright (c) 2007 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

progress() {
    echo "$@"
}

progress "Configuring XenRT installation..."

if [ -e localconfig.mk ]; then
    progress "Not changing existing localconfig.mk"
else
    progress "Creating localconfig.mk with default values"
    cp examples/localconfig.mk localconfig.mk
fi

progress "Configuration complete. Now run 'make install'"
