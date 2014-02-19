#
# XenRT Diskless Debian makefile
#

CHROOT = $(SUDO) chroot $(DISKLESSROOT)
CHROOTSH = $(SUDO) chroot $(DISKLESSROOT) sh -c

.PHONY: disklessdebian
disklessdebian: disklessboot debootstrap

.PHONY: debootstrap
debootstrap:
	$(info Creating debian root disk)
	$(SUDO) apt-get install -y debootstrap
	$(SUDO) mkdir -p /local/debianroot
	$(SUDO) debootstrap wheezy $(DISKLESSROOT)

	$(SUDO) cp $(ROOT)/$(XENRT)/infrastructure/disklessdebian/interfaces $(DISKLESSROOT)/etc/network/interfaces
	$(SUDO) cp $(ROOT)/$(XENRT)/infrastructure/disklessdebian/fstab $(DISKLESSROOT)/etc/fstab
	$(SUDO) cp /etc/timezone $(DISKLESSROOT)/etc/timezone
	$(SUDO) cp /etc/localtime $(DISKLESSROOT)/etc/localtime
	$(SUDO) cp -r /lib/modules/`uname -r`/ $(DISKLESSROOT)/lib/modules/
	$(SUDOSH) 'echo debian > $(DISKLESSROOT)/etc/hostname'
	$(CHROOT) apt-get update
	$(CHROOT) apt-get -y install ifupdown locales libui-dialog-perl dialog isc-dhcp-client netbase net-tools iproute vim apt-utils openssh-server
	$(CHROOTSH) "echo 'en_US.UTF-8 UTF-8' >> /etc/locale.gen"
	$(CHROOT) locale-gen en_US.UTF-8
	$(CHROOT) dpkg-reconfigure -u tzdata
	$(CHROOTSH) "echo 'root:xensource' | chpasswd"
	$(SUDO) touch $(DISKLESSROOT)/xenrt

.PHONY: disklessboot
disklessboot:
	$(info Copying kernel and creating initrd)
	$(SUDO) mkdir -p $(TFTPROOT)/debian
	$(SUDO) cp /boot/vmlinuz-`uname -r` /$(TFTPROOT)/debian/vmlinuz
	$(SUDO) cp -r /etc/initramfs-tools /etc/initramfs-pxe
	$(SUDO) sed -i 's/BOOT=local/BOOT=nfs/' /etc/initramfs-pxe/initramfs.conf
	$(SUDO) sed -i 's/MODULES=most/MODULES=netboot/' /etc/initramfs-pxe/initramfs.conf
	-$(SUDO) dpkg -i $(TEST_INPUTS)/disklessdebian/firmware/*.deb
	-$(SUDO) mkinitramfs -d /etc/initramfs-pxe -o $(TFTPROOT)/debian/initrd.img `uname -r`
