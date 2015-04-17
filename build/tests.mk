#
# XenRT Test Makefile
#
include build/config.mk
include build/tools.mk

TESTS	= $(patsubst %,$(SHAREDIR)/%.tgz,$(wildcard tests/*))
BUILD	= $(ROOT)/$(XENRT)/scripts/buildtarball

.PHONY: test-tarballs
ifeq ($(BUILDTESTS),no)
test-tarballs:
	$(info Skipping building test tarballs...)
else
test-tarballs: 
	$(info Building test tarballs...)
	$(MAKE) -j 3 $(TESTS)
endif

.PHONY: tests-clean
tests-clean:
	$(info Removing test tarballs...)
	$(SUDO) $(RMTREE) $(SHAREDIR)/tests

$(SHAREDIR)/tests:
	$(info Creating test tarball output directory... \($@\))
	$(SUDO) mkdir -p /local/outputs/tests
	$(SUDO) ln -sfT /local/outputs/tests $(SHAREDIR)/tests
	$(SUDO) chown $(USERID):$(GROUPID) $(SHAREDIR)/tests

.PHONY: $(TESTS)
$(TESTS): $(SHAREDIR)/tests
	$(info Building $@...)
	-$(BUILD) $(call STRIP,$@) \
	         $(SHAREDIR)/tests \
	         $(shell mktemp -d /tmp/test.XXX) \
	         $(ROOT)/$(XENRT)/tests/$(call STRIP,$@) \
	         $(TEST_INPUTS)/$(call STRIP,$@) \
	         $(ROOT)/$(INTERNAL)/keys/$(call STRIP,$@) \
	         $(BUILDALLTESTS)

