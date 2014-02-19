#
# XenRT: Test harness for Xen and the XenServer product family
#
# Specific regression testcases
#
# Copyright (c) 2008 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import socket, re, string, time, traceback, sys, random, copy, threading, os.path, xml.dom.minidom
import xenrt, xenrt.util, xenrt.lib.xenserver, uuid, XenAPI

class TC8297(xenrt.TestCase):
    """Regression test for CA-23591 (Xen crash when VCPU setting is set to 1)"""

    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid=tcid)
        self.host = None
        self.guest = None

    def prepare(self, arglist=None):
        # Install a linux VM
        self.host = self.getDefaultHost()
        self.guest = self.host.createGenericLinuxGuest()
        self.guest.shutdown()

    def run(self, arglist=None):
        # Set (and check) VCPUs-params:weight=1 for the VM
        self.guest.paramSet("VCPUs-params:weight", 1)
        weight = self.guest.paramGet("VCPUs-params", "weight")
        if str(weight) != "1":
            raise xenrt.XRTError("VCPUs-params:weight setting failed (we read "
                                 "%s after setting it to 1)" % (weight))

        # Try and start the VM
        try:
            # We do it this way as the start() method has a 1 hour timeout!
            cli = self.guest.getCLIInstance()
            cli.execute("vm-start", "uuid=%s" % (self.guest.getUUID()),
                        timeout=300)
        except Exception, e:
            # See if the host is reachable
            try:
                self.host.checkReachable()
                # It's reachable, but check the uptime
                uptime = self.host.execdom0("uptime")
                r = re.search(r"up (\d+) min", uptime)
                if r and int(r.group(1)) < 10:
                    xenrt.TEC().logverbose("Host reachable but uptime less "
                                           "than 10 minutes, assuming crashed")
                    raise Exception()
            except:
                raise xenrt.XRTFailure("CA-23591 Host crash when starting VM "
                                       "with VCPU weight set to 1 (Lowest)")
            # Some other failure...
            raise xenrt.XRTFailure("Exception when starting guest (host still "
                                   "reachable): %s" % (str(e)))

        # Check the VM
        self.guest.check()

    def preLogs(self):
        if self.host:
            try:
                self.host.waitForSSH(600, desc="Host boot for log collection")
            except:
                pass

class TC8357(xenrt.TestCase):
    """Regression test for CA-21760. Dom-0 lockup when shutting down large 64-bit VM."""

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.guest = self.getLocation()
        if self.guest.getState() != "DOWN":
            self.guest.shutdown()

    def run(self, arglist):
        livefile = "/tmp/liveness"
        livesleep = 2

        self.startAsync(self.host,
                       "while /bin/true; do echo `date` >> %s; sleep %s; done" %
                       (livefile, livesleep))
        self.guest.start()
        time.sleep(120)
        self.guest.shutdown()
        
        data = self.host.execdom0("cat %s" % (livefile))
        data = data.strip()
        data = data.split("\n")
        data = map(lambda x:time.strptime(x, "%a %b %d %H:%M:%S %Z %Y"), data)
        data = map(lambda x:time.mktime(x), data)
        differences = [ (data[x+1]-data[x]) for x in range(len(data)-1) ]
        gaps = filter(lambda x:x > 2*livesleep, differences)
        if gaps:
            raise xenrt.XRTFailure("Found gap(s) larger than %ss in liveness file." % (2*livesleep))

class TC8456(xenrt.TestCase):
    """Regression test for CA-25183. Live migration of HVM VMs with empty CD
    drives fails."""

    def prepare(self, arglist):
        self.host = self.getDefaultHost()
        self.guest = self.host.createGenericWindowsGuest()

        # Eject the Windows CD it will have been installed from
        self.guest.changeCD(None)

        # Verify there is a CD drive
        cds = self.host.minimalList("vm-cd-list", args="uuid=%s" % 
                                                  (self.guest.getUUID()))
        if len(cds) == 0:
            raise xenrt.XRTError("No CD drive present on guest")
        elif len(cds) > 1:
            # We should just have the VBD, if we have multiple things, we've
            # a VDI present
            raise xenrt.XRTError("CD doesn't appear to have ejected")

    def run(self, arglist):
        # Do a localhost live migrate
        self.guest.migrateVM(self.host, live="true")

class TC8607(xenrt.TestCase):
    """Test for time drift on Windows 2008"""

    GUESTA = "VM1"
    GUESTB = "VM2"

    WORKLOADS = ["Burnintest", "Prime95", "IOMeter"]

    def prepare(self, arglist):
        self.guesta = self.getGuest(self.GUESTA)
        self.guestb = self.getGuest(self.GUESTB)
        self.guesta.xmlrpcUnpackTarball("%s/timedrift.tgz" % 
                                        (xenrt.TEC().lookup("TEST_TARBALL_BASE")),
                                        "c:\\")
        self.awork = self.guesta.startWorkloads(self.WORKLOADS)
        self.bwork = self.guestb.startWorkloads(self.WORKLOADS)
        

    def run(self, arglist):
        result = self.guesta.xmlrpcExec("c:\\timedrift\\timetest.exe", 
                                         returndata=True, 
                                         timeout=1800)
        maxdrift = max(map(lambda x:int(x, 16), (re.findall("freq 0x([a-fA-F0-9]+)", result))))
        if maxdrift > 20:
            raise xenrt.XRTFailure("Found time drift of 0x%s." % (maxdrift))

    def postRun(self):
        try: self.guesta.stopWorkloads(self.awork)
        except: pass
        try: self.guestb.stopWorkloads(self.bwork)
        except: pass

class TC9048(xenrt.TestCase):
    """Regression test for CA-26736 (New master didn't restart xapi until poked
       with a CLI command"""

    def prepare(self, arglist=None):
        self.pool = self.getDefaultPool()
        self.originalMaster = self.pool.master
        self.newMaster = self.pool.getSlaves()[0]
        self.startCount = self.countRestarts(self.newMaster)

    def run(self, arglist=None):
        xenrt.TEC().logverbose("Designating %s as the new master (from %s)" %
                               (self.newMaster.getName(),
                                self.originalMaster.getName()))

        cli = self.pool.getCLIInstance()
        cli.execute("pool-designate-new-master", "host-uuid=%s" %
                                               (self.newMaster.getMyHostUUID()))
        xenrt.TEC().logverbose("Updating harness metadata")
        self.pool.designateNewMaster(self.newMaster, metadataOnly=True)
        time.sleep(300)

        # Check for the "restarting xapi in different operating mode"
        newCount = self.countRestarts(self.newMaster)
        if newCount == self.startCount:
            # We don't appear to have restarted, poke it and see if that helps
            xenrt.TEC().logverbose("New master has not restarted, attempting CLI 'poke'")
            try:
                self.newMaster.getHostParam("host-metrics-live")
            except:
                pass
            time.sleep(60)
            if self.countRestarts(self.newMaster) > self.startCount:
                raise xenrt.XRTFailure("CA-26736 New master didn't restart "
                                       "xapi until 'poked' with a CLI command")
            raise xenrt.XRTFailure("New master didn't restart xapi, even after "
                                   "CLI command 'poke'")

        # It appears to have restarted, do a simple CLI check
        try:
            self.newMaster.getHostParam("host-metrics-live")
        except:
            raise xenrt.XRTFailure("New master appeared to restart xapi, but "
                                   "CLI command test failed")

    def countRestarts(self, host):
        """Count the number of xapi restarts"""
        data = host.execdom0("grep -c 'restarting xapi in different operating mode' /var/log/xensource.log || true")
        count = int(data.strip())
        return count

class TC9051(xenrt.TestCase):
    """Regression test for sr-uuid issue from CA-28742"""

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()

        # Get the host default SR
        self.defaultSR = self.host.lookupDefaultSR()
        # Create an 8GB file SR to use as the destination
        self.fileSR = self.host.createFileSR(8192)

        # Install a VM
        self.guest = self.host.createGenericLinuxGuest(sr=self.defaultSR)
        self.uninstallOnCleanup(self.guest)
        self.guest.preCloneTailor()
        self.guest.shutdown()

        # Turn it in to a template
        self.guest.paramSet("is-a-template", "true")

        self.newGuest = None

    def run(self, arglist=None):
        # Attempt to 'install' a new VM from the template we created
        cli = self.host.getCLIInstance()
        args = []
        args.append("new-name-label=\"TC9051\"")
        args.append("sr-uuid=%s" % (self.fileSR))
        args.append("template-uuid=%s" % (self.guest.getUUID()))
        newUUID = cli.execute("vm-install", string.join(args), strip=True)
        self.newGuest = newUUID

        # See if the newUUID is on the correct SR
        args = []
        args.append("uuid=%s" % (newUUID))
        args.append("vdi-params=sr-uuid")
        args.append("vbd-params=null")
        sruuids = self.host.minimalList("vm-disk-list", args=string.join(args))
        for sru in sruuids:
            if sru != self.fileSR:
                raise xenrt.XRTFailure("sr-uuid parameter to vm-install ignored "
                                       "when installing template with attached "
                                       "disks",
                                       data="Expecting SR uuid %s, found %s" %
                                            (self.fileSR, sru))

    def postRun(self):
        if self.newGuest:
            try:
                # Remove the new VM
                cli = self.host.getCLIInstance()
                cli.execute("vm-uninstall", "uuid=%s force=true" %
                                            (self.newGuest))
            except:
                pass
        if self.guest:
            try:
                self.guest.paramSet("is-a-template", "false")
                self.guest.uninstall()
            except:
                pass
        if self.fileSR:
            try:
                self.host.destroyFileSR(self.fileSR)
            except:
                pass

class TC9222(xenrt.TestCase):
    """Regression test for CA-30367"""

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.guest = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guest)
        self.guest.suspend()

    def run(self, arglist=None):
        data = self.guest.paramGet("allowed-operations").strip()
        allowedOps = data.split("; ")
        if "hard_reboot" in allowedOps:
            raise xenrt.XRTFailure("CA-30367 Suspended VM has hard_reboot as "
                                   "an allowed operation")

        
class TC10189(xenrt.TestCase):

    VDISIZE = 30 * xenrt.MEGA
    ERRORCODE = 999

    def prepare(self, arglist=[]):

        args = xenrt.util.strlistToDict(arglist)
        self.VDISIZE = int(args.get("vdisize") or self.VDISIZE)

        self.host = self.getDefaultHost()

        local_dir = xenrt.TEC().tempDir()
        remote_dir = self.host.tempDir()
        mount_dir = self.host.tempDir()
        
        vdi_name = "vdi" + str(int(time.time()))
        self.vdi_from = self.host.createVDI(self.VDISIZE, name=vdi_name+"_from")
        self.vdi_to = self.host.createVDI(self.VDISIZE, name=vdi_name+"_to")

        db_name = "db" + str(int(time.time()))
        db_tmp = os.path.join(remote_dir, db_name + ".db")
        db_xml = os.path.join(local_dir, db_name + ".db")
        self.host.execdom0("xe pool-dump-database file-name=%s" % db_tmp)
        
        vdi_key = os.path.join(mount_dir, vdi_name + ".key")
        self.vdi_img_host = os.path.join(remote_dir, vdi_name + ".img")
        self.vdi_img_controller = os.path.join(local_dir, vdi_name + ".img")

        make_key_name = "make_key.sh"
        make_key_cmd = """#!/bin/sh
mkfs -t ext3 /dev/${DEVICE}
mount /dev/${DEVICE} %s
touch %s
umount /dev/${DEVICE}""" % (mount_dir, vdi_key)
        make_key_tmp = os.path.join(local_dir, make_key_name)
        fd = open(make_key_tmp, "w")
        fd.write(make_key_cmd)
        fd.close()
        self.make_key_sh = os.path.join(remote_dir, make_key_name)

        copy_key_name = "copy_key.sh"
        copy_key_cmd = """#!/bin/sh
dd if=/dev/${DEVICE} of=%s""" % (self.vdi_img_host)
        copy_key_tmp = os.path.join(local_dir, copy_key_name)
        fd = open(copy_key_tmp, "w")
        fd.write(copy_key_cmd)
        fd.close()
        self.copy_key_sh = os.path.join(remote_dir, copy_key_name)

        find_key_name = "find_key.sh"
        find_key_cmd = """#!/bin/sh
mount /dev/${DEVICE} %s
KEY=%s
if [ -e ${KEY} ]; then echo Found key ${KEY}; FLAG=0; else echo Missing key ${KEY}; FLAG=%s; fi
umount /dev/${DEVICE}
exit $FLAG""" % (mount_dir, vdi_key, self.ERRORCODE)
        find_key_tmp = os.path.join(local_dir, find_key_name)
        fd = file(find_key_tmp, "w")
        fd.write(find_key_cmd)
        fd.close()
        self.find_key_sh = os.path.join(remote_dir, find_key_name)

        sftp = self.host.sftpClient()
        try:
            sftp.copyTo(make_key_tmp, self.make_key_sh)
            sftp.copyTo(find_key_tmp, self.find_key_sh)
            sftp.copyTo(copy_key_tmp, self.copy_key_sh)
        finally:
            sftp.close()

        self.host.execdom0("chmod a+x " + self.make_key_sh)
        self.host.execdom0("chmod a+x " + self.find_key_sh)
        self.host.execdom0("chmod a+x " + self.copy_key_sh)
        self.host.execdom0("/opt/xensource/debug/with-vdi %s %s" % (self.vdi_from, self.make_key_sh))
        if not self.findKey(self.vdi_from): raise xenrt.XRTError("Secret key was not found on the VDI")
        self.host.execdom0("/opt/xensource/debug/with-vdi %s %s" % (self.vdi_from, self.copy_key_sh))

        sftp = self.host.sftpClient()
        try:
            sftp.copyFrom(db_tmp, db_xml)
            sftp.copyFrom(self.vdi_img_host, self.vdi_img_controller)
        finally:
            sftp.close()

        db_dom = xml.dom.minidom.parse(db_xml)
        vdi_table = [x for x in db_dom.getElementsByTagName('table')
                     if x.attributes['name'].value == 'VDI'][0]
        vdi_entry = [x for x in vdi_table.getElementsByTagName('row')
                     if x.attributes['uuid'].value == self.vdi_to][0]
        self.vdi_ref = vdi_entry.attributes['_ref'].value


    def gencmd(self, img, hostname):
        root_name = "root"
        root_pass = self.host.lookup("DEFAULT_PASSWORD")
        cmd = ("curl -T %s http://%s:%s@%s/import_raw_vdi?vdi=%s" %
               (img, root_name, root_pass, hostname, self.vdi_ref))
        return cmd

    # with-vdi script doesn't preserve the error code, this is a work around
    def findKey(self, vdi):
        data = self.host.execdom0("/opt/xensource/debug/with-vdi %s %s" % (vdi, self.find_key_sh))
        return data.find("Found") >= 0
        

    def run(self, arglist=[]):

        # Upload from localhost
        cmd = self.gencmd(self.vdi_img_host, "localhost")
        timeout = self.VDISIZE / xenrt.MEGA
        xenrt.TEC().progress("Start to upload the image from local host and verify")
        try:
            self.runAsync(self.host, [cmd], timeout=timeout)
        finally:
            self.host.execdom0("killall curl || true")
        if not self.findKey(self.vdi_to): raise xenrt.XRTFailure("Secret key was not found on the VDI")
        xenrt.TEC().logverbose("Suceeded in verifying import_raw_vdi http call from its own host")

        # Upload from scheduler
        cmd = self.gencmd(self.vdi_img_controller, self.host.getIP())
        timeout = self.VDISIZE / xenrt.MEGA * 10
        xenrt.TEC().progress("Start to upload the image from controller and verify")
        xenrt.command(cmd, timeout=timeout)
        if not self.findKey(self.vdi_to): raise xenrt.XRTFailure("Secret key was not found on the VDI")
        xenrt.TEC().logverbose("Suceeded in verifying import_raw_vdi http call from the controller")

class TC17768(xenrt.TestCase):
    """Regression test for CA-75710"""

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.bumpToolsISO()

        for guest in self.host.guests.values():
            if guest.getState() != "UP":
                guest.start()

        time.sleep(30)
        self.host.execdom0("xe-toolstack-restart")
        time.sleep(60)

    def run(self, arglist=None):
        for guest in self.host.guests.values():
            if guest.paramGet("PV-drivers-up-to-date") == "true":
                raise xenrt.XRTFailure("field PV-drivers-up-to-date not updated")

    def bumpToolsISO(self):
        from os.path import basename
        
        # Find the highest major version and increase it by 1
        isos = self.host.execdom0("ls -1 /opt/xensource/packages/iso/xs-tools-*.iso")
        versions = re.findall("(\d+\.\d+\.\d+)\.iso", isos)
        majors = map(lambda x: int(x.split('.')[0]), versions)
        majors.sort()
        self.host.execdom0("cp /opt/xensource/packages/iso/%s /opt/xensource/packages/iso/xs-tools-%s.0.0.iso" % \
                (basename(isos.splitlines()[0]), majors[0] + 1))


class _DBTooLarge(xenrt.TestCase):
    """ Base class for hfx-340 and hfx-368 """
    
    NUM_VDIS = 200

    def prepare(self, arglist=None):
        self.pool = self.getDefaultPool()
        self.host = self.pool.master
        self.slave = self.pool.getSlaves()[0]

        # Allow the number of VDIs to be configureable
        if len(arglist) >= 1:
            self.NUM_VDIS = int(arglist[0])
            
        self.session = XenAPI.Session(
            "http://%s" % (self.host.getIP()))

        self.session.xenapi.login_with_password("root", self.host.password)
        self.sr = self.session.xenapi.SR.get_all_records_where(
                "field \"name__label\" = \"Local storage\"")
        self.sr = self.sr.keys()[0]

        self.session.xenapi.session.add_to_other_config(self.session._session, 
            "_sm_session", self.sr) 

        name = "XenServer rocks my XML socks, " * 10000
        self.session.xenapi.SR.scan(self.sr)

        vdis = []
        for i in range(self.NUM_VDIS):
            #ensure we don't duplicate vdis which would result in exception
            while 1: 
                vdiuuid = str(uuid.uuid4())
                if vdiuuid in vdis:
                    continue
                vdis.append(vdiuuid)
                break

            ref = self.session.xenapi.VDI.db_introduce(vdiuuid, name, "desc", self.sr, 
                "user", False, False, {}, vdiuuid)
            xenrt.TEC().logverbose("Creating %s [%s]" % (vdiuuid, ref))
            # some time for xapi to settle and flush the vdi data to disk
            #time.sleep(120) 

class TC17767(_DBTooLarge):
    """Regression for CA-75708"""

    def run(self, arglist):
        self.slave.execdom0("xe-toolstack-restart")
        self.slave.waitForEnabled(600, 
            desc="Slave never enabled: possible cause: VDI table too long [CA-75708]")

    def postrun(self):
        self.session.xenapi.SR.scan(self.sr)

class TC17894(_DBTooLarge):
    """ Regression test for CA-79715 """

    def run(self, arglist=None):
        pool = self.getDefaultPool()
        slave = pool.getSlaves()[0]
        cli = slave.getCLIInstance()

        script="""#!/usr/bin/python
import XenAPI
session = XenAPI.xapi_local()
session.xenapi.login_with_password("root", "%s")
session.xenapi.VDI.get_all_records()\n""" % (self.slave.password)

        fn = xenrt.TEC().tempFile()
        f = open(fn, "w")
        f.write(script)
        f.close()

        sftp = self.slave.sftpClient()
        try:
            sftp.copyTo(fn, "/tmp/local/kaboom.sh")
        finally:
            sftp.close()

        try:            
            self.slave.execdom0("chmod +x /tmp/local/kaboom.sh && /tmp/local/kaboom.sh")
        except:
            raise xenrt.XRTFailure("we failed to retrieve all VDI records from a slave, possibly caused by CA-79715")

class TC20621(xenrt.TestCase):
    """Regression test for CA-116436"""

    def run(self, arglist=None):
        host = self.getDefaultHost()
        host.execdom0("vhd-util create -n /tmp/ca116436.vhd -s 8 -S 2097152")
        rc = host.execdom0("vhd-util read -n /tmp/ca116436.vhd -b 0 -c 1048575 > /dev/null", retval="code")
        if rc == 139: # 139 = Segmentation Fault
            raise xenrt.XRTFailure("CA-116436 vhd-util read segfaults if a VHD is created with maximum -S size")

