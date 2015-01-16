UTILSCRIPTS := certmgr.exe devcon64.exe devcon.exe psloglist.exe soon.exe

.PHONY: utils
utils: $(addprefix $(ROOT)/$(XENRT)/scripts/distutils/,$(UTILSCRIPTS))

$(addprefix $(ROOT)/$(XENRT)/scripts/distutils/,$(UTILSCRIPTS)):
	$(info Obtaining $(notdir $@)...)
	[ -e $(ROOT)/$(INTERNAL)/utils/$(notdir $@) ] && \
	  ln -s $(ROOT)/$(INTERNAL)/utils/$(notdir $@) $@ || \
	  $(ROOT)/$(XENRT)/scripts/distutils/getUtil.py $(notdir $@) $(ROOT)/$(XENRT)/scripts/distutils

.PHONY: dbschema
dbschema:
	$(ROOT)/$(XENRT)/scripts/getdbschema $(ROOT)/$(XENRT)/control/database.sql
	git diff $(ROOT)/$(XENRT)/control/database.sql
