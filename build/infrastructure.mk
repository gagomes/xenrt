#
# XenRT Infrastructure Makefile
#
include build/tools.mk

BACKUP	= if [ -e $(1) ]; then $(SUDO) cp $(1) $(1).xrt; fi
RESTORE = if [ -e $(1).xrt ]; then $(SUDO) mv $(1).xrt $(1); fi

ifeq ($(PRODUCTIONCONFIG),yes)
DOWINPE ?= yes
DOFILES ?= yes
DODHCPD ?= yes
DODHCPD6 ?= yes
DOHOSTS ?= yes
DONETWORK ?= yes
DOCONSERVER ?= yes
DOLOGROTATE ?= yes
DOSITECONTROLLERCMD ?= yes
DOGITCONFIG ?= yes
endif
ifeq ($(NISPRODUCTIONCONFIG),yes)
DOWINPE ?= yes
DOFILES ?= yes
DOHOSTS ?= yes
DOCONSERVER ?= yes
DOLOGROTATE ?= yes
DOSITECONTROLLERCMD ?= yes
DOGITCONFIG ?= yes
endif

INETD_DAEMON ?= openbsd-inetd

serverbase := $(patsubst %/,%,$(WEB_CONTROL_PATH))
serverbase := $(patsubst http://%/share/control,http://%,$(serverbase))
serverbase := $(patsubst http://%/xenrt,http://%,$(serverbase))
serverbase := $(patsubst http://%/control,http://%,$(serverbase))

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
	$(SUDO) ln -sf $(SHAREDIR)/api_build/python/dist/xenrtapi-0.09.tar.gz $(WEBROOT)/xenrtapi.tar.gz
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
	-$(SUDO) systemctl daemon-reload
	$(SUDO) mv $(ROOT)/$(XENRT)/xenrtdhcpd.cfg $(SHAREDIR)/xenrtdhcpd/xenrtdhcpd.cfg
	$(SUDO) service xenrtdhcpd restart
	$(SUDO) sed -i '/leases/d' $(INETD)
	$(SUDOSH) 'echo "5556            stream  tcp     nowait          nobody  /usr/bin/python python $(SHAREDIR)/xenrtdhcpd/leases.py" >> $(INETD)'
	$(SUDO) service $(INETD_DAEMON) restart
else
	-$(SUDO) insserv -r xenrtdhcpd
	-$(SUDO) systemctl daemon-reload
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
	$(SUDO) service isc-dhcp-server restart
	$(SUDO) sed -i '/leases/d' $(INETD)
	$(SUDOSH) 'echo "5556            stream  tcp     nowait          nobody  /bin/cat cat /var/lib/dhcp/dhcpd.leases" >> $(INETD)'
	$(SUDO) service $(INETD_DAEMON) restart
endif
else
	$(info Skipping DHCP config)
endif


.PHONY: dhcpd6
dhcpd6: files
ifeq ($(DODHCPD6),yes)
	$(info Installing IPv6 DHCPD...)
	-$(SUDO) mv $(ROOT)/$(XENRT)/dibbler-server.conf $(DHCPD6)
	-$(SUDO) service dibbler-server stop 
	-$(SUDO) service dibbler-server start 
else
	$(info Skipping DHCP6 config)
endif

.PHONY: hosts
hosts: files
ifeq ($(DOHOSTS),yes)
	$(info Installing $(HOSTS)...)
	$(call BACKUP,$(HOSTS))
	$(SUDO) mv $(ROOT)/$(XENRT)/hosts $(HOSTS)
	$(SUDO) service dnsmasq restart
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

.PHONY: conserver
conserver: files
ifeq ($(DOCONSERVER),yes)
	$(SUDO) mv $(ROOT)/$(XENRT)/conserver.cf /etc/conserver/conserver.cf
	$(SUDO) service conserver-server reload || $(SUDO) service conserver-server restart || $(SUDO) service conserver-server start
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
infrastructure: puppetrun api winpe machines files dhcpd dhcpd6 hosts network conserver logrotate sitecontrollercmd
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
ifeq ($(PUPPETNODE),yes)
	$(SUDO) puppet agent --onetime --verbose --ignorecache --no-daemonize --no-usecacheonfailure --no-splay --show_diff
else
	make ${PUPPETREPO}
	$(SUDO) puppet apply -e 'class {"xenrt_controller::xenrt_dev": user => "${USERNAME}", group => "${GROUPNAME}"}' --modulepath ${ROOT}/${PUPPETREPO}/modules --verbose --show_diff
endif

.PHONY: puppetinstall-%
puppetinstall-%:
	$(info Installing puppet agent)
	wget -O puppet-release.deb https://apt.puppetlabs.com/puppetlabs-release-$(patsubst puppetinstall-%,%,$@).deb
	$(SUDO) dpkg -i puppet-release.deb
	rm puppet-release.deb
	$(SUDO) apt-get update
	$(SUDO) apt-get install -y puppet
ifeq ($(PUPPETNODE),yes)
	$(SUDO) cp $(ROOT)/$(INTERNAL)/config/puppet/puppet.conf /etc/puppet
	$(SUDO) sed -i 's/xenrt.xs.citrite.net/xenrt.citrite.net/' /etc/resolv.conf
endif

.PHONY: puppetinstall
puppetinstall:
	make puppetinstall-`grep -Iroh -e wheezy -e squeeze -e precise -e lucid -e trusty -e jessie /etc/apt 2>/dev/null | head -1`
