#
# XenRT ISO Makefile
#
include build/config.mk
include build/tools.mk

ISOS	= $(ls $(LINUX_ISOS_INPUTS))

linuxisos:$(LINUX_ISOS_OUTPUTS)
	$(info Building Linux ISOs...)
	$(foreach iso,$(ISOS), $(MAKE) $(iso);)

$(LINUX_ISOS_OUTPUTS):
	$(info Creating linux ISO output directory... \($@\))
	$(SUDO) mkdir -p $(LINUX_ISOS_OUTPUTS)
	$(SUDO) chown $(USERID):$(GROUPID) $(IMAGEDIR)

.PRECIOUS: $(LINUX_ISOS_OUTPUTS)/%.iso
$(LINUX_ISOS_OUTPUTS)/%.iso:
	$(info Building $@...)
