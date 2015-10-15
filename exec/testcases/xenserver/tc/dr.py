#
# XenRT: Test harness for Xen and the XenServer product family
#
# Disaster Recovery Testcases.
#
# Copyright (c) 2010 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

#import socket, re, string, time, traceback, sys, random, copy, threading
import xenrt, xenrt.lib.xenserver
import time, calendar, sys, random, re, string
import xml.dom.minidom
from xml.dom.minidom import parseString


def getSCSIID(host, iscsi_params):
    cli = host.getCLIInstance()
    args = []
    args.append("type='lvmoiscsi'")
    args.append("device-config:target=%(ip)s" % (iscsi_params))
    args.append("device-config:targetIQN=%(iscsi_iqn)s" % (iscsi_params))
    args.append("device-config:chapuser=%(username)s" % (iscsi_params))
    args.append("device-config:chappassword=%(password)s" % (iscsi_params))
  
    #sr-probe always return with an exception
    startTime = xenrt.util.timenow()
    while xenrt.util.timenow() - startTime < 900:
        try:
            tempStr = cli.execute("sr-probe",string.join(args))
        except Exception, e:
            if "SR_BACKEND_FAILURE_141" in str(e.data):
                xenrt.TEC().logverbose("iSCSI service on target not reachable...trying again")
                xenrt.sleep(20)
                continue
            tempStr = str(e.data)
            tempStr = '\n'.join(tempStr.split('\n')[2:])

        temp = parseString(tempStr)
        ids = temp.getElementsByTagName('SCSIid')
        for id in ids:
            for node in id.childNodes:
                scsiId = (node.nodeValue).strip()
        return scsiId
    raise xenrt.XRTFailure("Unable to get iSCSIid")

def createSROnHost(host, iscsi_params, sr_name):
    """Returns the uuid of the newly created SR."""
    
    iscsi_params['iscsi_id'] = getSCSIID(host, iscsi_params)
    
    args = ['name-label=%s' % sr_name,
            'shared=true',
            'type=lvmoiscsi',
            'device-config:target=%(ip)s' % iscsi_params,
            'device-config:targetIQN=%(iscsi_iqn)s' % iscsi_params,
            'device-config:chapuser=%(username)s' % iscsi_params,
            'device-config:chappassword=%(password)s' % iscsi_params,
            'device-config:SCSIid=%(iscsi_id)s' % iscsi_params]
    
    cli = host.getCLIInstance()
    sr_uuid = cli.execute('sr-create',' '.join(args), strip=True)
    
    return sr_uuid

# size of the lun (suffix KiB, MiB, GiB or TiB)
def createIscsiLun(storage_host, lun_size):
    res = storage_host.execdom0('cd /root; /root/iu.py create_lun -s %s' % lun_size)
    lun_id = res.strip()
    mac = xenrt.randomMAC()
    # CA-138805 - Transfer VM does not renew IPs, so we'll reserve one
    if xenrt.TEC().lookup("XENRT_DHCPD", False, boolean=True):
        xenrt.StaticIP4Addr(mac=mac)
    res = storage_host.execdom0('cd /root; /root/iu.py expose -l %s --mac %s' % (lun_id, mac))
    return lun_id
    
def getIscsiParams(storage_host, lun_id):
    res = storage_host.execdom0('cd /root; /root/iu.py get_info --xml -l %s' % lun_id)
    
    dom = xml.dom.minidom.parseString(res)
    attribs = dom.getElementsByTagName('transfer_record')[0].attributes
    iscsi_params = dict([(k.encode('ascii'), attribs[k].value.strip().encode('ascii')) 
                         for k in attribs.keys()])
    
    if iscsi_params.has_key('iscsi_id'):
        del iscsi_params['iscsi_id']
        
    return iscsi_params

def setupIscsiUtilOnStorageHost(host):
    host.execdom0('cp -f %s/utils/iu.py /root/; chmod +x /root/iu.py' % xenrt.TEC().lookup("REMOTE_SCRIPTDIR"))
    
    return


def createLargeXapiDb(host):

    vm_list = host.minimalList("vm-list", args="name-label=xenrt_dummy_1000")
    if vm_list:
        return

    host.execdom0('echo #!/bin/bash > /tmp/create_vm_objects.sh')
    host.execdom0('echo for i in \`seq 1 1000\` >> /tmp/create_vm_objects.sh')
    host.execdom0('echo do >> /tmp/create_vm_objects.sh')
    host.execdom0("echo '   ' xe vm-create name-label=xenrt_dummy_\$i >> /tmp/create_vm_objects.sh")
    host.execdom0('echo done >> /tmp/create_vm_objects.sh')
    host.execdom0('echo exit 0 >> /tmp/create_vm_objects.sh')
    host.execdom0('chmod +x /tmp/create_vm_objects.sh; nohup /tmp/create_vm_objects.sh &> /dev/null < /dev/null & exit 0')

    return

def checkLunBrokenAlert(host):
    pass

def randomSRName():
    return 'sr_%08x' % random.randint(0, 0x7fffffff)

def randomGuestName():
    return xenrt.randomGuestName()


def createSR(site, lun_size, lun_id=None):
    storage_host = site['storage_host']
    if lun_id is None:
        lun_id = createIscsiLun(storage_host, lun_size)
    iscsi_params = getIscsiParams(storage_host, lun_id)
    sr_uuid = createSROnHost(site['pool_master'], iscsi_params, randomSRName())
    site['srs'][sr_uuid] = {'lun_id' : lun_id, 'metadata' : False}
    return sr_uuid

def chooseSRUuid(site, local_sr, sr_uuid, size):
    
    assert site.has_key('pool_master')
    host = site['pool_master']

    if sr_uuid is not None:
        return sr_uuid
    
    if local_sr and site['local_sr'] is not None:
        return site['local_sr']
    
    if local_sr: 
        sr_list_lvm = host.minimalList("sr-list", 
                                       args="host=%s type=lvm" % host.getMyHostName())
        sr_list_ext = host.minimalList("sr-list", 
                                       args="host=%s type=ext" % host.getMyHostName())
        if sr_list_lvm:
            site['local_sr'] = sr_list_lvm[0]
        elif sr_list_ext:
            site['local_sr'] = sr_list_ext[0]
        else:
            raise xenrt.XRTFailure("%s doesn't have local storage" % host.getMyHostName())
        return site['local_sr'] 

    assert sr_uuid is None
    return createSR(site, size)

def installLinuxVM(site, stationary_vm=False, sr_uuid=None):
    host = site['pool_master']
    sr_uuid = chooseSRUuid(site, stationary_vm, sr_uuid, '10GiB')
    if 'templateLinVM' not in site:
        installLinuxVMTemplate(site)
    templateVM = site['templateLinVM']

    guest = templateVM.copyVM(name=randomGuestName(), sruuid=sr_uuid)
    guest.start()
    return (guest, 'linux', sr_uuid, templateVM.distro)

def installLinuxVMTemplate(site):
    host = site['pool_master']
    distro = "rhel5x"
    if 'templateLinVM' in host.listGuests():
        site['templateLinVM'] = host.getGuest("templateLinVM")
    else:
        #install a new VM
        sr_uuid = chooseSRUuid(site, True, None, None)
        site['templateLinVM'] = host.createBasicGuest(distro, name="templateLinVM", sr=sr_uuid)
        site['templateLinVM'].shutdown()
    site['templateLinVM'].distro = distro

def installWindowsVM(site, stationary_vm=False, sr_uuid=None):

    host = site['pool_master']
    sr_uuid = chooseSRUuid(site, stationary_vm, sr_uuid, '30GiB')
    if 'templateWinVM' not in site:
        installWindowsVMTemplate(site)
    templateVM = site['templateWinVM']

    guest = templateVM.copyVM(name=randomGuestName(), sruuid=sr_uuid)
    guest.start()

    return (guest, 'windows', sr_uuid, templateVM.distro)

def installWindowsVMTemplate(site):
    host = site['pool_master']
    distro="ws08sp2-x86"
    if 'templateWinVM' in host.listGuests():
        site['templateWinVM'] = host.getGuest("templateWinVM")
    else:
        #install a new VM
        sr_uuid = chooseSRUuid(site, True, None, None)
        site['templateWinVM'] = host.createGenericWindowsGuest(name="templateWinVM", sr=sr_uuid, distro=distro, memory=1024)
        site['templateWinVM'].unenlightenedShutdown()
        site['templateWinVM'].poll('DOWN')
    site['templateWinVM'].distro = distro

def upgradePool(pool):
    pool_upgrade = xenrt.lib.xenserver.host.RollingPoolUpdate(pool)
    return pool.upgrade(poolUpgrade=pool_upgrade)


def parseXapiTime(timestamp):
        
    if timestamp.endswith('Z'):
        timestamp = timestamp[0:-1]
        
    return int(calendar.timegm(time.strptime(timestamp, "%Y%m%dT%H:%M:%S")))

def getVMPowerState(host, vm_uuid):
    return host.genParamGet("vm", vm_uuid, "power-state")
    
def getVMStartTimeAndBootOrder(host, vm_uuid):
    order = host.genParamGet("vm",vm_uuid, "order")
    start_time = host.genParamGet("vm",vm_uuid, "start-time")
    
    return (int(order), parseXapiTime(start_time), vm_uuid)

def sortListInPlace(list_to_sorted, by_field=1):
    cmp_fn = lambda x, y: cmp(x[by_field], y[by_field])
    list_to_sorted.sort(cmp=cmp_fn)

def verifyListIsSorted(sorted_list, by_field=0):
    lst_len = len(sorted_list)
    if lst_len <= 1: # if there is 0 or 1 item in the list
        return True
    cmp_fn = lambda x: x[0][by_field] <= x[1][by_field]
    
    lst_1 = zip(sorted_list, sorted_list[1:])
    lst_2 = map(cmp_fn, lst_1)
    
    return reduce(lambda x, y: x and y,  lst_2, True)

def createGuestObject(host, vm_uuid, distro, vm_type):
    vm_name = host.genParamGet('vm', vm_uuid, 'name-label')
    guest = host.guestFactory()(vm_name, None)
    guest.distro = distro
    if vm_type == 'windows':
        guest.windows = True
    else:
        guest.windows = False
    guest.tailored = True
    guest.existing(host)
    xenrt.TEC().logverbose("Found existing guest: %s" % vm_name)
    xenrt.TEC().registry.guestPut(vm_name, guest)
    
    return guest

def checkVMHealth(guest, vm_type, only_health_check=True):
        
    if only_health_check:
        if guest.getState() != 'UP':
            raise xenrt.XRTFailure('VM (%s) is not UP' % guest.getUUID())
        guest.checkHealth()
        return
    
    if guest.getState() != 'UP':
        guest.checkHealth(noreachcheck=True)
        guest.reboot()
    if vm_type == 'linux':
        guest.waitForSSH(1440, desc='Guest reboot')
    else:
        guest.waitForDaemon(1440, desc='Guest reboot')
    guest.shutdown()
    guest.poll('DOWN')
    time.sleep(30)
    guest.start()
    if vm_type == 'linux':
        guest.waitForSSH(1440, desc='Guest reboot')
    else:
        guest.waitForDaemon(1440, desc='Guest reboot')
    guest.checkHealth()
    return

def verifyVMBootOrder(host, vm_uuids):
    
    if len(vm_uuids) == 0:
        return True   
 
    lst = [getVMStartTimeAndBootOrder(host, vm_uuid) for vm_uuid in vm_uuids]
    sortListInPlace(lst)
    
    if not verifyListIsSorted(lst):
        xenrt.TEC().logverbose("VMs didn't boot in the order specified")
        
        for item in lst:
            xenrt.TEC().logverbose("order = %s   time = %s   vm_uuid = %s" % item) 
            
            return False

    return True


def isVMProtected(host, vm_uuid):
    return (host.genParamGet('vm', vm_uuid, 'ha-restart-priority') == 'restart')


def waitForVMToBeUp(host, vm_uuid):
    cli = host.getCLIInstance()
    cli.execute("event-wait class=vm uuid=%s power-state=running" % vm_uuid)
    
    return
    
def enableMetadataReplication(host, instances=8, large_xapi_db=True):

    dr_utils = DRUtils()
    site = dict()    
    dr_utils.sites['site_A'] = site
    site['pool_master'] = host
    site['storage_host'] = host
    site['vms'] = dict()
    site['appliances'] = dict()
    site['heartbeat_sr'] = None
    site['srs'] = dict()
    site['metadata_vdis'] =  dict()
    site['metadata_luns'] = []
    site['local_sr'] = None

    setupIscsiUtilOnStorageHost(host)

    if large_xapi_db:
        createLargeXapiDb(host)
        
    dr_utils.createMetadataSRs('site_A', no_of_srs=instances, enable_db_replication=True)


class Appliance(object):
    
    """This class implements appliance feature (implemented in Boston) """

    def __init__(self, host, name=None, uuid=None):
        
        if name is None:
            name = xenrt.randomApplianceName()

        assert host is not None
            
        self.name = name
        self.host = host
        self.uuid = uuid

        if self.uuid is not None:
            self.name = host.genParamGet('appliance', self.uuid, 'name-label')
        
        self.vms = dict()
        
    def getName(self):
        return self.name

    def getUuid(self):
        assert self.uuid is not None
        return self.uuid

    def getVMsParams(self):
        return self.vms.values()
    
    def create(self):
        
        if self.uuid is not None:
            return 
        
        cli = self.host.getCLIInstance()
        self.uuid = cli.execute('appliance-create', 'name-label=%s' % self.name, strip=True)
        
        return

    def addVM(self, guest, vm_type, sr_uuid, distro, only_metadata_update=False):
        assert self.uuid is not None
        assert guest is not None

        if not only_metadata_update:
            cli = self.host.getCLIInstance()
            args = ['uuid=%s' % guest.getUUID(), 'appliance=%s' % self.uuid]
            cli.execute('vm-param-set', ' '.join(args))
        
        self.vms[guest.getName()] = { 'guest'   : guest, 
                                      'vm_type' : vm_type, 
                                      'vm_uuid' : guest.getUUID(), 
                                      'sr_uuid' : sr_uuid, 
                                      'distro'  : distro }

        return
        
    def start(self):
        
        assert self.uuid is not None
        
        if not self.vms:
            xenrt.TEC().logverbose('Appliance (%s) has 0 VMs' % self.uuid)
            return

        cli = self.host.getCLIInstance()
        cli.execute('appliance-start', 'uuid=%s' % self.uuid)
        return

    def shutdown(self, force=False):
        
        assert self.uuid is not None

        if not self.vms:
            xenrt.TEC().logverbose('Appliance (%s) has 0 VMs' % self.uuid)
            return
        
        cli = self.host.getCLIInstance()
        args = 'uuid=%s' % self.uuid
        if force:
            args += ' force=true'
        cli.execute('appliance-shutdown', args)
        
        return 

    def checkHealth(self):
        for vm_info in self.vms.values():
            checkVMHealth(vm_info['guest'], vm_info['vm_type'])

        return

    def checkBootOrder(self):

        if not self.vms:
            return True

        vm_uuids = [vm_info['vm_uuid'] for vm_info in self.vms.values()]
        return verifyVMBootOrder(self.host, vm_uuids)
        

    def getSRs(self):
        
        return [vm_info['sr_uuid'] for vm_info in self.vms.values()]   

    def delete(self):
        
        vms_value = self.host.genParamGet('appliance', self.getUuid(), 'VMs')
        p = re.compile('(;|,)')
        vms = p.sub(' ', vms_value).split()
        
        left_over_vms = set(vms) - set([vm_info['vm_uuid']  for vm_info in self.vms.values()])
        
        cli = self.host.getCLIInstance()
        try:
            cli.execute('appliance-shutdown', args='uuid=%s force=true' % self.getUuid())
        except:
            pass

        cli.execute('appliance-destroy', 'uuid=%s' % self.getUuid())
        
        for vm_info in self.vms.values():
            guest = vm_info['guest']
            assert guest.getState() == 'DOWN'
            try:
                guest.uninstall()
            except:
                xenrt.TEC().warning('VM (%s) uninstall failed' % guest.getUUID())
        
        for vm_uuid in left_over_vms:
            cli.execute('vm-shutdown', args='uuid=%s force=true' % vm_uuid)

        self.vms = dict()
        self.uuid = None
        return 

class DRUtils(object):
    
    def __init__(self):

        self.sites = dict()
        return

    def createMetadataSRs(self, site_name, no_of_srs=1, enable_db_replication=True, list_of_luns=None):  # to be called from the SR
        assert self.sites.has_key(site_name)

        site = self.sites[site_name]
        
        if list_of_luns is None:
            for i in range(no_of_srs):
                sr_uuid = createSR(site, '2GiB')
                if enable_db_replication:
                    self.enableDatabaseReplication(site_name, sr_uuid)
        else:
            for lun in list_of_luns:
                sr_uuid = createSR(site, '2GiB', lun_id=lun)
                if enable_db_replication:
                    self.enableDatabaseReplication(site_name, sr_uuid)

        site['metadata_vdis'].update(self.getMetadataVDISRPairs(site_name))
        return

    def enableDatabaseReplication(self, site_name, sr_uuid):
        assert self.sites.has_key(site_name)
        assert self.sites[site_name].has_key('pool_master')
        
        host = self.sites[site_name]['pool_master']
        site = self.sites[site_name]
        cli = host.getCLIInstance()
        cli.execute('sr-enable-database-replication', 'uuid=%s' % sr_uuid)
        site['srs'][sr_uuid]['metadata'] = True
        

    def flushXapiDB(self, site_name):
        assert self.sites.has_key(site_name)
        assert self.sites[site_name].has_key('pool_master')
        
        host = self.sites[site_name]['pool_master']
        cli = host.getCLIInstance()
        cli.execute('vm-create', 'name-label=%s' % randomGuestName())
        

    def disableDatabaseReplication(self, site_name, sr_uuid):
        assert self.sites.has_key(site_name)
        assert self.sites[site_name].has_key('pool_master')
        
        host = self.sites[site_name]['pool_master']
        site = self.sites[site_name]
        cli = host.getCLIInstance()
        cli.execute('sr-disable-database-replication', 'uuid=%s' % sr_uuid)
        site['srs'][sr_uuid]['metadata'] = False

    def createAppliance(self, site, site_params):
        
        assert site.has_key('pool_master')
        host = site['pool_master']
        assert site.has_key('appliances')

        appliance = Appliance(host)
        appliance.create()
        
        site['appliances'][appliance.getName()] = appliance

        sr_uuid = None
        if site_params.has_key('vms_on_same_sr') and site_params['vms_on_same_sr']:
            sr_size = 10 * site_params['vms_in_an_appliance']
            sr_uuid = createSR(site, str(sr_size) + 'GiB')
        
        vm_start_delay = site['vm_start_delay']

        for i in range(site_params['vms_in_an_appliance']):
            (guest, vm_type, vm_sr_uuid, distro) = installLinuxVM(site, sr_uuid=sr_uuid)
            appliance.addVM(guest, vm_type, vm_sr_uuid, distro)
            guest.getHost().genParamSet('vm', guest.getUUID(), 'order', str(i))
            guest.getHost().genParamSet('vm', guest.getUUID(), 'start-delay', str(vm_start_delay))

        return

    def installAppliances(self, site, site_params):
        
        if not site_params.has_key('appliances'):
            return

        for i in range(site_params['appliances']):
            self.createAppliance(site, site_params)

        return
    

    def installVMs(self, site, site_params):
        
        if site_params.has_key('win_vms') and site_params['win_vms'] > 0:

            sr_uuid = None
            if site_params.has_key('vms_on_same_sr') and site_params['vms_on_same_sr']:
                sr_size = 30 * site_params['win_vms']
                sr_uuid = createSR(site, str(sr_size) + 'GiB')

            for i in range(site_params['win_vms']):
                (guest, vm_type, vm_sr_uuid, distro) = installWindowsVM(site, sr_uuid=sr_uuid)
                site['vms'][guest.getName()] = { 'guest'   : guest, 
                                                 'vm_type' : vm_type, 
                                                 'vm_uuid' : guest.getUUID(), 
                                                 'sr_uuid' : vm_sr_uuid, 
                                                 'distro'  : distro }
        
        if site_params.has_key('lin_vms') and site_params['lin_vms'] > 0:
            
            sr_uuid = None
            if site_params.has_key('vms_on_same_sr') and site_params['vms_on_same_sr']:
                sr_size = 10 * site_params['lin_vms']
                sr_uuid = createSR(site, str(sr_size) + 'GiB')

            
            for i in range(site_params['lin_vms']):
                (guest, vm_type, vm_sr_uuid, distro) = installLinuxVM(site, sr_uuid=sr_uuid)
                site['vms'][guest.getName()] = { 'guest'   : guest, 
                                                 'vm_type' : vm_type, 
                                                 'vm_uuid' : guest.getUUID(), 
                                                 'sr_uuid' : vm_sr_uuid, 
                                                 'distro'  : distro }

        if site_params.has_key('stationary_vms'):
            for i in range(site_params['stationary_vms']):
                (guest, vm_type, vm_sr_uuid, distro) = installLinuxVM(site, stationary_vm=True)
                site['stationary_vms'][guest.getName()] = { 'guest'   : guest, 
                                                            'vm_type' : vm_type, 
                                                            'vm_uuid' : guest.getUUID(), 
                                                            'sr_uuid' : vm_sr_uuid, 
                                                            'distro'  : distro }
        return        


    def getAllAppliancesSRs(self, site_name):
        
        assert self.sites.has_key(site_name)
        site = self.sites[site_name]
        
        if not site.has_key('appliances'):
            return set()
    
        appl_srs = reduce(lambda x, y: x + y, 
                          [appliance.getSRs() for appliance in site['appliances'].values()],
                          [])
        return set(appl_srs)        

    def getMetadataSRs(self, site_name):
        
        assert self.sites.has_key(site_name)
        site = self.sites[site_name]
        assert site.has_key('srs')
        
        metadata_srs = []
        for sr, sr_info in site['srs'].items():
            if sr_info.has_key('metadata') and sr_info['metadata']:
                metadata_srs.append(sr)

        return set(metadata_srs)


    def getMetadataLuns(self, site_name):
        assert self.sites.has_key(site_name)
        site = self.sites[site_name]
        
        metadata_srs = self.getMetadataSRs(site_name)
        return [site['srs'][sr_uuid]['lun_id'] for sr_uuid in metadata_srs]
        

    def unplugSR(self, site_name, sr_uuid):
        assert self.sites.has_key(site_name)
        site = self.sites[site_name]
        host = site['pool_master']
                
        pbds = host.minimalList("pbd-list",args="sr-uuid=%s" % sr_uuid) 
        
        cli = host.getCLIInstance()
        for pbd in pbds:
            pbd = pbd.strip()
            ca = host.genParamGet("pbd", pbd, "currently-attached")
            if ca != "true":
                xenrt.TEC().logverbose("PBD %s of SR %s not attached" % (pbd, sr_uuid))
            else:
                cli.execute("pbd-unplug","uuid=%s" % pbd)

        return

    def unplugMetadataSRs(self, site_name):
#CHECKME:   We need to look for METADATA_LUN_BROKEN messages
#CHECKME:   We need some logic to check for broken_luns        
        
        srs = self.getMetadataSRs(site_name)
        for sr in srs:
            self.unplugSR(site_name, sr)

        return
        
    def unplugAllSRs(self, site_name):
        
        assert self.sites.has_key(site_name)

        site = self.sites[site_name]
        srs = site['srs'].keys()
        
        for sr in srs:
            self.unplugSR(site_name, sr)
            
        return

    def plugSR(self, site_name, sr_uuid):
        assert self.sites.has_key(site_name)
        site = self.sites[site_name]
        host = site['pool_master']
                
        pbds = host.minimalList("pbd-list",args="sr-uuid=%s" % sr_uuid) 
        
        cli = host.getCLIInstance()
        for pbd in pbds:
            pbd = pbd.strip()
            ca = host.genParamGet("pbd", pbd, "currently-attached")
            if ca != "true":
                cli.execute("pbd-plug","uuid=%s" % pbd)
            else:
                xenrt.TEC().logverbose("PBD %s of SR %s is attached" % (pbd, sr_uuid))                

        return


    def plugAllSRs(self, site_name):
        assert self.sites.has_key(site_name)
        site = self.sites[site_name]

        srs = site['srs'].keys()
        
        for sr in srs:
            self.plugSR(site_name, sr)

        return
        

    def forgetSR(self, site_name, sr_uuid):
        assert self.sites.has_key(site_name)
        site = self.sites[site_name]
        host = site['pool_master']
        
        cli = host.getCLIInstance()
        # drtask-destroy would have "forgotten" the SR
        sr_list = host.minimalList("sr-list", args="uuid=%s" % sr_uuid)
        if sr_list:
            cli.execute('sr-forget', 'uuid=%s' % sr_uuid)
    
        if site['srs'].has_key(sr_uuid):
            del site['srs'][sr_uuid]

        return

    def forgetAllSRs(self, site_name):
        assert self.sites.has_key(site_name)

        site = self.sites[site_name]
        srs = site['srs'].keys()
        
        for sr in srs:
            self.forgetSR(site_name, sr)

        return

    def stopMetadataReplication(self, site_name):
        assert self.sites.has_key(site_name)
        srs = self.getMetadataSRs(site_name)

        for sr_uuid in srs:
            try:
                self.disableDatabaseReplication(site_name, sr_uuid)
            except:
                pass
        return

    def cleanupSite(self, site_name, uninstall_vms=False, disable_ha=False):
        assert self.sites.has_key(site_name)
        site = self.sites[site_name]

        if disable_ha:
            self.disableHA(site_name)
        
        if uninstall_vms:
            items = site['vms'].items()
            if site.has_key('stationary_vms'):
                items.extend(site['stationary_vms'].items())
            for vm_name, vm_info in items:
                guest = vm_info['guest']
                if guest.getState() == 'UP':
                    guest.shutdown(force=True)
                try:
                    guest.uninstall()
                except:
                    xenrt.TEC().warning('VM (%s) uninstall failed' % guest.getUUID())
            site['vms'] = dict()
            if site.has_key('stationary_vms'):
                site['stationary_vms'] = dict()
            
            self.deleteAppliances(site_name)

        self.stopMetadataReplication(site_name)
        self.unplugAllSRs(site_name)
        self.forgetAllSRs(site_name)

        return

    def cleanupStorageSite(self, host):

        host.execdom0('echo #!/bin/bash > /root/delete_luns.sh')
        host.execdom0('echo for i in \`/root/iu.py list_luns -q\` >> /root/delete_luns.sh')
        host.execdom0('echo do >> /root/delete_luns.sh')
        host.execdom0("echo '   ' /root/iu.py unexpose -l \$i >> /root/delete_luns.sh")
        host.execdom0("echo '   ' /root/iu.py delete_lun -l \$i >> /root/delete_luns.sh")
        host.execdom0('echo done >> /root/delete_luns.sh')
        host.execdom0('echo exit 0 >> /root/delete_luns.sh')
        host.execdom0('chmod +x /root/delete_luns.sh; /root/delete_luns.sh')

        return


    def detachMetadataSRs(self, site_name):
        assert self.sites.has_key(site_name)
        
        srs = self.getMetadataSRs(site_name)
        site = self.sites[site_name]

        self.unplugMetadataSRs(site_name)
        return
            
    
    def breakStorage(self, site_name):
        assert self.sites.has_key(site_name)
        site = self.sites[site_name]
        assert site.has_key('storage_host')
        sr_lun_pairs = self.getAllSRLunPairsPresentedToTheSite(site_name)
        
        storage_host = site['storage_host'] 
        for lun_id in sr_lun_pairs.values():
            storage_host.execdom0('cd /root; /root/iu.py unexpose -l %s' % lun_id)
            mac = xenrt.randomMAC()
            storage_host.execdom0('cd /root; /root/iu.py expose -l %s --mac %s' % (lun_id, mac))
            
        return


    def enableHA(self, site_name):
        
        assert self.sites.has_key(site_name)
        site = self.sites[site_name]
        
        assert site.has_key('pool')
        pool = site['pool']    
    
        if pool.getPoolParam('ha-enabled') == 'true':
            return

        sr_uuid = createSR(site, '2GiB', lun_id=site['heartbeat_lun'])
        site['heartbeat_sr'] = sr_uuid
        site['heartbeat_lun'] = site['srs'][sr_uuid]['lun_id']
        
        pool.enableHA(srs=[sr_uuid])

        return

    def disableHA(self, site_name):
        assert self.sites.has_key(site_name)
        site = self.sites[site_name]
        assert site.has_key('pool')
        pool = site['pool']

        if pool.getPoolParam('ha-enabled') == 'true':
            pool.disableHA()
            sr_uuid = site['heartbeat_sr']
            self.unplugSR(site_name, sr_uuid)
            self.forgetSR(site_name, sr_uuid)
            site['heartbeat_sr'] = None

        return 
    
    def protectVMs(self, site):
        
        assert site.has_key('vms')
        assert site.has_key('pool_master')

        host = site['pool_master']
        vm_start_delay = site['vm_start_delay']
        order = 0
        for vm in site['vms'].values():
            guest = vm['guest']
            host.genParamSet('vm', guest.getUUID(), 'ha-restart-priority', 'restart')
            host.genParamSet('vm', guest.getUUID(), 'order', str(order))
            host.genParamSet('vm', guest.getUUID(), 'start-delay', str(vm_start_delay))
            order += 1
        
        return

    def getProtectedVMUuids(self, site):

        assert site.has_key('vms')
        assert site.has_key('pool_master')

        host = site['pool_master']
        
        protected_vms = []
        for vm in site['vms'].values():
            guest = vm['guest']
            if isVMProtected(host, guest.getUUID()):
                protected_vms.append(guest.getUUID())
                
        return protected_vms


    def suspendVMs(self, site_name):
        
        assert self.sites.has_key(site_name)
        site = self.sites[site_name]

        assert site.has_key('vms')
        assert site.has_key('pool_master')

        host = site['pool_master']
        #set suspend image SR to SR on which VM resides
        self.setVMSuspendSR(site)
        for vm in site['vms'].values():
            guest = vm['guest']
            guest.suspend()
            vm['suspended'] = True

        return


    def setVMSuspendSR(self, site):
        assert site.has_key('vms')
        assert site.has_key('pool_master')

        host = site['pool_master']
        
        for vm in site['vms'].values():
            host.genParamSet('vm', vm['vm_uuid'], 'suspend-SR-uuid', vm['sr_uuid'])
            
        return
            

    def createVDI(self, site, vdi_type="suspend", size=4294967296):
        assert site.has_key('pool_master')
        host = site['pool_master'] 

        sr_uuid = chooseSRUuid(site, True, None, None) 
        cli = host.getCLIInstance()
        args = []
        args.append("name-label='XenRT Test VDI on %s'" % sr_uuid)
        args.append("sr-uuid=%s" % sr_uuid)
        args.append("virtual-size=%s" % str(size)) 
        args.append("type=%s" % vdi_type)
        vdi = cli.execute("vdi-create", ' '.join(args), strip=True)

        return vdi

    def copyVDI(self, site, source_vdi, sr_uuid=None):
        assert site.has_key('pool_master')
        host = site['pool_master'] 
        
        if sr_uuid is None:
            sr_uuid = chooseSRUuid(site, True, None, None) 

        cli = host.getCLIInstance()
        args = []
        args.append("sr-uuid=%s" % sr_uuid)
        args.append("uuid=%s" % source_vdi)
        vdi = cli.execute('vdi-copy', ' '.join(args), strip=True)
    
        return vdi   
 
    def setSuspendVDI(self, host, vm_uuid, vdi_uuid, accept_failure=False):
        
        try:
            host.genParamSet('vm', vm_uuid, 'suspend-VDI-uuid', vdi_uuid) 
        except xenrt.XRTFailure, e:
            if accept_failure is False:
                raise e.__class__, e, sys.exc_info()[2]
            else:
                pass
        else:
            if accept_failure is True:
                raise xenrt.XRTFailure('We could set suspend-VDI-uuid to an invalid copy of suspend image')
        return

            
    def testSuspendVDIs(self, site_name):
        assert self.sites.has_key(site_name)
        site = self.sites[site_name]
        assert site.has_key('pool_master')
        host = site['pool_master']        

        suspended_vms = self.getSuspendedVMs(site)
        if len(suspended_vms) == 0:
            return
        
        bad_copy = self.createVDI(site)

        for vm in suspended_vms:
            suspend_vdi = host.genParamGet('vm', vm['vm_uuid'], 'suspend-VDI-uuid')
            good_copy_1 = self.copyVDI(site, suspend_vdi) 
            self.setSuspendVDI(host, vm['vm_uuid'], bad_copy, accept_failure=True)
            self.setSuspendVDI(host, vm['vm_uuid'], good_copy_1, accept_failure=False)
            host.destroyVDI(suspend_vdi)
            xenrt.sleep(30)
            good_copy_2 = self.copyVDI(site, good_copy_1, sr_uuid=vm['sr_uuid'])
            self.setSuspendVDI(host, vm['vm_uuid'], good_copy_2, accept_failure=False)
            host.destroyVDI(good_copy_1)

        host.destroyVDI(bad_copy)
        return

    def setupSite(self, site_params):
        
        assert site_params.has_key('pool_master')
        assert site_params.has_key('storage_host')
        assert site_params.has_key('site_name')

        site_name = site_params['site_name']
        assert site_name not in self.sites.keys()
        
        self.sites[site_name] = dict()
        site = self.sites[site_name]

        site['pool_master'] = site_params['pool_master']
        site['pool'] = site_params['pool']
        site['storage_host'] = site_params['storage_host']
        site['vms'] = dict()
        site['stationary_vms'] = dict()
        site['appliances'] = dict()
        site['srs'] = dict()
        site['metadata_vdis'] =  dict()
        site['metadata_luns'] = []
        site['vm_start_delay'] = site_params['vm_start_delay']
        site['heartbeat_sr'] = None 
        site['heartbeat_lun'] = None
        site['active_dr_tasks'] = dict()
        site['local_sr'] = None

        if site_params.has_key('large_xapi_db') and site_params['large_xapi_db']:
            createLargeXapiDb(site['pool_master'])

        if site_params.has_key('win_vms') or site_params.has_key('lin_vms') or  site_params.has_key('stationary_vms'):
            self.installVMs(site, site_params)

        if site_params.has_key('appliances'):
            self.installAppliances(site, site_params)

        if site_params.has_key('suspend_vms') and site_params['suspend_vms']:
            if site_params.has_key('upgrade_test') and site_params['upgrade_test']:
                pass
            else:
                self.suspendVMs(site_name)
       
        if site_params.has_key('ha_enabled'): 
            site['ha_enabled'] = site_params['ha_enabled']
        else:
            site['ha_enabled'] = False

        if site['ha_enabled']:
            self.protectVMs(site)
            self.enableHA(site_name)

        return

    def powerOff(self, site_name):

        assert self.sites.has_key(site_name)
        site = self.sites[site_name]
        assert site.has_key('pool_master')
        host = site['pool_master']        
        pool = site['pool']

        for h in pool.getHosts():
            xenrt.TEC().logverbose("Attempting power off %s" % h.getName())
            h.poweroff()


    def powerOn(self, site_name):

        assert self.sites.has_key(site_name)
        site = self.sites[site_name]
        assert site.has_key('pool_master')
        host = site['pool_master']        
        pool = site['pool']

        for h in pool.getHosts():
            xenrt.TEC().logverbose("Attempting power on 1/2")
            h.machine.powerctl.on()

        for h in pool.getHosts():
            try:                
                h.waitForSSH(600, desc="First boot attempt on dead host")
                xenrt.TEC().logverbose("Host booted after one power cycle")
            except:
                # Try again
                xenrt.TEC().warning("Host %s still unreachable after 1 power cycle" % 
                                    h.getName())
                xenrt.TEC().logverbose("Attempting power cycle 2/2")
                h.machine.powerctl.cycle()
                # If this fails we want to bail out, so don't wrap in try/except
                h.waitForSSH(600, desc="Second boot attempt on dead host")

        pool.findMaster()
        if pool.master != host:
            xenrt.TEC().logverbose("New master == %s. Old master == %s" % 
                                   (pool.master.getName(), host.getName()))
            site['pool_master'] = pool.master


    def drTaskCreate(self, site, sr_uuid, lun_id):
        
        assert site.has_key('storage_host')
        assert site.has_key('pool_master')
        
        storage_host = site['storage_host']
        iscsi_params = getIscsiParams(storage_host, lun_id)

        host = site['pool_master']
        iscsi_params['iscsi_id'] = getSCSIID(host, iscsi_params)
            
        args = ['shared=true',
                'type=lvmoiscsi',
                'device-config:target=%(ip)s' % iscsi_params,
                'device-config:targetIQN=%(iscsi_iqn)s' % iscsi_params,
                'device-config:chapuser=%(username)s' % iscsi_params,
                'device-config:chappassword=%(password)s' % iscsi_params,
                'device-config:SCSIid=%(iscsi_id)s' % iscsi_params,
                'sr-whitelist=%s' % sr_uuid]

        cli = host.getCLIInstance()
        dr_uuid = cli.execute('drtask-create', ' '.join(args), strip=True)
        
# #CHECKME: Workaround for CA-55666
#         cli.execute('sr-scan', 'uuid=%s' % sr_uuid)
#CHECKME: verify that introduced SR has the same UUID as the original SR
#CHECKME: Check with John about this behaviour
        
        site['srs'][sr_uuid] = {'lun_id' : lun_id}

        assert site.has_key('active_dr_tasks')
        site['active_dr_tasks'][dr_uuid] = sr_uuid
            
    
    def getAllSRLunPairsPresentedToTheSite(self, site_name):
        
        assert self.sites.has_key(site_name)
        site = self.sites[site_name]
        assert site.has_key('srs')
        srs = dict([(sr_uuid, sr_info['lun_id']) for (sr_uuid, sr_info) in site['srs'].items()])
        if site['heartbeat_sr']:
            del srs[site['heartbeat_sr']]             
        return srs 
        

    def introduceLunsToSite(self, site_name, sr_lun_pairs):
        
        assert self.sites.has_key(site_name)

        for sr_uuid, lun_id in sr_lun_pairs.items():
            self.drTaskCreate(self.sites[site_name], sr_uuid, lun_id)

        return


    def forgetUnwantedSRsIntroducedByDRTtask(self, site_name):
        assert self.sites.has_key(site_name)
        site = self.sites[site_name]

        if not site.has_key('active_dr_tasks'):
            return
        
        host = site['pool_master']
        cli = host.getCLIInstance()
        for dr_uuid,sr_uuid in site['active_dr_tasks'].items():
            cli.execute('drtask-destroy', 'uuid=%s' % dr_uuid)
            sr_list = host.minimalList("sr-list", args="uuid=%s" % sr_uuid)
            if len(sr_list) == 0:
                assert site['srs'].has_key(sr_uuid)
                del site['srs'][sr_uuid]
        return

    def getMetadataVDISRPairs(self, site_name):
        assert self.sites.has_key(site_name)
        site = self.sites[site_name]
        
        metadata_srs = self.getMetadataSRs(site_name)
        host = site['pool_master']
        vdi_sr_pairs = dict()

        for sr in metadata_srs:
            vdis = host.minimalList("vdi-list",args="sr-uuid=%s type=Metadata" % sr)
            assert len(vdis) > 0
            for vdi in vdis:
                vdi_sr_pairs[vdi] = sr
        
        return vdi_sr_pairs
        

    def getMetadataVDIsOnSite(self, site_name):
        assert self.sites.has_key(site_name)
        site = self.sites[site_name]
        assert site.has_key('metadata_vdis') and (len(site['metadata_vdis'].keys()) > 0)
        return site['metadata_vdis'].keys()
    

    def getListOfVMParamsOnSite(self, site_name):
        assert self.sites.has_key(site_name)
        site = self.sites[site_name]
        assert site.has_key('vms')

        return site['vms'].values()

    def getSuspendedVMs(self, site):
        
        assert site.has_key('vms')
        fn = lambda vm_info : vm_info.has_key('suspended') and vm_info['suspended']
        return filter(fn, site['vms'].values())

    def checkVMBootOrder(self, site_name):
        assert self.sites.has_key(site_name)
        site = self.sites[site_name]
        
        assert site.has_key('pool_master')
        host = site['pool_master']
        
        if not site['ha_enabled']:
            return 
        
        protected_vms = self.getProtectedVMUuids(site)
        boot_order_ok = verifyVMBootOrder(host, protected_vms)

        if not boot_order_ok:
            raise xenrt.XRTFailure("VMs didn't boot in the specified order")
 
    
    def waitForAllVMsToBeUp(self, site, vm_uuids):
        
        assert site.has_key('pool_master')
        host = site['pool_master']

        for vm_uuid in vm_uuids:
            waitForVMToBeUp(host, vm_uuid)
        
        return

    def recoverVMsOnSite(self, 
                              site_name, 
                              list_of_vm_params, 
                              metadata_vdis,
                              ignore_ha=False):
        assert self.sites.has_key(site_name)
        site = self.sites[site_name]
        
        assert site.has_key('pool_master')
        host = site['pool_master']
        assert site.has_key('pool')
        pool = site['pool']

        cli = host.getCLIInstance()
        for vm_params in list_of_vm_params:
            args = 'uuid=%(vm_uuid)s' % vm_params + ' database:vdi-uuid=%s' % metadata_vdis[0]
            cli.execute('vm-recover', args, strip=True)

        protected_vms = []
        if site['ha_enabled'] and not ignore_ha:
            vm_uuids = [vm_param['vm_uuid'] for vm_param in list_of_vm_params]
            protected_vms = filter(lambda vm_uuid : isVMProtected(host, vm_uuid),
                                   vm_uuids)
            self.waitForAllVMsToBeUp(site, protected_vms)
            time.sleep(360)

        vms_resumed = []
        for vm_info in list_of_vm_params:
            if vm_info.has_key('suspended') and vm_info['suspended']:
                cli.execute('vm-resume', 'uuid=%s' % vm_info['vm_uuid'])
                vms_resumed.append(vm_info['vm_uuid'])

        self.waitForAllVMsToBeUp(site, vms_resumed)
        if vms_resumed:
            time.sleep(360)

        for vm_params in list_of_vm_params:

            if getVMPowerState(host, vm_params['vm_uuid']) == 'running':
                resident_host_uuid = pool.master.genParamGet("vm",
                                                             vm_params['vm_uuid'],
                                                             "resident-on")
                resident_host = pool.getHost(resident_host_uuid)
            else:
                resident_host = host
                
            guest = createGuestObject(resident_host, 
                                          vm_params['vm_uuid'], 
                                          vm_params['distro'], 
                                          vm_params['vm_type'])

            if guest.getState() == 'UP':
                pass
            else:
                guest.start()
                guest.poll('UP')
                
            if vm_params['vm_type'] == 'linux':
                guest.waitForSSH(1440, desc='Guest boot after recovery')
            else:
                guest.waitForDaemon(1440, desc='Guest boot after recovery')

            site['vms'][guest.getName()] = {'guest'   : guest, 
                                            'vm_type' : vm_params['vm_type'], 
                                            'vm_uuid' : guest.getUUID(), 
                                            'sr_uuid' : vm_params['sr_uuid'], 
                                            'distro'  : vm_params['distro']}
            
        return


    def recoverApplianceObject(self, site, appliance_uuid, appliance_params):

        assert site.has_key('pool_master')
        host = site['pool_master']
        assert site.has_key('pool')
        pool = site['pool']
        
        if not site.has_key('appliances'):
            site['appliances'] = dict()

        appliance = Appliance(host, uuid=appliance_uuid)
        
        for vm_params in appliance_params:
            resident_host_uuid = pool.master.genParamGet("vm",
                                                         vm_params['vm_uuid'],
                                                         "resident-on")
             
            guest = createGuestObject(pool.getHost(resident_host_uuid), 
                                          vm_params['vm_uuid'], 
                                          vm_params['distro'], 
                                          vm_params['vm_type'])

            if vm_params['vm_type'] == 'linux':
                guest.waitForSSH(1440, desc='Guest boot after recovery')
            else:
                guest.waitForDaemon(1440, desc='Guest boot after recovery')
           
            appliance.addVM(guest, 
                               vm_params['vm_type'], 
                               vm_params['sr_uuid'], 
                               vm_params['distro'], 
                               only_metadata_update=True)
        
        return appliance
                              

    def recoverAppliancesOnSite(self, 
                                     site_name, 
                                     appl_params, 
                                     metadata_vdis, 
                                     ignore_ha=False): 
        assert self.sites.has_key(site_name)
        site = self.sites[site_name]
        
        assert site.has_key('pool_master')
        host = site['pool_master']

        cli = host.getCLIInstance()
        for appliance_uuid in appl_params.keys():
            appl_list = host.minimalList("appliance-list", args="uuid=%s" % appliance_uuid)
            if appl_list:
                cli.execute('appliance-destroy', 'uuid=%s' % appliance_uuid)
            args = 'uuid=%s database:vdi-uuid=%s' % (appliance_uuid, metadata_vdis[0])
            cli.execute('appliance-recover', args, strip=True)

        
        vm_uuids = []
        for vm_params in appl_params.values():
            vm_uuids.extend([vm_info['vm_uuid'] for vm_info in vm_params])
            
        protected_vms = []
        if site['ha_enabled'] and not ignore_ha:
            protected_vms = filter(lambda vm_uuid : isVMProtected(host, vm_uuid),
                                   vm_uuids)
                        
            self.waitForAllVMsToBeUp(site, protected_vms)
            
        for appliance_uuid in appl_params.keys():
            cli.execute('appliance-start', 'uuid=%s' % appliance_uuid)

        self.waitForAllVMsToBeUp(site, list(set(vm_uuids) - set(protected_vms)))
        time.sleep(360)

        for appliance_uuid in appl_params.keys():
            appliance = self.recoverApplianceObject(site, appliance_uuid, appl_params[appliance_uuid]) 
            site['appliances'][appliance.getName()] = appliance
        
        return


    def getListOfApplianceParamsOnSite(self, site_name):
        
        assert self.sites.has_key(site_name)
        site = self.sites[site_name]
        
        assert site.has_key('appliances')
        appl_params = dict()

        for appliance in site['appliances'].values():
            appl_params[appliance.getUuid()] = appliance.getVMsParams()

        return appl_params
        

    def checkVMBootOrderInAppliances(self, site_name):
        
        assert self.sites.has_key(site_name)
        site = self.sites[site_name]
        
        assert site.has_key('appliances')
        
        boot_order_ok = True
        for appliance in site['appliances'].values():
            boot_order_ok = appliance.checkBootOrder()

        if not boot_order_ok:
            raise xenrt.XRTFailure("VMs in the appliance didn't boot in the specified order")
    
        return

    def checkAppliancesOnSite(self, site_name):
        assert self.sites.has_key(site_name)
        site = self.sites[site_name]
        
        assert site.has_key('appliances')
        
        for appliance in site['appliances'].values():
            appliance.checkHealth()


    def checkVMsOnSite(self, site_name):

        assert self.sites.has_key(site_name)
        site = self.sites[site_name]
        site.has_key('pool_master')
        host = site['pool_master']

        if site.has_key('vms') or site.has_key('stationary_vms'):
            pass
        else:
            return
        
        vms = site['vms'].values()
        if site.has_key('stationary_vms'):
            vms.extend(site['stationary_vms'].values())
    
        for vm_info in vms:
            if vm_info.has_key('suspended') and vm_info['suspended']:
                continue
            checkVMHealth(vm_info['guest'], 
                            vm_info['vm_type'])

        
        return

    def shutdownAppliances(self, site_name, force=False):
        assert self.sites.has_key(site_name)
        site = self.sites[site_name]
        assert site.has_key('appliances')
        
        for appliance in site['appliances'].values():
            appliance.shutdown(force=force)

        return

    def deleteAppliances(self, site_name):
        assert self.sites.has_key(site_name)
        site = self.sites[site_name]
        assert site.has_key('appliances')
        
        for appliance in site['appliances'].values():
            appliance.delete()

        site['appliances'] = dict()
        return 
        

    def shutdownVMs(self, site_name, handle_stationary_vms=False, force=False):
        assert self.sites.has_key(site_name)
        site = self.sites[site_name]
        site.has_key('pool_master')
        host = site['pool_master']

        if site.has_key('vms') or site.has_key('stationary_vms'):
            pass
        else:
            return
        
        vms = site['vms'].values()
        if handle_stationary_vms and site.has_key('stationary_vms'):
            vms.extend(site['stationary_vms'].values())
            
        for vm_info in vms:
            guest = vm_info['guest']
            vm_state = guest.getState()
            if vm_state == 'DOWN':
                guest.checkHealth(noreachcheck=True)
            else:
                guest.shutdown(force=force)
                guest.poll('DOWN')
            
        time.sleep(30)

        return

    def startVMs(self, site_name, handle_stationary_vms=False):
        assert self.sites.has_key(site_name)
        site = self.sites[site_name]
        site.has_key('pool_master')
        host = site['pool_master']

        if site.has_key('vms') or site.has_key('stationary_vms'):
            pass
        else:
            return

        vms = site['vms'].values()
        if handle_stationary_vms and site.has_key('stationary_vms'):
            vms.extend(site['stationary_vms'].values())
        
        for vm_info in vms:
            guest = vm_info['guest']
            if guest.getState() == 'DOWN':
                guest.start()
                guest.poll('UP')
            
        time.sleep(30)

        return
        
    def updatePoolMaster(self, site_name, pool):
        assert self.sites.has_key(site_name)
        site = self.sites[site_name]
        assert site.has_key('pool')
        site['pool'] = pool
        assert site.has_key('pool_master')
        site['pool_master'] = pool.master
        return

    def restartSite(self, site_name):

        assert self.sites.has_key(site_name)
        site = self.sites[site_name]
        assert site.has_key('pool_master')
        host = site['pool_master']
        assert site.has_key('pool')
        pool = site['pool']
        slaves = set(pool.getHosts()) - set([host])

        self.disableHA(site_name)
        
        for h in slaves:
            h.reboot()
        host.reboot()
        
        return    
        
    def ejectCDs(self, site_name):
        assert self.sites.has_key(site_name)
        site = self.sites[site_name]
        site.has_key('pool_master')
        host = site['pool_master']

        if site.has_key('vms') or site.has_key('stationary_vms'):
            pass
        else:
            return
        
        vms = site['vms'].values()
        for g in vms:
            xenrt.TEC().progress("Ejecting CD from VM %s" % (g['guest'].getName()))
            g['guest'].changeCD(None)
            
    def upgradeVMs(self, site_name):

        # upgrade guest objects
        assert self.sites.has_key(site_name)
        site = self.sites[site_name]
        site.has_key('pool_master')
        host = site['pool_master']

        if site.has_key('vms') or site.has_key('stationary_vms'):
            pass
        else:
            return

        vms = site['vms']
        for n,g in vms.iteritems():
            newGuest = createGuestObject(g['guest'].host, g['vm_uuid'], g['distro'], g['vm_type'])
            vms[n]['guest'] = newGuest

        for g in vms.values():
            xenrt.TEC().progress("Upgrading VM %s" % (g['guest'].getName()))
            if g['guest'].windows:
                g['guest'].installDrivers()
            else:
                g['guest'].installTools()
        for g in vms.values():
            g['guest'].checkHealth()


class _DRBase(xenrt.TestCase):

    UPGRADE_POOL = False
    VMS_ON_SECONDARY_SITE = False
    DONT_SIMULATE_BROKEN_STORAGE = False
    STATIONARY_VMS = False
    APPLIANCES = 0
    VMS_IN_AN_APPLIANCE = 4
    VMS_ON_SAME_SR = False
    VM_START_DELAY = 0
    LINUX_VMS = 1
    WINDOWS_VMS = 0
    NO_OF_METADATA_SRS = 1
    HA_ENABLED = False
    SUSPEND_VMS = False
    TEST_SUSPEND_VDIS = False
    SIMULATE_POWER_FAILURE = False
    
    def prepare(self, arglist=None):

        self.storage_pool = self.getPool("RESOURCE_POOL_0")
        self.storage_master = self.storage_pool.master
        setupIscsiUtilOnStorageHost(self.storage_master)
        
        self.primary_pool = self.getPool("RESOURCE_POOL_1")
        self.primary_master = self.primary_pool.master

        self.secondary_pool = self.getPool("RESOURCE_POOL_2")
        self.secondary_master = self.secondary_pool.master
        
        self.dr_utils = DRUtils()

        # Upgrade test can work with only VMs
        assert not (self.UPGRADE_POOL and self.APPLIANCES > 0)
 
        site_params = dict()
        site_params['pool_master'] = self.primary_master
        site_params['pool'] = self.primary_pool
        site_params['storage_host'] = self.storage_master
        site_params['win_vms'] = self.WINDOWS_VMS
        site_params['lin_vms'] = self.LINUX_VMS
        site_params['site_name'] = 'site_A'
        site_params['large_xapi_db'] = True
        site_params['appliances'] = self.APPLIANCES
        site_params['vms_in_an_appliance'] = self.VMS_IN_AN_APPLIANCE
        site_params['vms_on_same_sr'] = self.VMS_ON_SAME_SR
        site_params['vm_start_delay'] = self.VM_START_DELAY
        site_params['no_of_metadata_srs'] = self.NO_OF_METADATA_SRS
        site_params['ha_enabled'] = self.HA_ENABLED
        site_params['suspend_vms'] = self.SUSPEND_VMS
        site_params['upgrade_test'] = self.UPGRADE_POOL
        
        # Don't mix and match SUSPEND VM test and HA test
        assert not (self.HA_ENABLED and self.SUSPEND_VMS)

        if self.STATIONARY_VMS:
            site_params['stationary_vms'] = 1

        xenrt.TEC().logverbose('setup the site A (primary)')

        self.dr_utils.setupSite(site_params)
        
        xenrt.TEC().logverbose('check VMs on the primary site (if any)')
        self.dr_utils.checkVMsOnSite('site_A')
        self.dr_utils.checkAppliancesOnSite('site_A')

        if self.UPGRADE_POOL:
            self.dr_utils.shutdownVMs('site_A', handle_stationary_vms=True)
            self.dr_utils.ejectCDs('site_A')
            self.primary_pool = upgradePool(self.primary_pool)
            self.primary_master = self.primary_pool.master
            self.dr_utils.updatePoolMaster('site_A', self.primary_pool)
            self.dr_utils.plugAllSRs('site_A')
            self.dr_utils.startVMs('site_A', handle_stationary_vms=True)
            self.dr_utils.upgradeVMs('site_A')
            if self.SUSPEND_VMS:
                self.dr_utils.suspendVMs('site_A')

        self.dr_utils.createMetadataSRs(site_name='site_A', no_of_srs=site_params['no_of_metadata_srs'])
        self.dr_utils.flushXapiDB('site_A')


    def run(self, arglist=None):
        

        if self.SUSPEND_VMS and self.TEST_SUSPEND_VDIS:
            self.dr_utils.testSuspendVDIs('site_A')

        # 1. Setup site_B
        site_params = dict()
        site_params['pool_master'] = self.secondary_master
        site_params['pool'] = self.secondary_pool
        site_params['storage_host'] = self.storage_master
        site_params['site_name'] = 'site_B'
        site_params['large_xapi_db'] = True
        site_params['no_of_metadata_srs'] = self.NO_OF_METADATA_SRS
        site_params['vm_start_delay'] = self.VM_START_DELAY
        site_params['ha_enabled'] = self.HA_ENABLED
        
        if self.VMS_ON_SECONDARY_SITE:
            site_params['lin_vms'] = 1

        if self.STATIONARY_VMS:
            site_params['stationary_vms'] = 1

        xenrt.TEC().logverbose('setup the site B (secondary)')
        self.dr_utils.setupSite(site_params)
        
        if self.UPGRADE_POOL:
            self.dr_utils.shutdownVMs('site_B', handle_stationary_vms=True)
            self.dr_utils.ejectCDs('site_B')
            self.secondary_pool = upgradePool(self.secondary_pool)
            self.secondary_master = self.secondary_pool.master
            self.dr_utils.updatePoolMaster('site_B', self.secondary_pool)
            self.dr_utils.plugAllSRs('site_B')
            self.dr_utils.startVMs('site_B', handle_stationary_vms=True)
            self.dr_utils.upgradeVMs('site_B')

        self.dr_utils.createMetadataSRs(site_name='site_B', no_of_srs=site_params['no_of_metadata_srs'])

        # 2. Get metadata VDIs (from site_A)
        xenrt.TEC().logverbose('get the list of metadata VDIs from site A')
        vdi_sr_pairs = self.dr_utils.getMetadataVDISRPairs('site_A')
    
        # Get the list of metadata luns from site_A
        metadata_luns_from_site_A = self.dr_utils.getMetadataLuns('site_A')
        
        #if self.DONT_SIMULATE_BROKEN_STORAGE:
        #    self.dr_utils.detachMetadataSRs('site_A')
        #else: 
        xenrt.TEC().logverbose('flushing xapi db before breaking the storage')
        self.dr_utils.flushXapiDB('site_A')
        
        # 4. Break the storage to site_A (VM_srs + Metadata_srs)
        if self.SIMULATE_POWER_FAILURE:
            xenrt.TEC().logverbose('turning off all machines in primary site')
            self.dr_utils.powerOff('site_A')
        xenrt.TEC().logverbose('break storage on site A')
        self.dr_utils.breakStorage('site_A')

        if self.SIMULATE_POWER_FAILURE:
            xenrt.TEC().logverbose('turning on all machines in primary site')
            self.dr_utils.powerOn('site_A')

        # If it's power failure (simulation) we won't bother disabling HA 
        if self.HA_ENABLED and not self.SIMULATE_POWER_FAILURE:
            self.dr_utils.disableHA('site_A')

        # 3. Shutdown VMs and Appliances on site_A
        if not self.SIMULATE_POWER_FAILURE:
            xenrt.TEC().logverbose('shutdown VMs on site A')
            self.dr_utils.shutdownVMs('site_A', force=True)
            self.dr_utils.shutdownAppliances('site_A', force=True)

        # 5. Plug in VM and metadata SRs on to site_B
        xenrt.TEC().logverbose('plug in VM and metadata SRs on site B')
        sr_lun_pairs = self.dr_utils.getAllSRLunPairsPresentedToTheSite('site_A')
        self.dr_utils.introduceLunsToSite('site_B', sr_lun_pairs)
        
        # 6. Recover the VMs and Appliances
        xenrt.TEC().logverbose('recover VMs on site B')
        vm_params = self.dr_utils.getListOfVMParamsOnSite('site_A')
        metadata_vdis = self.dr_utils.getMetadataVDIsOnSite('site_A')
        appl_params = self.dr_utils.getListOfApplianceParamsOnSite('site_A')
        self.dr_utils.recoverVMsOnSite('site_B', vm_params, metadata_vdis)
        self.dr_utils.recoverAppliancesOnSite('site_B', appl_params, metadata_vdis)
        self.dr_utils.checkVMBootOrder('site_B')
        self.dr_utils.checkVMBootOrderInAppliances('site_B')
        self.dr_utils.forgetUnwantedSRsIntroducedByDRTtask('site_B')
        self.dr_utils.checkVMsOnSite('site_B')
        self.dr_utils.checkAppliancesOnSite('site_B')

        if self.SIMULATE_POWER_FAILURE:
            xenrt.TEC().logverbose("We won't bother with failback onto primary site (hosts have been rebooted)")
            return
                                   
        # 7. Cleanup site A
        xenrt.TEC().logverbose('cleanup site A')
        self.dr_utils.cleanupSite('site_A')
        
        if self.HA_ENABLED:
            self.dr_utils.enableHA('site_A')

        # 8. Shutdown the VMs and Appliances on site_B
        xenrt.TEC().logverbose('shutdown VMs on site B')
        self.dr_utils.shutdownVMs('site_B')
        self.dr_utils.shutdownAppliances('site_B')
        metadata_luns_from_site_B = self.dr_utils.getMetadataLuns('site_B')
        self.dr_utils.detachMetadataSRs('site_B')
        
        # 9. Break the storage to site_B (VM_srs + Metadata_srs)
        xenrt.TEC().logverbose('break storage to site B')
        self.dr_utils.breakStorage('site_B')
        
        # 10. Plug in VM and metadata SRs on to site_A
        xenrt.TEC().logverbose('get all LUNs presented to site B')
        sr_lun_pairs = self.dr_utils.getAllSRLunPairsPresentedToTheSite('site_B')
        xenrt.TEC().logverbose('plug in VM and metadata SRs on to site A')
        self.dr_utils.introduceLunsToSite('site_A', sr_lun_pairs)
        
        # 11. Recover the VMs
        xenrt.TEC().logverbose('recover VMs on site A')
        vm_params = self.dr_utils.getListOfVMParamsOnSite('site_B')
        metadata_vdis = self.dr_utils.getMetadataVDIsOnSite('site_B')
        appl_params = self.dr_utils.getListOfApplianceParamsOnSite('site_B')
        self.dr_utils.recoverVMsOnSite('site_A', vm_params, metadata_vdis, 
                                            ignore_ha=True)
        self.dr_utils.recoverAppliancesOnSite('site_A', appl_params, metadata_vdis, 
                                                   ignore_ha=True)
        self.dr_utils.forgetUnwantedSRsIntroducedByDRTtask('site_A')
        self.dr_utils.checkVMsOnSite('site_A')
        self.dr_utils.checkAppliancesOnSite('site_A')
        self.dr_utils.createMetadataSRs(site_name='site_A', list_of_luns=metadata_luns_from_site_A)

        
    def postRun(self):
        try:
            self.dr_utils.cleanupSite('site_A', uninstall_vms=True, disable_ha=True)
            self.dr_utils.cleanupSite('site_B', uninstall_vms=True, disable_ha=True)
        except: pass
        self.dr_utils.cleanupStorageSite(self.storage_master)
        # self.dr_utils.restartSite('site_A')
        # self.dr_utils.restartSite('site_B')
        # self.storage_master.reboot() 

class TC13538(_DRBase):
    DONT_SIMULATE_BROKEN_STORAGE = True
    LINUX_VMS = 1
    WINDOWS_VMS = 1

class TC13553(_DRBase):
    UPGRADE_POOL = True
    LINUX_VMS = 1
    WINDOWS_VMS = 1
    VMS_ON_SECONDARY_SITE = True
    DONT_SIMULATE_BROKEN_STORAGE = True

class TC13554(_DRBase):
    UPGRADE_POOL = True
    LINUX_VMS = 1
    WINDOWS_VMS = 1
    VMS_ON_SECONDARY_SITE = True
    DONT_SIMULATE_BROKEN_STORAGE = True

class TC13567(_DRBase):
    VMS_ON_SECONDARY_SITE = True
    STATIONARY_VMS = True

class TC13819(_DRBase):
    LINUX_VMS = 2
    WINDOWS_VMS = 0
    NO_OF_METADATA_SRS = 8

class TC13820(_DRBase):
    APPLIANCES = 1
    LINUX_VMS = 1
    NO_OF_METADATA_SRS = 4

class TC13821(_DRBase):
    APPLIANCES = 2
    LINUX_VMS = 0
    NO_OF_METADATA_SRS = 4
    VMS_IN_AN_APPLIANCE = 2

class TC13822(_DRBase):
    VMS_ON_SECONDARY_SITE = True
    STATIONARY_VMS = True
    LINUX_VMS = 2
    VMS_ON_SAME_SR = True
    NO_OF_METADATA_SRS = 8

class TC13934(_DRBase):
    LINUX_VMS = 4
    NO_OF_METADATA_SRS = 4
    HA_ENABLED = True

class TC13938(_DRBase):
    LINUX_VMS = 2
    APPLIANCES = 1
    NO_OF_METADATA_SRS = 4
    HA_ENABLED = True
    VMS_ON_SECONDARY_SITE = True
    STATIONARY_VMS = True
    VMS_IN_AN_APPLIANCE = 2

class TC14159(_DRBase):
    LINUX_VMS = 2
    NO_OF_METADATA_SRS = 4
    SUSPEND_VMS = True

class TC14440(_DRBase):
    LINUX_VMS = 2
    NO_OF_METADATA_SRS = 4
    SUSPEND_VMS = True
    TEST_SUSPEND_VDIS = True

class TC14352(_DRBase):
    LINUX_VMS = 2
    NO_OF_METADATA_SRS = 4
    SUSPEND_VMS = True

class TC14351(_DRBase):
    LINUX_VMS = 1
    WINDOWS_VMS = 1

class TC14857(_DRBase):
    LINUX_VMS = 1
    WINDOWS_VMS = 1
    APPLIANCES = 1
    NO_OF_METADATA_SRS = 8
    VMS_IN_AN_APPLIANCE = 2
    VMS_ON_SECONDARY_SITE = True
    STATIONARY_VMS = True
    SIMULATE_POWER_FAILURE = True

class TC14858(_DRBase):
    LINUX_VMS = 2
    APPLIANCES = 1
    NO_OF_METADATA_SRS = 8
    HA_ENABLED = True
    VMS_ON_SECONDARY_SITE = True
    STATIONARY_VMS = True
    VMS_IN_AN_APPLIANCE = 2
    SIMULATE_POWER_FAILURE = True

class EnableDbReplication(xenrt.TestCase):
    
    def prepare(self, arglist=None):
        pool = self.getDefaultPool()
        if pool is None:
            self.host = self.getDefaultHost()
        else:
            self.host = pool.master

    def run(self, arglist=None):
        enableMetadataReplication(self.host)
        
    def postRun(self):
        pass
