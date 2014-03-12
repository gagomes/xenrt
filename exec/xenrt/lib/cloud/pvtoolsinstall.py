import xenrt
import logging
import os, urllib
from datetime import datetime

import xenrt.lib.cloud
try:
    from marvin import cloudstackTestClient
    from marvin.integration.lib.base import *
    from marvin import configGenerator
except ImportError:
    pass

installerList = []

def PVToolsInstallerFactory(cloudstack, instance):
    for i in installerList:
        if i.supportedInstaller(cloudstack, instance):
            return i(cloudstack, instance)
    raise xenrt.XRTError("No PV Tools installer found")

def RegisterInstaller(installer):
    installerList.append(installer)

class PVToolsInstaller(object):
    def __init__(self, cloudstack, instance):
        self.cloudstack = cloudstack
        self.instance = instance

    @staticmethod
    def supportedInstaller(cloudstack, instance):
        return False

class WindowsXenServer(PVToolsInstaller):

    @staticmethod
    def supportedInstaller(cloudstack, instance):
        # TODO: Check the instance is running on XenServer

        if not isinstance(instance.os, xenrt.lib.opsys.WindowsOS):
            return False

        return True

    def install(self):
        listIsosC = listIsos.listIsosCmd()
        listIsosC.name="xs-tools.iso"
        isoId = self.cloudstack.marvin.apiClient.listIsos(listIsosC)[0].id

        attachIsoC = attachIso.attachIsoCmd()
        attachIsoC.id = isoId
        attachIsoC.virtualmachineid = self.instance.toolstackId
        self.cloudstack.marvin.apiClient.attachIso(attachIsoC)

        # Allow the CD to appear
        xenrt.sleep(30)

        deadline = xenrt.util.timenow() + 300 
        while True:
            try:
                if self.instance.os.fileExists("D:\\installwizard.msi"):
                    break
            except:
                pass
            if xenrt.util.timenow() > deadline:
                raise xenrt.XRTError("Installer did not appear")
            
            xenrt.sleep(5)

        self.instance.os.startCmd("D:\\installwizard.msi /passive /liwearcmuopvx c:\\tools_msi_install.log")
        
        deadline = xenrt.util.timenow() + 3600
        while True:
            regValue = ""
            try:
                regValue = self.instance.os.winRegLookup('HKLM', "SOFTWARE\\Wow6432Node\\Citrix\\XenToolsInstaller", "InstallStatus", healthCheckOnFailure=False)
            except:
                try:
                    regValue = self.instance.os.winRegLookup('HKLM', "SOFTWARE\\Citrix\\XenToolsInstaller", "InstallStatus", healthCheckOnFailure=False)
                except:
                    pass
                
            if xenrt.util.timenow() > deadline:
                #instanse.os.checkHealth(desc="Waiting for installer registry key to be written")
                
                if regValue and len(regValue) > 0:
                    raise xenrt.XRTFailure("Timed out waiting for installer registry key to be written. Value=%s" % regValue)
                else:
                    raise xenrt.XRTFailure("Timed out waiting for installer registry key to be written.")
            
            elif "Installed" == regValue:
                break
            else:
                xenrt.sleep(30)

RegisterInstaller(WindowsXenServer)
