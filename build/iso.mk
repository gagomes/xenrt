#
# XenRT ISO Makefile
#
include build/tools.mk

ISOS	= $(shell cat $(ROOT)/$(INTERNAL)/keys/windows | awk '{ print "$(IMAGEDIR)/"$$1".iso" }')
MKISO	= CONFDIR=$(ROOT)/$(INTERNAL) $(ROOT)/$(XENRT)/images/buildiso

isos:$(IMAGEDIR)
	$(info Building Windows ISOs...)
	$(foreach iso,$(ISOS), $(MAKE) $(iso);)

.PHONY: isos-clean
isos-clean:
	$(info Removing Windows ISOs...)
	$(SUDO) $(RMTREE) $(IMAGEDIR)

$(IMAGEDIR):
	$(info Creating windows ISO output directory... \($@\))
	$(SUDO) mkdir -p $(IMAGEDIR)
	$(SUDO) chown $(USERID):$(GROUPID) $(IMAGEDIR)

.PRECIOUS: $(ISODIR)/%.iso
$(IMAGEDIR)/%.iso:
	$(info Building $@...)
	cp -v $(TEST_INPUTS)/activepython/* $(ROOT)/$(XENRT)/images/windows/iso/common/\$$1/install/python/
	[ -e /usr/bin/mkisofs ] || $(SUDO) ln -s `which genisoimage` /usr/bin/mkisofs
	$(SUDO) $(MKISO) $(WINDOWS_ISOS_INPUTS)/$(notdir $@) \
			 $(call STRIP,$@) \
			 $@ NOSFU=ALL

.PHONY: $(WEBROOT)/wininstall/netinstall/%
$(WEBROOT)/wininstall/netinstall/%:
	$(info Building $@...)
	$(SUDO) $(ROOT)/$(XENRT)/scripts/buildwinnetinstall.sh $@
	$(SUDO) mkdir $@/winpe
	$(SUDO) cp $(ROOT)/$(XENRT)/infrastructure/wimboot/boot.ipxe $@/winpe/
	$(SUDO) cp $(ROOT)/$(XENRT)/infrastructure/wimboot/diskpart.txt $@/
	$(SUDO) cp $(TEST_INPUTS)/wimboot-1.0.5/wimboot $@/winpe
	$(SUDO) chown -R $(USERID):$(GROUPID) $@
