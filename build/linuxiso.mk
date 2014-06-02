#
# XenRT ISO Makefile
#
include build/config.mk
include build/tools.mk

LINUX_ISOS	= $(shell ls $(LINUX_ISOS_INPUTS))
LINUX_ISOS_INPLACE	= $(shell ls $(LINUX_ISOS))

linuxisos:$(LINUX_ISOS_OUTPUTS)
	$(info Building Linux ISOs...)
	$(foreach iso,$(LINUX_ISOS), $(MAKE) $(iso);)

linuxisos-inplace:
	$(info Building Linux ISOs in place...)
	$(foreach iso,$(LINUX_ISOS_INPLACE), $(MAKE) $(iso).inplace;)

$(LINUX_ISOS_OUTPUTS):
	$(info Creating linux ISO output directory... \($@\))
	$(SUDO) mkdir -p $(LINUX_ISOS_OUTPUTS)
	$(SUDO) chown $(USERID):$(GROUPID) $(IMAGEDIR)

.PHONY: %.iso
%.iso:
	$(info Building $@...)
	images/linux/buildiso.py $(LINUX_ISOS_INPUTS)/$@ $(LINUX_ISOS_OUTPUTS)/$@

.PHONY: %.iso.inplace
%.iso.inplace:
	$(info Building $@...)
	mkdir -p /tmp/linisos
	images/linux/buildiso.py $(LINUX_ISOS)/$(patsubst %.inplace,%,$@) /tmp/linisos/$@ nocopy
	if [ -e /tmp/linisos/$@ ]; then mv /tmp/linisos/$@ $(LINUX_ISOS)/$(patsubst %.inplace,%,$@); fi
