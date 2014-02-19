#
# XenRT Makefile Tools
#
USERID		= $(shell id -u)
GROUPID		= $(shell id -g)

USERNAME    = $(shell getent passwd $(USERID) | cut -d ':' -f 1)
GROUPNAME   = $(shell getent group $(GROUPID) | cut -d ':' -f 1)

HG		= hg
GIT		= git
SUDO		= sudo
SUDOSH		= $(SUDO) sh -c
RMTREE		= rm --recursive --force --one-file-system
STRIP		= $(basename $(notdir $(1)))
MAKE    = make
