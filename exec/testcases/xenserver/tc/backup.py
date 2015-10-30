#
# XenRT: Test harness for Xen and the XenServer product family
#
# Testcases for backup / disaster recovery features.
#
# Copyright (c) 2008 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and conditions
# as licensed by Citrix Systems, Inc. All other rights reserved.
#

import string, time, re, traceback, sys
import xml.dom.minidom
import calendar, random, os, glob, XenAPI, copy
import xenrt, testcases, xenrt.lib.xenserver
from xenrt.lazylog import step, comment, log, warning

class TC8226(xenrt.TestCase):
    """Smoketest of metadata backup and restore (aka Portable SRs)"""

    BACKUP_SR = "iscsi"

    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid=tcid)
        self.pool = None
        self.sruuid = None
        self.sr = None
        self.guests = []
        self.template = None

    def prepare(self, arglist=None):
        step("Set up a pool of 2 hosts, using iSCSI storage")
        self.pool1 = self.getPool("RESOURCE_POOL_0")
        self.pool2 = self.getPool("RESOURCE_POOL_1")
        
        if self.BACKUP_SR == "iscsi":
            self.sr = xenrt.lib.xenserver.ISCSIStorageRepository(self.pool1.master, "iSCSI", thin_prov=(self.tcsku=="thin"))
            self.sr.create(subtype="lvm")
        else:
            nfs = xenrt.ExternalNFSShare().getMount()
            r = re.search(r"([0-9\.]+):(\S+)", nfs)
            if not r:
                raise xenrt.XRTError("Unable to parse NFS paths %s" % (nfs))
            self.sr = xenrt.lib.xenserver.NFSStorageRepository(self.pool1.master, "nfs")
            self.sr.create(r.group(1), r.group(2))
        
        self.pool1.addSRToPool(self.sr)
        if self.BACKUP_SR == "iscsi":
            self.sruuid = self.pool1.master.minimalList("sr-list", args="type=lvmoiscsi")[0]
        else:
            self.sruuid = self.pool1.master.minimalList("sr-list", args="type=nfs")[0]

        step("Install a VM, and make it a template")
        t = self.pool1.master.createGenericLinuxGuest()
        self.template = t
        t.preCloneTailor()
        t.shutdown()
        t.paramSet("is-a-template", "true")
        t.removeVIF("eth0")
        password = t.password
        
        step("Install 4 VMs from the template")
        for i in range(4):
            name = "guest%u" % (i)
            g = self.pool1.master.guestFactory()(name,
                                                template=t.getName(),
                                                password=password)
            g.install(self.pool1.master)
            g.execguest("touch /vm%u" % (i))
            if i == 1:
                g.changeCD("xs-tools.iso")
                
            # shut it down
            g.shutdown()

            # copy it from local storage to the defined SR
            newGuest = g.copyVM(name="copy%u"%i, sruuid=self.sruuid)
            
            # delete it from local storage
            g.uninstall()
            
            self.guests.append(newGuest)
            
        step("copy the template to the defined storage")
        self.template = t.copyVM(name="copy" + t.getName(), sruuid=self.sruuid)
        
        step("delete the template from local storage")
        self.pool1.master.removeTemplate(t.uuid)
        
        step("set default SR to be defined SR")
        self.pool1.master.genParamSet("pool", self.pool1.getUUID(), "default-SR", self.sruuid)
        
    def run(self, arglist=None):
        step("Run xe-backup-metadata -c -u <sr_uuid> on the master")
        master = self.pool1.master
        master.execdom0("xe-backup-metadata -c -u %s" % (self.sruuid))

        self.sr.forget()

        step("Set up any IQNs etc required for the SR")
        for h in self.pool2.getHosts():
            for sr in self.pool1.master.srs.values():
                sr.prepareSlave(self.pool1.master, h)
        
        self.sr.host = self.pool2.master
        step("Introduce the SR and wait a little for the VDIs to be found")
        self.sr.introduce()

        step("Wait 1 minute to ensure the master has picked up the VDIs etc")
        time.sleep(60)

        step("Run xe-restore-metadata -u <sr_uuid> -v -y on the master")
        self.pool2.master.execdom0("xe-restore-metadata -u %s -v -y -m sr" % (self.sruuid))

        step("Verify that all the VMs exist on the new pool. Start them, and ensure they all boot and have the unique identifying files")
        step("Check the template")
        templates = self.pool2.master.minimalList("template-list",
                                               args="name-label=%s" %
                                               (self.template.getName()))
        if len(templates) == 0:
            raise xenrt.XRTFailure("Template did not import")
       
        i = 0
        for g in self.guests:
            g.host = self.pool2.master
            g.uuid = None # We expect the UUID to change 
            g.start()
            g.check()
            self.uninstallOnCleanup(g)
            rc = g.execguest("ls /vm%u" % (i), retval="code")
            if rc > 0:
                raise xenrt.XRTFailure("VMs have been mismatched!")
            if i == 1:
                # Check it has xs-tools.iso
                cds = g.host.minimalList("vbd-list", 
                                         args="vm-uuid=%s type=CD" %
                                         (g.getUUID()))
                if len(cds) == 0:
                    raise xenrt.XRTFailure("No CD VBD found, expecting "
                                           "xs-tools.iso")
                vbd = cds[0]
                name = g.host.genParamGet("vbd", vbd, "vdi-name-label")
                if name == "<EMPTY>":
                    raise xenrt.XRTFailure("No CDs found on guest")
                if name != "xs-tools.iso":
                    raise xenrt.XRTFailure("Found CD %s, expecting "
                                           "xs-tools.iso" % (name))
            i += 1

    def postRun(self):
        self.sr.forget()
        self.sr.destroy()
    

class MetadataOnNFSSR(TC8226):
    """Smoketest of metadata backup and restore (on NFS SR)"""
    
    BACKUP_SR = "nfs"

wdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

class _VMPPTest(xenrt.TestCase):

    CIFSVMNAME = 'cifsvm'
    SAFEZONE = 2
    TIMEOUT = 3600 * 6

    FORBIDHEAD = ["CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4",
                  "COM5", "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2",
                  "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"]
    # Temporarily disable the double quote mark and backslash until CA-45658
    # been fixed. And we won't use consecutive backslashes, so backslash should
    # be all right here.
    FORBIDCHAR = r'<>:"/\|?*'
    FORBIDEND = ['.']

    def anyQuarter(self):
        return random.choice([0,15,30,45])

    def anyHour(self):
        return random.randint(0, 23)

    def anyDay(self):
        return random.choice(wdays)

    def normalizeName(self, name):
        for h in self.FORBIDHEAD:
            if name.startswith(h):
                name = "_" + name
                break
        for i in range(len(name)):
            c = name[i]
            if c in self.FORBIDCHAR or ord(c) < 32 or ord(c) > 125:
                name = name[:i] + '_' + name[i+1:]
        for e in self.FORBIDEND:
            if name.endswith(e):
                name = name[:-len(e)] + '_'
        return name

    def createName(self, oldname):
        head = random.choice(self.FORBIDHEAD)
        sep1 = random.choice(self.FORBIDCHAR)
        sep2 = random.choice(self.FORBIDCHAR)
        # Workaround for CA-46111        
        # end = random.choice(self.FORBIDEND)
        end = "_"
        return head + sep1 + oldname + sep2 + end

    def findNextProtection(self, pool, vmpp, ptype, now=None, offset=0):

        vmppconf = pool.getVMPPConf(vmpp)
        timenow = now is None and pool.master.getTime() or now
        datetimenow = year,mon,mday,hour,min,sec,wday = time.gmtime(timenow)[0:7]
        schedule = vmppconf[ptype+'-schedule']
        if vmppconf[ptype+'-frequency'] == 'never':
            return None
        elif vmppconf[ptype+'-frequency'] == 'always_after_backup':
            return self.findNextProtection(pool, vmpp, 'backup',
                                           now = now, offset=offset)
        else:
            if now is None:
                last_str = vmppconf[ptype+'-last-run-time']
                last_fmt = "%Y%m%dT%H:%M:%SZ"
                last = time.strptime(last_str, last_fmt)
                if last != (1970, 1, 1, 0, 0, 0, 3, 1, -1):
                    last = calendar.timegm(last)
                    lastnext = self.findNextProtection(pool, vmpp, ptype, now=last,
                                                       offset=offset)
                    if lastnext < timenow:
                        minobj = (min / 15 + 1) * 15 + offset
                        timeobj = (year, mon, mday, hour, minobj, 0)
                        return calendar.timegm(timeobj)
                
            if vmppconf[ptype+'-frequency'] == 'hourly':
                assert ptype == 'backup'
                minobj = (int(schedule['min']) + offset) % 60
                hourobj = min < minobj and hour or hour + 1
                timeobj = (year,mon,mday,hourobj,minobj,0)
            elif vmppconf[ptype+'-frequency'] == 'daily':
                minobj = (int(schedule['min'])
                          + 60 * int(schedule['hour'])
                          + offset) % (24 * 60)
                hourobj = minobj / 60
                minobj = minobj % 60
                mdayobj = (hour, min) < (hourobj, minobj) and mday or mday + 1
                timeobj = (year, mon, mdayobj, hourobj, minobj, 0)
            elif vmppconf[ptype+'-frequency'] == 'weekly':
                allobjs = []
                for d in schedule['days'].split(','):
                    d = wdays.index(d)
                    t = ((d * 24 + int(schedule['hour'])) * 60
                         + int(schedule['min']) + offset)
                    wdayobj = t / (60 * 24)
                    t = t % (60 * 24)
                    hourobj = t / 60
                    minobj = t % 60
                    allobjs.append((wdayobj, hourobj, minobj))
                allobjs.sort()
                allobjs.append((allobjs[0][0]+7, allobjs[0][1], allobjs[0][2]))
                for obj in allobjs:
                    if (wday, hour, min) < obj:
                        timeobj = (year, mon, mday + obj[0] - wday,
                                   obj[1], obj[2], 0)
                        break
            else:
                assert False
            return calendar.timegm(timeobj)

    def findNextEvents(self, pool, vmpps, offset=0):
        vmppconfs = dict(map(lambda v: (v, pool.getVMPPConf(vmpp=v)),
                             vmpps))
        vmppconfs = filter(lambda v: (bool(vmppconfs[v]['is-policy-enabled'])
                                      and vmppconfs[v]['VMs'] != set()),
                           vmppconfs)
        events = {}
        for v in vmppconfs:
            for ty in ['backup', 'archive']:
                t = self.findNextProtection(pool, v, ty, offset=offset)
                if t:
                    if not events.has_key(t):
                        events[t] = {}
                    if not events[t].has_key(v):
                        events[t][v] = []
                    events[t][v].append(ty)
        allt = events.keys()
        if not allt:
            return None
        else:
            allt.sort()
            return (allt[0], events[allt[0]])

    def gotoClock(self, pool, t):
        xenrt.TEC().logverbose("Set pool's clock to %s"
                               % time.asctime(time.gmtime(t)))
        pool.master.setTime(t)        
        for s in pool.getSlaves(): s.setTime(t)


    def setSyncFlag(self, pool, flag):
        for s in pool.getSlaves(): s.setClockSync(flag)        
        pool.master.setClockSync(flag)

    def getnfs(self):
        if not self._nfs:
            rshare = xenrt.ExternalNFSShare()
            rpath =  rshare.getMount()
            lshare = xenrt.rootops.MountNFS(rpath)
            lpath = lshare.getMount()
            self._nfs = { 'rshare': rshare,
                          'rpath': rpath,
                          'lshare': lshare,
                          'lpath': lpath }
        return self._nfs
    
    def getcifs(self, size=None):
        if not size:
            cifs = self._cifs
            if not cifs:
                self.cifssrv.goState('UP')
                self.cifssrv.xmlrpcExec("netsh firewall set service "
                                  "type=fileandprint mode=enable profile=all")
                rshare = self.cifssrv.xmlrpcTempDir()
                rname = "cifs"
                cifs = {'rshare': rshare,
                        'rname': rname}
                self._cifs = cifs
        else:
            cifs = self._cifsext
            if not cifs:
                self.cifssrv.xmlrpcExec("netsh firewall set service "
                                  "type=fileandprint mode=enable profile=all")
                rdisk = self.cifssrv.createDisk(sizebytes=size)
                time.sleep(60)
                rpart = self.cifssrv.xmlrpcPartition(rdisk)
                self.cifssrv.xmlrpcFormat(rpart, quick=True, timeout=1200)
                time.sleep(60)
                rshare = rpart + ":"
                rname = "cifsext"
                cifs = {'rshare': rshare,
                        'rname': rname,
                        'rdisk': rdisk }
                self._cifsext = cifs
        if not cifs.has_key('rpath'):
            cifs['ruser'] = 'Administrator'
            cifs['rpass'] = xenrt.TEC().lookup(["WINDOWS_INSTALL_ISOS", "ADMINISTRATOR_PASSWORD"])
            self.cifssrv.xmlrpcExec("net share %s=%s /GRANT:%s,FULL"
                              % (cifs['rname'], cifs['rshare'], cifs['ruser']))
            # Stick with current double quote solution for comptability, hence
            # a workaround is needed
            cifs['rpath'] = "\\\\\\\\%s\\\\%s" % (self.cifssrv.getIP(), rname)
        return cifs

    def getsmtp(self):
        if not self._smtp:
            smtpServer = xenrt.SimpleSMTPServer(debug=True)
            smtpServer.start()
            time.sleep(5)
            self._smtp = {'server': smtpServer,
                          'address': xenrt.TEC().lookup("XENRT_SERVER_ADDRESS"),
                          'port': smtpServer.port }
        return self._smtp

    def getvm(self, pool, type, state, name=None, copy=True):
        if type == 'winhvm':
            if not pool.winhvm:
                pool.winhvm = xenrt.TEC().gec.registry.guestGet('winhvm')
            if pool.winhvm.getState() != 'DOWN': pool.winhvm.xmlrpcShutdown()
            # For interactive debugging (due to the weakness of existing())
            pool.winhvm.enlightenedDrivers=False
            vm = copy and pool.winhvm.cloneVM(name=name) or pool.winhvm
        elif type == 'winpv':
            if not pool.winpv:
                pool.winpv = xenrt.TEC().gec.registry.guestGet('winpv')
            if not pool.winpv:
                winhvm = self.getvm(pool, 'winhvm', 'DOWN', copy=False)
                pool.winpv = winhvm.cloneVM(name='winpv')
                xenrt.TEC().gec.registry.guestPut('winpv', pool.winpv)
                pool.winpv.goState('UP')
                pool.winpv.installDrivers()
            pool.winpv.goState('DOWN')
            vm = copy and pool.winpv.cloneVM(name=name) or pool.winpv
        elif type == "linux":
            if not pool.linux:
                pool.linux = xenrt.TEC().gec.registry.guestGet('linux')
            pool.linux.goState('DOWN')
            vm = copy and pool.linux.cloneVM(name=name) or pool.linux
        elif type == "dummy":
            if not pool.dummy:
                dummy = xenrt.TEC().gec.registry.guestGet('dummy')
                if not dummy or dummy.host.pool != pool:
                    pool.dummy = pool.master.guestFactory()('dummy', host=pool.master)
                    pool.dummy.createHVMGuest([(100, pool.master.lookupDefaultSR())])
                    pool.dummy.memset(16)
                    if not dummy:
                        xenrt.TEC().gec.registry.guestPut(pool.dummy.name, pool.dummy)
                else:
                    pool.dummy = dummy
            pool.dummy.enlightenedDrivers=False
            if pool.dummy.getState() != 'DOWN': pool.dummy.shutdown(force=True)
            vm = copy and pool.dummy.cloneVM(name=name) or pool.dummy
        else:
            raise xenrt.XRTError("Wrong VM type specified")
        if copy:
            if not name:
                vm.setName(self.createName(vm.getName()))
            vm.tailored = True
            xenrt.TEC().registry.guestPut(vm.getName(), vm)
            self.getLogsFrom(vm)
            self.uninstallOnCleanup(vm)
        vm.goState(state)
        return vm

    def getBackups(self, pool, vm, vmpp_only=True):
        args = 'snapshot-of=%s' % vm
        if vmpp_only:
            args += ' is-snapshot-from-vmpp=true'
        return pool.master.minimalList("snapshot-list", args=args)
        
    def getArchives(self, pool, vm):
        vmpp = pool.master.genParamGet('vm', vm, 'protection-policy')
        vmppconf = pool.getVMPPConf(vmpp=vmpp)
        atype = vmppconf['archive-target-type']
        vmname = pool.master.genParamGet('vm', vm, 'name-label')
        nmname = self.normalizeName(vmname)

        if atype == "none": return []
        
        if atype == 'nfs':
            target = self.getnfs()
            archives = glob.glob("%s/%s-%s/*.xva"
                                 % (target['lpath'],
                                    nmname, vm[0:16]))
            archives = map(lambda p: p.split('/')[-1], archives)
            allfiles = glob.glob("%s/*/*" % target['lpath'])
        elif atype == 'cifs':
            target = (
                vmppconf['archive-target-config']['location'].endswith('cifs')
                and self._cifs or self._cifsext
                )
            archives = self.cifssrv.xmlrpcGlobPattern(
                "%s\\%s-%s\\*.xva" % (target['rshare'], nmname, vm[0:16])
                )
            archives = map(lambda p: p.split('\\')[-1], archives)            
            allfiles = self.cifssrv.xmlrpcGlobPattern(
                "%s\\*\\*" % (target['rshare'])
                )
        else:
            assert False
        if len(archives) == 0:
            # For debugging purpose
            xenrt.TEC().logverbose("No archives matches our path/pattern, "
                                   "here are all files currently inside "
                                   "the shared directory: %s" % allfiles)
        return archives
                      

    def getProtectStatus(self, pool):
        vmppconfs = pool.getVMPPConf()
        for vmpp in vmppconfs:
            vconf = vmppconfs[vmpp]
            vms = vconf['VMs']
            vconf['VMs'] = {}
            for vm in vms:
                vconf['VMs'][vm] = \
                                { 'backup': self.getBackups(pool, vm),
                                  'archive': self.getArchives(pool, vm) }
            vconf['alerts'] = pool.getVMPPAlerts(vmpp)
            
        xenrt.TEC().logverbose("The current protection status is:\n%s"
                               % vmppconfs)
        return vmppconfs

    def waitVMPPEvent(self, pool, vmpp, condition, timeout=3600):
        start = xenrt.timenow()
        deadline = start + timeout
        freq = 300
        args = []
        args.append("class=vmpp")
        args.append("uuid=%s" % vmpp)
        args.append(condition)
        cli = pool.getCLIInstance()
        # Cope with event-wait bug
        while xenrt.timenow() < deadline:
            rc = cli.execute("event-wait", args=" ".join(args),
                             timeout=freq, level=xenrt.RC_OK, retval="code")
            if rc == 0:
                return
        raise xenrt.XRTFailure("Wait VMPP event %s timed out" % condition)

    def cleanupVMPP(self, pool):
        vconfs = pool.getVMPPConf()
        cli = pool.getCLIInstance()
        for vmpp in vconfs:
            for vm_uuid in vconfs[vmpp]['VMs']:
                if pool.master.genParamGet('vm', vm_uuid, 'power-state') != 'halted':
                    cli.execute('vm-shutdown', 'vm=%s --force' % vm_uuid)
                cli.execute('vm-uninstall', 'vm=%s --force' % vm_uuid)
        pool.deleteVMPP(auto=True)

    def cleanupArchives(self):
        if self._nfs:
            xenrt.rootops.sudo("rm -rf %s/*" % self._nfs['lpath'])
        for cifs in filter(None, [self._cifs, self._cifsext]):
            files = self.cifssrv.xmlrpcGlobPattern(cifs['rshare'] + '\\*')
            for f in files:
                self.cifssrv.xmlrpcDelTree(f)
            
    def shutdownServices(self):
        if self._nfs:
            try:
                self._nfs['lshare'].unmount()
                self._nfs['rshare'].release()
                self._nfs = None
            except:
                pass
        if self._cifs:
            try:
                self.cifssrv.xmlrpcExec('net share %s /DELETE' % self._cifs['rname'])
                self.cifssrv.xmlrpcDelTree(self._cifs['rshare'])
                self._cifs = None
            except:
                pass
        if self._cifsext:
            try:
                self.cifssrv.xmlrpcExec('net share %s /DELETE' % self._cifsext['rname'])
                self.cifssrv.unplugDisk(self._cifsext['rdisk'])
                self.cifssrv.removeDisk(self._cifsext['rdisk'], keepvdi=False)
                self._cifsext = None
            except:
                pass
        if self._smtp:
            try:
                if self._smtp['server'].isAlive():
                    self._smtp['server'].stop()
                self._smtp = None
            except:
                pass

    def cleanupSetup(self, pool):
        self.stopBackOp()
        self.cleanupVMPP(pool)
        self.cleanupArchives()

    def runBackOp(self, vms, deadline):
        xenrt.TEC().logverbose("Start to run VM Operations at background")
        while self._backop and xenrt.timenow() < deadline:
            vm = random.choice(vms)
            opnum = random.randint(1,3)
            try:
                vm.lifecycleSequence(pool=True, opcount=opnum, back=False)
                time.sleep(15)
            except Exception, e:
                xenrt.TEC().warning("VM Operations background got exception "
                                    "%s during VM %s's lifecycle" %
                                    (e, vm.getName()))
        xenrt.TEC().logverbose("VM Operations at background is now stopped")
            
    def stopBackOp(self):
        if self._backop:
            backop = self._backop
            self._backop = None
            backop.join()

    def runConf(self, pool, confs, lifeop=True):

        opvms = []
        
        for conf in confs:
            
            v = conf['vmpp']
            vmpp = pool.createVMPP(v['name'], v['btype'], v['bfreq'])
            
            v['params'] = v.get('params', {})
            params = v['params']
            
            if v.has_key('brtnt'):
                pool.setVMPPParam(vmpp, 'backup-retention-value',
                                  str(v['brtnt']))
            
            if not params.has_key('backup-schedule:min'):
                params['backup-schedule:min'] = str(self.anyQuarter())
            if (v['bfreq'] in ['daily', 'weekly']
                and not params.has_key('backup-schedule:hour')):
                params['backup-schedule:hour'] = str(self.anyHour())
            if (v['bfreq'] == 'weekly'
                and not params.has_key('backup-schedule:days')):
                params['backup-schedule:days'] = str(self.anyDay())

            if v.has_key('afreq') and not v.has_key('atype'):
                v['atype'] = 'nfs'

            if v.has_key('atype'):
                pool.setVMPPParam(vmpp, 'archive-target-type', v['atype'])                
                if v['atype'] == 'nfs':
                    nfs = self.getnfs()
                    pool.setVMPPParam(vmpp,
                                      'archive-target-config:location',
                                      nfs['rpath'])
                elif v['atype'] == 'cifs':
                    cifs = self.getcifs()
                    pool.setVMPPParam(vmpp,
                                      'archive-target-config:location',
                                      cifs['rpath'])
                    pool.setVMPPParam(vmpp,
                                      'archive-target-config:username',
                                      cifs['ruser'])
                    pool.setVMPPParam(vmpp,
                                      'archive-target-config:password',
                                      cifs['rpass'])
                else:
                    raise xenrt.XRTError("Unkown archive target type "
                                         "in config: %s" % v['atype'])
                
            if v.has_key('afreq'):
                pool.setVMPPParam(vmpp, 'archive-frequency', v['afreq'])
                if (v['afreq'] in ['daily', 'weekly']
                    and not params.has_key('archive-schedule:hour')):
                    params['archive-schedule:hour'] = str(self.anyHour())
                if (v['afreq'] == 'weekly'
                    and not params.has_key('archive-schedule:days')):
                    params['archive-schdule:days'] = str(self.anyDay())
        
            for key,val in params.iteritems():
                pool.setVMPPParam(vmpp, key, val)
                
            conf['vmpp'] = (v, vmpp)


            # Disable the VMPP for now for preparation
            pool.setVMPPParam(vmpp, 'is-policy-enabled', "false")

            vms = conf['vms']
            conf['vms'] = []
            for vm in vms:
                name, state = vm
                vmobj = self.getvm(pool, name, state)
                vmobj.paramSet("protection-policy", vmpp)
                conf['vms'].append((vm, vmobj))
                if v['btype'] == "snapshot":
                    opvms.append(vmobj)
                assert vmobj.getUUID() in pool.getVMPPConf(vmpp)['VMs']
                
        deadline = xenrt.timenow() + self.TIMEOUT

        if lifeop and opvms:
            # Start background VM Ops
            self._backop = xenrt.PTask(self.runBackOp, opvms, deadline)
            self._backop.start()
            # We'll have to set variable after start()
            self._backop.setVariable('nolog', True)

        # When the loop should ends        
        overflow = False
        vmpps = pool.listVMPP()
        
        # Set the clock to a same time to enable VMPPs, leave extra room for
        # the settings before the first run
        clock, _ = self.findNextEvents(pool, vmpps, offset=-5-self.SAFEZONE)
        self.gotoClock(pool, clock)
        
        # Actually let the vmpps run
        for conf in confs:
            if not conf.get('disabled'):
                _, vmpp_uuid = conf['vmpp']
                pool.setVMPPParam(vmpp_uuid, 'is-policy-enabled', 'true')


        # Start the loop
        while not overflow and xenrt.timenow() < deadline:
            
            clock, events = self.findNextEvents(pool, vmpps,
                                                offset=-self.SAFEZONE)
            # PP state before the events            
            status = self.getProtectStatus(pool)

            self.gotoClock(pool, clock)

            # Make sure VMPP has not started and will start
            for vmpp in events:
                vmppconf = status[vmpp]
                last_backup = time.strptime(vmppconf['backup-last-run-time'],
                                            "%Y%m%dT%H:%M:%SZ")
                last_archive = time.strptime(vmppconf['archive-last-run-time'],
                                             "%Y%m%dT%H:%M:%SZ")
                clock_now = time.gmtime(pool.master.getTime())
                as_expect = vmppconf['is-backup-running'] == 'false' \
                            and vmppconf['is-archive-running'] == 'false' \
                            and last_backup < clock_now \
                            and last_archive < clock_now
                if not as_expect:
                    raise xenrt.XRTFailure("Current protection running "
                                           "status or last protection "
                                           "running time is out of "
                                           "expectation.",
                                           data = vmpp)
            event_start = xenrt.timenow()
            
            for vmpp in events:
                for ptype in events[vmpp]:
                    last_run = "%s-last-run-time" % ptype
                    self.waitVMPPEvent(pool, vmpp,
                                       "%s=/=%s" % (last_run,
                                                    status[vmpp][last_run]),
                                       timeout=5400)
                    # Have to wait until the operation is done (or already done)
                    self.waitVMPPEvent(pool, vmpp,
                                       "is-%s-running=false" % ptype,
                                       timeout = 5400)
            event_end = xenrt.timenow()

            if event_end - event_start > 3600:
                xenrt.TEC().warning("The whole VMPP event took more than one "
                                    "hour: % seconds."
                                    % (event_end - event_start))

            # PP status after the events
            xstatus = self.getProtectStatus(pool)

            assert len(status.keys()) == len(xstatus.keys())

            # Only apply restrictive rules to the relevant VMPP, since when the
            # events happen, they might last very long hence other VMPP might kick in
            # already and change their own status. But the same VMPPs won't
            # kick in again for sure. So we'll only exam the status of the VMPP
            # which are relevant to this event.
            for vmpp in vmpps:
                conf = status[vmpp]
                xconf = xstatus[vmpp]
                if vmpp not in events.keys():
                    if conf != xconf:
                        xenrt.TEC().warning("VMPP %s had some fields "
                                            "changed, it usually means our "
                                            "execution took too long so that "
                                            "other VMPP kicked in." % vmpp)
                    continue
                for ptype in events[vmpp]:
                    for vm in conf['VMs']:
                        ents = set(conf['VMs'][vm][ptype])
                        xents = set(xconf['VMs'][vm][ptype])
                        rtnt = int(conf['backup-retention-value'])
                        if ptype == 'backup' and len(ents) == rtnt:
                            expect_len = rtnt
                            expect_uni = expect_len + 1
                        elif (ptype == 'archive'
                              and len(xconf['VMs'][vm]['backup']) == 0):
                            expect_len = 0
                            expect_uni = expect_len
                        else:
                            expect_len = len(ents) + 1
                            expect_uni = expect_len
                        if (len(xents) != expect_len or
                            len(xents.union(ents)) != expect_uni):
                            raise xenrt.XRTFailure("The number of %s of "
                                                   "VM %s created by VMPP "
                                                   "%s is not as expected."
                                                   % (ptype, vm, vmpp),
                                                   data = (ents, xents))
                        else:
                            xenrt.TEC().logverbose("The number of %s of "
                                                   "VM %s created by VMPP "
                                                   "%s is as expected."
                                                   % (ptype, vm, vmpp))
                    if len(conf['alerts']) > 0 :
                        last_alert = conf['alerts'][0]
                        last_alert_idx = xconf['alerts'].index(last_alert)
                        if last_alert_idx < 0:
                            raise xenrt.XRTError("Couldn't find the last "
                                                 "alert before the event.")
                    else:
                        last_alert_idx = len(xconf['alerts'])
                    if last_alert_idx == 0:
                        raise xenrt.XRTFailure("No new alerts generated",
                                               data = (conf['alerts'],
                                                       xconf['alerts']))
                    new_alerts = xconf['alerts'][:last_alert_idx]
                    new_msgs = map(lambda a: a['message'], new_alerts)
                    if ptype == 'backup':
                        exp_msg = "VMPP_SNAPSHOT_SUCCEEDED"
                    elif ptype == 'archive':
                        exp_msg = "VMPP_ARCHIVE_SUCCEEDED"
                    else:
                        raise xenrt.XRTError("No such protection type: %s"
                                             % ptype)
                    if exp_msg not in new_msgs:
                        raise xenrt.XRTFailure("Failed to find expected "
                                               "message.", data=new_alerts)

            # Due to the long wait (if archiving), some other protection rule
            # might have kicked in. Let's wait until everything is quiet again.
            while True:
                running = False
                for vmpp in vmpps:
                    for ptype in ['backup', 'archive']:
                        running = running or \
                                  (xstatus[vmpp]['is-%s-running' % ptype] in ['true', 'True'])
                if not running: break
                xenrt.TEC().logverbose("Some protection is still running, "
                                       "let's wait another 60 seconds.")
                time.sleep(60)
                xstatus = self.getProtectStatus(pool)
                    
            # Verification is done, clean up archives to save space
            # for future loop.
            self.cleanupArchives()
            
            overflow = True
            for vmpp in vmpps:
                if status[vmpp]['is-policy-enabled']:
                    rtnt = int(xstatus[vmpp]['backup-retention-value'])
                    for vm in xstatus[vmpp]['VMs']:
                        if len(set.union(set(xstatus[vmpp]['VMs'][vm]['backup']),
                                         set(status[vmpp]['VMs'][vm]['backup'])))\
                                         < rtnt:
                            overflow = False
                            break
                if not overflow: break
    
    def prepare(self, arglist=[]):
        self.pool = self.getDefaultPool()
        for h in self.pool.getHosts(): h.license(edition='platinum')
        self.cifssrv = self.getGuest(self.CIFSVMNAME)
        self._nfs = None
        self._cifs = None
        self._cifsext = None
        self._smtp = None
        self._backop = None
        self.pool.winhvm = None
        self.pool.winpv = None
        self.pool.linux = None
        self.pool.dummy = None
        self.cleanupSetup(self.pool)

    def postRun(self):
        # When fail, we want the logging side-effect of getProtectStatus
        self.getProtectStatus(self.pool)        
        self.cleanupSetup(self.pool)
        self.shutdownServices()

        
# For debugging purpose only
class VMPPTC00(_VMPPTest):
    msg = "We stop here for debugging purpose"
    def prepare(self, arglist=[]):
        raise xenrt.XRTError(self.msg)
    def run(self, arglist=[]):
        raise xenrt.XRTFailure(self.msg)

class TC12143(_VMPPTest):

    """
    VMPP-Syntax
    """

    def genVMPPCreate(self, pdict, expectFail=None, defaultArgs=True):
        xenrt.TEC().logverbose("To create VMPP with arguments %s %s, %s."
                               % (pdict,
                                  defaultArgs and "on top of default arguments"
                                  or "without default arguments",
                                  expectFail and "expected failure: " + expectFail
                                  or "no failure expected"))
        
        name = pdict.pop('name', defaultArgs and ("%08x" % random.randint(0, 0x7fffffff)))
        type = pdict.pop('backup-type', defaultArgs and 'snapshot')
        frequency = pdict.pop('backup-frequency', defaultArgs and 'weekly')
        pdict['is-policy-enabled'] = 'false'
        vmpps_before = set(self.pool.listVMPP())
        vmpp = None
        fail = None
        try:
            vmpp = self.pool.createVMPP(name, type, frequency, pdict)
        except Exception, e:
            if not (expectFail and re.search(expectFail, e.reason + e.data or "")):
                fail = e
        else:
            if expectFail:
                fail = xenrt.XRTFailure("Failure expected: %s, while creation "
                                        "succeeded." % expectFail)
        if vmpp:
            self.pool.getVMPPConf(vmpp)
            self.pool.deleteVMPP(vmpp)
            
        vmpps_after = set(self.pool.listVMPP())                
        if vmpps_before != vmpps_after:
            raise xenrt.XRTFailure("VMPPs after the test is unexpected.",
                                   data = ("Before: %s, after: %s"
                                           % (vmpps_before, vmpps_after)))
        if fail:
            raise fail

    def genVMPPSet(self, vmpp, pdict, expectFail=None):
        vmpps_before = set(self.pool.listVMPP())
        assert vmpp in vmpps_before
        fail = None
        try:
            for k,v in pdict.iteritems():
                self.pool.setVMPPParam(vmpp, k, v)
                assert self.pool.getVMPPParam(vmpp, k) == v
        except Exception, e:
            if not (expectFail and re.search(expectFail, e.reason + e.data or "")):
                fail = e
        vmpps_after = set(self.pool.listVMPP())
        assert vmpps_before == vmpps_after
        if fail:
            raise fail
        
    def run(self, arglist=[]):
        crconf = { "backup-type":
                   { "checkpoint": None,
                     "snapshot": None,
                     "checkpoints": "wrong type" },
                   "backup-frequency":
                   { "hourly": None,
                     "daily": None,
                     "weekly": None,
                     "nightly": "wrong type" },
                   "backup-schedule:min":
                   { "0": None,
                     "15": None,
                     "30": None,
                     "45": None,
                     "60": "invalid",
                     "25": "invalid" },
                   "backup-schedule:hour":
                   { "0": None,
                     "23": None,
                     "24": "invalid" },
                   "backup-schedule:days":
                   {"Monday,Saturday": None,
                    "Sun": "invalid",
                    "1": "invalid" },
                   "backup-retention-value":
                   { "1": None,
                     "10": None,
                     "0": "invalid",
                     "11": "invalid" } }
        stconf = { "archive-target-type":
                   { "nfs": None,
                     "cifs": None,
                     "iscsi": "wrong type" },
                   "archive-frequency":
                   { "weekly": None,
                     "daily": "frequent",
                     "never": None,
                     "always_after_backup": None,
                     "hourly": "wrong type" },
                   "archive-schedule:min":
                   { "0": None,
                     "15": None,
                     "30": None,
                     "45": None,
                     "60": "invalid",
                     "25": "invalid" },
                   "archive-schedule:hour":
                   { "0": None,
                     "23": None,
                     "24": "invalid" },
                   "archive-schedule:days":
                   { "Monday,Saturday": None,
                     "Sun": "invalid",
                     "1": "invalid" },
                   "is-policy-enabled":
                   { "true": None,
                     "false": None,
                     "yes": "boolean" },
                   "is-backup-running":
                   { "true": "read-only" },
                   "backup-last-run-time":
                   { "19700101T00:00:00Z": "read-only" },
                   "is-archive-running":
                   { "false": "read-only" },
                   "archive-last-run-time":
                   { "19700101T00:00:00Z": "read-only" },
                   "is-alarm-enabled":
                   { "true": None,
                     "false": None,
                     "Yes": "boolean" } }
        failures = []
        for param, settings in crconf.iteritems():
            for value, expect in settings.iteritems():
                subcase = "%s/%s=%s" % ("vmpp-create", param, value)
                if self.runSubcase("genVMPPCreate",
                                   ({param: value}, expect, True),
                                   "vmpp-create", param) != xenrt.RESULT_PASS:
                    failures.append(subcase)
        vmpp = self.pool.createVMPP(self.tcid, "snapshot", "weekly", {'archive-target-type':'nfs'})
        for param, settings in stconf.iteritems():
            for value, expect in settings.iteritems():
                subcase = "%s/%s=%s" % ("vmpp-config", param, value)
                if self.runSubcase("genVMPPSet",
                                   (vmpp, {param: value}, expect),
                                   "vmpp-config", param) != xenrt.RESULT_PASS:
                    failures.append(subcase)
        self.pool.deleteVMPP()
        if len(failures) > 0:
            raise xenrt.XRTFailure("Multiple subcases failed: %s" % failures)

        
class TC12144(_VMPPTest):
    
    """
    VMPP association
    """

    def noVMPP(self, vm, op):
        time.sleep(10)
        pp = vm.paramGet('protection-policy')
        if pp != "<not in database>":
            raise xenrt.XRTFailure("We expect a VM created by %s with no "
                                   "VMPP assigned." % op)

    def newVMVerif(self, op, vm):
        newvm = eval("self." + op + "ToNew")(vm)
        newvm.tailored = True
        newvm.start()
        self.noVMPP(newvm, op)
        newvm.shutdown(again=True)
        newvm.uninstall()

    def cloneToNew(self, vm):
        return vm.cloneVM()

    def copyToNew(self, vm):
        return vm.copyVM()

    def exportToNew(self, vm):
        # Hackish way to do it on host, in order to reduce control workload and
        # transfer time
        vm.goState('DOWN')
        host = vm.getHost()
        td = host.tempDir()
        tf = td + "/" + vm.uuid
        try:
            host.execcmd("xe vm-export uuid=%s filename=%s compress=true"
                         % (vm.getUUID(), tf))
            newvm = copy.copy(vm)
            newvm.special = copy.copy(vm.special)
            newvm.name = xenrt.randomGuestName()
            newvm.uuid = host.execcmd("xe vm-import filename=%s" % tf).strip()
            host.execcmd("xe vm-param-set uuid=%s name-label='%s'"
                         % (newvm.uuid, newvm.name))
        finally:
            if os.path.exists(tf):
                os.unlink(tf)
                os.unlink(td)
        return newvm

    def snapshotToNew(self, vm):
        snaps = self.getBackups(self.pool, vm.getUUID())
        if len(snaps) > 0:
            snap = snaps[0]
        else:
            snap = vm.snapshot()
        tname = xenrt.randomGuestName()
        tvm = copy.copy(vm)
        tvm.special = copy.copy(vm.special)
        tvm.name = tname
        cli = self.pool.getCLIInstance()
        tvm.uuid = cli.execute('snapshot-clone',
                               'uuid=%s new-name-label=%s' % (snap, tname)).strip()
        self.pool.master.genParamSet('snapshot', tvm.uuid, 'is-a-template', 'false')
        return tvm

    def checkpointToNew(self, vm):
        vm.goState('UP')
        check = vm.checkpoint()
        tname = xenrt.randomGuestName()
        tvm = copy.copy(vm)
        tvm.special = copy.copy(vm.special)
        tvm.name = tname
        cli = self.pool.getCLIInstance()
        tvm.uuid = cli.execute('snapshot-clone',
                               'uuid=%s new-name-label=%s' % (check, tname)).strip()
        self.pool.master.genParamSet('snapshot', tvm.uuid, 'is-a-template', 'false')
        vm.goState('DOWN')
        return tvm

    def run(self, arglist=[]):
        vmpp = self.pool.createVMPP("assoc", "snapshot", "hourly")
        vm = self.getvm(self.pool, 'linux', 'DOWN')
        vm_uuid = vm.getUUID()
        self.noVMPP(vm, "create")
        vm.paramSet("protection-policy", vmpp)
        expect = (vm_uuid in self.pool.getVMPPConf(vmpp=vmpp)['VMs']
                  and vm.paramGet("protection-policy") == vmpp)
        if not expect:
            raise xenrt.XRTFailure("VM %s and VMPP %s are not conencted as we "
                                   "expect." % (vm_uuid, vmpp))
        for op in ['clone', 'copy', 'export', 'snapshot', 'checkpoint']:
            if self.runSubcase("newVMVerif", (op, vm), "VM-VMPP", op) != xenrt.RESULT_PASS:
                break
        try:
            self.pool.deleteVMPP(vmpp)
        except xenrt.XRTException, e:
            if e.reason.find("at least") >= 0:
                xenrt.TEC().logverbose("VMPP with at least one VM assigned "
                                       "can not be deleted as expected")
                self.pool.deleteVMPP(vmpp,auto=True)
            else:
                raise e
        else:
            raise xenrt.XRTFailure("VMPP with at least one VM assigned "
                                   "should not be deletable.",
                                   data=self.pool.getVMPPConf(vmpp=vmpp))
        
class TC12145(_VMPPTest):
    
    """
    VMPP-Normal
    """

    def prepare(self, arglist=[]):
        _VMPPTest.prepare(self)
        self.setSyncFlag(self.pool, False)

    def runCase(self, pool, conf):
        self.cleanupSetup(pool)
        try:
            self.runConf(pool, conf)
        finally:
            try:
                self.cleanupSetup(pool)
            except:
                pass

    def run(self, arglist=[]):
        
        dtnow = time.gmtime(self.pool.master.getTime())
        
        vmpp_hour_after = {
            'name': 'hour_after',
            'btype': 'snapshot',
            'bfreq': 'hourly',
            'brtnt': 10,
            'atype': 'nfs',
            'afreq': 'always_after_backup',
            }
        vmpp_hour_never = {
            'name': 'hour_never',
            'btype': 'snapshot',
            'bfreq': 'hourly',
            'brtnt': 10,
            'afreq': 'never',
            }
        vmpp_day_day = {
            'name': 'day_day',
            'btype': 'snapshot',
            'bfreq': 'daily',
            'brtnt': 1,
            'atype': 'cifs',
            'afreq': 'daily',
            'params': {'archive-schedule:hour': str((dtnow[3]+5)%24)}
            }
        vmpp_day_week = {
            'name': 'day_week',
            'btype': 'checkpoint',
            'bfreq': 'daily',
            'brtnt': 4,
            'atype': 'nfs',
            'afreq': 'weekly',
            'params': {'archive-schedule:days': 'Monday,Thursday',
                       }
            }
        vmpp_week_after = {
            'name': 'week_after',
            'btype': 'snapshot',
            'bfreq': 'weekly',
            'brtnt': 1,
            'atype': 'nfs',
            'afreq': 'always_after_backup',
            }

        # For perf test only
        case0 = [ {'vmpp': vmpp_hour_after,
                   'vms': [ ('winpv', 'UP') for _ in range(5) ]}
                  ]
        case1 = [ {'vmpp': vmpp_hour_never,
                   'vms': [ ('winhvm', 'UP'),
                            ('linux', 'DOWN'),
                            ('winpv', 'DOWN'),
                            ('dummy', 'DOWN') ]},
                  {'vmpp': vmpp_day_day,
                   'vms': [ ('linux', 'UP'),
                            ('dummy', 'UP'),
                            ('winhvm', 'DOWN'),
                            ('winpv', 'UP') ]}
                  ]
        case2 = [ {'vmpp': vmpp_day_week,
                   'vms': [ ('linux', 'UP'),
                            ('winpv', 'UP'),
                            ('linux', 'UP'),
                            ('winpv', 'UP') ]},
                  {'vmpp': vmpp_week_after,
                   'vms': [ ('dummy', 'UP'),
                            ('winhvm', 'UP'),
                            ('linux', 'UP'),
                            ('winpv', 'UP') ]}
                  ]
        
        cases = [
                  # Dev test only
                  # (case0, "BenchM", "case0"),
                  (case1, "Normal", "case1"),
                  (case2, "Normal", "case2")
                  ]

        # The testcase is so complicated, so We stop as soon as a single
        # subcase fail, we'll not proceed to the next subcase as in normal situation.
        for c, gn, cn in cases:
            if self.runSubcase("runCase", (self.pool, c), gn, cn) != xenrt.RESULT_PASS: break
            
    def postRun(self):
        _VMPPTest.postRun(self)
        self.setSyncFlag(self.pool, True)

        
class TC12146(TC12145):
    
    """
    VMPP-Stress
    """
    
    def run(self, arglist=[]):
        
        vmpp_0 = {
            'name': 'vmpp_0',
            'btype': 'checkpoint',
            'bfreq': 'hourly',
            # I'd like to have 10 here as stress, but that would take days to run
            'brtnt': 2,
            'afreq': 'always_after_backup',
            'atype': 'nfs',
            'params': {'backup-schedule:min':'0'}
            }
        
        vmpp_15 = copy.copy(vmpp_0)
        vmpp_15['btype'] = 'snapshot'
        vmpp_15['name'] = 'vmpp_15'
        vmpp_15['params'] = {'backup-schedule:min':'15'}
        vmpp_15['afreq'] = 'never'
        
        vmpp_30 = copy.copy(vmpp_0)
        vmpp_30['btype'] = 'snapshot'
        vmpp_30['name'] = 'vmpp_30'
        vmpp_30['params'] = {'backup-schedule:min':'30'}
        
        vmpp_45 = copy.copy(vmpp_15)
        vmpp_45['name'] = 'vmpp_45'
        vmpp_45['params'] = {'backup-schedule:min':'45'}

        mixup4 = [ (os, st)
                   for os in ['winpv', 'linux']
                   for st in ['UP', 'UP'] ]
        mixdown4 = [ (os, st)
                     for os in ['winpv', 'linux']
                     for st in ['DOWN', 'DOWN'] ]
        mixupdown4 = [ (os, st)
                       for os in ['winpv', 'linux']
                       for st in ['UP', 'DOWN'] ]
        
        case1 = [ {'vmpp': vmpp_0,
                   'vms': mixup4 },
                  {'vmpp': vmpp_15,
                   'vms': mixdown4 },
                  {'vmpp': vmpp_30,
                   'vms': mixupdown4 },
                  {'vmpp': vmpp_45,
                   'vms': mixupdown4 } ]

        cases = [ (case1, "Stress", "case1") ]
        for c, gn, cn in cases:
            if self.runSubcase("runCase", (self.pool, c), gn, cn) != xenrt.RESULT_PASS: break
                   
        
class TC12147(_VMPPTest):

    """
    VMPP-Pool
    """

    def prepare(self, arglist=[]):
        _VMPPTest.prepare(self)
        self.setSyncFlag(self.pool, False)

    def postRun(self):
        _VMPPTest.postRun(self)
        try: 
            self.setSyncFlag(self.pool, True)
        except:
            pass

    def getVMPPBasic(self, pool):
        return dict(map(lambda (k,v): (k, v['VMs']),
                        pool.getVMPPConf().iteritems()))

    def run(self, arglist=[]):
        vmpp_1 = {
            'name': 'vmpp_1',
            'btype': 'snapshot',
            'bfreq': 'hourly',
            'brtnt': 2,
            }
        vmpp_2 = {
            'name': 'vmpp_2',
            'btype': 'snapshot',
            'bfreq': 'hourly',
            'brtnt': 3,
            }
        vmpp_3 = {
            'name': 'vmpp_3',
            'btype': 'snapshot',
            'bfreq': 'hourly',
            'brtnt': 2
            }
        conf = [{'vmpp': vmpp_1,
                 'vms': [ ('linux', 'UP'),
                          ('dummy', 'UP') ]},
                {'vmpp': vmpp_2,
                 'vms': [ ('dummy', 'UP') ]}]
        # Only use dummy VM in the second pool, as which OS is not relevant at
        # all and creating dummy VM is much faster. Also note that this needs
        # special care in the getvm method (currently only getvm(dummy) has).
        conf2 = [{'vmpp': vmpp_3,
                  'vms': [ ('dummy', 'UP') ]}]

        self.runConf(self.pool, conf, lifeop=False)
        status = self.getVMPPBasic(self.pool)
        
        self.host2 = self.pool.getSlaves()[0]

        if self.cifssrv.getHost() == self.host2:
            self.cifssrv.migrateVM(self.pool.master)

        for gname in self.host2.listGuests(running=True):
            g = xenrt.TEC().registry.guestGet(gname)
            g.shutdown(againOK=True)
            
        self.pool.eject(self.host2)

        status1 = self.getVMPPBasic(self.pool)

        if status != status1:
            raise xenrt.XRTFailure("After ejecting slave, the VMPP+VM mapping "
                                   " should remain the same, while it's not.",
                                   data = (status, status1))

        self.host2.license(edition="platinum")
        self.pool2 = xenrt.lib.xenserver.poolFactory(self.host2.productVersion)(self.host2)
        self.pool2._nfs = None
        self.pool2._cifs = None
        self.pool2.winhvm = None
        self.pool2.winpv = None
        self.pool2.linux = None
        self.pool2.dummy = None
        

        self.runConf(self.pool2, conf2, lifeop=False)
        status2 = self.getVMPPBasic(self.pool)

        cli2 = self.pool2.getCLIInstance()
        vms2 = self.host2.minimalList('vm-list', args='is-control-domain=false')
        for vm in vms2:
            if self.host2.genParamGet('vm', vm, 'power-state') != 'halted':
                cli2.execute('vm-shutdown', 'vm=%s --force' % vm)

        self.pool.addHost(self.host2)
        status3 = self.getVMPPBasic(self.pool)
        if status != status3:
            raise xenrt.XRTFailure("After slave rejoin, the VMPP+VM mapping "
                                   " should remain the same, while it's not.",
                                   data = (status, status3))

        cli = self.pool.getCLIInstance()
        for vm in vms2:
            pp = self.pool.master.genParamGet('vm', vm, 'protection-policy')
            if pp != '<not in database>':
                raise xenrt.XRTFailure("The VM introduced by pool slave "
                                       "still comes with its own VMPP",
                                       data=(vm, pp))
            else:
                cli.execute('vm-uninstall', 'vm=%s --force' % vm)


class TC12148(_VMPPTest):

    """
    VMPP-ErrorMsg
    """
    
    def run(self, arglist=[]):
        cifs = self.getcifs(size=50 * xenrt.MEGA)
        smtp = self.getsmtp()
        pdict = { 'archive-frequency': 'always_after_backup',
                  'archive-target-type': 'cifs',
                  'archive-target-config:location': cifs['rpath'],
                  'archive-target-config:username': cifs['ruser'],
                  'archive-target-config:password': cifs['rpass'],
                  'is-alarm-enabled': 'true',
                  'alarm-config:smtp_server': smtp['address'],
                  'alarm-config:smtp_port': smtp['port'],
                  'alarm-config:email_address': 'qa@xensource.com'}
        vmpp = self.pool.createVMPP('tofail', 'snapshot', 'hourly',
                                    pdict=pdict)
        vm = self.getvm(self.pool, 'linux', 'UP')
        vm.paramSet('protection-policy', vmpp)
        vmppconf = self.pool.getVMPPConf(vmpp=vmpp)
        clock, _ = self.findNextEvents(self.pool, [vmpp], offset=-self.SAFEZONE)
        self.gotoClock(self.pool, clock)
        self.waitVMPPEvent(self.pool, vmpp, "%s=/=%s" % ('backup-last-run-time',
                                                    vmppconf['backup-last-run-time']))
        self.waitVMPPEvent(self.pool, vmpp, "is-backup-running=false")
        self.waitVMPPEvent(self.pool, vmpp, "%s=/=%s" % ('archive-last-run-time',
                                                    vmppconf['archive-last-run-time']))
        self.waitVMPPEvent(self.pool, vmpp, "is-archive-running=false")
        self.pool.setVMPPParam(vmpp, 'is-policy-enabled', 'false')

        time.sleep(30)
        archives = self.getArchives(self.pool, vm.getUUID())        
        alerts = self.pool.getVMPPAlerts(vmpp)
        emails = smtp['server'].getMail()
        msgs = self.pool.master.minimalList('message-list', args='class=VMPP')

        if len(archives) != 0:
            raise xenrt.XRTFailure("Archiving is supposed to fail and leave "
                                   "no images behind.", data = archives)

        if len(alerts[:2]) != 2:
            raise xenrt.XRTFailure("We are supposed to get two alerts: "
                                   "backup succeed, archive failed.",
                                   data = alerts)
        if not (alerts[1].has_key('message')
                and alerts[1]['message'] == 'VMPP_SNAPSHOT_SUCCEEDED'):
            raise xenrt.XRTError("VMPP backup failed, this brought "
                                 "unpredicatable consequence to the result "
                                 "of this testcase.", data = alerts)
        if not (alerts[0].has_key('error')
                and alerts[0]['error']['errorcode'].startswith('VMPP_ARCHIVE_FAILED')):
            raise xenrt.XRTFailure("VMPP archive is supposed to fail "
                                   "and generate proper alert message "
                                   "but not.", data = alerts)
        if not (len(msgs) > 0):
            raise xenrt.XRTFailure("No messages regarding the archive failure "
                                   "has been generated.")
        
        msgbody = self.pool.master.genParamGet('message', msgs[0], 'body')
        if not (msgbody.find('ARCHIVE failed') >= 0
                and msgbody.find(vm.getUUID()) >= 0):
            raise xenrt.XRTFailure("The most recent VMPP message doesn't have "
                                   "the archive failure info as we expected.",
                                   data = msgbody)
        
        if not (len(emails) > 0):
            raise xenrt.XRTFailure("No email regarding the archive failure "
                                   "has been received.", data=emails)

        xenrt.TEC().logverbose("All the files/alerts/messages/emails happened "
                               "as expected when archiving failed")

class TCMultiSnapshot(_VMPPTest):
    """Server should not generate false errors while creating many snapshots"""
    # Jira ID TC-19988
    
    DISTRO = ["centos56","rhel5"]
    
    def __init__(self,tcid=None):
        self.pool = None
        self.vmpp = None
        self.vms = []
        xenrt.TestCase.__init__(self, tcid)
    
    def createDataWritingScript(self, host, tapdiskpath, ddPattern, fileid):
        """Write the script to the controller then copy it to the host"""
        writeScript = """#!/bin/bash
dd if=/dev/urandom of=%s %s oflag=direct
touch write_done_%d.dat""" % (tapdiskpath, ddPattern.strip(), fileid)
        fn = xenrt.TEC().tempFile()
        f = file(fn, "w")
        f.write(writeScript)
        f.close()
        sftp = host.sftpClient()
        sftp.copyTo(fn, "/home/script_%d.sh" % fileid)
        host.execdom0("chmod a+x /home/script_%d.sh; exit 0" % fileid)
    
    def writeToVMDisk(self):
        """Script to write 40MBs to the VMs Disk."""
        ddPattern = "bs=40 count=1MB"
        fileid = 1
        host = self.pool.master
        vgname = "VG_XenStorage-%s" % host.lookupDefaultSR()
        for vm in self.vms:
            vbduuid = host.minimalList("vbd-list", args="vm-uuid=%s type=Disk" % vm.getUUID())[0]
            vdiuuid = host.minimalList("vdi-list", args="vbd-uuids=%s " % vbduuid)[0]
            lvname = "VHD-%s" % vdiuuid
            lvpath = "/dev/%s/%s" % (vgname, lvname)
            tapdiskminor = int(host.execdom0("tap-ctl list | grep %s | awk '{print $2}' | awk -F= '{print $2}'" % lvpath))
            tapdiskpath = "/dev/xen/blktap-2/tapdev%d" % tapdiskminor
            self.createDataWritingScript(host, tapdiskpath, ddPattern, fileid)
            host.execdom0("/home/script_%d.sh < /dev/null > script_%d.log 2>&1 &" % (fileid, fileid))
            # Wait until the write is complete.
            deadline = xenrt.util.timenow() + 1800 # 30 minutes
            while xenrt.util.timenow() < deadline:
                if host.execdom0("test -e write_done_%d.dat" % fileid, retval="code") != 1:
                    break
                    xenrt.sleep(30)
                else:
                    xenrt.TEC().warning("Timed out waiting for the pattern to be written to disk.")
    
    def verifyErrors(self):
        error = "vhd-util: libvhd::vhd_validate_footer: invalid footer cookie:"
        # Grep the error logs
        if int(self.pool.master.execdom0("grep '%s' /var/log/messages | wc -l" % (error))):
            raise xenrt.XRTFailure("There are misleading vhd_validate_footer logs")
    
    def getVMs(self, pool, names):
        """Get all the VMs created in seq file"""
        VMs = []
        for name in names:
            vm = xenrt.TEC().gec.registry.guestGet(name)
            if vm.getState()!= 'UP':
                vm.lifecycleOperation("vm-start",specifyOn=True)
                xenrt.TEC().progress("Waiting for the VM to enter the UP state")
                vm.poll("UP", pollperiod=5)
                xenrt.sleep(120)
            VMs.append(vm)
        return VMs
        
    def prepare(self, arglist=[]):
        self.pool = self.getDefaultPool()
        for h in self.pool.getHosts():
            h.license(edition='platinum')
        # Get all the VMs
        self.vms = self.getVMs(self.pool, self.DISTRO)
        # Configure The VMPR policy
        pdict = { 'archive-frequency': 'never', 'backup-schedule:min': '0'}
        self.vmpp = self.pool.createVMPP('HFX', 'snapshot', 'hourly', pdict=pdict)
        # Assign VMs to the VMPR policy
        for vm in self.vms:
            vm.paramSet('protection-policy', self.vmpp)
        
    def run(self, arglist=[]):
        """Write to the VM disks each time before taking disk snapshot of VMs
           Set the pool time to next recurring snapshot time of VMPP
           After the snapshots are taken verify the misleading logs
           """
        attempts = 50
        while attempts:
            vmppconf = self.pool.getVMPPConf(vmpp=self.vmpp)
            self.writeToVMDisk()
            # Get the next recurring time of snapshots of VMPP
            clock, _ = self.findNextEvents(self.pool, [self.vmpp], offset=-self.SAFEZONE)
            # Tweak the pool time to next recurring time of snapshots of VMPP
            self.gotoClock(self.pool, clock)
            self.waitVMPPEvent(self.pool, self.vmpp, "%s=/=%s" % ('backup-last-run-time', vmppconf['backup-last-run-time']))
            self.waitVMPPEvent(self.pool, self.vmpp, "is-backup-running=false")
            self.verifyErrors()
            xenrt.sleep(60)
            attempts = attempts - 1
            
        xenrt.TEC().logverbose("VMPR run successfully without any spurious false errors")
    
