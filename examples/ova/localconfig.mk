# Where we keep ISO images of Windows product CDs, and the SFU CD.
BINARY_INPUTS_BASE ?= /local/inputs
WINDOWSISOS ?= $(BINARY_INPUTS_BASE)/windows

# Temporary space used to build images.
WORKDIR ?= /local/scratch/imagetmp

# Local cache of kernel tar.bz2 files for building the bootstrap kernel.
LINUX_SRC_PATH ?= $(BINARY_INPUTS_BASE)/linux/kernels

# Web path to control dir (include trailing /)
WEB_CONTROL_PATH ?= http://192.168.128.1/share/control/

# Path to 3rd party test executables and sources
TEST_INPUTS ?= ${BINARY_INPUTS_BASE}/tests

