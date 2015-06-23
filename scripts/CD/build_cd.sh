#!/bin/bash
#
# XenRT CD Build Script
#
# (C) XenSource UK Ltd, 2007
# Alex Brett, August 2007

echo "XenRT CD Build Script"
echo "====================="
echo "This script creates xenrtCD.iso in the current directory."
echo "It creates the image in /mnt/xenrt - this directory must be writeable by" 
echo "the current user."
echo
echo "Press any key to continue..."
read -n 1
echo

# Check we've been given xenrt.hg as the first argument
if [ ${#1} -lt 1 -o ! -d ${1} ]; then
    echo "You must specify the path to xenrt.hg as the first argument!"
    exit 1
fi

pwd=`pwd`

cd ${1}

# Install
make BUILD_ALL_TESTS=no WORKDIR=/tmp PREFIX=/mnt/xenrt install

# Remove all keys
rm -fr /mnt/xenrt/etc/keys/*

# Put in the default site.xml
cp -f scripts/CD/site.xml /mnt/xenrt/etc/

# Copy the setup and cleanup scripts to the root
cp scripts/CD/setup.sh /mnt/xenrt
cp scripts/CD/cleanup.sh /mnt/xenrt

# Make the iso
cd ${pwd}
genisoimage -o xenrtCD.iso -r /mnt/xenrt/
