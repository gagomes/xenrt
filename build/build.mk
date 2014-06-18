#
# XenRT Setup
#

include build/config.mk
include build/tools.mk

include build/scripts.mk
include build/infrastructure.mk
include build/tests.mk
include build/iso.mk
include build/linuxiso.mk
include build/disklessdebian.mk
include build/debugger.mk
include build/utils.mk

.PHONY: fullsetup
fullsetup: setup disklessdebian

.PHONY: setup 
setup: sudoers extrapackages update install server test-tarballs infrastructure
	$(info XenRT setup completed.)

.PHONY: minsetup
minsetup: sudoers extrapackages install test-tarballs infrastructure
	$(info XenRT setup completed.)

.PHONY: newmachines
newmachines: update files dhcpd dhcpd6 hosts conserver
	$(info XenRT new machines setup completed.)

.PHONY: remove
remove: uninstall clean infrastructure-uninstall
	$(info Removed XenRT from this host.)

.PHONY: purge
purge: remove isos-clean tests-clean
	$(info Purged XenRT from this host.)
