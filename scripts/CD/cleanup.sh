#!/bin/bash
#
# XenRT CD Cleanup Script
#
# (C) XenSource UK Ltd, 2007
# Alex Brett, August 2007

killall thttpd
rm -f /usr/bin/xrt
rm -fr /tmp/xenrt
