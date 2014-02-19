#!/bin/bash

set -e
set -x

XEN_BUILD_BASE=`pwd`/../build
XEN_INSTALL_BASE=${XEN_BUILD_BASE}/dist/install
if [ -d ${XEN_BUILD_BASE}/linux-*-xen0 ]; then
    XEN_LINUX=`echo ${XEN_BUILD_BASE}/linux-*-xen0`
    XEN_LINUX_MODS=`echo ${XEN_INSTALL_BASE}/lib/modules/*-xen0`
else
    XEN_LINUX=`echo ${XEN_BUILD_BASE}/linux-*-xen`
    XEN_LINUX_MODS=`echo ${XEN_INSTALL_BASE}/lib/modules/*-xen`
fi

./configure --kernel_src=${XEN_LINUX}
cd gnbd-kernel/
make ARCH=xen KERNEL_SRC=${XEN_LINUX}
install -d ${XEN_LINUX_MODS}/kernel/drivers/block/gnbd
install src/gnbd.ko ${XEN_LINUX_MODS}/kernel/drivers/block/gnbd
cd ..
mkdir -p gnbd/include/linux/
cp gnbd-kernel/src/gnbd.h gnbd/include/linux/
cd magma
make
cp -a lib/*.so* ${XEN_INSTALL_BASE}/usr/lib/
cd ..
cp magma/lib/magma.h magma/lib/magmamsg.h magma/lib/magma-build.h gnbd/include/
cd gnbd
make LDFLAGS=-L`pwd`/../magma/lib/
install -d ${XEN_INSTALL_BASE}/usr/sbin
make -C bin sbindir=${XEN_INSTALL_BASE}/usr/sbin install
