#
# XenRT ISO Makefile
#
include build/config.mk
include build/tools.mk

LINUX_ISOS_LIST	= $(shell ls $(LINUX_ISOS_INPUTS))
LINUX_ISOS_INPLACE_LIST	= $(shell ls $(LINUX_ISOS))

linuxisos:$(LINUX_ISOS_OUTPUTS)
	$(info Building Linux ISOs...)
	$(foreach iso,$(LINUX_ISOS_LIST), $(MAKE) $(iso).linux;)

linuxisos-inplace:
	$(info Building Linux ISOs in place...)
	$(foreach iso,$(LINUX_ISOS_INPLACE_LIST), $(MAKE) $(iso).linux.inplace;)

$(LINUX_ISOS_OUTPUTS):
	$(info Creating linux ISO output directory... \($@\))
	$(SUDO) mkdir -p $(LINUX_ISOS_OUTPUTS)
	$(SUDO) chown $(USERID):$(GROUPID) $(IMAGEDIR)

.PHONY: %.iso
%.iso.linux:
	$(info Building $@...)
	images/linux/buildiso.py $(LINUX_ISOS_INPUTS)/$(patsubst %.linux,%,$@) $(LINUX_ISOS_OUTPUTS)/$(patsubst %.linux,%,$@)

.PHONY: %.iso.inplace
%.iso.linux.inplace:
	$(info Building $@...)
	mkdir -p $(SCRATCHDIR)/tmp/isobuild
	images/linux/buildiso.py $(LINUX_ISOS)/$(patsubst %.linux.inplace,%,$@) $(SCRATCHDIR)/tmp/isobuild/$@ nocopy
	if [ -e $(SCRATCHDIR)/tmp/isobuild/$@ ]; then mv $(SCRATCHDIR)/tmp/isobuild/$@ $(LINUX_ISOS)/$(patsubst %.linux.inplace,%,$@); fi
