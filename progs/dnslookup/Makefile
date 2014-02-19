# 
# XenRT: build helper program
#
# James Bulpin, January 2006
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

TARGET = dnslookup

include ../config.mk 

all: $(TARGET)

$(TARGET): $(TARGET).c
	$(CC) $(CCOPTS) -o $@ $<

clean:
	rm -f $(TARGET)

