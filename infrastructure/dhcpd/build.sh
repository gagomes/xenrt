#!/bin/bash
set -e
set -x
RELEASE=`lsb_release -a 2>/dev/null | grep Codename | awk '{print $2}'`
pushd ${0%/*}
if [ $RELEASE == "wheezy" ]; then
	if [ ! -f isc-dhcp-server_*`dpkg --print-architecture`.deb ]; then
		rm -rf isc-dhcp*
		sudo apt-get install -y quilt autoconf fakeroot devscripts
		apt-get source isc-dhcp-server
		pushd isc-dhcp*
		quilt new ignore-client-uids.patch
		quilt pop
		cp ../ignore-client-uids.patch.wheezy debian/patches/ignore-client-uids.patch
		quilt push
		dch -i "Add option for ignore-client-uids"
		fakeroot debian/rules clean
		fakeroot debian/rules binary
		popd
	fi
	sudo dpkg -i  isc-dhcp-server_*.deb isc-dhcp-common_*.deb isc-dhcp-client_*.deb
fi
popd
