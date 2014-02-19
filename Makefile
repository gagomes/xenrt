ifeq ($(strip $(wildcard /etc/debian_version)),)
    include Makefile.old
else
    include Makefile.new
endif
