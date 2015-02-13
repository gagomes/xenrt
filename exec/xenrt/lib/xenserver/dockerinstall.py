# XenRT: Test harness for Xen and the XenServer product family
#
# Docker installation support into a guest.
#
# Copyright (c) 2015 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.

#import sys, string, time, socket, re, os.path, os, shutil, random, sets, math
#import xenrt, xenrt.ssh, xenrt.util, xenrt.rootops, xenrt.resources
#from abc import ABCMeta, abstractmethod
import xenrt

__all__ = ["RHELDockerInstall", "UbuntuDockerInstall", "CoreOSDockerInstall"]

"""
Docker installation.
"""

class DockerInstall(object):

    def __init__(self, guest):
        self.guest =guest

    def install(self): pass
    def check(self): pass

class RHELDockerInstall(DockerInstall):

    def install(self):
        xenrt.TEC().logverbose("Docker installation on RHEL to be implemented")
    def check(self):
        xenrt.TEC().logverbose("Docker installation check on RHEL to be implemented")

class UbuntuDockerInstall(DockerInstall):
    def install(self):
        xenrt.TEC().logverbose("Docker installation on Ubuntu to be implemented")
    def check(self):
        xenrt.TEC().logverbose("Docker installation check on Ubuntu to be implemented")

class CoreOSDockerInstall(DockerInstall):
    def install(self):
        xenrt.TEC().logverbose("CoreOS has the docker environment by default")
    def check(self):
        # Check docker environment is working.
        guestCmdOut = self.guest.execguest("docker -v; exit 0").strip() # 'Docker version 1.4.1, build 5bc2ff8-dirty\n'
        if "Docker version" in guestCmdOut:
            xenrt.TEC().logverbose("Docker installation is running")
        else: 
            raise xenrt.XRTError("Failed to find a running instance of Docker")
