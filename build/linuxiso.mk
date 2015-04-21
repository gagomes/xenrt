#
# XenRT ISO Makefile
#
include build/tools.mk

LINUX_ISOS_INPLACE_LIST	= $(shell cd $(LINUX_ISOS) && ls *.iso)

linuxisos:
	$(info Building Linux ISOs in place...)
	$(foreach iso,$(LINUX_ISOS_INPLACE_LIST), $(MAKE) $(iso).linux;)

.PHONY: %.iso
%.iso.linux:
	$(info Building $@...)
	mkdir -p $(SCRATCHDIR)/tmp/isobuild
	if [ ! -e $(LINUX_ISOS)/$(patsubst %.linux,%.stamp,$@) ]; then images/linux/buildiso.py $(LINUX_ISOS)/$(patsubst %.linux,%,$@) $(SCRATCHDIR)/tmp/isobuild/$@ nocopy; fi
	if [ -e $(SCRATCHDIR)/tmp/isobuild/$@ ]; then mv $(SCRATCHDIR)/tmp/isobuild/$@ $(LINUX_ISOS)/$(patsubst %.linux,%,$@); fi
	touch $(LINUX_ISOS)/$(patsubst %.linux,%.stamp,$@) 
