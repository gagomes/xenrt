#
# XenRTInfrastructure Makefile
#
include build/tools.mk
TEMPFOLDER := $(shell mktemp -d /tmp/DythonXXX)
PYTHONSOURCEFOLDER ?= $(TEMPFOLDER)/python2.7-2.7.3
DYTHONINSTALLATION ?= /usr/share/dython
VIRTUALENVPATH ?= /usr/share/dython-env


.PHONY: dython-install
dython-install:
	cd $(TEMPFOLDER) && apt-get source python2.7
	cd $(PYTHONSOURCEFOLDER) && patch -p1 < $(ROOT)/$(XENRT)/control/Dython_diff
	cd $(PYTHONSOURCEFOLDER) && ./configure
	cd $(PYTHONSOURCEFOLDER) && rm -f Python/graminit.c && make Python/graminit.c
	cd $(PYTHONSOURCEFOLDER) && rm -f Python/Python-ast.c && make Python/Python-ast.c
	cd $(PYTHONSOURCEFOLDER) && make clean && ./configure --prefix=$(DYTHONINSTALLATION) --enable-unicode=ucs4 && make && $(SUDO) make install
	cd $(ROOT) && rm -r -f $(TEMPFOLDER)

.PHONY: virtualenv-install
virtualenv-install:
	$(SUDO) apt-get install -y python-setuptools
	$(SUDO) apt-get install -y python-pip
	$(SUDO) pip install virtualenv==1.9.1

.PHONY: dython-env
dython-env: dython-install virtualenv-install
	$(SUDO) virtualenv $(VIRTUALENVPATH) -p $(DYTHONINSTALLATION)/bin/python

.PHONY: dython-sync
dython-sync: extrapackages-install
	if test -d $(VIRTUALENVPATH); then $(SUDO) rsync -avxl /usr/lib/python2.7/dist-packages $(VIRTUALENVPATH)/lib/python2.7/ ; $(SUDO) rsync -avxl /usr/lib/pymodules $(VIRTUALENVPATH)/lib/ ; $(SUDO) rsync -avxl /usr/lib/python2.7/lib-dynload/ $(VIRTUALENVPATH)/lib/python2.7/ ; $(SUDO) rsync -avxl /usr/local/lib/python2.7/dist-packages $(VIRTUALENVPATH)/lib/python2.7/ ; fi

.PHONY: debugger
debugger: dython-install virtualenv-install dython-env dython-sync


	


