#
# XenRT: Test harness for Xen and the XenServer product family
#
# Storage Xen Motion.
#
# Copyright (c) 2012 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import xenrt, xenrt.lib.xenserver, itertools, time, os, os.path, random, json

class LiveMigrate(xenrt.TestCase):

    def getCDsInserted(self, guest):
        ret = guest.getHost().minimalList("vm-cd-list", args="uuid=%s vdi-params=name-label" % guest.getUUID())
        return filter(lambda x: not xenrt.isUUID(x), ret)

    def isCDDriveEmpty(self, guest):
        CDs = self.getCDsInserted(guest)
        return len(CDs) == 0

    def getLocalSRs(self, host):
        if self.test_config.has_key('local_SRs'):
            if self.test_config['local_SRs'].has_key(host.getName()):
                return self.test_config['local_SRs'][host.getName()]
        
        local_SR_types = set(['ext', 'lvm'])
        sr_uuids = host.getSRs()
        sr_types = [host.getSRParam(uuid=sr_uuid, param='type') for sr_uuid in sr_uuids]
        local_SRs = dict(itertools.ifilter(lambda x: x[1] in local_SR_types,
                                           itertools.izip(sr_uuids, sr_types)))
        self.test_config['local_SRs'] = {host.getName() : local_SRs }

        return local_SRs

    def getSharedSRs(self, host):
        # CHECKME: what's the definition of shared SR ??
        #          Is it an SR with param 'shared' == True

        # SRs are created in the sequence file
        # here we only do the filtering
        
        if self.test_config.has_key('shared_SRs'):
            if self.test_config['shared_SRs'].has_key(host.getName()):
                return self.test_config['shared_SRs'][host.getName()]
        else:
            self.test_config['shared_SRs'] = {}

        interesting_sr_types = set(['ext','lvm','lvmohba','lvmoiscsi','nfs'])
        shared_SR_types = interesting_sr_types - set(['ext', 'lvm'])
        sr_uuids = host.getSRs()
        sr_types = [host.getSRParam(uuid=sr_uuid, param='type') for sr_uuid in sr_uuids]
        shared_SRs = dict(itertools.ifilter(lambda x: x[1] in shared_SR_types,
                                            itertools.izip(sr_uuids, sr_types)))
        self.test_config['shared_SRs'] = {host.getName() : shared_SRs }
        return shared_SRs

    
    def getAllSRsByType(self, host, sr_type):
        
        local_SRs = self.getLocalSRs(host)
        shared_SRs = self.getSharedSRs(host)
        
        return [sr for (sr, sr_typ) in (local_SRs.items() + shared_SRs.items()) if sr_typ == sr_type]

    def getSRByType(self, host, sr_type, exclude_SRs=set([])):
        
        SRs = filter(lambda sr: sr not in exclude_SRs, self.getAllSRsByType(host, sr_type))

        if SRs:
            return SRs[0]
        else:
            return None

    def updateVMMetadata(self, vm_name):

        vm = self.vm_config[vm_name]

        if self.test_config[vm_name].has_key('src_SR_type'):
            vm['src_SR_type'] = self.test_config[vm_name]['src_SR_type']
            vm['dest_SR_type'] = self.test_config[vm_name]['dest_SR_type']
        elif self.test_config[vm_name].has_key('VDI_src_SR_types'):
            vm['VDI_src_SR_types'] = self.test_config[vm_name]['VDI_src_SR_types']
            vm['VDI_dest_SR_types'] = self.test_config[vm_name]['VDI_dest_SR_types']
        elif self.test_config[vm_name].has_key('src_SR'):
            vm['src_SR'] = self.test_config[vm_name]['src_SR']
            vm['dest_SR'] = self.test_config[vm_name]['dest_SR']
        elif self.test_config[vm_name].has_key('VDI_src_SR_uuids'):
            vm['VDI_src_SR_uuids'] = self.test_config[vm_name]['VDI_src_SR_uuids']
            vm['VDI_dest_SR_uuids'] = self.test_config[vm_name]['VDI_dest_SR_uuids']

        return

    def createVM(self, vm_name):
        vm = self.vm_config[vm_name]
        vm_sr = None

        host = vm['src_host']

        self.updateVMMetadata(vm_name)
        
        if self.test_config[vm_name].has_key('src_SR_type'):

            sr_type = self.test_config[vm_name]['src_SR_type']
            vm_sr = self.getSRByType(host, sr_type=sr_type)

        elif self.test_config[vm_name].has_key('VDI_src_SR_types'):

            sr_type = self.test_config[vm_name]['VDI_src_SR_types'][0]
            vm_sr = self.getSRByType(host, sr_type=sr_type) 

        elif self.test_config[vm_name].has_key('src_SR'):

            vm_sr = self.test_config[vm_name]['src_SR']

        elif self.test_config[vm_name].has_key('VDI_src_SR_uuids'):

            vm_sr = self.test_config[vm_name]['VDI_src_SR_uuids'][0]

        else:

            vm_sr = self.getLocalSRs(host).keys()[0]

        no_drivers = False
        if vm.has_key('nodrivers'):
            if vm['nodrivers']:
                no_drivers=vm['nodrivers']
                
        reuse_VM = False
        if self.test_config.has_key('reuse_VM'):
            reuse_VM = self.test_config['reuse_VM']

        guest = None
        if reuse_VM:
            guest = host.getGuest(vm_name)

        if guest is not None:
            pass
        elif vm.has_key('distro'):
            guest = host.createBasicGuest(name=vm_name, distro=vm['distro'], sr=vm_sr, nodrivers=no_drivers)
            self.getLogsFrom(guest)
        else:
            if vm_name.startswith('win'):
                src_VM_name = 'win0'
            else:
                src_VM_name = 'lin0'
            src_VM = host.getGuest(src_VM_name)
            guest = src_VM.copyVM(name=vm_name, sruuid=vm_sr)
            guest.tailored = True

        vm['obj'] = guest

        if guest.getState() != 'UP':
            guest.start()
        self.guests.append(guest)
        guest.disableFirewall()

        sm_config=None # used for deciding whether the given vdi is raw or not. e.g type=raw
        # Create additional VDIs if required
        if self.test_config[vm_name].has_key('VDI_src_SR_types'):
            if self.test_config[vm_name].has_key('raw_vdi_required'):
                if self.test_config[vm_name]['raw_vdi_required']:
                    sm_config="type=raw"
            sr_uuids = [self.getSRByType(host, sr_type=sr_type) 
                        for sr_type in self.test_config[vm_name]['VDI_src_SR_types']]
            for sr_uuid in sr_uuids[1:]:
                guest.createDisk(sizebytes=(1024 * xenrt.MEGA), sruuid=sr_uuid, smconfig=sm_config)

        if vm.has_key('VDI_src_SR_uuids'):
            if vm.has_key('raw_vdi_required'):
                if vm['raw_vdi_required']:
                    sm_config="type=raw"
            sr_uuids = vm['VDI_src_SR_uuids']
            for sr_uuid in sr_uuids[1:]:
                guest.createDisk(sizebytes=(1024 * xenrt.MEGA), sruuid=sr_uuid, smconfig=sm_config)

        attached_disks = guest.listDiskDevices()
        attached_disks.sort()
        attached_VDIs = [guest.getDiskVDIUUID(d) for d in attached_disks]
        vm['src_VDIs'] = dict(zip(attached_disks, attached_VDIs))

        if not vm.has_key('VDI_src_SR_uuids'):
            vm['VDI_src_SR_uuids'] = [host.getVDISR(vdi) for vdi in attached_VDIs]
        
        vm['VDI_locations'] = [host.genParamGet('vdi', vdi, 'location') for vdi in attached_VDIs]
            
        if self.test_config[vm_name].has_key('target_power_state'):
            power_state = self.test_config[vm_name]['target_power_state']
            if power_state == "suspended":
                guest.suspend()
            elif power_state == "halted":
                guest.shutdown()
  
        self.storeOtherVMAttribs(guest)

        return guest

    def storeOtherVMAttribs(self,guest):

        vm = self.vm_config[guest.getName()]
   
        session = guest.getHost().getAPISession(secure=False)
        vmRef = session.xenapi.VM.get_by_uuid(guest.getUUID())
        guest.getHost().logoutAPISession(session)

        nodrivers = False
        vm['VM_Src_Ref'] = vmRef
        if vm.has_key('nodrivers'):
            nodrivers = vm['nodrivers']          
 
        if guest.windows and not nodrivers:
            vm['VM_Windows_uuid'] = self.getWinOSuuid(guest)

            devices = guest.getHost().minimalList("vif-list",
                                        "device",
                                        "vm-uuid=%s" % guest.getUUID())
            networkSettings = {}
            for device in devices:
                networkSettings[device] = guest.getVifOffloadSettings(int(device))
            vm['Network_Settings'] = networkSettings

    def getWinOSuuid(self,guest):

        os.system("echo 'wmic csproduct get uuid >c:\output' >%s/script.txt" % (xenrt.TEC().getWorkdir()))
        guest.xmlrpcSendFile("%s/script.txt" % (xenrt.TEC().getWorkdir()),"c:\\script.cmd")
        guest.xmlrpcExec("c:\\script.cmd")
        guest.xmlrpcGetFile("c:\\output","%s/output" % (xenrt.TEC().getWorkdir()))
        os.system("iconv -f UTF-16 -t UTF-8 %s/output >%s/result" % (xenrt.TEC().getWorkdir(),xenrt.TEC().getWorkdir()))        
        f = open("%s/result" %(xenrt.TEC().getWorkdir()),"r")
        data = f.read()
        f.close()

        return data.splitlines()[1]

    def typeOfTest(self):
        if self.pool_A is not self.pool_B:
            return 'inter-pool'
        else:
            # If we have atleast one slave, then the test could be 'intra-pool'
            if len(self.pool_A.getSlaves()) > 0:
                return 'intra-pool'
            else:
                return 'LiveVDI'

    def populateTestConfig(self):
        # Initialize the Test config
        # Here we document all the test parameters
        # This includes the following
        #      1. 'type_of_migration' = ['inter-pool', 'intra-pool', 'LiveVDI']
        #          If pool_A != pool_B then it's LiveVDI or intra-pool baased on the
        #          number of hosts in the pool
        #      2. use_invalid_sr :: Bool (-ve test)
        #      3. auxiliary_network :: Bool (default = False)    
        #      4. iterations :: Int

        # The type_of_migration can be overridden in test_parameters
        # here we try to determine the default
        self.test_config['type_of_migration'] = self.typeOfTest()

        # For all negative test cases, number of iterations is 1. So is the default
        # CHECKME: Make sure the above assertion is valid
        self.test_config['iterations'] = 1 
        self.test_config['check_src_VDIs'] = False
        self.test_config['cancel_migration'] = False
        self.test_config['negative_test'] = False
        self.test_config['paused'] = True
        self.test_config['win_crash'] = False
        self.test_config['immediate_failure'] = False
        self.test_config['monitoring_failure'] = False
        self.test_config['skip_vmdowntime']=False
        self.test_config['use_vmsecnetwork']=False

        return
 
    def createTestVMs(self):

        host_A = {}
        host_A['win_VMs'] = 0
        host_A['lin_VMs'] = 0
        host_A['obj'] = self.test_config['host_A']

        host_B = {}
        host_B['win_VMs'] = 0
        host_B['lin_VMs'] = 0
        host_B['obj'] = self.test_config['host_B']

        assert self.test_config.has_key('test_VMs'), "Test should have some test VM(s)!"
        for vm_name in self.test_config['test_VMs']:
            self.vm_config[vm_name] = {}
            if not self.test_config.has_key(vm_name):
                self.test_config[vm_name] = {}

            vm = self.test_config[vm_name]    
            vm_config = self.vm_config[vm_name]

            if vm.has_key('src_host'):
                vm_config['src_host'] = self.test_config[vm['src_host']]
            else:
                vm_config['src_host'] = self.test_config['host_A']

            if vm.has_key('nodrivers'):
                vm_config['nodrivers'] = vm['nodrivers']

            if vm.has_key('distro'):
                self.vm_config[vm_name]['distro'] = vm['distro']
            else: # This must be a generic VM 
                if vm_name.startswith('win'):
                    if vm.has_key('src_host'):
                        if vm['src_host'] == 'host_A':
                            host_A['win_VMs'] = host_A['win_VMs'] + 1
                        else:
                            host_B['win_VMs'] = host_B['win_VMs'] + 1
                    else:
                        host_A['win_VMs'] = host_A['win_VMs'] + 1
                else:
                    if vm.has_key('src_host'):
                        if vm['src_host'] == 'host_A':
                            host_A['lin_VMs'] = host_A['lin_VMs'] + 1
                        else:
                            host_B['lin_VMs'] = host_B['lin_VMs'] + 1
                    else:
                        host_A['lin_VMs'] = host_A['lin_VMs'] + 1
            
        local_sr_host_A = self.getLocalSRs(self.test_config['host_A']).keys()[0]
        local_sr_host_B = self.getLocalSRs(self.test_config['host_B']).keys()[0]

        self.guests = []

        win0_A = host_A['obj'].getGuest('win0')
        if win0_A is None and (host_A['win_VMs'] > 0):
            win0_A = host_A['obj'].createBasicGuest(name='win0', distro="win7-x86", sr=local_sr_host_A)
            self.getLogsFrom(win0_A)
            win0_A.shutdown()

        win0_B = host_B['obj'].getGuest('win0')
        if win0_B is None and (host_B['win_VMs'] > 0):
            win0_B = host_B['obj'].createBasicGuest(name='win0', distro="win7-x86", sr=local_sr_host_B)
            self.getLogsFrom(win0_B)
            win0_B.shutdown()

        lin0_A = host_A['obj'].getGuest('lin0')
        if lin0_A is None and (host_A['lin_VMs'] > 0):
            lin0_A = host_A['obj'].createBasicGuest(name='lin0', distro="debian60", sr=local_sr_host_A)
            lin0_A.shutdown()

        lin0_B = host_B['obj'].getGuest('lin0')
        if lin0_B is None and (host_B['lin_VMs'] > 0):
            lin0_B = host_B['obj'].createBasicGuest(name='lin0', distro="debian60", sr=local_sr_host_B)
            lin0_B.shutdown()
            
        for vm_name in self.test_config['test_VMs']:
            self.createVM(vm_name)

        return

    def findHostsWithSRType(self, pool, sr_type, exclude_hosts=None):

        hosts = pool.getHosts()

        sr_is_local = sr_type in set(['ext', 'lvm'])

        if exclude_hosts is None:
            exclude_hosts = set([])

        exclude_host_names = set([h.getName() for h in exclude_hosts])

        valid_hosts = []
        for h in hosts:
            if sr_is_local:
                SRs = self.getLocalSRs(h)
            else:
                SRs = self.getSharedSRs(h)
            if sr_type in SRs.values():
                valid_hosts.append(h)

        return filter(lambda x: x.getName() not in exclude_host_names,
                      valid_hosts)

    def identifyHostAAndB(self):
        
        src_host = None
        src_host_name = None
        dest_host = None
        dest_host_name = None
        
        if self.args.has_key('src_host'):
            src_host = self.getHost(self.args['src_host'])
            src_host_name = src_host.getName()

        if self.args.has_key('dest_host'):
            dest_host = self.getHost(self.args['dest_host'])
            dest_host_name = dest_host.getName()

        if self.test_config['type_of_migration'] == 'LiveVDI':
            host = None
            candidate_hosts_final = None

            if self.test_config.has_key('src_SR_type'):
                candidate_hosts_1 = self.findHostsWithSRType(self.pool_A, self.test_config['src_SR_type'])
                candidate_hosts_2 = self.findHostsWithSRType(self.pool_A, self.test_config['dest_SR_type'])
                candidate_hosts_final = list(set(candidate_hosts_1).intersection(set(candidate_hosts_2)))
                if candidate_hosts_final == []: # this must be a negative test (or due to a invalid sequence file)
                    xenrt.TEC().logverbose("Candidate src hosts = %s ; candidate dest hosts = %s" % 
                                           (candidate_hosts_1, candidate_hosts_2))
                    candidate_hosts_final = candidate_hosts_1
            else:
                candidate_hosts_final = self.pool_A.getHosts()

            candidate_host_names = map(lambda h: h.getName(), candidate_hosts_final)
            candidate_hosts = dict(zip(candidate_host_names, candidate_hosts_final))

            if src_host:
                if candidate_hosts.has_key(src_host_name):
                    host = candidate_hosts[src_host_name]
                else:
                    xenrt.TEC().logverbose('Acceptable hosts = %s, source host (test argument) = %s' % 
                                           (candidate_hosts.keys(), src_host_name))
                    raise xenrt.XRTError('Incorrect source host passed as test argument!')
            else:
                host = candidate_hosts.values()[0]

            self.test_config['host_A'] = host
            self.test_config['host_B'] = host

        else:
            if self.test_config['type_of_migration'] == 'inter-pool':
                pool_B = self.pool_B
            else: # for intra-pool
                assert len(self.pool_A.getSlaves()) > 0
                pool_B = self.pool_A
                
            host_A = None
            host_B = None
            src_hosts = self.pool_A.getHosts()
            dest_hosts = self.pool_B.getHosts()
            candidate_hosts_src = dict(zip(map(lambda h: h.getName(), src_hosts), src_hosts))
            candidate_hosts_dest = dict(zip(map(lambda h: h.getName(), dest_hosts), dest_hosts))
            
            # Get the candidate src hosts
            if self.test_config.has_key('src_SR_type'):

                hosts = self.findHostsWithSRType(self.pool_A, 
                                                     self.test_config['src_SR_type'])
                if not hosts:
                    raise xenrt.XRTError("Could not find any host in source pool with SR type %s" % 
                                         self.test_config['src_SR_type'])
                else: 
                    candidate_hosts_src = dict(zip(map(lambda h: h.getName(), hosts), hosts))

            # Get the candidate dest hosts
            if self.test_config.has_key('dest_SR_type'):
                hosts = self.findHostsWithSRType(pool_B, 
                                                     self.test_config['dest_SR_type'])
                if not hosts:
                    raise xenrt.XRTError("Could not find any host in destination pool with SR type %s" % 
                                         self.test_config['dest_SR_type'])
                else: 
                    candidate_hosts_dest = dict(zip(map(lambda h: h.getName(), hosts), hosts))

            # Choose the src host (host_A)
            if src_host:
                if candidate_hosts_src.has_key(src_host_name):
                    host_A = candidate_hosts_src[src_host_name]
                    if candidate_hosts_dest.has_key(src_host_name):
                        del candidate_hosts_dest[src_host_name]
                else:
                    xenrt.TEC().logverbose('Acceptable hosts = %s, source host (test argument) = %s' % 
                                           (candidate_hosts_src.keys(), src_host_name))
                    raise xenrt.XRTError('Incorrect source host passed as test argument!')
            else:
                tmp = set(candidate_hosts_dest.keys())
                for h in candidate_hosts_src.keys():
                    if (tmp - set([h])):
                        host_A = candidate_hosts_src[h]
                        if candidate_hosts_dest.has_key(h):
                            del candidate_hosts_dest[h]
                        break
                if host_A is None:
                    xenrt.TEC().logverbose('Candidate source hosts = %s destination hosts = %s' % 
                                           (candidate_hosts_src.keys(), candidate_hosts_dest.keys()))
                    raise xenrt.XRTError('Insufficient machines found for the test')
                
            # Choose dest host (host_B)
            if dest_host:
                if candidate_hosts_dest.has_key(dest_host_name):
                    host_B = candidate_hosts_dest[dest_host_name]
                else:
                    xenrt.TEC().logverbose('Acceptable hosts = %s, source host (test argument) = %s' % 
                                           (candidate_hosts_dest.keys(), dest_host_name))
                    raise xenrt.XRTError('Incorrect source host passed as test argument!')
            else:
                host_B = candidate_hosts_dest.values()[0]
                
            xenrt.TEC().logverbose('host_A = %s host_B = %s' % (host_A.getName(), host_B.getName()))

            self.test_config['host_A'] = host_A
            self.test_config['host_B'] = host_B

            assert host_A is not host_B, "For inter-pool and intra-pool, hosts have to be different"

        return

    def parseArgs(self, arglist):

        self.args = {}
        for arg in arglist:
            if arg.startswith('src_SR'):
                self.args['src_SR_type'] = arg.split('=')[1]
            if arg.startswith('dest_SR'):
                self.args['dest_SR_type'] = arg.split('=')[1]
            if arg.startswith('test'):
                self.args['test'] = arg.split('=')[1]
            if arg.startswith('use_xe'):
                self.args['use_xe'] = True
            if arg.startswith('negative_test'):
                self.args['negative_test'] = True
            if arg.startswith('immediate_failure'):
                self.args['immediate_failure'] = True
            if arg.startswith('monitoring_failure'): 
                self.args['monitoring_failure'] = True
            if arg.startswith('skip_vmdowntime'):
                self.args['skip_vmdowntime'] = True
            if arg.startswith('use_vmsecnetwork'):
                self.args['use_vmsecnetwork'] = True
            if arg.startswith('src_host'):
                self.args['src_host'] = arg.split('=')[1]
            if arg.startswith('dest_host'):
                self.args['dest_host'] = arg.split('=')[1]
            if arg.startswith('gname'):
                self.args['gname'] = arg.split('=')[1]
            if arg.startswith('iterations'):
                self.args['iterations'] = int(arg.split('=')[1])
            if arg.startswith('retain_VM'):
                self.args['reuse_VM'] = True
            else:
                self.args['reuse_VM'] = False
        # pass on the arglist so that individual testcase can interpret its specific args if necessary
        self.arglist = arglist
        return

    def identifyPoolAAndB(self):
        
        self.pool_A = None
        self.pool_B = None

        src_host = None
        src_host_name = None
        dest_host = None
        dest_host_name = None
        
        if self.args.has_key('src_host'):
            src_host = self.getHost(self.args['src_host'])
            src_host_name = src_host.getName()

        if self.args.has_key('dest_host'):
            dest_host = self.getHost(self.args['dest_host'])
            dest_host_name = dest_host.getName()

        pools = map(lambda x: self.getPool(x), ['RESOURCE_POOL_0', 'RESOURCE_POOL_1'])
        self.pool_A = pools[0]
        self.pool_B = pools[1]
        
        if src_host:
            if src_host_name in map(lambda h: h.getName(), pools[0].getHosts()):
                self.pool_A = pools[0]
                self.pool_B = pools[1]
            else:
                self.pool_A = pools[1]
                self.pool_B = pools[0]
                
        if dest_host:
            if dest_host_name in map(lambda h: h.getName(), pools[0].getHosts()):
                self.pool_B = pools[0]
            else:
                self.pool_B = pools[1]
                
        # Incase of live VDI migrate and intra-pool storage migration,
        # destination pool will be same as source Pool
        if self.pool_B is None:
            self.pool_B = self.pool_A
            
        return
                           
    def prepare(self, arglist=None):

        self.test_config = {}
        self.vm_config = {}
                                       
        self.parseArgs(arglist)
                                       
        self.identifyPoolAAndB()
                                       
        self.populateTestConfig()
        
        self.setTestParameters()
        
        self.identifyHostAAndB()

        self.createTestVMs()

        self.initiateDiskActivities()

        return

    def setTestParameters(self):
        # self.test_config['test_VMs'] = ['win01', 'lin01', 'win02'] # name decides the OS type of VM
        # self.test_config['win01'] = {'distro' : 'win7-x86', # If no distro, use a default one
        #                              'VDI_src_SR_uuids' : ['']
        #                              'VDI_dest_SR_uuids' : ['']
        #                              'VDI_src_SR_types' : [''],
        #                              'VDI_dest_SR_types' : [''],
        #                              'NICs' : ['NPRI', 'NSEC', '....'], #CHECKME: Need to implement this
        #                              'src_SR' : 'On source host',
        #                              'dest_SR' : 'On dest host',
        #                              'src_SR_type' : 'iSCSI',
        #                              'dest_SR_type' : 'NFS',
        #                              'src_host' : 'host_A',  # default is Host A
        #                              'dest_host' : 'host_B', # default is Host B
        #                              'power_state' : 'running'} # We might need it for -ve test
        #                              # 'running', 'suspended', 'halted'

        # self.test_config['type_of_migration'] = 'inter-pool'
        
        # self.test_config['dest_host_on_different_subnet'] = False 
        # # In preHook, we'll put the management interface on NSEC
        # # In postMigration, we'll reset this
        
        # self.test_config['auxiliary_network'] = 'NSEC'  # Used in get_guest_parameters

        # self.test_config['negative_test'] = False # If true, some failures are expected
        # self.test_config['expected_error'] = 'Error Message'

        # # In hook, we handle this
        # self.test_config['VM_action'] = ['shutdown', 'reboot', 'start', 'crash']  
        # self.test_config['cancel_migration'] = True
        # self.test_config['ignore_downtime'] = True
        
        if self.args.has_key('gname'):
            self.test_config['test_VMs'] = [self.args['gname']]
        else:
            self.test_config['test_VMs'] = ['lin01']
        # self.test_config['test_VMs'] = ['lin01', 'winsyed']
        assert self.args.has_key('src_SR_type')
        assert self.args.has_key('dest_SR_type') 

        self.test_config[self.test_config['test_VMs'][0]] = {'src_SR_type' : self.args['src_SR_type'],
                                                             'dest_SR_type' : self.args['dest_SR_type'] }

        # self.test_config['winsyed'] = { 'distro' : 'w2k8-x86',
        #                                 'VDI_src_SR_types' : ['ext', 'ext']
        #                                 'VDI_dest_SR_types' : ['nfs', 'nfs']
        #                                 'src_host' = 'host_B',
        #                                 'dest_host' = 'host_A'}
        
        self.test_config['src_SR_type'] = self.args['src_SR_type']
        self.test_config['dest_SR_type'] = self.args['dest_SR_type']

        if self.args.has_key('test'):
            self.test_config['type_of_migration'] = self.args['test']

        if self.args.has_key('negative_test'):
            self.test_config['negative_test'] = self.args['negative_test']
        
        if self.args.has_key('use_xe'):
            self.test_config['use_xe'] = self.args['use_xe']

        if self.args.has_key('src_host'):
            self.test_config['src_host'] = self.getHost(self.args['src_host'])

        if self.args.has_key('dest_host'):
            self.test_config['dest_host'] = self.getHost(self.args['dest_host'])

        if self.args.has_key('iterations'):
            self.test_config['iterations'] = self.args['iterations']
            
        if self.args.has_key('reuse_VM'):
            self.test_config['reuse_VM'] = self.args['reuse_VM']

        if self.args.has_key('immediate_failure'):
            self.test_config['immediate_failure'] = self.args['immediate_failure']

        if self.args.has_key('monitoring_failure'):
            self.test_config['monitoring_failure'] = self.args['monitoring_failure']
            
        if self.args.has_key('skip_vmdowntime'):
            self.test_config['skip_vmdowntime'] = self.args['skip_vmdowntime']
            
        if self.args.has_key('use_vmsecnetwork'):
            self.test_config['use_vmsecnetwork'] = self.args['use_vmsecnetwork']

        return

    def checkNumOfVDIs(self, guest):
       
        xenrt.TEC().logverbose('INFO_SXM: Checking for number of VDIs attached to VM') 
        vm = self.vm_config[guest.getName()]
        expected_num = len(vm['VDI_src_SR_uuids'])
        actual_num = len(vm['obj'].getAttachedVDIs())

        if actual_num != expected_num:
            xenrt.TEC().logverbose('INFO_SXM: [VM-uuid == %s] Expected number of VDIs == %d, Actual number of VDIs == %d' %
                                   (guest.getUUID(), expected_num, actual_num))
            return ['FAILURE_SXM: Not all VDIs are attached']
        else:
            return []

    def assertAbsenceOfVDIsWithNBDState(self, guest):
        
        xenrt.TEC().logverbose("INFO_SXM: Checking the absence of source VDIs with driver state 'nbd' ")

        vm = self.vm_config[guest.getName()]
        VDIs = vm['VDI_SR_map'].keys()
        src_host = vm['src_host']

        def getPIDAndMinorNum(vdi):
            out = src_host.execdom0("tap-ctl list | grep '%s'; exit 0" % vdi).strip()
            fields = out.split()[0:2]
            if len(fields) > 0:
                return tuple(map(lambda x: x.split('=')[1], fields))
            else:
                None
            
        def checkDriverName(arg):
            (vdi, pid_and_minor) = arg

            if pid_and_minor is None:
                return []
            out = src_host.execdom0('tap-ctl stats -p %s -m %s' % pid_and_minor).strip()
            json_data = json.loads(out)

            try:
                images = json_data[u'images']
                vhds_or_nbds = set(map(lambda x: str(x[u'driver'][u'name']), images))
            except:
                xenrt.TEC().warning('INFO_SXM: Could not parse tap-ctl json data')
                return []

            if 'nbd' in vhds_or_nbds:
                xenrt.TEC().logverbose('INFO_SXM: VDI %s has driver name set to nbd' % vdi)
                return ['FAILURE_SXM: VDI %s has driver name set to nbd' % vdi]
            else:
                return []
            
        pid_and_minor_nums = map(getPIDAndMinorNum, VDIs)

        return sum(map(checkDriverName, zip(VDIs, pid_and_minor_nums)), [])

        
    def assertAbsenceOfSrcVDIs(self, guest):

        # Let us get the VDIs from VDI_SR_map
        error_msg = []
        xenrt.TEC().logverbose('INFO_SXM: Checking the absence of source VDIs')

        vm = self.vm_config[guest.getName()]

        VDIs = vm['VDI_SR_map'].keys()
        src_host = vm['src_host']
        orig_disks = vm['src_VDIs'].keys()
        orig_disks.sort()
        VDIs_sorted = [vm['src_VDIs'][disk] for disk in orig_disks]
        
        src_VDI_SR_map = dict(zip(VDIs_sorted, vm['VDI_src_SR_uuids']))

        for vdi in VDIs:
            try:
                sr_uuid = src_host.getVDISR(vdi)
                orig_sr_uuid = src_VDI_SR_map[vdi]
                
                if sr_uuid == orig_sr_uuid:
                    xenrt.TEC().logverbose('INFO_SXM: VDI %s found on source SR %s' % (vdi, orig_sr_uuid))

                error_msg.append('FAILURE_SXM: VDI %s found on source SR %s' % (vdi, orig_sr_uuid))
            except:
                pass
 
        return error_msg

    def assertAbsenceOfSnapshotVDIs(self, guest):

        # Let us get the VDIs from VDI_SR_map
        error_msg = []
        xenrt.TEC().logverbose('INFO_SXM: Checking the absence of snapshot VDIs')

        vm = self.vm_config[guest.getName()]

        VDIs = vm['VDI_SR_map'].keys()
        src_host = vm['src_host']
        
        orig_disks = vm['src_VDIs'].keys()
        orig_disks.sort()
        VDIs_sorted = [vm['src_VDIs'][disk] for disk in orig_disks]
        src_VDI_SR_map = dict(zip(VDIs_sorted, vm['VDI_src_SR_uuids']))

        all_VDIs = sum([src_host.minimalList('vdi-list', args='sr-uuid=%s' % sr) for sr in set(vm['VDI_src_SR_uuids'])], [])

        def baseMirrorFun(vdi):
            try:
                return src_host.genParamGet('vdi', vdi, 'sm-config', pkey='base_mirror').strip()
            except:
                return None
        
        other_configs = map(baseMirrorFun, all_VDIs)
        VDIs_other_config = zip(all_VDIs, other_configs)
        base_mirror_values = set(["%s/%s" % val for val in zip(vm['VDI_src_SR_uuids'], vm['VDI_locations'])])

        for (vdi, base_mirror) in VDIs_other_config:
            if base_mirror in base_mirror_values:
                xenrt.TEC().logverbose('INFO_SXM: snapshot = %s; base_mirror = %s' % (vdi, base_mirror)) 
                error_msg.append('FAILURE_SXM: snapshot = %s found with base_mirror = %s' % (vdi, base_mirror))
        
        return error_msg


    def assertPresenceOfSrcVDIs(self, guest):

        # Let us get the VDIs from VDI_SR_map
        error_msg = []
        xenrt.TEC().logverbose('INFO_SXM: Checking for the presence of source VDIs')

        vm = self.vm_config[guest.getName()]

        VDIs = vm['VDI_SR_map'].keys()
        src_host = vm['src_host']

        for vdi in VDIs:
            try:
                sr_uuid = src_host.getVDISR(vdi)
            except:
                error_msg.append('FAILURE_SXM: VDI %s not found on %s' % (vdi, src_host.getName()))
 
        return error_msg


    def assertPresenceOfDestVDIsOnRelevantSRs(self, guest):

        error_msg = []
        xenrt.TEC().logverbose('INFO_SXM: Checking for the presense of destination VDIs on relevant SRs')

        vm = self.vm_config[guest.getName()]

        dest_host = vm['dest_host']

        attached_disks = vm['obj'].listDiskDevices()
        attached_disks.sort()
        attached_VDIs = [vm['obj'].getDiskVDIUUID(d) for d in attached_disks]
        current_VDIs = dict(zip(attached_disks, attached_VDIs))
        try:
            for disk,vdi in current_VDIs.items():
                dest_SR = dest_host.getVDISR(vdi)
                src_VDI = vm['src_VDIs'][disk]
                expected_SR = vm['VDI_SR_map'][src_VDI]

                if dest_SR != expected_SR:
                    error_msg.append('FAILURE_SXM: src_VDI [%s] dest_VDI [%s] expected_dest_SR [%s] actual_dest_SR [%s].\n'
                                     'VDI was copied onto incorrect SR' % (src_VDI, vdi, expected_SR, dest_SR))
        except  Exception as e:
            error_msg.append(str(e))
            
        return error_msg


    def assertVMIsNotRunningOnSrcHost(self,guest):

        error_msg = []
        xenrt.TEC().logverbose('INFO_SXM: Checking the absence of source VM on source host')

        vm = self.vm_config[guest.getName()]
        session = vm['src_host'].getAPISession(secure=False)

        try: 
            actualHostUUIds = vm['src_host'].minimalList('vm-param-get',args="uuid=%s param-name=resident-on" %(vm['obj'].getUUID()))
            srcHostUUID = vm['src_host'].getMyHostUUID()

            if srcHostUUID in set(actualHostUUIds):
            
                if self.test_config['type_of_migration'] != 'LiveVDI': # must be inter-pool or intra-pool
                    error_msg.append('FAILURE_SXM: VM is still present on source host %s' % srcHostUUID)
                    try:
                        if session.xenapi.VM.get_record(vm['VM_Src_Ref'])['power_state'] == 'Running':
                            error_msg.append('FAILURE_SXM: VM %s is still running on source host' % guest.getUUID())
                    except:
                        pass
                        #This will throw exception when VM is not running on host
        except:
            pass
        vm['src_host'].logoutAPISession(session)

        return error_msg


    def assertVMIsRunningOnDestHost(self, guest, dest_host=None):
        
        error_msg = []
        xenrt.TEC().logverbose('INFO_SXM: Checking the presence of VM on destination host')

        vm = self.vm_config[guest.getName()]
        if dest_host is None:
            dest_host = vm['dest_host']
        session = dest_host.getAPISession(secure=False)
        
        dest_host_uuid = dest_host.getMyHostUUID()
        
        check_VM_is_running = True
        if self.test_config.has_key('vm_lifecycle_operation') and self.test_config['vm_lifecycle_operation']:
            check_VM_is_running = False
        if vm['pre_power_state'] != 'UP':
            check_VM_is_running = False
        if self.test_config.has_key('vm_reboot') and self.test_config['vm_reboot']:
            check_VM_is_running = True
        
        if check_VM_is_running:
            try:
                actualHostUUIds = vm['obj'].getHost().minimalList('vm-param-get',args="uuid=%s param-name=resident-on" %(vm['obj'].getUUID()))
            except:
                error_msg.append('FAILURE_SXM: VM is running on host %s' % vm['obj'].getHost())
                dest_host.logoutAPISession(session)
                return error_msg
            if dest_host_uuid in set(actualHostUUIds):
                try:
                    if session.xenapi.VM.get_record(vm['VM_Src_Ref'])['power_state'] != 'Running':
                        error_msg.append('FAILURE_SXM: VM %s is not running on destination host %s' % (guest.getUUID(), dest_host_uuid))
                except:
                    pass
                    #This will throw exception when VM is not running on host
            else:
                error_msg.append('FAILURE_SXM: VM %s is not present on destination host %s' % (guest.getUUID(), dest_host_uuid))

        dest_host.logoutAPISession(session)

        return error_msg

    def assertPresenceOfSrcVifNw(self,guest,host=None):
 
        vm = self.vm_config[guest.getName()]
        vifs = vm['VIF_NW_map'].keys()     

        xenrt.TEC().logverbose('INFO_SXM: Checking the presence of VIF attached to VM on source host')
        if not host:
            host = guest.getHost()
        
        allVifs = host.minimalList('vm-vif-list uuid=%s' % guest.getUUID()) 
        if len(vifs) <> len(allVifs):
            xenrt.TEC().logverbose('FAILURE_SXM: Expected VIFs on VM %s are %d, found %d' % (guest.getUUID(),len(vifs),len(allVifs)))
            return ['FAILURE_SXM: Number of vifs on VM are not same'] 
        
        return []

    def assertPresenceOfDestVIFNw(self,guest):
 
        error_msg = []
        xenrt.TEC().logverbose('INFO_SXM: Checking the presence of VIF attached to VM on destination network')
        vm = self.vm_config[guest.getName()]
        destHost = vm['dest_host']
        error_msg.extend(self.assertPresenceOfSrcVifNw(guest,destHost)) 
        
        if not error_msg: 
            network = []
            expDestNWs = vm['VIF_NW_map'].values()
            allVifs = destHost.minimalList('vm-vif-list uuid=%s' % guest.getUUID())
            for vif in allVifs:
                network.append(destHost.minimalList('vif-param-get',args="uuid=%s param-name=network-uuid" % (vif))[0])

            for nw in expDestNWs:
                if not nw in network:
                    error_msg.append("FAILURE_SXM: No VIF of VM %s is on network %s" % (guest.getUUID(),nw))

        return error_msg

    def checkSnapshot(self,guest):

        error_msg = []
        xenrt.TEC().logverbose('INFO_SXM: Checking the snapshot validity')
        try:
            snapshots = guest.getHost().minimalList('vm-param-get',args="uuid=%s param-name=snapshots" %(guest.getUUID()))
        except Exception as e:
            error_msg.append(str(e))

        if len(snapshots) <> 1:
            error_msg.append('FAILURE_SXM: Snapshot mismatch')
        else:
            if snapshots[0] <> self.vm_config[guest.getName()]['snapshot']:
                error_msg.append('FAILURE_SXM: Snapshot uuid is not same instead found %s' % snapshots[0])
            try:
                guest.checkSnapshot(snapshots[0])
            except Exception as e:
                err = 'FAILURE_SXM: ' + str(e)
                error_msg.append(err)
  
        return error_msg

    def checkWinLicense(self,guest):

        vm = self.vm_config[guest.getName()]

        try:
            vmWinOSuuid = self.getWinOSuuid(guest)
        except Exception as e:
            return ['FAILURE_SXM: Exception ocurred while fetching VM License and error is %s' %(str(e))]
        if vmWinOSuuid <> vm['VM_Windows_uuid']:
            return ['FAILURE_SXM: VM License is not same']

        return []

    def checkVDIIntegrity(self,guest):

        error_msg = []
        vdiInfo = []
        vdis = []
        xenrt.TEC().logverbose('INFO_SXM: Checking the integrity of VDIs')

        session = guest.getHost().getAPISession(secure=False)
        vmRef = session.xenapi.VM.get_by_uuid(guest.getUUID())
        domid = session.xenapi.VM.get_domid(vmRef)
        try:            
            if isinstance(guest.getHost(), xenrt.lib.xenserver.DundeeHost):                
                guest.getHost().execdom0("xl pause %s" % domid)
            else:
                guest.getHost().execdom0("/opt/xensource/debug/xenops pause_domain -domid %s" % domid)
        except:
            error_msg.append("Unable to pause VM")
            guest.getHost().logoutAPISession(session)
            return 
        guest.getHost().logoutAPISession(session)

        vm = self.vm_config[guest.getName()]
        srcHost = vm['src_host']
        destHost = vm['dest_host']

        if isinstance(guest.getHost(), xenrt.lib.xenserver.DundeeHost):
            output = srcHost.execdom0('sm-cli mirror-list')
        else:
            output = srcHost.execdom0('/opt/xensource/debug/sm mirror-list') 
 
        vdiInfo = output.splitlines()
        for item in vdiInfo:
            if 'dest_vdi' in item:
                vdis.append((item.split(':')[1]).strip())

        #Skipping md5sum check as it is causing intermittent failures
        """md5SumOfVMVDI = guest.getVdiMD5Sums()

        for vdi in vdis:
            if not (destHost.getVdiMD5Sum(vdi) in md5SumOfVMVDI.values()):
                error_msg.append("FAILURE_SXM: VDI %s MD5 sum is not same after migration" % vdi)"""

        try:
            if isinstance(guest.getHost(), xenrt.lib.xenserver.DundeeHost):                
                guest.getHost().execdom0("xl unpause %s" % domid)
            else:
                guest.getHost().execdom0("/opt/xensource/debug/xenops unpause_domain -domid %s" % domid)
        except:
            xenrt.TEC().logverbose('INFO_SXM: Exception occurred while trying to unpause the VM')

        return error_msg

    def checkGuest(self,guest):
        
        xenrt.TEC().logverbose("Checking guest health ...")
        test_status = []
        if not self.test_config.has_key('test_status'):
            self.test_config['test_status'] = {guest.getName() : test_status}
        elif self.test_config['test_status'].has_key(guest.getName()):
            test_status = self.test_config['test_status'][guest.getName()]
        else:
            self.test_config['test_status'][guest.getName()] = test_status

        vm = self.vm_config[guest.getName()]

        do_checks = True
        if self.test_config['negative_test'] or \
                self.test_config['type_of_migration'] == 'LiveVDI' or \
                self.test_config['cancel_migration']:
            do_checks = False

        # Empty DVD drive check
        if do_checks and not self.isCDDriveEmpty(guest):
            test_status.append('FAILURE_SXM: CD drive is not empty')

        # Check presence of VDIs on correct destination SRs
        if not (self.test_config['cancel_migration'] or self.test_config['negative_test']):
            test_status.extend(self.assertPresenceOfDestVDIsOnRelevantSRs(guest))

        # Check presence of source VDIs
        if self.test_config['cancel_migration'] or self.test_config['negative_test']:
            test_status.extend(self.assertPresenceOfSrcVDIs(guest))
        else:
            test_status.extend(self.assertAbsenceOfSrcVDIs(guest))


        if self.test_config['type_of_migration'] == 'inter-pool':
            if self.test_config['cancel_migration'] or self.test_config['negative_test']:
                test_status.extend(self.assertPresenceOfSrcVifNw(guest))
            else:
                test_status.extend(self.assertPresenceOfDestVIFNw(guest))

        # Check absence of source VDIs with status nbd
        test_status.extend(self.assertAbsenceOfVDIsWithNBDState(guest))

        #Check snapshot VDIs are present or not .If ignore_snapshotvdi_check is set true then skip it.
        if not(self.test_config.has_key('ignore_snapshotvdi_check') and self.test_config['ignore_snapshotvdi_check']):            
            test_status.extend(self.assertAbsenceOfSnapshotVDIs(guest))
        else:
            pass

        # Check source VM is not runnning
        if do_checks:
            test_status.extend(self.assertVMIsNotRunningOnSrcHost(guest))

        # Check destination VM is running
        if self.test_config['cancel_migration'] or self.test_config['negative_test']:
            test_status.extend(self.assertVMIsRunningOnDestHost(guest, 
                                                                      dest_host=self.vm_config[guest.getName()]['src_host']))
        else:
            test_status.extend(self.assertVMIsRunningOnDestHost(guest))
            
        #Check Snapshot if there is any
        if vm.has_key('snapshot'):
            test_status.extend(self.checkSnapshot(guest))

        # vCPUs, NICs, Memory check
        if not self.test_config['win_crash']:
            try:
                if not (vm.has_key('nodrivers') and vm['nodrivers']):
                    guest.setState('UP')
                    guest.check()
            except Exception as e:
                err = 'FAILURE_SXM: ' + str(e)
                test_status.append(err)

        # PV Driver check
        if guest.windows and guest.enlightenedDrivers:
            xenrt.TEC().logverbose('INFO_SXM: Checking for PV drivers')
            try:
                if not (vm.has_key('nodrivers') and vm['nodrivers']):
                    guest.checkPVDevices()
            except:
                test_status.append('FAILURE_SXM: PV driver check failed')

        # Check wiindows network parameters
        if guest.windows:
            if not (vm.has_key('nodrivers') and vm['nodrivers']):
                xenrt.TEC().logverbose('INFO_SXM: Checking the network settings of windows VM')
                if not (self.test_config.has_key('vm_lifecycle_operation') and self.test_config['vm_lifecycle_operation']):
                    for device in vm['Network_Settings'].keys():
                        try:
                            guest.getVifOffloadSettings(int(device)).verifyEqualTo(vm['Network_Settings'][device])
                        except:
                            test_status.append('FAILURE_SXM: VIF offload settings are not same for device %s' % device)

                    # Check windows license
                    test_status.extend(self.checkWinLicense(guest))

        # Number of VDIs on destination host
        test_status.extend(self.checkNumOfVDIs(guest))
        
        xenrt.TEC().logverbose("Guest health check finished")
        if len(test_status) > 0:
            xenrt.TEC().logverbose("Following errors found while verifying guest health after sxm")
            for error in test_status:
                xenrt.TEC().logverbose(error)
        elif len(test_status) ==  0:
            xenrt.TEC().logverbose("INFO_SXM:No issues found while checking guest health")        

        return test_status

    #CHECKME: All the *hook functions need more descriptive names

    def updateGuestDestinationHost(self, guest):
        
        vm = self.vm_config[guest.getName()]

        host_A = self.test_config['host_A']
        host_B = self.test_config['host_B']
        
        target_hosts = {host_A.getName() : host_A,
                        host_B.getName() : host_B}

        if self.test_config['type_of_migration'] == 'LiveVDI':
            vm['dest_host'] = vm['src_host']
        else:
            target_host = (set(target_hosts.keys()) - set([vm['src_host'].getName()])).pop()
            vm['dest_host'] = target_hosts[target_host]
            assert vm['dest_host'] is not vm['src_host'], "For inter-pool and intra-pool, src and dest hosts have to be different"

        return

    def updateGuestDestinationSRs(self, guest):

        # CHECKME: One VDI may be a CD that was inserted.

        vm = self.vm_config[guest.getName()]
        dest_host = vm['dest_host']
        disks = vm['src_VDIs'].keys()
        disks.sort()
        attached_VDIs = [vm['src_VDIs'][d] for d in disks]

        if vm.has_key('dest_SR_type'):

            sr_type = vm['dest_SR_type']
            vm_sr = self.getSRByType(dest_host, sr_type=sr_type, exclude_SRs=set(vm['VDI_src_SR_uuids']))
            vm['VDI_SR_map'] = dict(itertools.izip(attached_VDIs, itertools.repeat(vm_sr)))
            
        elif vm.has_key('VDI_dest_SR_types'):

            sr_types = vm['VDI_dest_SR_types']
            vm_SRs = [self.getSRByType(vm['dest_host'], sr_type=sr_type, exclude_SRs=set([sr_uuid])) 
                      for (sr_type, sr_uuid) in zip(sr_types, vm['VDI_src_SR_uuids'])]
            vm['VDI_SR_map'] = dict(itertools.izip(attached_VDIs, vm_SRs))
            
        elif vm.has_key('dest_SR'):
            vm_sr = vm['dest_SR']
            vm['VDI_SR_map'] = dict(itertools.izip(attached_VDIs, itertools.repeat(vm_sr)))
                                    
        elif vm.has_key('VDI_dest_SR_uuids'):
            vm_SRs = vm['VDI_dest_SR_uuids']
            vm['VDI_SR_map'] = dict(itertools.izip(attached_VDIs, vm_SRs))
        else:
            vm_sr = self.getLocalSRs(vm['dest_host']).keys()[0]
            vm['dest_SR'] = vm_sr
            vm['VDI_SR_map'] = dict(itertools.izip(attached_VDIs, itertools.repeat(vm_sr)))

        if not vm.has_key('VDI_dest_SR_uuids'):
            vm['VDI_dest_SR_uuids'] = [vm['VDI_SR_map'][vdi] for vdi in attached_VDIs]

        return

    def updateGuestDestinationVIFsNw(self,guest):

        vm = self.vm_config[guest.getName()]
        
        if self.test_config['type_of_migration'] == 'inter-pool':        
            destHost = vm['dest_host']
            host = guest.getHost()
            allVifs = host.minimalList('vm-vif-list uuid=%s' % guest.getUUID())
            mainNWuuid = destHost.getManagementNetworkUUID()

            vm['VIF_NW_map'] = {}
            for vif in allVifs:
                if self.test_config['use_vmsecnetwork']:
                    vmNWuuid=host.genParamGet("vif",vif,"network-uuid").strip()
                    vmNWname= host.genParamGet("network",vmNWuuid,"other-config","xenrtnetname")
                    xenrt.TEC().logverbose("Network name for vif %s is %s"%(vif,vmNWname))
                    if vmNWname =="NSEC":
                        nsecList=destHost.listSecondaryNICs("NSEC")
                        if nsecList:
                            nsecPif=destHost.getNICPIF(nsecList[0])
                            secNWuuid = destHost.genParamGet("pif",nsecPif,"network-uuid").strip()
                            xenrt.TEC().logverbose("Destination VIF %s set to NSEC network %s"%(vif,secNWuuid))
                            vm['VIF_NW_map'].update({vif:secNWuuid})
                        else:
                            raise xenrt.XRTError("On destination host there is No NSEC network which can be assigned as destination network for migrating VM")
                else:
                    xenrt.TEC().logverbose("Destination VIF %s set to NPRI network %s"%(vif,mainNWuuid))
                    vm['VIF_NW_map'].update({vif:mainNWuuid})
        else:
            vm['VIF_NW_map'] = {}
    
    def preHook(self):

        for vm in self.vm_config.values():
            guest = vm['obj']
            self.updateGuestDestinationHost(guest)
            self.updateGuestDestinationSRs(guest)
            self.updateGuestDestinationVIFsNw(guest)

        return

    def hook(self):
        # Based on the test parameters, we may cancel the migration
        pass

    def updateGuestMetadataForNextIteration(self, guest):

        # 1. Swap src and dest host

        vm = self.vm_config[guest.getName()]
        tmp = vm['src_host']
        vm['src_host'] = vm['dest_host']
        vm['dest_host'] = tmp

        # 2. Delete unwanted keys
        
        if vm.has_key('src_SR_type'):
            del vm['src_SR_type'] 
            del vm['dest_SR_type']
        if vm.has_key('VDI_src_SR_types'):
            del vm['VDI_src_SR_types']
            del vm['VDI_dest_SR_types']
        if vm.has_key('src_SR'):
            del vm['src_SR'] 
            del vm['dest_SR'] 

        tmp = vm['VDI_src_SR_uuids']
        vm['VDI_src_SR_uuids'] = vm['VDI_dest_SR_uuids'] 
        vm['VDI_dest_SR_uuids'] = tmp

        # 3. Update VDIs 
        attached_disks = vm['obj'].listDiskDevices()
        attached_disks.sort()
        attached_VDIs = [vm['obj'].getDiskVDIUUID(d) for d in attached_disks]
        vm['src_VDIs'] = dict(zip(attached_disks, attached_VDIs))
        host = vm['src_host']
        vm['VDI_locations'] = [host.genParamGet('vdi', vdi, 'location') for vdi in attached_VDIs] 

        self.storeOtherVMAttribs(vm['obj'])
 
        return

    def postMigration(self):

        for vm in self.vm_config.values():
            guest = vm['obj']
            self.updateGuestMetadataForNextIteration(guest)

        return

    def getGuestMigrateParams(self, guest):

        params = {'dest_host' : self.vm_config[guest.getName()]['dest_host'],
                  'VDI_SR_map' : self.vm_config[guest.getName()]['VDI_SR_map'],
                  'VIF_NW_map' : self.vm_config[guest.getName()]['VIF_NW_map']}
        return params


#CHECKME: Refactor postHook to use checkVMs    
    
    def postHook(self):

        # obs.getResult would return a DICT

        results = {}
        totalFailures = 0
        firstFailureMsg = None       
 
        for obs in self.observers:
            results[obs.vm.getName()] = obs.getSXMResult()

        for obs in self.observers:
            error_messages = []
            status = True
            vmName = obs.vm.getName()
            vmuuid = obs.vm.getUUID() 
            srcHost = obs.srcHost.getMyHostUUID()
            vmconfig = self.vm_config[vmName] 

            if self.test_config['monitoring_failure']:
                results[vmName]['eventStatus'] = "COMPLETED"
                self.test_config['negative_test'] = True

            if results[vmName]['eventStatus'] == "TIMEOUT":
                xenrt.TEC().logverbose("VM %s was not migrated from host %s with in the given time, Timeout occurs" % (vmName,srcHost))
                totalFailures = totalFailures + 1

            elif results[vmName]['eventStatus'] == "ERROR_MONITORING":
                xenrt.TEC().logverbose("Error occurred while monitoring Migration of VM %s from host %s" % (vmName,srcHost))
                totalFailures = totalFailures + 1

            elif results[vmName]['eventStatus'] == "COMPLETED" or results[vmName]['eventStatus'] == "NOT_RUNNING":

                test_status = [] 
                # Don't  check the guest in the case of failed/errored non-negative tests
                if (results[vmName]['taskResult'] == 'error' or results[vmName]['taskResult'] == 'failure'):
                    if self.test_config['cancel_migration'] or self.test_config['negative_test']:
                        xenrt.TEC().logverbose("INFO_SXM:Migration seems to be errored/failed which is expected due to negative scenario ;now checking guest health postsxm")
                        test_status = self.checkGuest(obs.vm)                                             
                    else:
                        pass # we skip the guest checks
                else: # In case of a successful migration, we should do checkGuest
                    xenrt.TEC().logverbose("INFO_SXM:Migration seems to be successful ;now checking guest health postsxm")
                    test_status = self.checkGuest(obs.vm)                    
                    
                if not self.test_config['win_crash']:
                    if vmconfig.has_key('nodrivers') and vmconfig['nodrivers']:
                        pass
                    else:
                        self.testLifecycleOperations(obs.vm)
                
                if self.test_config.has_key('vm_lifecycle_operation') and self.test_config['vm_lifecycle_operation']:
                    pass
                else:
                    if self.test_config['paused'] and not self.test_config['negative_test'] and not self.test_config['cancel_migration'] and not self.test_config['skip_vmdowntime'] :
                        if results[vmName]['vmDownTime'] > 30:
                            test_status.append("FAILURE_SXM: VM downtime of %s migrated from %s was more than 30 secs,it was %f " % 
                                               (vmName,srcHost,results[vmName]['vmDownTime']))

                if (results[vmName]['taskResult'] == 'error' or results[vmName]['taskResult'] == 'failure') and self.test_config['cancel_migration'] == False and self.test_config['negative_test'] == False: 
                    test_status.append("FAILURE_SXM: Migration of VM %s from host %s was unsuccessful" % (vmName,srcHost))
                if self.test_config['negative_test']:
                    if not (results[vmName]['taskResult'] == 'error' or results[vmName]['taskResult'] == 'failure'):
                        test_status.append("FAILURE_SXM: Migration is successful but expected either failure or error")
                if self.test_config['cancel_migration']:
                    if not (results[vmName]['taskResult'] == 'cancelled'):
                        test_status.append("FAILURE_SXM: Task result is not cancelled")
                   
                if len(test_status) > 0:
                    totalFailures = totalFailures + 1
                    xenrt.TEC().logverbose("FAILURE_SXM: Following error occurred while verifying various VM attributes of %s migrated from %s" % (vmName,srcHost))
                    for error in test_status:
                        if not firstFailureMsg:
                            firstFailureMsg = "VM: %s " % (vmuuid) + error
                        xenrt.TEC().logverbose(error)
                if results[vmName]['taskResult'] == 'success':
                    xenrt.TEC().logverbose("INFO_PERF_SXM: Total time taken by the migration: %s" % results[vmName]['totalTime'])
            xenrt.TEC().logverbose("INFO_SXM: Task result of task %s SXM is :%s " % (obs.getTaskID(),results[vmName]['taskResult']))
        
        if totalFailures > 0:
            xenrt.TEC().logverbose("%d out of %d migration Failed." %(totalFailures,len(self.observers)))
            if self.test_config['iterations'] > 1:
                hostlist = xenrt.TEC().registry.hostList()
                for h in hostlist:
                    host = xenrt.TEC().registry.hostGet(h)
                    host.execdom0("netstat -na")
            raise xenrt.XRTFailure(firstFailureMsg)

    def migrateVDIsWithXe(self):
    
        for guest in self.guests:
            params = self.getGuestMigrateParams(guest)
            dest_host = params['dest_host']
            
            for vdi,sr in params['VDI_SR_map'].items():
                dest_host.migrateVDI(vdi,sr)
        return

    def testLifecycleOperations(self, guest):

        test_status = []
        if not self.test_config.has_key('test_status'):
            self.test_config['test_status'] = {guest.getName() : test_status}
        elif self.test_config['test_status'].has_key(guest.getName()):
            test_status = self.test_config['test_status'][guest.getName()]
        else:
            self.test_config['test_status'][guest.getName()] = test_status
        
        try:
            guest.setState('UP')
        except Exception as e:
            test_status.append("FAILURE_SXM: guest.start() [%s] failed with '%s'" %
                               (guest.getUUID(), e))
        try:
            guest.shutdown()
            guest.start()
            guest.suspend()
            guest.resume()
            guest.reboot()
        except Exception as e:
            test_status.append("FAILURE_SXM: VM %s lifcycle operations failed with '%s'" %
                                                (guest.getUUID(), e))
        return test_status


    def migrateVMsWithXe(self):
        
        if self.test_config['type_of_migration'] == 'LiveVDI':
            self.migrateVDIsWithXe()
            return
        status = True
        for guest in self.guests:
            params = self.getGuestMigrateParams(guest)
            dest_host = params['dest_host']
            try:
                guest.migrateVM(remote_host=dest_host,
                                vdi_sr_list=params['VDI_SR_map'].items(),
                                live="true")
            except Exception as e:
                xenrt.TEC().logverbose("Migration of VM %s failed with '%s'"
                                       % (guest.getUUID(), e))
                status = False
        return

    def checkVMs(self):
        
        for guest in self.guests:
            self.checkGuest(guest)
        
        for guest in self.guests:
            self.testLifecycleOperations(guest)

        test_status = sum(self.test_config['test_status'].values(), [])
 
        if len(test_status) == 0: # We don't have a single error
            return
        
        xenrt.TEC().logverbose('FAILURE_SXM: Following errors were detected during and after migration')
        for msg in test_status:
            xenrt.TEC().logverbose(msg)
        
        raise xenrt.XRTFailure('Storage Xen Migration failed with various errors')

    def migrateVMs(self):

        if not self.test_config.has_key('iterations'):
            self.test_config['iterations'] = 1
        
        if self.test_config['negative_test']:
            self.test_config['iterations'] = 1
            
        for i in range(self.test_config['iterations']):
            xenrt.TEC().logverbose("Iteration %s"%(i+1))
            self.preHook()

            for guest in self.guests:
                vm_config = self.vm_config[guest.getName()]
                vm_config['pre_power_state'] = guest.getState()

            if self.test_config.has_key('use_xe') and self.test_config['use_xe']:
                self.migrateVMsWithXe()
                self.checkVMs()
            else:
                exception = False
                self.observers = []
                guestWithExceptions = []

                for guest in self.guests:
                    try:
                        obs = guest.sxmVMMigrate(self.getGuestMigrateParams(guest),
                                                 pauseAfterMigrate=self.test_config['paused'])
                        self.observers.append(obs)
                    except Exception as e:
                        xenrt.TEC().logverbose("INFO_SXM: Exception occurred while trying to call migrate api %s for VM %s" % (str(e),guest.getUUID()))
                        guestWithExceptions.append(guest)
                        exception = True

                self.hook()
                for obs in self.observers:
                    obs.waitToFinish()

                self.postHook()

                if self.test_config['immediate_failure']:
                    if exception:
                        xenrt.TEC().logverbose("INFO_SXM: Exception was thrown which was expected")
                        for guest in guestWithExceptions:
                            guest.check()
                    else: 
                        raise xenrt.XRTFailure("Immediate exception was not thrown by the migrate api")
                else:
                    if exception:
                        for guest in guestWithExceptions:
                            guest.check()
                        raise xenrt.XRTFailure("Exception occurred while trying to initiate migration")
         
            if not (self.test_config['negative_test'] or self.test_config['cancel_migration'] or self.test_config['immediate_failure'] or self.test_config['monitoring_failure']):
                self.postMigration()

        return

    def initiateDiskActivities(self):
        # CHECKME: Call Dan's code
        #          decide on the parameters
        #          All the disks should have sufficient IO on it
        WINDOWS_WORKLOADS = ["IOMeter"]
        LINUX_WORKLOADS = ["LinuxSysbench"]

        for guest in self.guests:

            if guest.windows:
                guest.installWorkloads(WINDOWS_WORKLOADS)
                workloadsExecd = guest.startWorkloads(WINDOWS_WORKLOADS)
            else:
                guest.installWorkloads(LINUX_WORKLOADS)
                workloadsExecd = guest.startWorkloads(LINUX_WORKLOADS)

    def run(self, arglist=None):
        self.migrateVMs()
        return

    def postRun(self):
        reuse_VM = False
        if self.test_config.has_key('reuse_VM'):
            reuse_VM = self.test_config['reuse_VM']
        
        if reuse_VM:
            return
        
        for guest in self.guests:
            guest.uninstall()

class MultipleVifs(LiveMigrate):

    def preHook(self):

        deviceName = 'eth'
        count = 2
        newVIF = []
        newNetwork = []
        LiveMigrate.preHook(self)
        guest = self.guests[0]
        vm = self.vm_config[guest.getName()]
        host = guest.getHost()
        cli = host.getCLIInstance()
        bridges = host.getBridges()
        connected_bridges = []

        if 'xenapi' in bridges:
            bridges.remove('xenapi')
            
        for b in bridges:
            pif_uuids = host.minimalList("network-list", "PIF-uuids", "bridge=%s" % b)            
            pifsWithCarrierFalse = [pif for pif in pif_uuids if host.genParamGet("pif",pif,"carrier").strip() == "true"] 
            if pifsWithCarrierFalse:
                connected_bridges.append(b)            
    
        for bridge in connected_bridges:
            for i in range(0,2):
                eth = deviceName + str(count)
                guest.createVIF(bridge=bridge,eth=eth)
                vifuuid = guest.getVIFUUID(eth)
                cli.execute("vif-plug", "uuid=%s" % (vifuuid)) 
                newVIF.append(vifuuid)
                count = count + 1

        guest.reboot()
        guest.check()
        vm = self.vm_config[guest.getName()]       
        destHost = vm['dest_host']
        for i in range(0,2):
            newNetwork.append(destHost.createNetwork())

        allVifs = host.minimalList('vm-vif-list uuid=%s' % guest.getUUID())
        mainVifs = list(set(allVifs) - set(newVIF))
        mainNWuuid = destHost.getManagementNetworkUUID()

        vm['VIF_NW_map'] = {}
        for mainVif in mainVifs:
            vm['VIF_NW_map'].update({mainVif:mainNWuuid})

        j = 0
        for bridge in connected_bridges:
            for i in range(0,2):      
                vm['VIF_NW_map'].update({newVIF[j]:newNetwork[i]})
                j = j + 1

        
 
class MidMigrateFailure(LiveMigrate):
    # Assuming only single VM is being migrated

    def setTestParameters(self):

        self.test_config['test_VMs'] = ['win01']
        assert self.args.has_key('src_SR_type')
        assert self.args.has_key('dest_SR_type')
        self.test_config['win01'] = {'distro' : 'win7-x86',
                                     'src_SR_type' : self.args['src_SR_type'],
                                     'dest_SR_type' : self.args['dest_SR_type'] }

        self.test_config['src_SR_type'] = self.args['src_SR_type']
        self.test_config['dest_SR_type'] = self.args['dest_SR_type']

        if self.args.has_key('test'):
            self.test_config['type_of_migration'] = self.args['test']

        if self.args.has_key('negative_test'):
            self.test_config['negative_test'] = self.args['negative_test']

        if self.args.has_key('monitoring_failure'):
            self.test_config['monitoring_failure'] = self.args['monitoring_failure']

        return

    def srFailure(self,host):
 
        host.execdom0("iptables -I INPUT -p tcp --source-port 3260 -j DROP")
        host.execdom0("iptables -I INPUT -p tcp --destination-port 3260 -j DROP")
        host.execdom0("iptables -I OUTPUT -p tcp --destination-port 3260 -j DROP")
        host.execdom0("iptables -I OUTPUT -p tcp --source-port 3260 -j DROP")
        host.execdom0("iptables --list")
        time.sleep(300)
        host.execdom0("iptables -D INPUT -p tcp --source-port 3260 -j DROP")
        host.execdom0("iptables -D INPUT -p tcp --destination-port 3260 -j DROP")
        host.execdom0("iptables -D OUTPUT -p tcp --destination-port 3260 -j DROP")
        host.execdom0("iptables -D OUTPUT -p tcp --source-port 3260 -j DROP")

class SrcHostDownDuringMig(MidMigrateFailure):
    # Assuming only single VM/VDI is being migrated

    def hook(self):

        sourceHost = self.observers[0].srcHost
        sourceHost.reboot()
        
    def postHook(self):    
        
        for vm in self.vm_config.values():
            guest = vm['obj']

            # Check if the guest is in a halted state
            if guest.getState() == "DOWN":
                guest.start()
        
        #Skip the snapshotvdi check ,hence set the flag true
        self.test_config['ignore_snapshotvdi_check'] = True        
        LiveMigrate.postHook(self)
    

class DestHostDownDuringMig(MidMigrateFailure):
    # Assuming only single VM/VDI is being migrated

    def hook(self):

        destHost = self.observers[0].destHost
        destHost.reboot()

    def postHook(self):

    #Skip the snapshotvdi check ,hence set the flag true
        self.test_config['ignore_snapshotvdi_check'] = True        
        LiveMigrate.postHook(self)

class SrcSRFailDuringMig(MidMigrateFailure):
    # Assuming only single VM/VDI is being migrated

    def hook(self):

        sourceHost = self.observers[0].srcHost
        self.srFailure(sourceHost)
        
    def postHook(self):
    #Fixing CA-96410: As the storage connectivity was lost ...once the sr connectivity is up rescan the sr and force reboot the vm 
    #before we proceed for guest healthcheck
        guest = self.guests[0]
        if guest.getState() == "UP":                
                cli = self.observers[0].srcHost.getCLIInstance()
                vm = self.vm_config[guest.getName()]
                VDIs = vm['VDI_SR_map'].keys()
                src_host = vm['src_host']
                orig_disks = vm['src_VDIs'].keys()
                orig_disks.sort()
                VDIs_sorted = [vm['src_VDIs'][disk] for disk in orig_disks]                
                src_VDI_SR_map = dict(zip(VDIs_sorted, vm['VDI_src_SR_uuids']))
                for vdi in VDIs:
                    try:
                        sr_uuid = src_host.getVDISR(vdi)
                        orig_sr_uuid = src_VDI_SR_map[vdi]
                        cli.execute("sr-scan", "uuid=%s" % (orig_sr_uuid))
                        time.sleep(10)
                    except Exception, e:
                        xenrt.TEC().warning("Exception on sr-scan of %s: %s" % 
                                    (orig_sr_uuid, str(e)))               
                guest.reboot(force=True)
        LiveMigrate.postHook(self)

class DestSRFailDringMig(MidMigrateFailure):
    # Assuming only single VM/VDI is being migrated

    def hook(self):

        destHost = self.observers[0].destHost
        self.srFailure(destHost)

class SrcSesDownDuringMig(MidMigrateFailure):
    # Assuming only single VM/VDI is being migrated

    def hook(self):

        self.observers[0].closeXapiSession()

class DestSesDownDuringMig(MidMigrateFailure):
    # Assuming only single VM/VDI is being migrated

    def hook(self):

        self.observers[0].closeDestHostSession() 
        
class InsuffMemoryForLiveVDI(LiveMigrate):

    def preHook(self):
        LiveMigrate.preHook(self)
        host = self.test_config['host_A']
        
        xenrt.TEC().logverbose("Configuring %s so that it has memory left in host is almost equal to the ram of the VM ,which I want to migrate" % (host.getName()))        
        freemem = host.getFreeMemory()
        freemem = freemem - 256        
        g = host.createGenericLinuxGuest(start=False , memory=freemem)
        self.uninstallOnCleanup(g)
        g.start()
       
class InsuffSpaceDestSR(MidMigrateFailure):
    # Assuming only single VM/VDI is being migrated
    # Destination SR will have somewhere between 200 GB and 225GB specified in the suite file and since the VM has got 220GB of disk migration should fail

    def preHook(self):

        MidMigrateFailure.preHook(self)
        vm = self.guests[0]
        device = vm.listDiskDevices()[0]
        vm.shutdown()
        vm.resizeDisk(device,225280)
        vm.start()

        #creating large VDI(200GB) on destination SR
        host = self.test_config['host_B']
        vdi = host.createVDI( 102400 * xenrt.MEGA)

class LargeDiskWin(LiveMigrate):

    def setTestParameters(self):

        self.test_config['test_VMs'] = ['win01']
        self.test_config['win01'] = {'distro' : 'win7-x86',
                                     'VDI_src_SR_types' : ['nfs', 'nfs'],
                                     'VDI_dest_SR_types' : ['nfs', 'nfs']}

        if self.args.has_key('test'):
            self.test_config['type_of_migration'] = self.args['test']

    def preHook(self):
   
        LiveMigrate.preHook(self)
        vm = self.guests[0]
        device = vm.listDiskDevices()[0]
        vm.shutdown()
        vm.resizeDisk(device,102400)
        vm.start()

class WinInGuestReboot(MidMigrateFailure):

    def hook(self):
        self.test_config['vm_lifecycle_operation'] = True 
        self.test_config['vm_reboot'] = True
        vm = self.guests[0]
        vm.xmlrpcExec("shutdown -r")

class WinInGuestShutdown(MidMigrateFailure):

    def hook(self):
        self.test_config['vm_lifecycle_operation'] = True 
        vm = self.guests[0]
        vm.xmlrpcExec("shutdown -s")

#CHECKME : 1. Need  KEYs for shutdown, reboot, crash
#          2. Incase of shutdown and crash, check for existance of VM on destination host

class WinCrash(MidMigrateFailure):

    def preHook(self):
        LiveMigrate.preHook(self)
        vm = self.guests[0]
        vm.paramSet("actions-after-crash", "Restart")
        xenrt.TEC().logverbose("Guest actions-after-crash changed to restart " )

    def hook(self):
        self.test_config['vm_lifecycle_operation'] = True
        self.test_config['win_crash'] = True 
        
        vm = self.guests[0]
        crashAttempt = 1 
        while True:
            xenrt.TEC().logverbose("Crashing Guest %s, attempt %d" % (vm.getName(), crashAttempt))
            vm.crash()
            try:
                vm.checkReachable(timeout=10, level=None)
                xenrt.TEC().logverbose("Guest %s, failed to crash on attempt %d" % (vm.getName(), crashAttempt))
            except:
                xenrt.TEC().logverbose("Guest %s, crashed on attempt %d" % (vm.getName(), crashAttempt))
                break
            if crashAttempt > 10:
                raise xenrt.XRTFailure("Guest failed to crash after %d attempts" % (crashAttempt))
            crashAttempt += 1

class LinInGuestReboot(LiveMigrate):
    
    def hook(self):
        self.test_config['vm_lifecycle_operation'] = True 
        self.test_config['vm_reboot'] = True
        vm = self.guests[0]
        vm.execguest("shutdown -r now")
        
class LinInGuestShutdown(LiveMigrate):

    def hook(self):
        self.test_config['vm_lifecycle_operation'] = True 
        vm = self.guests[0]
        vm.execguest("shutdown -h now")

class SixVdiAttached(LiveMigrate):

    def setTestParameters(self):
        
        self.test_config['test_VMs'] = ['lin01']
        self.test_config['lin01'] = { 'VDI_src_SR_types' : ['ext', 'ext','ext','ext','ext','ext'],
                                      'VDI_dest_SR_types' : ['nfs', 'nfs','nfs','nfs','nfs','nfs']}

        if self.args.has_key('test'):
            self.test_config['type_of_migration'] = self.args['test']

class MulVDIacrossDifSRs(LiveMigrate):

    def setTestParameters(self):

        self.test_config['test_VMs'] = ['lin01']
        self.test_config['lin01'] = { 'VDI_src_SR_types' : ['ext', 'nfs','lvmoiscsi'],
                                      'VDI_dest_SR_types' : ['nfs', 'lvmoiscsi','lvm']}       

        if self.args.has_key('test'):
            self.test_config['type_of_migration'] = self.args['test']        
        
        #Skipt the snapshotvdi check as per the comments in CA-87710 ,hence set the flag true
        self.test_config['ignore_snapshotvdi_check'] = True     

class VMWithSnapshot(LiveMigrate):

    def preHook(self):

        LiveMigrate.preHook(self)
        vm = self.guests[0]
        snapUUID = vm.snapshot()
        self.vm_config[vm.getName()]['snapshot'] = snapUUID
        
class VMWithSnapshotUsingXE(LiveMigrate) :
#Scenario is derived from HFX-818 (Hotfix Oliver ) & the testcase will fail on Tampa RTM .

    def preHook(self):
        LiveMigrate.preHook(self)        
        vm = self.guests[0]
        if not "snapshot" in self.vm_config[vm.getName()].keys():        
            snapUUID = vm.snapshot()
            self.vm_config[vm.getName()]['snapshot'] = snapUUID


class VMWithCDin(LiveMigrate):

    def preHook(self):

        LiveMigrate.preHook(self)
        vm = self.guests[0]
        vm.changeCD("xs-tools.iso")

class CancelMigrate(MidMigrateFailure):

    def hook(self):

        self.test_config['cancel_migration'] = True
        self.observers[0].cancelTask()

class CheckLinVDIIntegrity(LiveMigrate):

    def preHook(self):

        LiveMigrate.preHook(self)
        vm = self.guests[0]
        host = vm.getHost()
        host.execdom0("touch /tmp/fist_pause_storage_migrate",timeout=300)
        self.test_config['paused'] = False
 
    def hook(self):

        test_status = []
        obs = self.observers[0]
        vm = self.guests[0]

        if not self.test_config.has_key('test_status'):
            self.test_config['test_status'] = {vm.getName() : test_status}
        elif self.test_config['test_status'].has_key(vm.getName()):
            test_status = self.test_config['test_status'][vm.getName()]
        else:
            self.test_config['test_status'][vm.getName()] = test_status

        paused = False
        while True:
 
            if obs.getTaskStatus() == 'pending':
                if self.test_config['type_of_migration'] == 'LiveVDI':
                    parentTask = obs.getTaskID()
                    session = obs.getSession() 
                    #subtask = session.xenapi.task.get_subtasks(parentTask)[0]
                    otherConfig = session.xenapi.task.get_other_config(parentTask)
                    if otherConfig.has_key('fist'):
                        if 'pause_storage_migrate' in otherConfig['fist']:
                            xenrt.TEC().logverbose("INFO_SXM: Migration has been paused")
                            paused = True
                            break
                else:
                    otherConfig = obs.getTaskOtherConfig()
                    if otherConfig.has_key('fist'):
                        if 'pause_storage_migrate' in otherConfig['fist']:
                            xenrt.TEC().logverbose("INFO_SXM: Migration has been paused")
                            paused = True
                            break 
            else:
                xenrt.TEC().logverbose("INFO_SXM: Task has been completed")
                break
        if paused:
            test_status.extend(self.checkVDIIntegrity(vm))
        else:
            test_status.append("FAILURE_SXM: Migration was not paused so couldnt check the vdi integrity")
        host = vm.getHost()
        host.execdom0("rm /tmp/fist_pause_storage_migrate",timeout=300)
        
class CheckWinVDIIntegrity(CheckLinVDIIntegrity):

    def setTestParameters(self):

        self.test_config['test_VMs'] = ['win01']
        assert self.args.has_key('src_SR_type')
        assert self.args.has_key('dest_SR_type')
        self.test_config['win01'] = {'distro' : 'win7-x86',
                                     'src_SR_type' : self.args['src_SR_type'],
                                     'dest_SR_type' : self.args['dest_SR_type'] }

        self.test_config['src_SR_type'] = self.args['src_SR_type']
        self.test_config['dest_SR_type'] = self.args['dest_SR_type']

        if self.args.has_key('test'):
            self.test_config['type_of_migration'] = self.args['test']

        if self.args.has_key('negative_test'):
            self.test_config['negative_test'] = self.args['negative_test']

        return

class AgentlessVMStorageMigration(LiveMigrate):
    """Baseclass for migrating VMs without PV drivers"""

    def setTestParameters(self):
    
        self.test_config['test_VMs'] = ['win01']
        assert self.args.has_key('src_SR_type')
        assert self.args.has_key('dest_SR_type')

        self.test_config['win01'] = {'distro' : 'win7-x86',
                                    'src_SR_type' : self.args['src_SR_type'],
                                    'dest_SR_type' : self.args['dest_SR_type'],
                                    'nodrivers' : True }

        self.test_config['src_SR_type'] = self.args['src_SR_type']
        self.test_config['dest_SR_type'] = self.args['dest_SR_type']

        if self.args.has_key('test'):
            self.test_config['type_of_migration'] = self.args['test']

        if self.args.has_key('negative_test'):
            self.test_config['negative_test'] = self.args['negative_test']
            
        return
        
class SxmFromLowToHighVersion(LiveMigrate):
    """Baseclass for migrating VMs without PV drivers"""

    def setTestParameters(self):
    
        self.test_config['test_VMs'] = ['win01']
        assert self.args.has_key('src_SR_type')
        assert self.args.has_key('dest_SR_type')

        self.test_config['win01'] = {'distro' : 'win7-x86',
                                    'src_SR_type' : self.args['src_SR_type'],
                                    'dest_SR_type' : self.args['dest_SR_type'],
                                    'nodrivers' : False }

        self.test_config['src_SR_type'] = self.args['src_SR_type']
        self.test_config['dest_SR_type'] = self.args['dest_SR_type']
       
        return

#class TC17088(AgentlessVMStorageMigration):
#    """Intra Pool Storage Migration when the PV drivers are not installed on the VM"""
#    pass

#class TC17089(AgentlessVMStorageMigration):
#    """Cross Pool Storage Migration when the PV drivers are not installed on the VM"""
#    pass

class DestHostFullVMStorageMigration(LiveMigrate):
    """Baseclass for migrating VMs when the destination host lacks enough memory"""

    def preHook(self):

        LiveMigrate.preHook(self)
        host = self.test_config['host_B']

        xenrt.TEC().logverbose("Configuring %s to be 'full'" % (host.getName()))
        # Configure the host to be 'full' - we need to leave a value somewhere
        # between 600 and 1000MiB free (deliberately randomise within this range)
        # Make sure that static+dynamic-max is greater
        freemem = host.getFreeMemory()

        # We start up two VMs
        max = (freemem + 4096) / 2 # 4GiB over the host free memory
        shadowOH = max/128 + 1 # This takes account of the shadow overhead
        leaveFree = random.randint(600, 1000)
        min = (freemem - leaveFree - 2*shadowOH) / 2

        for i in range(2):
            g = host.createGenericLinuxGuest(start=False)
            self.uninstallOnCleanup(g)
            g.setMemoryProperties(None, min, max, max)
            g.start()

    def setTestParameters(self):

        self.test_config['test_VMs'] = ['win01']
        assert self.args.has_key('src_SR_type')
        assert self.args.has_key('dest_SR_type')

        self.test_config['win01'] = {'distro' : 'win7-x86',
                                    'src_SR_type' : self.args['src_SR_type'],
                                    'dest_SR_type' : self.args['dest_SR_type']}

        self.test_config['src_SR_type'] = self.args['src_SR_type']
        self.test_config['dest_SR_type'] = self.args['dest_SR_type']

        if self.args.has_key('test'):
            self.test_config['type_of_migration'] = self.args['test']

        if self.args.has_key('negative_test'):
            self.test_config['negative_test'] = self.args['negative_test']

        return

#class TC17090(DestHostFullVMStorageMigration):
#    """Intra Pool Storage Migration when the destination host is not having enough memory"""
#    pass

#class TC17091(DestHostFullVMStorageMigration):
#    """Cross Pool Storage Migration when the destination host is not having enough memory"""
#    pass

class MoreVDIsStorageMigration(LiveMigrate):
    """Baseclass for migrating VMs when the VM has more than 6 VDIs"""

    def setTestParameters(self):
    
        self.test_config['test_VMs'] = ['lin01']
        assert self.args.has_key('src_SR_type')
        assert self.args.has_key('dest_SR_type')

        self.test_config['lin01'] = {'distro' : 'debian60',
                                    'VDI_src_SR_types' : ['ext', 'ext', 'ext', 'ext', 'ext', 'ext', 'ext'],
                                    'VDI_dest_SR_types' : ['lvm', 'lvm', 'lvm', 'lvm', 'lvm', 'lvm', 'lvm']}

        self.test_config['src_SR_type'] = self.args['src_SR_type']
        self.test_config['dest_SR_type'] = self.args['dest_SR_type']

        if self.args.has_key('test'):
            self.test_config['type_of_migration'] = self.args['test']

        if self.args.has_key('negative_test'):
            self.test_config['negative_test'] = self.args['negative_test']

        return

#class TC17092(MoreVDIsStorageMigration):
#    """Verifying Intra Pool Storage Migration when the VM has more than 6 VDIs"""
#    pass

#class TC17093(MoreVDIsStorageMigration):
#    """Verifying Cross Pool Storage Migration when the VM has more than 6 VDIs"""
#    pass

class SuspendDuringIntraPoolMigration(MidMigrateFailure):
    """Baseclass for migrating VMs along with life cycle operations"""

    def hook(self):

        guest = self.guests[0]
        destHost = self.observers[0].destHost
        destCli = destHost.getCLIInstance()

        test_status = []
        if not self.test_config.has_key('test_status'):
            self.test_config['test_status'] = {guest.getName() : test_status}  
        elif self.test_config['test_status'].has_key(guest.getName()):
            test_status = self.test_config['test_status'][guest.getName()]
        else:
            self.test_config['test_status'][guest.getName()] = test_status

        try:
            xenrt.TEC().logverbose("INFO_SXM: Going to suspend VM")
            guest.suspend()
        except Exception as e:
            test_status.append("FAILURE_SXM: Cant suspend VM %s during migration" % (guest.getName()))
            test_status.append("FAILURE_SXM: " + str(e))
            xenrt.TEC().logverbose("Could not Suspend VM %s " % (guest.getName()))

        try:
            if guest.getState() == "SUSPENDED":
                xenrt.TEC().logverbose("INFO_SXM: Going to Resume VM")
                destCli.execute("vm-resume uuid=%s"% guest.getUUID()) 
        except Exception as e:
            test_status.append("FAILURE_SXM: Unable to resume VM %s" % (guest.getName()))
            test_status.append("FAILURE_SXM: " + str(e)) 

class PauseDuringIntraPoolMigration(MidMigrateFailure):
    """Baseclass for migrating VMs along with life cycle operations"""

    def hook(self):

        guest = self.guests[0]
        destHost = self.observers[0].destHost
        destCli = destHost.getCLIInstance()

        test_status = []
        if not self.test_config.has_key('test_status'):
            self.test_config['test_status'] = {guest.getName() : test_status}
        elif self.test_config['test_status'].has_key(guest.getName()):
            test_status = self.test_config['test_status'][guest.getName()]
        else:
            self.test_config['test_status'][guest.getName()] = test_status

        try:
            xenrt.TEC().logverbose("INFO_SXM: Going to pause VM")
            guest.pause()
        except Exception as e:
            test_status.append("FAILURE_SXM: Cant pause VM %s during migration" % (guest.getName()))
            test_status.append("FAILURE_SXM: " + str(e))
            xenrt.TEC().logverbose("Could not pause VM %s " % (guest.getName()))

        try:
            if guest.getState() == "PAUSED":
                xenrt.TEC().logverbose("INFO_SXM: Going to UNPAUSE VM")
                destCli.execute("vm-unpause uuid=%s" % guest.getUUID())
        except Exception as e:
            test_status.append("FAILURE_SXM: Unable to unpause VM %s" % (guest.getName()))
            test_status.append("FAILURE_SXM: " + str(e))

class SuspendDuringCrossPoolMigration(MidMigrateFailure):
    """Baseclass for migrating VMs along with life cycle operations"""

    def hook(self):

        guest = self.guests[0]

        test_status = []
        if not self.test_config.has_key('test_status'):
            self.test_config['test_status'] = {guest.getName() : test_status}
        elif self.test_config['test_status'].has_key(guest.getName()):
            test_status = self.test_config['test_status'][guest.getName()]
        else:
            self.test_config['test_status'][guest.getName()] = test_status
        #Intoduce a delay of 2 secs to ensure suspend is called while sxm is in progress
        xenrt.sleep(2)
        try:
            xenrt.TEC().logverbose("INFO_SXM: Going to suspend VM")
            guest.suspend()
            test_status.append("FAILURE_SXM: VM %s was suspended but expected failure" % (guest.getName()))
        except:
            xenrt.TEC().logverbose("Suspendng of VM %s failed as expected" % (guest.getName()))

class PauseDuringCrossPoolMigration(MidMigrateFailure):
    """Baseclass for migrating VMs along with life cycle operations"""

    def hook(self):

        guest = self.guests[0]

        test_status = []
        if not self.test_config.has_key('test_status'):
            self.test_config['test_status'] = {guest.getName() : test_status}
        elif self.test_config['test_status'].has_key(guest.getName()):
            test_status = self.test_config['test_status'][guest.getName()]
        else:
            self.test_config['test_status'][guest.getName()] = test_status

        try:
            xenrt.sleep(3)#Sleep for 3 secs to ensure that migration is in progree while we try to pause VM
            xenrt.TEC().logverbose("INFO_SXM: Going to pause VM")
            guest.pause()
            test_status.append("FAILURE_SXM: VM %s was paused but expected failure" % (guest.getName()))
        except:
            xenrt.TEC().logverbose("Pausing of VM %s failed as expected " % (guest.getName()))

#class TC17094(LifeCycleOperationDuringStorageMigration):
#    """Verifying VM life cycle operations during an Intra Pool Storage Migration"""
#    pass

#class TC17095(LifeCycleOperationDuringStorageMigration):
#    """Verifying VM life cycle operations during a Cross Pool Storage Migration"""
#    pass

class DestHostWithInvalidSRUUIDStorageMigration(LiveMigrate):
    """Baseclass for migrating VMs when the destination SR has an invalid SR UUID"""

    def preHook(self):

        LiveMigrate.preHook(self)
        for vm in self.vm_config.values():
            guest = vm['obj']

            #guest = self.observers[0].vm
            vdiSRMap=self.vm_config[guest.getName()]['VDI_SR_map']
            self.vm_config[guest.getName()]['VDI_SR_map'][vdiSRMap.keys()[0]] = '026a92e4-22b5-a06d-ba6f-abcdefghijkl'
        return

#class TC17096(DestHostWithInvalidSRUUIDStorageMigration):
#    """Verifying Live VDI Storage Migration to destination SR with invalid SR UUID"""
#    pass

#class TC17097(DestHostWithInvalidSRUUIDStorageMigration):
#    """Verifying Intra Pool Storage Migration to destination SR with invalid SR UUID"""
#    pass

#class TC17098(DestHostWithInvalidSRUUIDStorageMigration):
#    """Verifying Cross Pool Storage migration to destination SR with invalid SR UUID"""
#    pass

class RawVDIStorageMigration(LiveMigrate):
    """Baseclass for migrating VMs when the VDIs attached are Raw"""

    def setTestParameters(self):
    
        self.test_config['test_VMs'] = ['lin01']
        assert self.args.has_key('src_SR_type')
        assert self.args.has_key('dest_SR_type')

        self.test_config['lin01'] = {'distro' : 'debian60',
                                     'VDI_src_SR_types' : ['ext', 'ext'],
                                     'VDI_dest_SR_types' : ['nfs', 'nfs'],
                                     'raw_vdi_required' : True} # Raw VDI required is True

        self.test_config['src_SR_type'] = self.args['src_SR_type']
        self.test_config['dest_SR_type'] = self.args['dest_SR_type']

        if self.args.has_key('test'):
            self.test_config['type_of_migration'] = self.args['test']

        if self.args.has_key('negative_test'):
            self.test_config['negative_test'] = self.args['negative_test']

        if self.args.has_key('use_xe'):
            self.test_config['use_xe'] = self.args['use_xe']

        if self.args.has_key('src_host'):
            self.test_config['src_host'] = self.getHost(self.args['src_host'])

        if self.args.has_key('dest_host'):
            self.test_config['dest_host'] = self.getHost(self.args['dest_host'])

        if self.args.has_key('iterations'):
            self.test_config['iterations'] = self.args['iterations']

        if self.args.has_key('reuse_VM'):
            self.test_config['reuse_VM'] = self.args['reuse_VM']

        if self.args.has_key('immediate_failure'):
            self.test_config['immediate_failure'] = self.args['immediate_failure']

        if self.args.has_key('monitoring_failure'):
            self.test_config['monitoring_failure'] = self.args['monitoring_failure']

        return

#class TC17099(RawVDIStorageMigration):
#    """Verifying Live VDI Storage Migration when the VDI is raw"""
#    pass

#class TC17100(RawVDIStorageMigration):
#    """Verifying Intra Pool Storage Migration when the VM has raw VDI attached"""
#    pass

#class TC17101(RawVDIStorageMigration):
#    """Verifying Cross Pool Storage Migration when the VM has raw VDI attached"""
#    pass

#class TC17102(LiveMigrate):
class HaltedVMStorageMigration(LiveMigrate):
    """Intra Pool Storage Migration when the VM is an halted state"""

    def preHook(self):

        LiveMigrate.preHook(self)
        for vm in self.vm_config.values():
            guest = vm['obj']

            # Check if the guest is halted
            if guest.getState() == "UP":
                guest.shutdown()
            if guest.getState() == "SUSPENDED":
                guest.resume()
                guest.shutdown()
        return
        
    def postHook(self):    
        
        for vm in self.vm_config.values():
            guest = vm['obj']

            # Check if the guest is in a halted state
            if guest.getState() == "DOWN":
                guest.start()
        LiveMigrate.postHook(self)

#class TC17103(LiveMigrate):
class SuspendedVMStorageMigration(LiveMigrate):
    """Intra Pool Storage Migration when the VM is in a suspended state"""

    def preHook(self):

        LiveMigrate.preHook(self)
        for vm in self.vm_config.values():
            guest = vm['obj']

            # Check if the guest is suspended
            if guest.getState() == "UP":
                guest.suspend()
        return
        
    def postHook(self):    
        
        for vm in self.vm_config.values():
            guest = vm['obj']

            # Check if the guest is in a suspended state
            if guest.getState() == "SUSPENDED":
                guest.resume()
        LiveMigrate.postHook(self)    

#class TC17104(LiveMigrate):
class PausedVMStorageMigration(LiveMigrate):
    """Intra Pool Storage Migration when the VM is in a paused state"""

    def preHook(self):
        
        LiveMigrate.preHook(self)
        for vm in self.vm_config.values():
            guest = vm['obj']

            # Check if the guest is in a paused state
            if guest.getState() == "UP":
                guest.pause()
        return
        
    def postHook(self):    
        
        for vm in self.vm_config.values():
            guest = vm['obj']

            # Check if the guest is in a paused state then unpause it 
            if guest.getState() == "PAUSED":
                guest.lifecycleOperation("vm-unpause")
        LiveMigrate.postHook(self)

#class TC17105(LiveMigrate):
class SnapshotVMStorageMigration(LiveMigrate):
    """Verifying Cross Pool Storage Migration when the VM has more than one snapshot"""

    def preHook(self):
  
        LiveMigrate.preHook(self)
        for vm in self.vm_config.values():
            guest = vm['obj']

            for i in xrange(1,5):
                guest.snapshot() 
        return

#class TC17106(LiveMigrate):
class CheckpointVMStorageMigration(LiveMigrate):
    """Verifying Cross Pool Storage Migration when the VM has one checkpoint"""

    def preHook(self):

        LiveMigrate.preHook(self)
        for vm in self.vm_config.values():
            guest = vm['obj']

            guest.checkpoint()
        return

#class TC17219(LiveMigrate):
class InvalidDrvVerVMStorageMigration(LiveMigrate):
    """Verifying Cross Pool Storage Migration when the VM has an invalid version of PV driver"""

    # We prepare a sourcepool with previous GA version. (from sequence definition) 
    # That means VM with older pv drivers installed.
    # And then upgrade the pool to newer XenServer version. But pv drivers of the vm not updated.

    def prepare(self, arglist=None):
        
        LiveMigrate.prepare(self, arglist)
        # LiveMigrate.prepare gets you VM installed on the source pool: self.pool_A

        # Update our internal pool object before starting the upgrade
        newP = xenrt.lib.xenserver.poolFactory(xenrt.TEC().lookup("PRODUCT_VERSION", None))(self.pool_A.master)
        self.pool_A.populateSubclass(newP)

        # Suspend VMs on the source pool
        for guest in self.guests:
            guest.suspend()
            xenrt.TEC().progress("Suspending VM %s" % guest.getName())

        # Upgrade the source pool (only one host as the master)
        currentVersion = xenrt.TEC().lookup("PRODUCT_VERSION")
        self.pool_A.master.tailored = False
        xenrt.lib.xenserver.cli.clearCacheFor(self.pool_A.master.machine)
        self.pool_A.master = self.pool_A.master.upgrade(currentVersion)
        time.sleep(180)
        self.pool_A.master.check()
        if len(self.pool_A.master.listGuests()) == 0:
            raise xenrt.XRTFailure("VMs missing after host upgrade")

        # Resume VMs on the master
        for guest in self.guests:
            guest.resume()
            xenrt.TEC().progress("Resuming VM %s" % guest.getName())

        # Upgrade all our guest objects now before the live migration.
        newguests = []
        for g in self.guests:
            newg = self.pool_A.master.guestFactory()(g.name, host=g.host)
            g.populateSubclass(newg)
            newguests.append(newg)
        self.guests = newguests

        for guest in self.guests:
            vm = self.vm_config[guest.getName()]
            vm['obj'] = guest

        return

    def setTestParameters(self):

        self.test_config['test_VMs'] = ['win01']
        assert self.args.has_key('src_SR_type')
        assert self.args.has_key('dest_SR_type')

        self.test_config['win01'] = {'distro' : 'win7-x86',
                                    'src_SR_type' : self.args['src_SR_type'],
                                    'dest_SR_type' : self.args['dest_SR_type']}

        self.test_config['src_SR_type'] = self.args['src_SR_type']
        self.test_config['dest_SR_type'] = self.args['dest_SR_type']

        if self.args.has_key('test'):
            self.test_config['type_of_migration'] = self.args['test']

        if self.args.has_key('negative_test'):
            self.test_config['negative_test'] = self.args['negative_test']

        return

#class TC17222(LiveMigrate):
class WithvGPUVMStorageMigration(LiveMigrate):
    """Verifying Cross Pool Storage Migration when the VM has vGPU assigned"""

    def prepare(self, arglist=None):
        
        LiveMigrate.prepare(self, arglist)

        host = self.test_config['host_A']
        gpu_group_uuids = [x for x in host.minimalList("gpu-group-list") if "NVIDIA" in host.genParamGet("gpu-group",x,"name-label")]
        #>0 gpu hw required for this license test

        if len(gpu_group_uuids)<1:
            raise xenrt.XRTFailure("This host does not contain a GPU group list as expected")        
        cli = host.getCLIInstance()
            
        for guest in self.guests:            
            if guest.getState() == 'UP':
                #shutdown the VM and assign gpu to the Windows VM and then start it before we attempt to do sxm 
                guest.shutdown()
                vgpu_uuid = cli.execute("vgpu-create", "gpu-group-uuid=%s vm-uuid=%s" % (gpu_group_uuids[0],guest.getUUID())).strip()
                guest.start()
    
            
    def setTestParameters(self):
    
        self.test_config['test_VMs'] = ['win01']
        assert self.args.has_key('src_SR_type')
        assert self.args.has_key('dest_SR_type')
        self.test_config['win01'] = {'distro' : 'win7-x86',
                                     'src_SR_type' : self.args['src_SR_type'],
                                     'dest_SR_type' : self.args['dest_SR_type'] }

        self.test_config['src_SR_type'] = self.args['src_SR_type']
        self.test_config['dest_SR_type'] = self.args['dest_SR_type']
        
        self.test_config['win_crash'] = True        

        if self.args.has_key('test'):
            self.test_config['type_of_migration'] = self.args['test']

        if self.args.has_key('negative_test'):
            self.test_config['negative_test'] = self.args['negative_test']
            
    def postHook(self):
        
        LiveMigrate.postHook(self)
        for guest in self.guests:
            if guest.getState() != 'UP':                
                guest.start()
               
            try:
               guest.shutdown()
               guest.start()
               
            except Exception as e:
               raise xenrt.XRTFailure("FAILURE_SXM: VM %s lifcycle operations failed with '%s'" %(guest.getUUID(), e))
        

#class TC17352(LiveMigrate):
class HotFixStorageMigration(LiveMigrate):
    """Verifying Cross Pool Storage Migration on a Tampa build with an hotfix applied"""
    # Sourcepool is on Base Tampa build
    # TargetPool is on Base Tampa build + Hotfixes

    def prepare(self, arglist=None):

        self.test_config = {}
        self.vm_config = {}

        self.pool_A = self.getPool('RESOURCE_POOL_0')
        self.pool_B = self.getPool('RESOURCE_POOL_1')     
        
        try:
            self.pool_B.master.applyPatch(self.pool_B.master.getTestHotfix(1), returndata=True)
        except xenrt.XRTFailure, e:
            raise xenrt.XRTFailure("Failure while applying patch: " + e.reason)

        try:            
            self.pool_B.master.execdom0("rm -f /root/hotfix-test1")
        except xenrt.XRTFailure, e:
            raise xenrt.XRTFailure("Failure while applying patch: " + e.reason)

        # Incase of live VDI migrate and intra-pool storage migration,
        # destination pool will be same as source Pool
        if self.pool_B is None:
            self.pool_B = self.pool_A

        self.parseArgs(arglist)

        self.populateTestConfig()

        self.identifyHostAAndB()

        self.setTestParameters()

        self.createTestVMs()

        self.initiateDiskActivities()

        return

class ConcurrentVMMigrate1(LiveMigrate):
    
    def setTestParameters(self):

        self.test_config['test_VMs'] = ['lin01', 'win01', 'lin02']
        assert self.args.has_key('src_SR_type')
        assert self.args.has_key('dest_SR_type')

        self.test_config['lin01'] = {'src_SR_type' : self.args['src_SR_type'],
                                     'dest_SR_type' : self.args['dest_SR_type'] }

        self.test_config['win01'] = {'src_SR_type' : self.args['src_SR_type'],
                                     'dest_SR_type' : self.args['dest_SR_type'] }

        self.test_config['lin02'] = {'src_SR_type' : self.args['src_SR_type'],
                                     'dest_SR_type' : self.args['dest_SR_type'] }

        self.test_config['src_SR_type'] = self.args['src_SR_type']
        self.test_config['dest_SR_type'] = self.args['dest_SR_type']

        if self.args.has_key('test'):
            self.test_config['type_of_migration'] = self.args['test']

        if self.args.has_key('negative_test'):
            self.test_config['negative_test'] = self.args['negative_test']

        return

class ConcurrentVMMigrate2(LiveMigrate):

    def setTestParameters(self):

        self.test_config['test_VMs'] = ['lin01', 'win01', 'lin02']
        assert self.args.has_key('src_SR_type')
        assert self.args.has_key('dest_SR_type')

        self.test_config['lin01'] = {'src_SR_type' : self.args['src_SR_type'],
                                     'dest_SR_type' : self.args['dest_SR_type'] }

        self.test_config['win01'] = {'src_SR_type' : self.args['src_SR_type'],
                                     'dest_SR_type' : self.args['dest_SR_type'] }

        # This one is in the reverse direction.
        self.test_config['lin02'] = {'src_SR_type' : self.args['dest_SR_type'], 
                                     'dest_SR_type' : self.args['src_SR_type'],
                                     'src_host' : 'host_B',
                                     'dest_host' : 'host_A'}
        
        self.test_config['src_SR_type'] = self.args['src_SR_type']
        self.test_config['dest_SR_type'] = self.args['dest_SR_type']

        if self.args.has_key('test'):
            self.test_config['type_of_migration'] = self.args['test']

        if self.args.has_key('negative_test'):
            self.test_config['negative_test'] = self.args['negative_test']

        return

class VMRevertedToSnapshot(LiveMigrate):
    """Verifying Cross Pool Storage Migration with a VM that has been reverted to a snapshot"""

    def preHook(self):

        LiveMigrate.preHook(self)
        vm = self.guests[0]
        snapUUID = vm.snapshot()
        vm.revert(snapUUID)
        vm.start()
        self.vm_config[vm.getName()]['snapshot'] = snapUUID

        # Update vm_config with the right VDIs and VIFs after snapshot revert
        attached_disks = vm.listDiskDevices()
        attached_disks.sort()
        attached_VDIs = [vm.getDiskVDIUUID(d) for d in attached_disks]
        dest_SRs = self.vm_config[vm.getName()]['VDI_SR_map'].values()
        self.vm_config[vm.getName()]['VDI_SR_map'] = dict(itertools.izip(attached_VDIs, dest_SRs))
        self.vm_config[vm.getName()]['src_VDIs'] = dict(itertools.izip(attached_disks, attached_VDIs))
        vif_nw_map = {}
        if self.test_config['type_of_migration'] == 'inter-pool':
            destHost = self.vm_config[vm.getName()]['dest_host']
            host = vm.getHost()
            allVifs = host.minimalList('vm-vif-list uuid=%s' % vm.getUUID())
            mainNWuuid = destHost.getManagementNetworkUUID()
            for vif in allVifs:
                vif_nw_map.update({vif:mainNWuuid})
        self.vm_config[vm.getName()]['VIF_NW_map'] = vif_nw_map
