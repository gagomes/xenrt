#!/bin/bash

sshpass -p xensource scp -r -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o CheckHostIP=no xenrtd@xenrt.hq.xensource.com:.ssh ./

git clone git://hg.uk.xensource.com/xenrt/xenrt.git xenrt.git
git clone git://hg.uk.xensource.com/xenrt/xenrt-internal.git xenrt-internal.git

ln -s ../../xenrt-internal.git/config/$1/config.mk xenrt.git/build/

echo "xensource" | sudo -S ls

sudo mkdir -p /local/inputs/tests
sudo chown -R xenrtd:xenrtd /local/

ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o CheckHostIP=no xenrtd@xenrt.hq.xensource.com xenrt-internal.hg/scripts/sync-distmaster -y

echo "xensource" | sudo -S ls
make -C xenrt.git setup
make -C xenrt.git setup
