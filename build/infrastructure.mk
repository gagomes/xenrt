#
# XenRT Infrastructure Makefile
#
include build/config.mk
include build/tools.mk

BACKUP	= if [ -e $(1) ]; then $(SUDO) cp $(1) $(1).xrt; fi
RESTORE = if [ -e $(1).xrt ]; then $(SUDO) mv $(1).xrt $(1); fi

ifeq ($(PRODUCTIONCONFIG),yes)
DOSSH ?= yes
DOWINPE ?= yes
DOFILES ?= yes
DOPROMPT ?= yes
DOAUTOFS ?= yes
DODHCPD ?= yes
DODHCPD6 ?= yes
DOHOSTS ?= yes
DONETWORK ?= yes
DONAGIOS ?= yes
DOCONSERVER ?= yes
DOLOGROTATE ?= yes
DOCRON ?= yes
DOSITECONTROLLERCMD ?= yes
DOLIBVIRT ?= yes
DOGITCONFIG ?= yes
endif
ifeq ($(NISPRODUCTIONCONFIG),yes)
DOSSH ?= yes
DOWINPE ?= yes
DOFILES ?= yes
DOHOSTS ?= yes
DONAGIOS ?= yes
DOCONSERVER ?= yes
DOLOGROTATE ?= yes
DOCRON ?= yes
DOSITECONTROLLERCMD ?= yes
DOAUTOFSNIS ?= yes
DOLIBVIRT ?= yes
DOGITCONFIG ?= yes
endif
ifeq ($(SSHCONFIG),yes)
DOSSH ?= yes
endif

INETD_DAEMON ?= openbsd-inetd

.PHONY: aptcacher
aptcacher:
	$(info Configuring apt-cacher...)
	$(SUDO) ln -sfT $(TEST_INPUTS)/apt-cache /local/apt-cache
	$(SUDO) cp $(ROOT)/$(XENRT)/infrastructure/apt-cacher/apt-cacher.conf $(APTCACHER)
	$(SUDO) sed -i 's/group=xenrtd/group=$(GROUPNAME)/' $(APTCACHER)
	$(SUDO) sed -i 's/user=xenrtd/user=$(USERNAME)/' $(APTCACHER)
	$(SUDO) ln -sfT /usr/share/apt-cacher $(WEBROOT)/apt
	$(SUDO) mkdir -p /var/log/apt-cacher 
	$(SUDO) chown -R $(USERID):$(GROUPID) /var/log/apt-cacher
	-$(SUDO) ln -s apt-cacher.pl $(WEBROOT)/apt/apt-cacher-cgi.pl
ifeq ($(APT_CACHER_ONLINE),yes)
	$(SUDO) sed -i 's/offline_mode=1/offline_mode=0/' $(APTCACHER)
endif

.PHONY: extrapackages
extrapackages: extrapackages-install
	

.PHONY: extrapackages-install
extrapackages-install:
	$(info Installing extra packages not included in preseed file)
	$(SUDO) apt-get update
	$(SUDO) apt-get install -y --force-yes unzip zip ipmitool openipmi snmp-mibs-downloader dsh curl libxml2-utils python-profiler expect patchutils pylint libxml2-dev libpcap-dev libssl-dev telnet python-pygresql openssh-server psmisc less postgresql mercurial sudo make nfs-common rsync gcc python-crypto python-ipy python-simplejson python-paramiko python-fpconst python-soappy python-imaging python-logilab-common python-logilab-astng python-pywbem python-epydoc python-numpy python-tlslite python-libxml2 pylint nfs-kernel-server stunnel ntp dnsmasq vlan tftpd-hpa iscsitarget rpm2cpio module-assistant debhelper genisoimage conserver-client vim screen apt-cacher vsftpd python-matplotlib nmap ucspi-tcp uuid-runtime realpath autofs lsof xfsprogs libnet-ldap-perl python-mysqldb sshpass postgresql postgresql-client build-essential snmp python-lxml python-requests gcc-multilib squashfs-tools fping python-setuptools libapache2-mod-wsgi python-dev cabextract elinks python-pip samba cifs-utils python-psycopg2 libkrb5-dev
	# Squeeze only
	-$(SUDO) apt-get install -y --force-yes iscsitarget-source
	# Wheezy only
	-$(SUDO) apt-get install -y --force-yes libc6-i386 xcp-xe

	-$(SUDO) apt-get install -y --force-yes git
	-$(SUDO) apt-get install -y --force-yes git-core
	-$(SUDO) apt-get install -y --force-yes default-jre-headless

	$(SUDO) easy_install --upgrade requests_oauthlib
	$(SUDO) easy_install --upgrade pyramid
	$(SUDO) easy_install --upgrade pyramid_chameleon
	$(SUDO) easy_install --upgrade flup
	$(SUDO) easy_install paramiko==1.12.3
	$(SUDO) easy_install --upgrade uwsgi
	$(SUDO) easy_install --upgrade zope.interface
	$(SUDO) easy_install --upgrade nose
	$(SUDO) easy_install --upgrade mock
	$(SUDO) easy_install --upgrade pep8
	$(SUDO) easy_install --upgrade jenkinsapi
	$(SUDO) easy_install --upgrade virtualenv
	$(SUDO) easy_install --upgrade fs
	$(SUDO) easy_install --upgrade netifaces
	$(SUDO) easy_install --upgrade mysql-connector-python
	$(SUDO) easy_install --upgrade kerberos
	$(SUDO) easy_install --upgrade pywinrm
	$(SUDO) easy_install --upgrade pyyaml
	$(SUDO) easy_install --upgrade jsonschema

	$(SUDO) ln -sf `which genisoimage` /usr/bin/mkisofs
	$(SUDO) apt-get install -y --force-yes python-m2crypto
	$(SUDO) sed -i 's/^URLopener.open_https \=/# Removed as this breaks urllib\n# URLopener.open_https \=/' /usr/share/pyshared/M2Crypto/m2urllib.py

$(SHAREDIR)/images/vms/etch-4.1.img:
	$(info Installing etch image)
	mkdir -p $(SHAREDIR)/images/vms
	-cp $(TEST_INPUTS)/vms/etch-4.1.img.gz $(SHAREDIR)/images/vms
	-gunzip $(SHAREDIR)/images/vms/etch-4.1.img.gz

.PHONY: libvirt
libvirt: extrapackages libvirt-pkg /usr/lib/libvirt-qemu.so.0.1000.0 /usr/local/lib/python2.6/dist-packages/virtinst

libvirt-pkg:
ifeq ($(DOLIBVIRT),yes)
	$(info Installing libvirt after removing old version included in debian package...)
	$(SUDO) apt-get remove -y libvirt0 python-libvirt
	$(SUDO) apt-get install -y --force-yes libgnutls-dev libyajl-dev libdevmapper-dev libcurl4-gnutls-dev python-dev libnl-dev libxml2-dev python-pexpect 
endif

/usr/lib/libvirt-qemu.so.0.1000.0:
ifeq ($(DOLIBVIRT),yes)
	$(eval TMP := $(shell mktemp -d))
	tar xzf $(TEST_INPUTS)/libvirt/libvirt-1.0.0.tar.gz -C $(TMP)
	cd $(TMP)/libvirt-1.0.0;./configure --prefix=/usr --localstatedir=/var --with-esx --with-storage-fs --with-python -q
	cd $(TMP)/libvirt-1.0.0;nice make > /dev/null
	cd $(TMP)/libvirt-1.0.0;$(SUDO) make install > /dev/null
	$(SUDO) rm -rf $(TMP)
endif

/usr/local/lib/python2.6/dist-packages/virtinst:
ifeq ($(DOLIBVIRT),yes)
	$(eval TMP := $(shell mktemp -d))
	tar xzf $(TEST_INPUTS)/libvirt/virtinst-0.600.3.tar.gz -C $(TMP)
	cd $(TMP)/virtinst-0.600.3;$(SUDO) python setup.py install > /dev/null
	$(SUDO) rm -rf $(TMP)
endif

.PHONY: dsh
dsh:
	$(info Configuring DSH...)
	ln -sfT $(ROOT)/$(INTERNAL)/config/dsh $(HOME)/.dsh

.PHONY: ntp
ntp:
ifeq ($(PUPPETNODE),yes)
	$(info Skipping NTP config)
else
	$(info Configuring NTP...)
	$(SUDO) cp $(ROOT)/$(XENRT)/infrastructure/ntp/ntp.conf /etc/ntp.conf
	$(SUDO) sed -i 's/__NTP__/$(NTP_SERVER)/' /etc/ntp.conf
	$(SUDO) /etc/init.d/ntp restart
endif

.PHONY: ssh
ssh:
	$(info Configuring SSH...)
ifeq ($(DOSSH),yes)
	cp $(ROOT)/$(XENRT)/infrastructure/ssh/config $(HOME)/.ssh/config
	$(SUDO) sed -i '/PermitBlacklistedKeys/d' /etc/ssh/sshd_config
	$(SUDOSH) 'echo "PermitBlacklistedKeys yes" >> /etc/ssh/sshd_config'
	$(SUDO) /etc/init.d/ssh reload
	cp $(ROOT)/$(INTERNAL)/config/ssh/* $(HOME)/.ssh/
	chmod 600 $(HOME)/.ssh/id_*
else
	$(info Skipping config)
endif

.PHONY: snmp
snmp:
	$(info Configuring SNMP...)
	if [ -e $(SNMP) ]; then $(SUDO) sed -i 's/^mibs :/# mibs :/' $(SNMP); fi

.PHONY: sudoers
sudoers:
	$(info Enabling password-less sudo...)
	$(call BACKUP,$(SUDOERS))
	$(SUDO) sed -i '/nagios/d' $(SUDOERS)
	$(SUDOSH) 'echo "nagios ALL=NOPASSWD: ALL" >> $(SUDOERS)'
	$(SUDO) sed -i 's/ALL=(ALL)/ALL=NOPASSWD:/' $(SUDOERS)
	$(SUDO) sed -i 's/ALL=(ALL:ALL)/ALL=NOPASSWD:/' $(SUDOERS)

.PHONY: sudoers-uninstall
sudoers-uninstall:
	$(info Restoring original sudo configuration...)
	$(call RESTORE,$(SUDOERS))

.PHONY: winpe
winpe:
ifeq ($(DOWINPE),yes)
	$(info Installing WinPE files...)
	$(eval TMP := $(shell mktemp -d))
	tar -C $(TMP) -xvzf $(SHAREDIR)/tests/native.tgz
	rm -rf $(SCRATCHDIR)/www/native
	mv $(TMP)/native/pe $(SCRATCHDIR)/www/native
	rm -rf $(TMP)
endif

.PHONY: machines
machines:
ifeq ($(DOFILES),yes)
	$(SHAREDIR)/exec/main.py --make-machines
endif

.PHONY: machine-%
machine-%:
ifeq ($(DOFILES),yes)
	$(SHAREDIR)/exec/main.py --make-machine $(patsubst machine-%,%,$@)
endif

.PHONY: files
files:
ifeq ($(DOFILES),yes)
	$(info Creating infrastructure configuration files...)
	$(SHAREDIR)/exec/main.py --make-configs --debian
endif

.PHONY: prompt 
prompt:
ifeq ($(DOPROMPT),yes)
	$(info Setting bash prompt...)
	sed -i '/$(SITE)/d' $(HOME)/.bashrc
	echo PS1=\"$(SITE):\$$PS1\" >> $(HOME)/.bashrc
endif

.PHONY: autofs
autofs:
	$(info Setting up autofs)
ifeq ($(DOAUTOFSNIS),yes)
	$(SUDOSH) 'echo "# auto.master generated by XenRT" > $(AUTOMASTER)'
	$(SUDOSH) 'echo "/misc2 /etc/auto.misc" >> $(AUTOMASTER)'
	$(SUDOSH) 'echo "+auto.master" >> $(AUTOMASTER)'
	$(SUDOSH) 'echo "# auto.misc generated by XenRT" > $(AUTOMISC)'
	$(foreach mnt,$(AUTOFSMOUNTS), $(SUDOSH) 'echo "`echo $(mnt) | cut -d "," -f 1` -soft,intr `echo $(mnt) | cut -d "," -f 2`" >> $(AUTOMISC)';)
	$(SUDO) /etc/init.d/autofs reload
endif
ifeq ($(DOAUTOFS),yes)
	$(SUDOSH) 'echo "# auto.master generated by XenRT" > $(AUTOMASTER)'
	$(SUDOSH) 'echo "/misc /etc/auto.misc" >> $(AUTOMASTER)'
	$(SUDOSH) 'echo "# auto.misc generated by XenRT" > $(AUTOMISC)'
	$(foreach mnt,$(AUTOFSMOUNTS), $(SUDOSH) 'echo "`echo $(mnt) | cut -d "," -f 1` -soft,intr `echo $(mnt) | cut -d "," -f 2`" >> $(AUTOMISC)';)
	$(SUDO) /etc/init.d/autofs reload
endif

.PHONY: symlinks
symlinks:
	$(info Creating symlinks)
	$(foreach symlink,$(SYMLINKS), $(SUDOSH) 'mkdir -p `dirname \`echo $(symlink) | cut -d "," -f 2\``; ln -sfT `echo $(symlink) | cut -d "," -f 1` `echo $(symlink) | cut -d "," -f 2`';)

.PHONY: nfs
nfs: $(SCRATCHDIR)
	$(info Installing NFS...)
	$(call BACKUP,$(EXPORTS))
	$(SUDOSH) 'echo "$(IMAGEDIR) *(ro,$(NFSCOMMON))" > $(EXPORTS)'
	$(SUDOSH) 'echo "$(SCRATCHDIR) *(rw,$(NFSCOMMON))" >> $(EXPORTS)'
	$(SUDOSH) 'echo "$(XVADIR) *(rw,$(NFSCOMMON))" >> $(EXPORTS)'
	$(SUDOSH) 'echo "/local/tftpboot *(rw,$(NFSCOMMON))" >> $(EXPORTS)'
	$(foreach dir,$(EXTRANFSDIRS), $(SUDOSH) 'echo "$(dir) *(rw,$(NFSCOMMON))" >> $(EXPORTS)';)
	$(SUDO) mkdir -p $(IMAGEDIR)
	$(SUDO) mkdir -p $(XVADIR)
	$(SUDO) chown $(USERID):$(GROUPID) $(IMAGEDIR)
	$(SUDO) /etc/init.d/nfs-kernel-server restart

.PHONY: nfs-uninstall
nfs-uninstall:
	$(info Uninstalling NFS...)
	$(call RESTORE,$(EXPORTS))
	$(SUDO) /etc/init.d/nfs-kernel-server stop 

.PHONY: dhcpdb
dhcpdb: files
	$(SUDO) mv $(ROOT)/$(XENRT)/xenrtdhcpd.cfg $(SHAREDIR)/xenrtdhcpd/xenrtdhcpd.cfg
	$(SUDOSH) 'su postgres -c "psql < $(SHAREDIR)/xenrtdhcpd/dhcp.sql"'
	$(ROOT)/$(XENRT)/xenrtdhcpd/importleases.py /var/lib/dhcp/dhcpd.leases 

.PHONY: dhcpd
dhcpd: install files
ifeq ($(DODHCPD),yes)
ifeq ($(XENRT_DHCPD), yes)
	$(info Removing ISC DHCPD)
	$(SUDO) apt-get remove -y isc-dhcp-server
	$(SUDOSH) 'su postgres -c "psql < $(SHAREDIR)/xenrtdhcpd/dhcp.sql"'
	$(SUDO) cp $(SHAREDIR)/xenrtdhcpd/xenrtdhcpd-init /etc/init.d/xenrtdhcpd
	$(SUDO) insserv xenrtdhcpd
	$(SUDO) mv $(ROOT)/$(XENRT)/xenrtdhcpd.cfg $(SHAREDIR)/xenrtdhcpd/xenrtdhcpd.cfg
	$(SUDO) /etc/init.d/xenrtdhcpd restart
	$(SUDO) sed -i '/leases/d' $(INETD)
	$(SUDOSH) 'echo "5556            stream  tcp     nowait          nobody  /usr/bin/python python $(SHAREDIR)/xenrtdhcpd/leases.py" >> $(INETD)'
	$(SUDO) /etc/init.d/$(INETD_DAEMON) restart
else
	-$(SUDO) insserv -r xenrtdhcpd
	$(SUDO) rm -f /etc/init.d/xenrtdhcpd
ifeq ($(DHCP_UID_WORKAROUND),yes)
	-$(ROOT)/$(XENRT)/infrastructure/dhcpd/build.sh
endif
	$(info Installing DHCPD...)
	$(SUDO) apt-get install -y --force-yes dhcp3-server
	$(call BACKUP,$(DHCPD))
ifeq ($(DHCP_UID_WORKAROUND),yes)
	$(ROOT)/$(XENRT)/infrastructure/dhcpd/build.sh
endif
	$(SUDO) mv $(ROOT)/$(XENRT)/dhcpd.conf $(DHCPD)
	$(SUDO) /etc/init.d/isc-dhcp-server restart
	$(SUDO) sed -i '/leases/d' $(INETD)
	$(SUDOSH) 'echo "5556            stream  tcp     nowait          nobody  /bin/cat cat /var/lib/dhcp/dhcpd.leases" >> $(INETD)'
	$(SUDO) /etc/init.d/$(INETD_DAEMON) restart
endif
else
	$(info Skipping DHCP config)
endif


.PHONY: dhcpd-uninstall
dhcpd-uninstall:
	$(info Uninstalling DHCPD...)
	$(call RESTORE,$(DHCPD))
	$(SUDO) /etc/init.d/isc-dhcp-server stop

.PHONY: dhcpd6
dhcpd6: files
ifeq ($(DODHCPD6),yes)
	$(info Installing IPv6 DHCPD...)
	$(SUDO) tar -xvzkf $(TEST_INPUTS)/dibbler/dibbler-2012-08-06.tar.gz -C /local
	-$(SUDOSH) 'if [ ! -e /local/dibbler-0.8.2-git/Makefile ]; then cd /local/dibbler-0.8.2-git && ./configure; fi'
	$(SUDO) make -C /local/dibbler-0.8.2-git install
	$(SUDO) mkdir -p `dirname $(DHCPD6)`
	$(SUDO) chown -R $(USERID):$(GROUPID) `dirname $(DHCPD6)`
	$(SUDO) mkdir -p /var/lib/dibbler
	$(SUDO) chown -R $(USERID):$(GROUPID) /var/lib/dibbler
	$(SUDO) mkdir -p /var/log/dibbler
	$(SUDO) chown -R $(USERID):$(GROUPID) /var/log/dibbler
	$(SUDO) cp $(ROOT)/$(XENRT)/infrastructure/dibbler/dibbler-server /etc/init.d/
	$(SUDO) cp $(ROOT)/$(XENRT)/infrastructure/dibbler/logrotate /etc/logrotate.d/dibbler
	$(SUDO) update-rc.d dibbler-server defaults
	-$(SUDO) mv $(ROOT)/$(XENRT)/dibbler-server.conf $(DHCPD6)
	-$(SUDO) /etc/init.d/dibbler-server stop 
	-$(SUDO) /etc/init.d/dibbler-server start 
else
	$(info Skipping DHCP6 config)
endif

.PHONY: hosts
hosts: files
ifeq ($(DOHOSTS),yes)
	$(info Installing $(HOSTS)...)
	$(call BACKUP,$(HOSTS))
	$(SUDO) mv $(ROOT)/$(XENRT)/hosts $(HOSTS)
	$(SUDO) mv $(ROOT)/$(XENRT)/dnsmasq.conf /etc/dnsmasq.conf
	$(SUDO) /etc/init.d/dnsmasq restart
endif

.PHONY: hosts-uninstall
hosts-uninstall:
	$(info Uninstalling $(HOSTS)...)
	$(call RESTORE,$(HOSTS))
	-$(SUDO) /etc/init.d/dnsmasq stop

.PHONY: network
network: files
ifeq ($(DONETWORK),yes)
	$(info Installing VLAN interfaces...)
	$(call BACKUP,$(MODULES))
	$(call BACKUP,$(INTERFACES))
	$(SUDO) modprobe 8021q
	$(SUDOSH) 'echo 8021q >> $(MODULES)' 
	$(SUDO) mv $(ROOT)/$(XENRT)/interfaces $(INTERFACES) 
	$(SUDO) ifup -a
else
	$(info Skipping network config)
endif

.PHONY: network-uninstall
network-uninstall:
	$(info Uninstalling VLAN interfaces...)
	-for I in `ip link | egrep -o "eth0.[0-9]+"`; do $(SUDO) ifdown $${I}; done
	-$(SUDO) rmmod 8021q
	$(call RESTORE,$(MODULES))
	$(call RESTORE,$(INTERFACES))

$(TFTPROOT)/ipxe.embedded.0:
	$(info Building undionly.kpxe)
	mkdir -p $(SHAREDIR)/ipxe
	rsync -axl $(TEST_INPUTS)/ipxe/src $(SHAREDIR)/ipxe
	echo "#!ipxe" > $(SHAREDIR)/ipxe/src/ipxe.script
	echo dhcp >> $(SHAREDIR)/ipxe/src/ipxe.script
	echo chain http://`ip addr | grep 'state UP' -A2 | grep inet | head -1 | awk '{print $$2}' | cut -d "/" -f 1`/tftp/default-ipxe.cgi >> $(SHAREDIR)/ipxe/src/ipxe.script
	make -C $(SHAREDIR)/ipxe/src bin/undionly.kpxe EMBED=ipxe.script
	$(SUDO) cp $(SHAREDIR)/ipxe/src/bin/undionly.kpxe $@

.PHONY: tftp
tftp:
	$(info Installing TFTP...)
	$(call BACKUP,$(INETD))
	$(SUDO) mkdir -p /local/tftpboot
	$(SUDO) ln -sfT /local/tftpboot $(TFTPROOT)
	$(SUDO) mkdir -p $(TFTPROOT)/pxelinux.cfg
	$(SUDO) sed -i 's#/srv/tftp#$(TFTPROOT)#g' /etc/default/tftpd-hpa
	$(SUDO) /etc/init.d/tftpd-hpa restart
	$(SUDO) cp $(ROOT)/$(XENRT)/infrastructure/pxe/syslinux/pxelinux.0 $(TFTPROOT)
	$(SUDO) cp $(ROOT)/$(XENRT)/infrastructure/pxe/syslinux/menu.c32 $(TFTPROOT)
	$(SUDO) cp $(ROOT)/$(XENRT)/infrastructure/pxe/syslinux/mboot.c32 $(TFTPROOT)
	$(SUDO) cp $(ROOT)/$(XENRT)/infrastructure/pxe/syslinux/chain.c32 $(TFTPROOT)
	$(SUDO) cp $(ROOT)/$(XENRT)/infrastructure/pxe/syslinux/memdisk $(TFTPROOT)
	$(SUDO) cp $(ROOT)/$(XENRT)/infrastructure/pxe/banner $(TFTPROOT)
	$(SUDO) cp $(ROOT)/$(XENRT)/infrastructure/pxe/default $(TFTPROOT)/pxelinux.cfg
	$(SUDO) cp $(ROOT)/$(XENRT)/infrastructure/pxe/razor.ipxe $(TFTPROOT)
	$(SUDO) cp $(ROOT)/$(XENRT)/infrastructure/pxe/default-ipxe.cgi $(TFTPROOT)
	$(SUDO) sed -i 's/__RAZOR_SERVER__/$(RAZOR_SERVER)/' $(TFTPROOT)/razor.ipxe
	-$(SUDO) cp $(TEST_INPUTS)/ipxe/undionly.kpxe $(TFTPROOT)
	-$(SUDO) ln -sf undionly.kpxe $(TFTPROOT)/ipxe.0
	-$(SUDO) cp -R $(TEST_INPUTS)/clean $(TFTPROOT)
	$(SUDO) mkdir -p $(TFTPROOT)/tinycorelinux
	$(SUDO) mkdir -p $(TFTPROOT)/ipxe.cfg
	-$(SUDO) cp $(TEST_INPUTS)/tinycorelinux/output/vmlinuz $(TFTPROOT)/tinycorelinux/
	-$(SUDO) cp $(TEST_INPUTS)/tinycorelinux/output/core-xenrt.gz $(TFTPROOT)/tinycorelinux/
	-$(SUDO) wget -O $(TFTPROOT)/grubx64.efi $(UEFI_GRUB_SOURCE)
ifdef WINDOWS_ISOS
	$(SUDO) ln -sfT $(WINDOWS_ISOS)/winpe $(TFTPROOT)/winpe
endif
	$(SUDO) chown -R $(USERID):$(GROUPID) $(TFTPROOT)
	-make $(TFTPROOT)/ipxe.embedded.0

.PHONY: tftp-uninstall
tftp-uninstall:
	$(info Uninstalling TFTP...)
	$(call RESTORE,$(INETD))
	-$(SUDO) /etc/init.d/$(INETD_DAEMON) stop

.PHONY: httpd
httpd:
	$(info Installing web server...)
	$(SUDO) apt-get -y remove lighttpd
	$(SUDO) apt-get -y autoremove
	$(SUDO) apt-get -y install apache2
	$(SUDO) sed -i "s/APACHE_RUN_GROUP=.*/APACHE_RUN_GROUP=$(GROUPNAME)/" /etc/apache2/envvars
	$(SUDO) sed -i "s/APACHE_RUN_USER=.*/APACHE_RUN_USER=$(USERNAME)/" /etc/apache2/envvars
	$(SUDO) mkdir -p $(SCRATCHDIR)/www
	$(SUDO) ln -sfT $(SCRATCHDIR)/www $(WEBROOT)/export
	$(SUDO) ln -sfT $(TFTPROOT) $(WEBROOT)/tftp
	$(SUDO) ln -sfT $(SHAREDIR) $(WEBROOT)/share
	$(SUDO) ln -sfT $(SHAREDIR)/control $(WEBROOT)/control
	$(SUDO) ln -sfT $(SHAREDIR)/provision $(WEBROOT)/provision
	$(SUDO) cp $(ROOT)/$(XENRT)/infrastructure/apache2/unauth.html $(WEBROOT)/unauth.html
	$(SUDO) chown -R $(USERID):$(GROUPID) $(SCRATCHDIR)/www
	$(SUDO) mkdir -p /var/log/apache2 
	$(SUDO) chown -R $(USERID):$(GROUPID) /var/log/apache2
	$(SUDO) mkdir -p /var/lock/apache2 
	$(SUDO) chown -R $(USERID):$(GROUPID) /var/lock/apache2
	$(SUDO) mkdir -p /var/cache/apache2 
	$(SUDO) chown -R $(USERID):$(GROUPID) /var/cache/apache2 
ifeq ($(KERBEROS),yes)
	$(SUDO) cp $(ROOT)/$(XENRT)/infrastructure/apache2/default-kerberos /etc/apache2/sites-available/default
	$(SUDO) sed -i "s/@@KERBEROSREALM@@/$(KERBEROSREALM)/" /etc/apache2/sites-available/default
	$(SUDO) apt-get install -y --force-yes libapache2-mod-auth-kerb krb5-user
	$(SUDO) ln -sfT `realpath $(ROOT)/$(INTERNAL)/config/$(SITE)/keytab` $(CONFDIR)/keytab
	$(SUDO) a2enmod auth_kerb
	$(SUDO) a2enmod headers
	$(SUDO) cp $(ROOT)/$(INTERNAL)/config/$(SITE)/krb5.conf /etc/krb5.conf
else
	$(SUDO) cp $(ROOT)/$(XENRT)/infrastructure/apache2/default /etc/apache2/sites-available
endif
	$(SUDO) sed -i "s/@@USER@@/$(USERNAME)/" /etc/apache2/sites-available/default
	$(SUDO) sed -i "s/@@GROUP@@/$(GROUPNAME)/" /etc/apache2/sites-available/default
	$(SUDO) sed -i 's#@@SHAREDIR@@#$(SHAREDIR)#g' /etc/apache2/sites-available/default
ifeq ($(PROXY_JENKINS_8080),yes)
	$(SUDO) cp $(ROOT)/$(XENRT)/infrastructure/apache2/jenkins-proxy /etc/apache2/sites-available
	$(SUDO) sed -i 's#@@PROXY_JENKINS_URL@@#$(PROXY_JENKINS_URL)#' /etc/apache2/sites-available/jenkins-proxy
	$(SUDO) ln -sf /etc/apache2/sites-available/jenkins-proxy /etc/apache2/sites-enabled/001-jenkins
endif
	$(SUDO) a2enmod cgi
	$(SUDO) a2enmod alias
	$(SUDO) a2enmod rewrite
	$(SUDO) a2enmod wsgi
	$(SUDO) a2enmod proxy
	$(SUDO) a2enmod proxy_http
	$(SUDO) a2enmod deflate
	-$(SUDO) /etc/init.d/apache2 start
	$(SUDO) /etc/init.d/apache2 restart

.PHONY: samba
samba:
	$(SUDO) cp $(ROOT)/$(XENRT)/infrastructure/samba/smb.conf /etc/samba/smb.conf
	$(SUDO) sed -i s/xenrtd/$(USERNAME)/ /etc/samba/smb.conf
	$(SUDO) /etc/init.d/samba restart

.PHONY: iscsi
iscsi:
ifeq ($(BUILDISCSI),no)
	$(info Skipping iSCSI target setup)
else
	$(info Installing ISCSI target...)
	$(SUDO) apt-get install -y --force-yes linux-headers-`uname -r`
	$(SUDO) apt-get install -y --force-yes iscsitarget iscsitarget-dkms	
	$(SUDO) sed -i "s/false/true/" $(ISCSI)
	$(SUDO) /etc/init.d/iscsitarget restart
endif

.PHONY: iscsi-uninstall
iscsi-uninstall:
	$(info Uninstalling ISCSI target...)
	$(call RESTORE,$(ISCSI))
	-$(SUDO) /etc/init.d/iscsitarget stop

.PHONY: conserver
conserver: files
ifeq ($(DOCONSERVER),yes)
	$(call BACKUP,$(CONSERVER))
	$(SUDO) mv $(ROOT)/$(XENRT)/console.cf $(CONSERVER)
	$(SUDO) apt-get install -y --force-yes conserver-server
	$(SUDO) mv $(ROOT)/$(XENRT)/conserver.cf /etc/conserver/conserver.cf
	$(SUDO) cp $(ROOT)/$(XENRT)/infrastructure/conserver/* /etc/conserver/
	$(SUDO) mkdir -p /local/consoles
	$(SUDO) chmod -R a+rw /local/consoles
	$(SUDO) /etc/init.d/conserver-server start || $(SUDO) /etc/init.d/conserver-server reload
	$(SUDO) mkdir -p /var/lib/cons
	grep "^cons:" /etc/group || $(SUDO) groupadd cons
	grep "^cons:" /etc/passwd || $(SUDO) useradd cons -g cons -d /var/lib/cons
	$(SUDO) mkdir -p /var/lib/cons/.ssh
	$(SUDO) cp $(ROOT)/$(XENRT)/infrastructure/conserver/cons /usr/local/bin
	$(SUDOSH) 'echo -n "command=\"/usr/local/bin/cons\",no-port-forwarding,no-X11-forwarding,no-agent-forwarding " > /var/lib/cons/.ssh/authorized_keys'
	$(SUDOSH) 'cat $(ROOT)/$(INTERNAL)/keys/ssh/id_rsa_cons.pub >> /var/lib/cons/.ssh/authorized_keys'
	$(SUDO) chown -R cons:cons /var/lib/cons/.ssh
	$(SUDOSH) 'chmod 600 /var/lib/cons/.ssh/*'
endif

.PHONY: conserver-uninstall
conserver-uninstall:
	$(info Uninstalling conserver...)
	$(call RESTORE,$(CONSERVER))

.PHONY: ftp
ftp:
	$(info Setting up vsftpd)
	$(call BACKUP,$(VSFTPD))
	$(SUDO) cp $(ROOT)/$(XENRT)/infrastructure/vsftpd/vsftpd.conf $(VSFTPD)
	$(SUDO) /etc/init.d/vsftpd restart 

.PHONY: ftp-uninstall
ftp-uninstall:
	$(info Uninstalling vsftpd...)
	$(call RESTORE,$(VSFTPD))

.PHONY: loop
loop:
	$(info Setting up Loop devices)
	$(SUDO) cp $(ROOT)/$(XENRT)/infrastructure/loop/local-loop /etc/modprobe.d/
	-$(SUDO) rmmod -f loop
	-$(SUDO) modprobe loop max_loop=256
	$(SUDO) sed -i 's/^exit 0/rmmod -f loop\nmodprobe loop max_loop=256/' /etc/rc.local

.PHONY: nagios
nagios:
ifeq ($(DONAGIOS),yes)
	$(info Setting up nagios)
	$(SUDO) apt-get install -y --force-yes nagios-nrpe-server nagios-plugins
	$(SUDO) sed -i 's/^allowed_hosts/#allowed_hosts/g' $(NRPE)
	$(SUDO) sed -i 's/dont_blame_nrpe=0/dont_blame_nrpe=1/g' $(NRPE)
	$(SUDO) cp $(ROOT)/$(XENRT)/infrastructure/nagios/xenrt.cfg $(NRPECONFDIR)
	$(SUDO) cp $(ROOT)/$(XENRT)/infrastructure/nagios/check_* /usr/lib/nagios/plugins/
ifeq ($(PUPPETNODE),yes)
	$(SUDO) sed -i '/command[check_disk]/d' $(NRPECONFDIR)/xenrt.cfg
else
	$(SUDO) sed -i '/nrpe_user=/d' $(NRPE)
	$(SUDO) sed -i '/nrpe_group=/d' $(NRPE)
	$(SUDOSH) "echo 'nrpe_user=$(USERNAME)' >> $(NRPECONFDIR)/xenrt.cfg"
	$(SUDOSH) "echo 'nrpe_group=$(GROUPNAME)' >> $(NRPECONFDIR)/xenrt.cfg"
endif
	$(SUDO) /etc/init.d/nagios-nrpe-server restart 
endif

.PHONY: logrotate
logrotate:
ifeq ($(DOLOGROTATE),yes)
	$(info Setting logrotate to daily for syslog)
	$(SUDO) sed -i 's/weekly/daily/g' /etc/logrotate.d/rsyslog
	$(SUDO) sed -i '/delaycompress/d' /etc/logrotate.d/rsyslog
	$(SUDO) sed -i 's/weekly/daily/g' /etc/logrotate.d/apache2
	$(SUDO) sed -i '/delaycompress/d' /etc/logrotate.d/apache2
	$(SUDO) sed -i 's/rotate 52/rotate 7/' /etc/logrotate.d/apache2
endif

.PHONY: nagios-uninstall
nagios-uninstall:
	$(info Uninstalling vsftpd...)
	$(SUDO) rm $(NRPECONFDIR)/xenrt.cfg

.PHONY: cron
cron:
ifeq ($(DOCRON),yes)
	$(info Setting up crontab)
	cp $(ROOT)/$(XENRT)/infrastructure/cron/xenrt.cron.in $(ROOT)/$(XENRT)/infrastructure/cron/xenrt.cron
	sed -i 's#@@BINDIR@@#$(BINDIR)#g' $(ROOT)/$(XENRT)/infrastructure/cron/xenrt.cron
	sed -i 's#@@SHAREDIR@@#$(SHAREDIR)#g' $(ROOT)/$(XENRT)/infrastructure/cron/xenrt.cron
	sed -i 's#@@CONFDIR@@#$(CONFDIR)#g' $(ROOT)/$(XENRT)/infrastructure/cron/xenrt.cron
	crontab $(ROOT)/$(XENRT)/infrastructure/cron/xenrt.cron
endif

.PHONY: gitconfig
gitconfig:
ifeq ($(DOGITCONFIG),yes)
	$(info Setting up git config)
	$(GIT) config --global user.email '$(GITEMAIL)'
	$(GIT) config --global user.name '$(GITUSER)'
endif

.PHONY: sitecontrolllercmd
sitecontrollercmd:
ifeq ($(DOSITECONTROLLERCMD),yes)
	$(info Setting up site controller command)
	cp $(ROOT)/$(XENRT)/infrastructure/bin/xenrtsitecontroller.in $(ROOT)/$(XENRT)/infrastructure/bin/xenrtsitecontroller
	sed -i 's#@@BINDIR@@#$(BINDIR)#g' $(ROOT)/$(XENRT)/infrastructure/bin/xenrtsitecontroller
	sed -i 's#@@SHAREDIR@@#$(SHAREDIR)#g' $(ROOT)/$(XENRT)/infrastructure/bin/xenrtsitecontroller
	sed -i 's#@@CONFDIR@@#$(CONFDIR)#g' $(ROOT)/$(XENRT)/infrastructure/bin/xenrtsitecontroller
	$(SUDO) cp $(ROOT)/$(XENRT)/infrastructure/bin/xenrtsitecontroller $(BINDIR)/xenrtsitecontroller
	$(SUDO) chmod a+x $(BINDIR)/xenrtsitecontroller
endif

.PHONY: cron-uninstall
cron-uninstall:
	$(info Uninstalling crontab...)
	$(SUDO) crontab -r

.PHONY: infrastructure
infrastructure: ssh httpd winpe files prompt autofs dhcpd dhcpd6 hosts network nagios conserver logrotate cron sitecontrollercmd nfs tftp httpd iscsi sudoers aptcacher ftp snmp extrapackages loop dsh ntp $(SHAREDIR)/images/vms/etch-4.1.img symlinks samba libvirt
	$(info XenRT infrastructure installed.)


.PHONY: infrastructure-uninstall
infrastructure-uninstall: network-uninstall \
			  nfs-uninstall \
			  dhcpd-uninstall \
			  hosts-uninstall \
			  tftp-uninstall \
			  httpd-uninstall \
			  iscsi-uninstall \
			  conserver-uninstall \
			  sudoers-uninstall \
			  ftp-uninstall \
			  nagios-uninstall \
			  cron-uninstall
	$(info XenRT Infrastructure uninstalled.)			

.PHONY: marvin
marvin:
	$(info Installing marvin)
	wget -O $(SHAREDIR)/marvin-3.x.tar.gz http://repo-ccp.citrix.com/releases/Marvin/3.0.x/Marvin-66.tar.gz
	wget -O $(SHAREDIR)/marvin.tar.gz http://repo-ccp.citrix.com/releases/Marvin/4.3-forward/Marvin-master-asfrepo-current.tar.gz
	wget -O $(SHAREDIR)/marvin-4.4.tar.gz http://repo-ccp.citrix.com/releases/Marvin/4.4-forward/Marvin-master-asfrepo-current.tar.gz
	wget -O $(SHAREDIR)/marvin-master.tar.gz http://repo-ccp.citrix.com/releases/Marvin/master/Marvin-master-asfrepo-current.tar.gz

.PHONY: puppet-%
puppet-%:
ifeq ($(PUPPETNODE),yes)
	$(info Installing puppet agent)
	wget -O puppet-release.deb https://apt.puppetlabs.com/puppetlabs-release-$(patsubst puppet-%,%,$@).deb
	$(SUDO) dpkg -i puppet-release.deb
	$(SUDO) apt-get update
	$(SUDO) apt-get install -y puppet
	$(SUDO) cp $(ROOT)/$(INTERNAL)/config/puppet/puppet.conf /etc/puppet
	$(SUDO) sed -i 's/xenrt.xs.citrite.net/xenrt.citrite.net/' /etc/resolv.conf
else
	$(info This node must be set as a PUPPETNODE in the config.mk file)
endif
