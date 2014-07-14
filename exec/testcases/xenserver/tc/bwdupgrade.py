# XenRT: Test harness for Xen and the XenServer product family
#
# Borehamwood Rolling Pool Upgrade (RPU)testcases
#
# Copyright (c) 2014 Citrix Systems Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#
import socket, re, string, time, traceback, sys, random, copy, os, shutil
import os.path
import IPy
import xenrt, xenrt.lib.xenserver, xenrt.lib.xenserver.call, xenrt.lib.xenserver.context
import testcases.xenserver.tc.upgrade

class TCRpuBwd(testcases.xenserver.tc.upgrade._RPUBasic):
    """Clearwater Borehamwood to Creedence rolling pool upgrade test using RawHBA SR"""
    pass
