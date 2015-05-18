#
# XenRT Setup
#

include build/config.mk
-include $(CONFDIR)/conf.d/*/*.mk
include build/tools.mk

include build/scripts.mk
include build/infrastructure.mk
include build/tests.mk
include build/iso.mk
include build/linuxiso.mk
include build/debugger.mk
include build/utils.mk

.PHONY: fullsetup
fullsetup: setup

.PHONY: setup 
setup: update install server test-tarballs infrastructure
	$(info XenRT setup completed.)

.PHONY: minsetup
minsetup: sudoers extrapackages install test-tarballs infrastructure
	$(info XenRT setup completed.)

.PHONY: newmachines
newmachines: update machines files dhcpd dhcpd6 hosts conserver
	$(info XenRT new machines setup completed.)

.PHONY: newmachine-%
newmachine-%:
	make update machine-$(patsubst newmachine-%,%,$@) files dhcpd dhcpd6 hosts conserver
	$(info XenRT new machine setup completed.)
