#
# XenRT Script Makefile
#

CONSOLE ?= /usr/groups/xen/xenuse/bin/console
MAINCONSERVERADDR ?= 10.220.254.109
VARDIR ?= /var/xenrt
PYTHONLIB ?= /usr/local/lib/python2.6/dist-packages/
PYTHONLIB2 ?= /usr/local/lib/python2.7/dist-packages/
JENKINS ?= http://xenrt.hq.xensource.com:8080
WSGIWORKERS ?= 16
WSGITHREADS ?= 1
CURRENT_DIR ?= $(shell pwd)

include build/config.mk
include build/tools.mk

ifndef BUILDPREFIX
EXECDIR = exec
else
EXECDIR = $(BUILDPREFIX)-exec
endif

SRCDIRS		:= control scripts seqs lib data provision server xenrtdhcpd 
NEWDIRS		:= locks state results
SCRIPTS		:= $(patsubst %.in,%,$(wildcard **/*.in))
GENCODE		:= $(patsubst %.gen,%,$(wildcard **/*.gen))
LINKS		:= control/xenrt.py $(EXECDIR)/xenrt/ctrl.py control/xrt control/xrt1
BINLINKS    := xenrt xrt xrt1 xrtbranch runsuite

SRCDIRS		:= $(addprefix $(SHAREDIR)/,$(SRCDIRS))
NEWDIRS		:= $(addprefix $(SHAREDIR)/,$(NEWDIRS))

REVISION	= $(GIT) --git-dir=$(1)/.git --work-tree=$(1) log -1 --pretty=format:"$(notdir $(1)):%H"


.PHONY: update 
update: $(XENRT) $(INTERNAL)
	$(info Updated XenRT repositories.)

.PHONY: minimal-install
minimal-install: install

.PHONY: server
server: install
	$(SUDO) cp $(SHAREDIR)/server/xenrt-server /etc/init.d/
	$(SUDO) insserv xenrt-server
	$(SUDOSH) '/etc/init.d/xenrt-server start || $(SUDO) /etc/init.d/xenrt-server reload'

.PHONY: install
install: tarlibs $(NEWDIRS) utils $(SRCDIRS) exec $(LINKS) $(SCRATCHDIR) \
	 $(SHAREDIR)/VERSION $(SHAREDIR)/SITE $(CONFDIR) \
	 $(BINLINKS) images $(JOBRESULTDIR) progs tar $(VARDIR) pythonlibs copy unittests
	$(info XenRT installation completed.)	 

.PHONY: unittests
unittests:
	rsync -axl --delete unittests $(SHAREDIR)

.PHONY: tarlibs
tarlibs:
	-tar -C $(ROOT)/$(XENRT)/lib/ -xvf $(ROOT)/$(XENRT)/lib/*.tar.*

.PHONY: copy
copy:
ifdef COPYTO
	rsync -axl $(SHAREDIR)/ $(COPYTO)/
endif

.PHONY: pythonlibs
pythonlibs:
	$(SUDO) sed -i 's/^URLopener.open_https \=/# Removed as this breaks urllib\n# URLopener.open_https \=/' /usr/share/pyshared/M2Crypto/m2urllib.py
	-$(SUDO) rsync -axl lib/* $(PYTHONLIB)
	-$(SUDO) rsync -axl lib/* $(PYTHONLIB2)
	-$(SUDO) rsync -axl --exclude Manifest $(SHAREDIR)/tests/lib/* $(PYTHONLIB)
	-$(SUDO) rsync -axl --exclude Manifest $(SHAREDIR)/tests/lib/* $(PYTHONLIB2)

.PHONY: tar
tar:
	tar -C $(SHAREDIR)/control -cvzf xenrt-cli.tar.gz ./xenrt
	mv xenrt-cli.tar.gz $(SHAREDIR)

.PHONY: precommit precommit-all
precommit: xmllint pylint
precommit-all: xmllint-all pylint-all

.PHONY: pylint pylint-all
pylint:
	@for f in `(git diff | lsdiff --strip 1; git diff origin/master | lsdiff --strip 1) | egrep '\.(py|in)$$' | sort | uniq`; do \
	echo "Checking $$f..." && \
	export PYTHONPATH=$(SHAREDIR)/lib:$(ROOT)/$(XENRT)/exec:$(PYTHONPATH) && cd $(ROOT)/$(XENRT) && \
	pylint --rcfile=$(ROOT)/$(XENRT)/scripts/pylintrc \
	$$f && \
	$(ROOT)/$(XENRT)/scripts/misspelt $$f; \
	done; 
pylint-all:
	@for f in `find | egrep '\.(py)$$' | sort | uniq`; do \
    echo "Checking $$f..." && \
    export PYTHONPATH=$(SHAREDIR)/lib:$(ROOT)/$(XENRT)/exec:$(PYTHONPATH) && cd $(ROOT)/$(XENRT) && \
    pylint --rcfile=$(ROOT)/$(XENRT)/scripts/pylintrc \
    $$f && \
    $(ROOT)/$(XENRT)/scripts/misspelt $$f; \
    done; 

.PHONY: xmllint xmllint-all
xmllint:
	$(eval XSD = $(shell mktemp))
	sed 's/\\\$$/\\$$/' seqs/seq.xsd > $(XSD)
	@for f in `(git diff | lsdiff --strip 1; git diff origin/master | lsdiff --strip 1) | egrep '\.(seq)$$' | sort | uniq`; do \
	echo "Checking $$f..." && \
	xmllint --noout --schema $(XSD) $$f && \
	$(ROOT)/$(XENRT)/scripts/misspelt $$f; \
	done
	rm $(XSD)
xmllint-all:
	$(eval XSD = $(shell mktemp))
	sed 's/\\\$$/\\$$/' seqs/seq.xsd > $(XSD)
	@for f in `find | grep -e '\.seq$$'`; do \
	xmllint --noout --schema $(XSD) $$f 2>&1 | grep -v " validates$$" && \
	$(ROOT)/$(XENRT)/scripts/misspelt $$f; \
	done
	rm $(XSD)

.PHONY: clean
clean:
	$(info Removing compiled XenRT scripts...)
	$(RM) $(SCRIPTS) $(GENCODE)

.PHONY: uninstall
uninstall:
	$(info Uninstalling XenRT...)
	$(SUDO) $(RMTREE) $(SHAREDIR)
	$(SUDO) $(RMTREE) $(CONFDIR)

.PHONY: %.git
%.git:
	$(info Updating $@ repository...)
	[ -d $(ROOT)/$@ ] || $(GIT) clone $(GITPATH)/$@ $(ROOT)/$@
	cd $(ROOT)/$@ && $(GIT) pull

.PHONY: $(CONFDIR)
$(CONFDIR):
	$(info Creating link to $@...)#
	$(SUDO) mkdir -p $@
ifeq ($(PRODUCTIONCONFIG),yes)
	$(SUDO) ln -sfT `realpath $(ROOT)/$(INTERNAL)/config/$(SITE)/site.xml` $@/site.xml
	$(SUDO) ln -sfT `realpath $(ROOT)/$(INTERNAL)/config/$(SITE)/machines` $@/machinesinput
	$(SUDO) mkdir -p $@/machines
	$(SUDO) chown $(USERID):$(GROUPID) $@/machines
endif
ifeq ($(NISPRODUCTIONCONFIG),yes)
	$(SUDO) ln -sfT `realpath $(ROOT)/$(INTERNAL)/config/$(SITE)/site.xml` $@/site.xml
	$(SUDO) ln -sfT `realpath $(ROOT)/$(INTERNAL)/config/$(SITE)/machines` $@/machinesinput
	$(SUDO) mkdir -p $@/machines
	$(SUDO) chown $(USERID):$(GROUPID) $@/machines
endif
	if [ -e $(ROOT)/$(INTERNAL)/keys ]; then $(SUDO) ln -sfT `realpath $(ROOT)/$(INTERNAL)/keys` $@/keys; fi
	$(SUDO) mkdir -p $@/conf.d
	$(foreach dir,$(CONFDIRS), $(SUDO) ln -sfT `realpath $(ROOT)/$(INTERNAL)/config/$(dir)` $@/conf.d/$(dir);)
	$(SUDO) sh -c 'echo "$(SITE)" > $@/siteid'
	$(SUDO) ln -sfT `realpath $(ROOT)/$(INTERNAL)/suites` $@/suites

.PHONY: docs
docs:
ifeq ($(BUILDDOCS),yes)
	$(info Creating testcase API documentation...)
	mkdir -p $(SHAREDIR)/docs/API
	export PYTHONPATH=$(SHAREDIR)/lib && epydoc --html --name XenRT -q -o $(SHAREDIR)/docs/API $(SHAREDIR)/exec/xenrt $(SHAREDIR)/exec/testcases
else
	$(info Skipping building docs)
endif

control/xenrt.py:
	$(info Creating link to $@...)
	ln -sf xenrt $(SHAREDIR)/$@

$(EXECDIR)/xenrt/ctrl.py:
	$(info Creating link to $@...)
	ln -sf $(SHAREDIR)/control/xenrt $(SHAREDIR)/$@

control/xrt:
	$(info Creating link to $@...)
	-rm $(SHAREDIR)/$@
	/bin/echo -e '#!/bin/bash\n$(SHAREDIR)/control/venvwrapper2.sh `mktemp -d` /tmp/xenrtlogs NoJob $(SHAREDIR)/exec/main.py "$$@"' > $(SHAREDIR)/$@
	chmod a+x $(SHAREDIR)/$@

control/xrt1:
	$(info Creating link to $@...)
	ln -sf $(SHAREDIR)/exec/main.py $(SHAREDIR)/$@

xrt:
	$(info Creating link to $@...)
	$(SUDO) ln -sf $(SHAREDIR)/control/xrt $(BINDIR)/$@

xrt1:
	$(info Creating link to $@...)
	$(SUDO) ln -sf $(SHAREDIR)/control/xrt1 $(BINDIR)/$@

xrtbranch:
	$(info Creating link to $@...)
	$(SUDO) ln -sf $(SHAREDIR)/control/xrtbranch $(BINDIR)/$@

xenrt:
	$(info Creating link to $@...)
	$(SUDO) ln -sf $(SHAREDIR)/control/xenrt $(BINDIR)/$@

runsuite:
	$(info Creating link to $@...)
	$(SUDO) ln -sf $(SHAREDIR)/control/runsuite $(BINDIR)/$@

images:
	$(info Creating link to $@...)
	ln -s $(IMAGEDIR) $@

.PHONY: progs
progs:
	$(MAKE) -C progs ROOT=$(ROOT) DESTDIR=$(SHAREDIR)/scripts/progs install 

.PHONY: $(SHAREDIR)/VERSION
$(SHAREDIR)/VERSION: $(SRCDIRS) 
	$(info Creating $(notdir $@) stamp file...)
	echo `$(call REVISION,$(ROOT)/$(XENRT))` > $@ 
	echo `$(call REVISION,$(ROOT)/$(INTERNAL))` >> $@

$(SHAREDIR)/SITE: $(SHAREDIR)
	$(info Creating $(notdir $@) stamp file...)
	echo $(SITE) > $@

$(SHAREDIR):
	$(info Creating $@...)
	$(SUDO) mkdir -p $@ 
	$(SUDO) chown $(USERID):$(GROUPID) $@

$(SCRATCHDIR):
	$(info Creating $@...)
	$(SUDO) mkdir -p $@
	$(SUDO) chown $(USERID):$(GROUPID) $@

$(VARDIR):
	$(info Creating $@...)
	$(SUDO) mkdir -p $@
	$(SUDO) chown $(USERID):$(GROUPID) $@
	touch $@/deadjobs
	echo "0" > $@/site-controller-fail-count

$(JOBRESULTDIR):
	$(info Creating $@...)
	$(SUDO) mkdir -p $@
	$(SUDO) chown $(USERID):$(GROUPID) $@
	$(SUDO) rm -rf $(SHAREDIR)/results
	$(SUDO) ln -sfT $@ $(SHAREDIR)/results

$(NEWDIRS): $(SHAREDIR)
	$(info Creating $@...)
	mkdir -p $@

.PHONY: $(SRCDIRS)
$(SRCDIRS): $(SCRIPTS) $(GENCODE) $(SHAREDIR)
	$(info Installing files to $@...)
ifeq ($(CLEANSCRIPTS),yes)
	rsync -axl --delete $(notdir $@) $(SHAREDIR)
else
	rsync -axl $(notdir $@) $(SHAREDIR)
endif
	-rsync -axl $(ROOT)/$(INTERNAL)/$(notdir $@) $(SHAREDIR)

.PHONY: exec
exec:
	$(info Installing files to $(EXECDIR))
ifeq ($(CLEANSCRIPTS),yes)
	rsync -axl --delete $(notdir $@)/* $(SHAREDIR)/$(EXECDIR)/
else
	rsync -axl $(notdir $@)/* $(SHAREDIR)/$(EXECDIR)/
endif

.PHONY: $(SCRIPTS)
$(SCRIPTS): $(addsuffix .in,$(SCRIPTS))
	$(info Compiling XenRT scripts...)
	sed 's#@sharedir@#$(SHAREDIR)#g' $@.in > $@ 
	sed -i 's#@rootdir@#$(ROOT)/$(XENRT)#g' $@
	sed -i 's#@console@#$(CONSOLE)#g' $@
	sed -i 's#@conserver@#$(MAINCONSERVERADDR)#g' $@
	sed -i 's#@confdir@#$(CONFDIR)#g' $@
	sed -i 's#@vardir@#$(VARDIR)#g' $@
	sed -i 's#@webcontrdir@#$(WEB_CONTROL_PATH)#g' $@
	sed -i 's#@jenkins@#$(JENKINS)#g' $@
	sed -i 's#@wsgiworkers@#$(WSGIWORKERS)#g' $@
	sed -i 's#@wsgithreads@#$(WSGITHREADS)#g' $@
	sed -i 's#@user@#$(USERNAME)#g' $@
	sed -i 's#@group@#$(GROUPNAME)#g' $@
	sed -i 's#@stablebranch@#$(STABLE_BRANCH)#g' $@
	chmod --reference $@.in $@
	
.PHONY: $(GENCODE)
$(GENCODE): $(addsuffix .gen,$(GENCODE))
	$(info Generating XenRT Code ...)
	sed 's#@sharedir@#$(SHAREDIR)#g' $@.gen > $@.tmp 
	sed -i 's#@rootdir@#$(ROOT)/$(XENRT)#g' $@.tmp
	sed -i 's#@console@#$(CONSOLE)#g' $@.tmp
	sed -i 's#@conserver@#$(MAINCONSERVERADDR)#g' $@.tmp
	sed -i 's#@confdir@#$(CONFDIR)#g' $@.tmp
	sed -i 's#@vardir@#$(VARDIR)#g' $@.tmp
	sed -i 's#@webcontrdir@#$(WEB_CONTROL_PATH)#g' $@.tmp
	sed -i 's#@jenkins@#$(JENKINS)#g' $@.tmp
	python $@.tmp > $@
	rm $@.tmp
	chmod --reference $@.gen $@

.PHONY: check
check: install
	$(info Performing XenRT sanity checks ...)
	$(SHAREDIR)/exec/main.py --sanity-check
	$(SHAREDIR)/unittests/runner.sh $(SHAREDIR)
	$(eval XSD = $(shell mktemp))
	sed 's/\\\$$/\\$$/' seqs/seq.xsd > $(XSD)
	xmllint --schema $(XSD) seqs/*.seq --noout
	rm $(XSD)

.PHONY: minimal-check
minimal-check: install
	$(info Performing XenRT sanity checks ...)
	$(SHAREDIR)/exec/main.py --sanity-check
	$(SHAREDIR)/unittests/quickrunner.sh $(SHAREDIR)
	$(eval XSD = $(shell mktemp))
	sed 's/\\\$$/\\$$/' seqs/seq.xsd > $(XSD)
	xmllint --schema $(XSD) seqs/*.seq --noout
	rm $(XSD)
