#!/bin/csh

set PKG_PATH=/dev/fs/C/install/SFU/dist
set KEY_PATH=/dev/fs/C/install/SFU/keys
set LOG_FILE=/dev/fs/C/sshsetup.log

echo "Starting setup.csh..." >> ${LOG_FILE}

echo "Installing package tools..." >> ${LOG_FILE}

# Install the package management tool.
sh ${PKG_PATH}/pkg-current-bin35.sh || true
rehash

if ( -e /usr/local/bin/pkg_update ) then
	echo "File pkg_update exists!" >> ${LOG_FILE}
endif

echo "Renaming more..." >> ${LOG_FILE}

# If we remove /bin/more then we get rid of those pesky DISPLAY files. 
mv /bin/more /bin/more.bak

echo "Installing OpenSSH..." >> ${LOG_FILE}

# Install OpenSSH.
pkg_add -Q ${PKG_PATH}/openssh-current-bin.tgz >>& ${LOG_FILE}

# Disable DNS for sshd.
cat /etc/init.d/sshd | sed -e 's#/usr/local/sbin/sshd#/usr/local/sbin/sshd -o UseDNS=no#' > /
etc/init.d/sshd.new
mv /etc/init.d/sshd.new /etc/init.d/sshd
chmod ug+x /etc/init.d/sshd
/etc/init.d/sshd stop
/etc/init.d/sshd start

echo "Installing bash..." >> ${LOG_FILE}

# Install BASH shell and make it the default login shell.
pkg_add -Q ${PKG_PATH}/bash-current-bin.tgz >>& ${LOG_FILE}
chsh /usr/local/bin/bash
ln -s /usr/local/bin/bash /bin/bash

echo "Setting up prompt..." >> ${LOG_FILE}

# Set up prompt.
echo "export PS1='\u@\h:\w>'" >> /etc/profile.lcl

echo "Setting up public key authentication..." >> ${LOG_FILE}

# Set up public key authentication.
mkdir /.ssh
cp ${KEY_PATH}/id_dsa_xenrt /.ssh/
cp ${KEY_PATH}/id_dsa_xenrt.pub /.ssh/
cat /.ssh/id_dsa_xenrt.pub >> /.ssh/authorized_keys
chmod -R og-rwx /.ssh

# Install more packages
echo "Installing packages..." >> ${LOG_FILE}
pkg_add -Q ${PKG_PATH}/wget-current-bin.tgz >>& ${LOG_FILE}
pkg_add -Q ${PKG_PATH}/xargs-current-bin.tgz >>& ${LOG_FILE}
pkg_add -Q ${PKG_PATH}/bzip2-current-bin.tgz >>& ${LOG_FILE}
pkg_add -Q ${PKG_PATH}/mktemp-current-bin.tgz >>& ${LOG_FILE}

echo "Restore more..." >> ${LOG_FILE}

# I guess we can have more back now.
mv /bin/more.bak /bin/more
