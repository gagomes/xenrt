#
# XenRT: program build common configuration
#
# James Bulpin, January 2006
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

CCOPTS  = -Wall -O2 -m32
CC      = gcc
INSTALL = install

PROGDIR = $(ROOT)/scripts/progs

install: $(TARGET)
	$(INSTALL) -d $(DESTDIR)
	$(INSTALL) $< $(DESTDIR)

uninstall:
	rm -f $(DESTDIR)/$(TARGET) 
