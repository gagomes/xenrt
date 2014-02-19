#!/bin/bash

sshpass -p xensource scp -r -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o CheckHostIP=no xenrtd@xenrt.hq.xensource.com:.ssh ./

hg clone http://hg.uk.xensource.com/closed/xenrt.hg
hg clone http://hg.uk.xensource.com/closed/xenrt-internal.hg

ln -s ../../xenrt-internal.hg/config/$1/config.mk xenrt.hg/build/

echo "xensource" | sudo -S ls

sudo mkdir -p /local/inputs/tests
sudo chown -R xenrtd:xenrtd /local/

ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o CheckHostIP=no xenrtd@xenrt.hq.xensource.com xenrt-internal.hg/scripts/sync-distmaster -y

echo "xensource" | sudo -S ls
make -C xenrt.hg setup
make -C xenrt.hg setup
