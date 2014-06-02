#
# XenRT ISO Makefile
#
include build/config.mk
include build/tools.mk

ISOS	= $(shell ls $(LINUX_ISOS_INPUTS))

linuxisos:$(LINUX_ISOS_OUTPUTS)
	$(info Building Linux ISOs...)
	$(foreach iso,$(ISOS), $(MAKE) $(iso);)

$(LINUX_ISOS_OUTPUTS):
	$(info Creating linux ISO output directory... \($@\))
	$(SUDO) mkdir -p $(LINUX_ISOS_OUTPUTS)
	$(SUDO) chown $(USERID):$(GROUPID) $(IMAGEDIR)

.PHONY: %.iso
%.iso:
	$(info Building $@...)
	images/linux/buildiso.py $(LINUX_ISOS_INPUTS)/$@ $(LINUX_ISOS_OUTPUTS)/$@
