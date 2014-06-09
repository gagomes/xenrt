#!/bin/bash

set -ex

TD=`mktemp -d`

mount -o loop $1 $TD

rm -rf $2
mkdir -p $2

cp -Rv $TD/* $2/

echo "%systemdrive%\install\python\python.cmd" > $2/\$OEM\$/\$1/install/runonce.cmd
echo "EXIT" >> $2/\$OEM\$/\$1/install/runonce.cmd

sudo sed -i "s#<CommandLine>.*</CommandLine>#<CommandLine>c:\\\\install\\\\runonce.cmd</CommandLine>#" $2/Autounattend.xml

umount $TD
rm -rf $TD
