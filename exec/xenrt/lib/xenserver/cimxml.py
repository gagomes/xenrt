#
#
# XenRT: Test harness for Xen and the XenServer product family
#
# Encapsulate a XenServer host.
#
# Copyright (c) 2006 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import sys, string, os.path, glob, time, re, random, shutil, os, stat
import traceback, threading, types
import xml.dom.minidom
import tarfile
import xenrt
import xenrt.lib.xenserver.guest
import XenAPI

import pywbem
#from pywbem.cim_obj import *
from pywbem.cim_obj import CIMInstance
from pywbem.cim_obj import CIMInstanceName

# Symbols we want to export from the package.
__all__ = ["createCIMXMLVM",
           "verifyHost",
           "changeCIMXMLState",
           "deleteCIMXMLVM"]

def cimxmlConnection(password = None,
                     hostIPAddr = None):
    userName = "root"
    conn = pywbem.WBEMConnection('http://'+hostIPAddr, (userName, password))
    return conn

def verifyHost(hostIPAddr = None,
               password = None):
    userName = "root"
    try:
        conn = pywbem.WBEMConnection('http://'+hostIPAddr, (userName, password))
    except:
        raise xenrt.XRTFailure("Authentication of host failed with Password %s" % (password))

def changeCIMXMLState(password = None,
                      hostIPAddr = None,
                      vmuuid = None,
                      state = None):

    cimxmlConn = cimxmlConnection(password,hostIPAddr)

    vm = CIMInstanceName("Xen_ComputerSystem")
    vm['Name'] = vmuuid
    vm['CreationClassName'] = 'Xen_ComputerSystem'
    inParams = {'RequestedState': '%s' % (state)}
    try:
        (rval, outParams) = cimxmlConn.InvokeMethod('RequestStateChange', vm, **inParams)
        if((rval != 4096) and (rval != 0)):
            raise xenrt.XRTError("Following error occured while invoking DefineSystem %s" % (rval))
    except  Exception, e:
        raise xenrt.XRTError("Caught exception (%s) while invoking RequestedStateChange" % (str(e.data)))

def createCIMXMLVM(password = None,
                   hostIPAddr = None,
                   vmName = None):
    cimxmlConn = cimxmlConnection(password,hostIPAddr)

    # Virtual System setting data for an HVM type
    hvmVssd = CIMInstance("Xen_ComputerSystemSettingData")
    hvmVssd['Description'] = vmName
    hvmVssd['ElementName'] = vmName
    hvmVssd['VirtualSystemType'] = 'DMTF:xen:HVM'
    hvmVssd['HVM_Boot_Params'] = ['order=dc']
    hvmVssd['HVM_Boot_Policy'] = 'BIOS order'
    hvmVssd['Platform'] = ['acpi=true','apic=true','pae=true']

    # RASD to specify processor allocation for the VM
    # Processor RASD
    procRasd = CIMInstance('CIM_ResourceAllocationSettingData')
    procRasd['ResourceType'] = pywbem.Uint16(3)
    procRasd['VirtualQuantity'] = pywbem.Uint64(1)
    procRasd['AllocationUnits'] = 'count'

    # memory RASD to specify memory allocation settings for a VM
    memRasd = CIMInstance('Xen_MemorySettingData')
    memRasd['ResourceType'] = pywbem.Uint16(4)
    memRasd['VirtualQuantity'] = pywbem.Uint64(512)
    memRasd['AllocationUnits'] = 'byte*2^20'

    vsms = cimxmlConn.EnumerateInstanceNames("Xen_VirtualSystemManagementService")

    rasds = [procRasd, memRasd]
    hvmParams = {'SystemSettings': hvmVssd, 'ResourceSettings': rasds}

    newVM = None
    try:
        (rval, outParams) = cimxmlConn.InvokeMethod('DefineSystem', vsms[0], **hvmParams)

        if((rval != 4096) and (rval != 0)):
            raise xenrt.XRTError("Following error occured while invoking DefineSystem %s" % (rval))

        newVM = outParams['ResultingSystem']
        xenrt.sleep(10)

    except  Exception, e:
        raise xenrt.XRTError("Caught exception while invoking DefineSystem")

    return newVM

def deleteCIMXMLVM(password = None,
                   hostIPAddr = None,
                   vm = None):

    cimxmlConn = cimxmlConnection(password,hostIPAddr)
    vsms = cimxmlConn.EnumerateInstanceNames("Xen_VirtualSystemManagementService")

    params = {'AffectedSystem': vm}
    try:
        (rval, out_params) = cimxmlConn.InvokeMethod('DestroySystem', vsms[0], **params)
        xenrt.sleep(5)
    except Exception, e:
        raise xenrt.XRTError("Exception caught while invoking DestroySystem" )

    if rval != 0:
        raise xenrt.XRTError("DestroySystem returned with error")
