#
# XenRT: program build and installation
#
# James Bulpin, January 2006
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

SUBDIRS = dnslookup rsync slurp mappedfiletest flipbit fill linwrite linread winwrite winread 

all:
	for subdir in $(SUBDIRS); do \
	    $(MAKE) ROOT=$(ROOT) -C $$subdir $@; \
	done

install:
	for subdir in $(SUBDIRS); do \
	    $(MAKE) ROOT=$(ROOT) DESTDIR=$(DESTDIR) -C $$subdir $@; \
	done

uninstall:
	for subdir in $(SUBDIRS); do \
	    $(MAKE) ROOT=$(ROOT) DESTDIR=$(DESTDIR) -C $$subdir $@; \
	done

clean:
	for subdir in $(SUBDIRS); do \
	    $(MAKE) ROOT=$(ROOT) -C $$subdir $@; \
	done

