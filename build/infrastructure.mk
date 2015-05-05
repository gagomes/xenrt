#
# XenRT Infrastructure Makefile
#
include build/tools.mk

BACKUP	= if [ -e $(1) ]; then $(SUDO) cp $(1) $(1).xrt; fi
RESTORE = if [ -e $(1).xrt ]; then $(SUDO) mv $(1).xrt $(1); fi

ifeq ($(PRODUCTIONCONFIG),yes)
DOWINPE ?= yes
DOFILES ?= yes
DOAUTOFS ?= yes
DODHCPD ?= yes
DODHCPD6 ?= yes
DOHOSTS ?= yes
DONETWORK ?= yes
DOCONSERVER ?= yes
DOLOGROTATE ?= yes
DOCRON ?= yes
DOSITECONTROLLERCMD ?= yes
DOLIBVIRT ?= yes
DOGITCONFIG ?= yes
endif
ifeq ($(NISPRODUCTIONCONFIG),yes)
DOWINPE ?= yes
DOFILES ?= yes
DOHOSTS ?= yes
DOCONSERVER ?= yes
DOLOGROTATE ?= yes
DOCRON ?= yes
DOSITECONTROLLERCMD ?= yes
DOAUTOFS ?= yes
DOLIBVIRT ?= yes
DOGITCONFIG ?= yes
endif

INETD_DAEMON ?= openbsd-inetd

serverbase := $(patsubst %/,%,$(WEB_CONTROL_PATH))
serverbase := $(patsubst http://%/share/control,http://%,$(serverbase))
serverbase := $(patsubst http://%/xenrt,http://%,$(serverbase))
serverbase := $(patsubst http://%/control,http://%,$(serverbase))

.PHONY: extrapackages
extrapackages: extrapackages-install
	
.PHONY: apibuild
apibuild:
ifeq ($(APIBUILD), yes)
	rm -rf $(SHAREDIR)/api_build/python/xenrtapi
	rm -rf $(SHAREDIR)/api_build/python/scripts
	mkdir $(SHAREDIR)/api_build/python/xenrtapi
	mkdir $(SHAREDIR)/api_build/python/scripts
	wget -O $(SHAREDIR)/api_build/python/xenrtapi/__init__.py http://localhost:1025/share/control/bindings/__init__.py
	cp $(SHAREDIR)/control/xenrtnew $(SHAREDIR)/api_build/python/scripts/xenrtnew
	cp $(SHAREDIR)/control/xenrt $(SHAREDIR)/api_build/python/scripts/xenrt
	cd $(SHAREDIR)/api_build/python/ && python setup.py sdist
	$(SUDO) ln -sf $(SHAREDIR)/api_build/python/dist/xenrtapi-0.06.tar.gz $(WEBROOT)/xenrtapi.tar.gz
	$(SUDO) pip install -I $(WEBROOT)/xenrtapi.tar.gz
	$(SUDO) pdoc --html --html-dir /var/www --overwrite xenrtapi
	cd $(SHAREDIR)/api_build/python/ && python setup.py sdist upload -r pypi
	

	rm -rf $(SHAREDIR)/api_build/powershell/XenRT
	rm -f $(SHAREDIR)/api_build/powershell/xenrtpowershell.zip
	mkdir -p $(SHAREDIR)/api_build/powershell/XenRT
	cp $(SHAREDIR)/api_build/powershell/XenRT.psd1 $(SHAREDIR)/api_build/powershell/XenRT/XenRT.psd1
	wget -O $(SHAREDIR)/api_build/powershell/XenRT/XenRT.psm1  http://localhost:1025/share/control/bindings/xenrt.psm1
	cd $(SHAREDIR)/api_build/powershell/ && zip -r xenrtpowershell.zip XenRT readme.txt
	$(SUDO) ln -sf $(SHAREDIR)/api_build/powershell/xenrtpowershell.zip $(WEBROOT)/xenrtpowershell.zip
endif

.PHONY: api
api:
	$(eval TMP := $(shell mktemp -d))
	$(SUDOSH) 'cd $(TMP) && pip install -I $(serverbase)/xenrtapi.tar.gz'
	$(SUDO) rm -rf $(TMP)

.PHONY: extrapackages-install
extrapackages-install:
	$(info Installing extra packages not included in preseed file)
	$(SUDO) apt-get update
	$(SUDO) apt-get install -y --force-yes unzip zip ipmitool openipmi snmp-mibs-downloader dsh curl libxml2-utils python-profiler expect patchutils pylint libxml2-dev libpcap-dev libssl-dev telnet python-pygresql openssh-server psmisc less postgresql mercurial sudo make nfs-common rsync gcc python-crypto python-ipy python-simplejson python-paramiko python-fpconst python-soappy python-imaging python-logilab-common python-logilab-astng python-pywbem python-epydoc python-numpy python-tlslite python-libxml2 pylint nfs-kernel-server stunnel ntp dnsmasq vlan tftpd-hpa iscsitarget rpm2cpio module-assistant debhelper genisoimage conserver-client vim screen apt-cacher vsftpd python-matplotlib nmap ucspi-tcp uuid-runtime realpath autofs lsof xfsprogs libnet-ldap-perl python-mysqldb sshpass postgresql postgresql-client build-essential snmp python-lxml python-requests gcc-multilib squashfs-tools fping python-setuptools libapache2-mod-wsgi python-dev cabextract elinks python-pip python-psycopg2 libkrb5-dev python-ldap
	# Squeeze only
	-$(SUDO) apt-get install -y --force-yes iscsitarget-source
	# Wheezy only
	-$(SUDO) apt-get install -y --force-yes libc6-i386 xcp-xe
	-$(SUDO) apt-get install -y --force-yes samba cifs-utils
	-$(SUDO) apt-get install -y --force-yes git
	-$(SUDO) apt-get install -y --force-yes git-core
	-$(SUDO) apt-get install -y --force-yes default-jre-headless

	$(SUDO) easy_install --upgrade requests_oauthlib
	$(SUDO) easy_install --upgrade pyramid
	$(SUDO) easy_install --upgrade pyramid_chameleon
	$(SUDO) easy_install --upgrade pyramid_mako
	$(SUDO) easy_install --upgrade flup
	$(SUDO) easy_install paramiko==1.15.2
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
	$(SUDO) easy_install --upgrade pip
	$(SUDO) easy_install --upgrade pdoc
	$(SUDO) easy_install --upgrade uwsgitop

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

.PHONY: sudoers
sudoers:
ifeq ($(PUPPETNODE),yes)
	$(info Skipping sudo config)
else
	$(info Enabling password-less sudo...)
	$(call BACKUP,$(SUDOERS))
	$(SUDO) sed -i '/nagios/d' $(SUDOERS)
	$(SUDOSH) 'echo "nagios ALL=NOPASSWD: ALL" >> $(SUDOERS)'
	$(SUDO) sed -i 's/ALL=(ALL)/ALL=NOPASSWD:/' $(SUDOERS)
	$(SUDO) sed -i 's/ALL=(ALL:ALL)/ALL=NOPASSWD:/' $(SUDOERS)
endif

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

.PHONY: autofs
autofs:
	$(info Setting up autofs)
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


.PHONY: dhcpd6
dhcpd6: files
ifeq ($(DODHCPD6),yes)
	$(info Installing IPv6 DHCPD...)
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

.PHONY: httpd
httpd:
	$(info apache is now configured with puppet)

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

.PHONY: conserver
conserver: files
ifeq ($(DOCONSERVER),yes)
	$(SUDO) mv $(ROOT)/$(XENRT)/conserver.cf /etc/conserver/conserver.cf
	$(SUDO) /etc/init.d/conserver-server start || $(SUDO) /etc/init.d/conserver-server reload
endif

.PHONY: loop
loop:
	$(info Setting up Loop devices)
	$(SUDO) cp $(ROOT)/$(XENRT)/infrastructure/loop/local-loop /etc/modprobe.d/
	-$(SUDO) rmmod -f loop
	-$(SUDO) modprobe loop max_loop=256
	$(SUDO) sed -i 's/^exit 0/rmmod -f loop\nmodprobe loop max_loop=256/' /etc/rc.local

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

.PHONY: infrastructure
infrastructure: api winpe files autofs dhcpd dhcpd6 hosts network conserver logrotate cron sitecontrollercmd nfs tftp iscsi sudoers extrapackages loop $(SHAREDIR)/images/vms/etch-4.1.img symlinks samba libvirt
	$(info XenRT infrastructure installed.)


.PHONY: marvin
marvin:
	$(info Installing marvin)
	wget -O $(SHAREDIR)/marvin-3.x.tar.gz http://repo-ccp.citrix.com/releases/Marvin/3.0.x/Marvin-66.tar.gz
	wget -O $(SHAREDIR)/marvin.tar.gz http://repo-ccp.citrix.com/releases/Marvin/4.3-forward/Marvin-master-asfrepo-current.tar.gz
	wget -O $(SHAREDIR)/marvin-4.4.tar.gz http://repo-ccp.citrix.com/releases/Marvin/4.4-forward/Marvin-master-asfrepo-current.tar.gz
	wget -O $(SHAREDIR)/marvin-master.tar.gz http://repo-ccp.citrix.com/releases/Marvin/master/Marvin-master-asfrepo-current.tar.gz

.PHONY: puppetrun
puppetrun:
	$(SUDO) puppet agent -t

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
