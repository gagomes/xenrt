#!/bin/bash

set -ex

mkdir -p `dirname $1`

ISO=`dirname $1`/../`basename $1`.iso

TD=`mktemp -d`

mount -o loop $ISO $TD

rm -rf $1
mkdir -p $1

cp -Rv $TD/* $1/

echo "%systemdrive%\install\python\python.cmd" > $1/\$OEM\$/\$1/install/runonce.cmd
echo "EXIT" >> $1/\$OEM\$/\$1/install/runonce.cmd

sudo sed -i "s#<CommandLine>.*</CommandLine>#<CommandLine>c:\\\\install\\\\runonce.cmd</CommandLine>#" $1/Autounattend.xml

umount $TD
rm -rf $TD
