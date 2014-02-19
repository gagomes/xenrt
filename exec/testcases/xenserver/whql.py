#
# XenRT: Custom test case (Python) file.
#
# To run this test case you will need to:
#
# 1. Create a sequence file.
# 2. Reference this class in the sequence file.
# 3. Submit a job using the sequence.
# This python file is place holder for scripts to be used for WHQL and SVVP

import socket, re, string, time, traceback, sys, random, copy, xml.dom.minidom
import os, os.path
import xenrt, xenrt.lib.xenserver
import testcases.benchmarks.workloads
import guest

class SVVPBase(xenrt.TestCase):
    ISO_NAME="WLK_1.6_8367.iso"
    DotNetVersion=3.5;
    winHostName=None;
    DTMServerName="DTMSERVER";
    guestName=None;
    distro="ws08r2dc-x64";
    memory="4096";
    vcpus="2";
    machine=None;
    ADNAME="AUTHSERVERWHQL";
    targetGuest=None;
    inserttools="True";
    
    def prepare(self, arglist=None):
        
        if arglist and len(arglist) > 0:
            self.machine = arglist[0]
        else:
            raise xenrt.XRTError("No machine specified")
 
        for arg in arglist[1:]:
            l = string.split(arg, "=", 1)
            if l[0] == "guestName":
                self.guestName = l[1]
            if l[0] == "adVMName":
                self.ADNAME = l[1]
            if l[0] == "dotNetVer":
                self.DotNetVersion = l[1]
            if l[0] == "WHQLISOName":
                self.ISO_NAME = l[1]
            if l[0] == "winHostName":
                self.winHostName = l[1]
            if l[0] == "DTMServerName":
                self.DTMServerName = l[1]
            if l[0]=="distro":
                self.distro=l[1]
            if l[0]=="memory":
                self.memory=l[1]
            if l[0]=="vcpus":
                self.vcpus=l[1]
            if l[0]=="WHQLISOName":
                self.ISO_NAME=l[1]
               
        self.distro="distro=%s"%(self.distro)
        self.guestNameList="guest=%s"%(self.guestName)
        self.memory="memory=%s"%(self.memory)
        xenrt.TEC().logverbose(self.distro)
        xenrt.TEC().logverbose(self.guestName)
        xenrt.TEC().logverbose(self.memory)
        xenrt.TEC().logverbose(self.guestNameList)
        xenrt.TEC().logverbose(self.vcpus)
        self.windowInstall=guest.TCXenServerWindowsInstall()
        self.windowInstall.run([self.machine, self.distro, self.guestNameList, self.memory, self.vcpus, self.inserttools])
        
        """Get the host and VM object"""
        self.host=self.getHost(self.machine)
        #self.windowInstall = self.host.createGenericWindowsGuest(name=self.guestNameList, distro=self.distro, vcpus=2, memory=self.memory)
        #self.guest = self.host.createGenericWindowsGuest(name=self.guestNameList, distro=self.distro, vcpus=self.vcpus, memory=self.memory)
        for expGuest in self.host.listGuests():
            if self.guestName==expGuest:
                self.targetGuest=self.getGuest(expGuest)

                
    def updateWindowsVM(self, arglist=None):

        windUpdateFinsish=r"""
var fs= new ActiveXObject('Scripting.FileSystemObject');
var WshShellObj = new ActiveXObject("WScript.Shell");
var fname2=fs.CreateTextFile("c:\\counter.txt", true);
var n=0, n1=0;
Delay(20000);
do
{
var WshShellExecObj = WshShellObj.Exec('tasklist /FI \"IMAGENAME eq wuauclt.exe\"');
var updateProcess=WshShellExecObj.Stdout.ReadAll();
var count=updateProcess.match(/wuauclt/g);
try{
var n=count.length;}
catch(exception){
Delay(5000);
continue;}
fname2.WriteLine(count+"'"+n+"'");
if(n>1)
{
var fname1=fs.CreateTextFile("c:\\entered2ndloop.txt", true);
do
{
var WshShellExecObj = WshShellObj.Exec('tasklist /FI \"IMAGENAME eq wuauclt.exe\"');
var updateProcess1=WshShellExecObj.Stdout.ReadAll();
var count1=updateProcess1.match(/wuauclt/g);
try{
var n1=count1.length;}
catch(exception){
Delay(5000);
continue;}
fname2.WriteLine(count1+"'"+n1+"'");
if(n1==1)
{
var fname1=fs.CreateTextFile("c:\\WindowsUpdated.txt", true);
break;
}
Delay(5000);
}while(true);
}
if(fs.FileExists("c:\\WindowsUpdated.txt")==true){
break;
}
Delay(5000);
}while(true);
function Delay(milliseconds) {
var start = new Date().getTime();
for (var i = 0; i < 1e7; i++) {
if ((new Date().getTime() - start) > milliseconds){
break;
}
}
}
"""
        startUpdateCheckBatch=r"""
c:\windUpdateFinsish.js
"""

        #Upgrade the Guest
        self.targetGuest.xmlrpcExec("reg add \"HKLM\\Software\\Policies\\Microsoft\\Windows\\WindowsUpdate\\AU\" /v NoAutoUpdate /t REG_DWORD /d 0 /f")
        self.targetGuest.xmlrpcExec("reg add \"HKLM\\Software\\Policies\\Microsoft\\Windows\\WindowsUpdate\\AU\" /v AUOptions /t REG_DWORD /d 3 /f")
        self.targetGuest.xmlrpcExec("reg add \"HKLM\\Software\\Policies\\Microsoft\\Windows\\WindowsUpdate\\AU\" /v NoAutoRebootWithLoggedOnUsers /t REG_DWORD /d 1 /f")
        
        try:
            self.targetGuest.xmlrpcExec("reg delete \"HKLM\\Software\\Policies\\Microsoft\\Windows\\WindowsUpdate\\AU\" /v ScheduledInstallDay /f")
        except:
            pass
        try:
            self.targetGuest.xmlrpcExec("reg delete \"HKLM\\Software\\Policies\\Microsoft\\Windows\\WindowsUpdate\\AU\" /v ScheduledInstallTime /f")
        except:
            pass

        xenrt.sleep(60)
        #Restart the windows automatic update service
        self.targetGuest.xmlrpcExec("net stop wuauserv")
        self.targetGuest.xmlrpcExec("net start wuauserv")
        
        #Detect Windows Updates
        self.targetGuest.xmlrpcExec("wuauclt /detectnow")
        xenrt.sleep(600)
        self.targetGuest.xmlrpcExec("wuauclt /updatenow")
        
        self.targetGuest.xmlrpcWriteFile("c:\\windUpdateFinsish.js",windUpdateFinsish)
        self.targetGuest.xmlrpcWriteFile("c:\\startUpdateCheckBatch.bat",startUpdateCheckBatch)
        self.targetGuest.xmlrpcStart("c:\\startUpdateCheckBatch.bat")
        
              
        self.timeOut = xenrt.util.timenow() + 20000
        while True:
            try:
                updateComplete = self.targetGuest.xmlrpcFileExists("c:\\WindowsUpdated.txt")
            except Exception, e:
                xenrt.TEC().warning("Exception checking for WindowsUpdated text file")
                xenrt.sleep(300)
                break
            if updateComplete:
                xenrt.TEC().logverbose("DTMResult text file found")
                self.targetGuest.xmlrpcStart("del /f c:\\WindowsUpdated.txt")
                break
            if xenrt.util.timenow() > self.timeOut:
                raise xenrt.XRTFailure("Timed out waiting for WindowsUpdated complete")
            xenrt.sleep(600)
        
        #Detect Windows Updates
        self.targetGuest.xmlrpcExec("wuauclt /SelfUpdateUnmanaged")
        xenrt.sleep(600)
        self.targetGuest.xmlrpcExec("wuauclt /updatenow")
        xenrt.sleep(1200)
        
        #Reboot the guest after registry change
        self.targetGuest.reboot()
        
    def disableFirewall(self, arglist=None):
        """Disable the firewall"""
        self.targetGuest.disableFirewall()
        
    def createADDomain(self, arglist=None):
        xenrt.TEC().logverbose(self.ADNAME)
        self.authserver = self.getGuest(self.ADNAME)
        self.authserver = xenrt.ActiveDirectoryServer(self.authserver, domainname="whql1234.com")
    
    def joinADDomain(self, arglist=None):
        self.authguest = self.getGuest(self.ADNAME)
        self.adIP = self.authguest.getIP()
        self.authserver = self.authguest.getActiveDirectoryServer()
        xenrt.TEC().logverbose(self.authserver.domainname)
        xenrt.TEC().logverbose(self.authserver.place.password)
        xenrt.TEC().logverbose(self.adIP)

        self.targetGuest.xmlrpcExec("netsh interface ip set dns \"Local Area Connection\" static %s"%(self.adIP))
        self.targetGuest.xmlrpcExec("netsh firewall set opmode mode=DISABLE profile=ALL")
        self.targetGuest.xmlrpcExec("netdom join %%computername%% /domain:%s /userd:%s /passwordd:%s" %(self.authserver.domainname, "Administrator", self.authserver.place.password))

        self.targetGuest.waitForDaemon(90, desc="Guest check")
        self.targetGuest.reboot()

    def enableWindowsGuestAcc(self, arglist=None):
        self.targetGuest.xmlrpcExec("net user Guest /active:yes")
        self.targetGuest.xmlrpcExec("reg add \"HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon\" /v DefaultDomainName /d whql1234.com /f")
        self.targetGuest.xmlrpcExec("reg add \"HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon\" /v DefaultUserName /d Administrator /f")
        self.targetGuest.xmlrpcExec("reg add \"HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon\" /v DefaultPassword /d xensource /f")
        self.targetGuest.xmlrpcExec("reg add \"HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon\" /v AutoAdminLogon /d 1 /f")
        self.targetGuest.reboot()
     
    def disableUAC(self, arglist=None):
        self.targetGuest.xmlrpcExec("reg add \"HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\System\" /v EnableLUA /t REG_DWORD /d 0 /f")
        #Reboot the guest after registry change
        self.targetGuest.reboot()

    def removeexecdaemon(self, arglist=None):
        self.targetGuest.xmlrpcExec("reg delete \"HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run\" /v execdaemon.cmd /f")
        
    def whqlRegChange(self, arglist=None):
        self.targetGuest.xmlrpcExec("reg add \"HKLM\\SYSTEM\\CurrentControlSet\\services\\xenvif\\Parameters\" /v ReceiverAllowGsoPackets /t REG_DWORD /d 00000000 /f")
        self.targetGuest.xmlrpcExec("reg add \"HKLM\\SYSTEM\\CurrentControlSet\\services\\xenvif\\Parameters\" /v ReceiverCalculateChecksums /t REG_DWORD /d 00000001 /f")
        self.targetGuest.xmlrpcExec("reg add \"HKLM\\SYSTEM\\CurrentControlSet\\services\\xenvif\\Parameters\" /v PnpBusInterface /t REG_DWORD /d 00000001 /f")

    def disableDNSClient(self, arglist=None):
        self.targetGuest.xmlrpcExec("sc stop dnscache")
        self.targetGuest.xmlrpcExec("sc config dnscache start= disabled")
        #self.targetGuest.reboot()

    def disableGuestAgent(self, arglist=None):
        self.targetGuest.xmlrpcExec("sc stop XenSvc")
        self.targetGuest.xmlrpcExec("sc config XenSvc start= disabled")
        #self.targetGuest.reboot()

    def disableDriverSignCheck(self, arglist=None):
        self.targetGuest.xmlrpcExec("bcdedit /set testsigning on")
        self.targetGuest.reboot()

    def makeHostFileEntry(self, arglist=None):
        self.DTMServerGuest = self.getGuest(self.DTMServerName)
        self.DTMServerIP = self.DTMServerGuest.getIP()
        self.DTMServerHostName = self.DTMServerGuest.getName()
        xenrt.TEC().logverbose(self.DTMServerIP)
        xenrt.TEC().logverbose(self.DTMServerHostName)
        self.targetGuest.xmlrpcExec("echo "+self.DTMServerIP+" "+self.DTMServerHostName+" C:\Windows\System32\drivers\etc\Hosts")

    @xenrt.irregularName
    def SVVPDTMServerInstall(self, arglist=None):
        self.targetGuest.changeCD(self.ISO_NAME)
        xenrt.sleep(30)
        
        DTMResScript = r"""
Delay(20000);
var expString="No tasks are running";
var WshShellObj = new ActiveXObject("WScript.Shell");
for(var count=0; count<1100; count++)
{
var WshShellExecObj2 = WshShellObj.Exec("tasklist /FI \"imagename eq Kitsetup.exe*\"");
var kitSetUpStats=WshShellExecObj2.StdOut.ReadAll();
var n=kitSetUpStats.indexOf(expString);
if(n!=-1){
Delay(20000);
var fs= new ActiveXObject('Scripting.FileSystemObject');
var WshShellObj = new ActiveXObject("WScript.Shell");
var WshShellExecObj = WshShellObj.Exec("tasklist /FI \"imagename eq DTMService.exe*\"");
var kitSetUpStats=WshShellExecObj.StdOut.ReadAll();
var n1=kitSetUpStats.indexOf(expString);
var WshShellExecObj = WshShellObj.Exec("tasklist /FI \"imagename eq sqlservr.exe*\"");
var kitSetUpStats=WshShellExecObj.StdOut.ReadAll();
var n2=kitSetUpStats.indexOf(expString);
var WshShellExecObj = WshShellObj.Exec("tasklist /FI \"imagename eq WLKSvc.exe*\"");
var kitSetUpStats=WshShellExecObj.StdOut.ReadAll();
var n3=kitSetUpStats.indexOf(expString);
if(n1==-1 && n2==-1 && n3==-1){
var fs= new ActiveXObject('Scripting.FileSystemObject');
var fname1=fs.CreateTextFile("c:\\DTMServiceResult.txt", true);
}
break;
}
Delay(5000);
}
function Delay(milliseconds) {
var start = new Date().getTime();
for (var i = 0; i < 1e7; i++) {
if ((new Date().getTime() - start) > milliseconds){
break;
}
}
}
""" 
        DTMInstallScript = r"""
d:\\Kitsetup.exe /ui-level express /install {A6E93EA5-52E2-4F16-8AB2-A3A97533FE83}
d:\\Kitsetup.exe /ui-level express /install {EF30275E-5D68-40D2-8AF2-2665AAFCB555}
d:\\Kitsetup.exe /ui-level express /install {98EF97A5-C520-498D-8F0F-2C551636E4CC}
d:\\Kitsetup.exe /ui-level express /install {8868103C-3527-47FA-A116-84DFD1AE954E}
d:\\Kitsetup.exe /ui-level express /install {A9D61D70-94AD-43FF-B770-B05D4A633C34}
d:\\Kitsetup.exe /ui-level express /install {14DDB41C-3868-4566-B508-4F20DD649DE4}
echo DONE > c:\\DTMResult.txt
""" 
        self.targetGuest.xmlrpcWriteFile("c:\\DTMInstallScript.bat",DTMInstallScript)
        self.targetGuest.xmlrpcStart("c:\\DTMInstallScript.bat")
        
        self.timeOut = xenrt.util.timenow() + 7000
        while True:
            try:
                DTMResult = self.targetGuest.xmlrpcFileExists("c:\\DTMResult.txt")
            except Exception, e:
                xenrt.TEC().warning("Exception checking for DTMResult text file")
                xenrt.sleep(300)
                break
            if DTMResult:
                xenrt.TEC().logverbose("DTMResult text file found")
                self.targetGuest.xmlrpcStart("del /f c:\\DTMInstallScript.bat")
                self.targetGuest.xmlrpcStart("del /f c:\\DTMResult.txt")
        
                break
            if xenrt.util.timenow() > self.timeOut:
                raise xenrt.XRTFailure("Timed out waiting for DTM installationto complete")
            xenrt.sleep(60)
            
        self.targetGuest.xmlrpcWriteFile("c:\\DTMResScript.js",DTMResScript)
        self.targetGuest.xmlrpcStart("c:\\DTMResScript.js")
            
        self.timeOut = xenrt.util.timenow() + 7000
        while True:
            try:
                DTMResult = self.targetGuest.xmlrpcFileExists("c:\\DTMServiceResult.txt")
            except Exception, e:
                xenrt.TEC().warning("Exception checking for DTMServiceResult text file")
                xenrt.sleep(300)
                break
            if DTMResult:
                xenrt.TEC().logverbose("DTMServiceResult text file found")
                self.targetGuest.xmlrpcStart("del /f c:\\DTMServiceResult.txt")
                self.targetGuest.xmlrpcStart("del /f c:\\DTMResScript.js")
                break
            if xenrt.util.timenow() > self.timeOut:
                raise xenrt.XRTFailure("Timed out waiting for DTM installation to complete")
            xenrt.sleep(60)
    
    def installDotNet(self, arglist=None):
        if self.DotNetVersion == "3.5":
            self.targetGuest.installDotNet35()
        elif self.DotNetVersion =="4":
            self.targetGuest.installDotNet4()
            
    def changeHostName(self, arglist=None):
        self.targetGuest.xmlrpcExec("wmic computersystem where name=\"%%COMPUTERNAME%%\" call rename name=\"%s\""%(self.winHostName))
        self.targetGuest.reboot()

    def installPVDrivers(self, arglist=None):
        self.targetGuest.installDrivers()
    
    @xenrt.irregularName
    def SVVPDTMClientInstall(self, arglist=None):
        self.targetGuest.xmlrpcExec("\\\\%s\DtmInstall\\Client\\Setup.exe /qb ICFAGREE=Yes" %(self.DTMServerName) )
        
        DTMClientInstall = r"""
Delay(20000);
var expString="No tasks are running";
var WshShellObj = new ActiveXObject("WScript.Shell");
for(var count=0; count<1100; count++)
{
var WshShellExecObj2 = WshShellObj.Exec("tasklist /FI \"imagename eq Setup.exe*\"");
var kitSetUpStats=WshShellExecObj2.StdOut.ReadAll();
var n=kitSetUpStats.indexOf(expString);
if(n!=-1){
Delay(20000);
var fs= new ActiveXObject('Scripting.FileSystemObject');
var WshShellObj = new ActiveXObject("WScript.Shell");
var WshShellExecObj = WshShellObj.Exec("tasklist /FI \"imagename eq WLKSvc.exe*\"");
var kitSetUpStats=WshShellExecObj.StdOut.ReadAll();
var n=kitSetUpStats.indexOf(expString);
if(n==-1){
var fs= new ActiveXObject('Scripting.FileSystemObject');
var fname1=fs.CreateTextFile("c:\\DTMClientInstalled.txt", true);
}
break;
}
Delay(5000);
}
function Delay(milliseconds) {
var start = new Date().getTime();
for (var i = 0; i < 1e7; i++) {
if ((new Date().getTime() - start) > milliseconds){
break;
}
}
}"""
        
        self.targetGuest.xmlrpcWriteFile("c:\\DTMClientInstall.js",DTMClientInstall)
        self.targetGuest.xmlrpcStart("c:\\DTMClientInstall.js")
        
        self.timeOut = xenrt.util.timenow() + 150
        while True:
            try:
                DTMClientResult = self.targetGuest.xmlrpcFileExists("c:\\DTMClientInstalled.txt")
            except Exception, e:
                xenrt.TEC().warning("Exception checking for DTMClientInstalled text file")
                xenrt.sleep(300)
                break
            if DTMClientResult:
                xenrt.TEC().logverbose("DTMClientInstalled text file found")
                self.targetGuest.xmlrpcStart("del /f c:\\DTMClientInstalled.txt")
                self.targetGuest.xmlrpcStart("del /f c:\\DTMClientInstall.js")
                break
            if xenrt.util.timenow() > self.timeOut:
                raise xenrt.XRTFailure("Timed out waiting for DTM client installation to complete")
            xenrt.sleep(60)
        
        self.targetGuest.reboot()
    
    @xenrt.irregularName    
    def SVVPDTMStudioInstall(self, arglist=None):
        self.targetGuest.xmlrpcExec("\\\\%s\\DtmInstall\\Studio\\setup.exe /qb" %(self.DTMServerName) )
    
        DTMStudioInstallComp = r"""
Delay(20000);
var expString="No tasks are running";
var WshShellObj = new ActiveXObject("WScript.Shell");
for(var count=0; count<1100; count++)
{
Delay(20000);
var fs= new ActiveXObject('Scripting.FileSystemObject');
var WshShellObj = new ActiveXObject("WScript.Shell");
var WshShellExecObj = WshShellObj.Exec("tasklist /FI \"imagename eq msiexec.exe*\"");
var kitSetUpStats=WshShellExecObj.StdOut.ReadAll();
var n=kitSetUpStats.indexOf(expString);
if(n==-1){
var fs= new ActiveXObject('Scripting.FileSystemObject');
var fname1=fs.CreateTextFile("c:\\DTMStudioInstalled.txt", true);
break;
}
Delay(5000);
}
function Delay(milliseconds) {
var start = new Date().getTime();
for (var i = 0; i < 1e7; i++) {
if ((new Date().getTime() - start) > milliseconds){
break;
}
}
}"""
        
        self.targetGuest.xmlrpcWriteFile("c:\\DTMStudioInstallComp.js",DTMStudioInstallComp)
        self.targetGuest.xmlrpcStart("c:\\DTMStudioInstallComp.js")
        
        self.timeOut = xenrt.util.timenow() + 150
        while True:
            try:
                DTMStudioResult = self.targetGuest.xmlrpcFileExists("c:\\DTMStudioInstalled.txt")
            except Exception, e:
                xenrt.TEC().warning("Exception checking for DTMStudioInstalled.txt text file")
                xenrt.sleep(300)
                break
            if DTMStudioResult:
                xenrt.TEC().logverbose("DTMStudioInstalled text file found")
                self.targetGuest.xmlrpcStart("del /f c:\\DTMStudioInstalled.txt")
                self.targetGuest.xmlrpcStart("del /f c:\\DTMStudioInstallComp.js")
                break
            if xenrt.util.timenow() > self.timeOut:
                raise xenrt.XRTFailure("Timed out waiting for DTM studio installation to complete")
            xenrt.sleep(60)
            
class DTMServerSetup(SVVPBase):
    def run(self, arglist=None):
        self.disableFirewall()
        self.changeHostName()
        self.joinADDomain()
        self.enableWindowsGuestAcc()
        self.disableUAC()
        self.installDotNet()
        self.installPVDrivers()
        self.SVVPDTMServerInstall()
        self.SVVPDTMStudioInstall()

class DTMClientSetup(SVVPBase):
    def run(self, arglist=None):
        self.updateWindowsVM()
        self.disableFirewall()
        self.changeHostName()
        self.joinADDomain()
        self.enableWindowsGuestAcc()
        self.disableDriverSignCheck()
        self.disableUAC()
        self.whqlRegChange()
        self.installDotNet()
        self.installPVDrivers()
        self.SVVPDTMClientInstall()
        self.removeexecdaemon()
        self.disableGuestAgent()
        self.disableDNSClient()

class ADServerSetup(SVVPBase):
    def prepare(self, arglist=None):
        if arglist and len(arglist) > 0:
            self.machine = arglist[0]
        else:
            raise xenrt.XRTError("No machine specified")
 
        for arg in arglist[1:]:
            l = string.split(arg, "=", 1)
            if l[0] == "adVMName":
                self.ADNAME = l[1]
                
    def run(self, arglist=None):
        self.createADDomain()
        #self.disableFirewall()
        #self.enableWindowsGuestAcc()
        #self.changeHostName()
