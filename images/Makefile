# XenRT image creation

IMGROOT ?= $(shell pwd)
ROOT ?= $(shell dirname $(IMGROOT))

# Source local config from localconfig.mk in the parent dir
include $(ROOT)/localconfig.mk

# This is the temporary location for building images
WORKDIR ?= 

# The kernel versions we use
KERNEL_VERSION = 2.6
KERNEL_REVISION = 2.6.18
E1000_VERSION = 7.6.9
NETPERF_RPM = netperf-2.4.2-1.el4.rf.i386.rpm

# Where to find kernels if we don't have them cached
KERNEL_REPO ?= http://www.kernel.org

# Path to distribution repository for cleanroot
CLEANROOT_DISTRO ?= centos5

##############################################################################

ifeq ($(WORKDIR),)
  WORKDIR = $(IMGROOT)/build
endif

LINUX_SRC_PATH  ?= .:..:${WORKDIR}
vpath linux-%.tar.bz2 $(LINUX_SRC_PATH)

HG        = hg
SUDO      = sudo

##############################################################################

RPMCHROOT = $(IMGROOT)/rpmchroot/rpmchroot

# This is only used when generating the XenRT distribution. It has no
# meaning to XenRT deployments.
RPMCHROOT_REPO = http://hg.uk.xensource.com/carbon/carbon/rpmchroot.hg

# We snapshot rpmchroot, use this to update (but remember to check in!)
update:
	rm -rf rpmchroot
	${HG} clone $(RPMCHROOT_REPO) rpmchroot

##############################################################################
# Build the cleanroot ramdisk image                                          #
##############################################################################

.PRECIOUS: cleanroot-%.img
cleanroot-%.img:
	make packages.cleanroot.$*
	make bootstrap-$*
	$(SUDO) rm -f $(WORKDIR)/$@ $(WORKDIR)/$@.gz
	$(SUDO) dd if=/dev/zero of=$(WORKDIR)/$@ bs=1048576 count=1 seek=511
	$(SUDO) /sbin/mkfs.ext2 -F $(WORKDIR)/$@
	$(SUDO) mkdir -p /tmp/mount-$@
	$(SUDO) mount -oloop $(WORKDIR)/$@ /tmp/mount-$@
	NFSMOUNT=`mktemp -d /tmp/mntXXXXXX` && \
	NFSPATH=`xrt --lookup RPM_SOURCE/$(CLEANROOT_DISTRO)/x86-32/NFS` && \
	$(SUDO) mount -t nfs -oro $$NFSPATH $$NFSMOUNT && \
	PATH=$$PATH:/usr/sbin $(SUDO) $(RPMCHROOT) -c -g core -P packages.cleanroot.$* -r $$NFSMOUNT /tmp/mount-$@ ; RC=$$? ; $(SUDO) umount $$NFSMOUNT ; rmdir $$NFSMOUNT ; if [ $$RC != 0 ]; then false ; fi
	$(SUDO) ./cleanroot.tailor /tmp/mount-$@ ${ROOT} $(TEST_INPUTS)/images $(TEST_INPUTS)/images/$(NETPERF_RPM)
	$(SUDO) make -C $(WORKDIR)/linux-$(KERNEL_REVISION)-$(patsubst cleanroot-%.img,%,$@) INSTALL_MOD_PATH=/tmp/mount-$@ modules_install
	$(SUDO) make -C $(WORKDIR)/linux-$(KERNEL_REVISION)-$(patsubst cleanroot-%.img,%,$@) INSTALL_PATH=/tmp/mount-$@/boot install
	rm -rf $(WORKDIR)/e1000-$(patsubst cleanroot-%.img,%,$@)
	mkdir -p $(WORKDIR)/e1000-$(patsubst cleanroot-%.img,%,$@)
	tar -zxf $(TEST_INPUTS)/images/e1000-$(E1000_VERSION).tar.gz -C $(WORKDIR)/e1000-$(patsubst cleanroot-%.img,%,$@)
	make -C $(WORKDIR)/e1000-$(patsubst cleanroot-%.img,%,$@)/e1000-$(E1000_VERSION)/src KSRC=$(WORKDIR)/linux-$(KERNEL_REVISION)-$(patsubst cleanroot-%.img,%,$@) KVER=$(KERNEL_REVISION)
	$(SUDO) make -C $(WORKDIR)/e1000-$(patsubst cleanroot-%.img,%,$@)/e1000-$(E1000_VERSION)/src KSRC=$(WORKDIR)/linux-$(KERNEL_REVISION)-$(patsubst cleanroot-%.img,%,$@) INSTALL_MOD_PATH=/tmp/mount-$@ install
	$(SUDO) cp /tmp/mount-$@/boot/vmlinuz-$(KERNEL_REVISION)-xenrt-$(patsubst cleanroot-%.img,%,$@) $(WORKDIR)/vmlinuz-xenrt-$(patsubst cleanroot-%.img,%,$@)
	$(SUDO) chown $(shell whoami) $(WORKDIR)/vmlinuz-xenrt-$(patsubst cleanroot-%.img,%,$@)
	$(SUDO)	umount /tmp/mount-$@
	$(SUDO) gzip $(WORKDIR)/$@
	$(SUDO) chown $(shell whoami) $(WORKDIR)/$@.gz
	@echo "Built: $(WORKDIR)/vmlinuz-xenrt-$(patsubst cleanroot-%.img,%,$@)"
	@echo "Built: $(WORKDIR)/$@.gz"
	touch $@

install: cleanroot-x86-32.img bootstrap-x86-32
	TFTP=`xrt --lookup TFTP_BASE` && \
	mkdir -p $$TFTP/clean && \
	cp $(WORKDIR)/vmlinuz-xenrt-x86-32 $$TFTP/clean && \
	cp $(WORKDIR)/cleanroot-x86-32.img.gz $$TFTP/clean

##############################################################################
# Make the bootstrap kernel                                                  #
##############################################################################

# download a pristine Linux kernel tarball if there isn't one in LINUX_SRC_PATH
$(WORKDIR)/linux-%.tar.bz2:
	[ -e $@ ] || (mkdir -p $(@D) && wget $(KERNEL_REPO)/pub/linux/kernel/v$(KERNEL_VERSION)/$(@F) -O$@)

# Unpack the kernel tree
.PRECIOUS: $(WORKDIR)/linux-%/.valid-xenrt
$(WORKDIR)/linux-%/.valid-xenrt:
	make $(WORKDIR)/linux-$*.tar.bz2
	rm -rf $(WORKDIR)/tmp-linux-$* $(@D)
	mkdir -p $(WORKDIR)/tmp-linux-$*
	tar -C $(WORKDIR)/tmp-linux-$* -jxf $(WORKDIR)/linux-$*.tar.bz2 
	-@rm -f $(WORKDIR)/tmp-linux-$*/pax_global_header
	mv $(WORKDIR)/tmp-linux-$*/* $(@D)
	@rm -rf $(WORKDIR)/tmp-linux-$*
	touch $(@D)/.hgskip
	touch $@ # update timestamp to avoid rebuild

# Take a copy of the pristine tree for our architecture and build
.PRECIOUS: bootstrap-%
bootstrap-%:
	make config.bootstrap.$*
	make $(WORKDIR)/linux-$(KERNEL_REVISION)/.valid-xenrt
	rm -rf $(WORKDIR)/linux-$(KERNEL_REVISION)-$(patsubst bootstrap-%,%,$@)
	cp -a $(WORKDIR)/linux-$(KERNEL_REVISION) $(WORKDIR)/linux-$(KERNEL_REVISION)-$(patsubst bootstrap-%,%,$@)
	cp config.bootstrap.$* $(WORKDIR)/linux-$(KERNEL_REVISION)-$(patsubst bootstrap-%,%,$@)/.config
	yes | tr 'y' '\n'  | make -C $(WORKDIR)/linux-$(KERNEL_REVISION)-$(patsubst bootstrap-%,%,$@) oldconfig
	mv $(WORKDIR)/linux-$(KERNEL_REVISION)-$(patsubst bootstrap-%,%,$@)/Makefile $(WORKDIR)/linux-$(KERNEL_REVISION)-$(patsubst bootstrap-%,%,$@)/Makefile.orig
	sed -re's/^(EXTRAVERSION =.*)$$/\1 -xenrt-$(patsubst bootstrap-%,%,$@)/' < $(WORKDIR)/linux-$(KERNEL_REVISION)-$(patsubst bootstrap-%,%,$@)/Makefile.orig > $(WORKDIR)/linux-$(KERNEL_REVISION)-$(patsubst bootstrap-%,%,$@)/Makefile
	make -C $(WORKDIR)/linux-$(KERNEL_REVISION)-$(patsubst bootstrap-%,%,$@) -j 4
	touch $@

##############################################################################

clean:
	rm -f bootstrap-*
	rm -rf $(WORKDIR)/linux-$(KERNEL_REVISION)*
	$(SUDO) rm -f $(WORKDIR)/cleanroot-*.img $(WORKDIR)/cleanroot-*.img.gz
	rm -rf $(WORKDIR)/e1000-*

