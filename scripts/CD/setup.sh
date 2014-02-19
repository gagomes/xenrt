#!/bin/bash
#
# XenRT CD Setup Script
#
# (C) XenSource UK Ltd, 2007
# Alex Brett, August 2007

/mnt/xenrt/share/bin/thttpd -p 88 -d /mnt/xenrt
rm -f /usr/bin/xrt
ln -s /mnt/xenrt/share/exec/main.py /usr/bin/xrt
mkdir -p /tmp/xenrt
echo `cat /mnt/xenrt/share/scripts/keys/id_dsa_xenrt.pub` >> /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
export PYTHONPATH="/mnt/xenrt/share/lib:${PYTHONPATH}"
