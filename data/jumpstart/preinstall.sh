#!/bin/sh

# use in the installer the dns servers obtained from dhcp
cp `ls -1 /tmp/resolv.conf* | head -n 1` /tmp/root/etc/resolv.conf
cat /etc/nsswitch.conf | sed 's/hosts:[ \t]*files/hosts:      files dns/g' > /tmp/nsswitch.conf.tmp
cp /tmp/nsswitch.conf.tmp /etc/nsswitch.conf

# you might want to do some preconfiguration here.
