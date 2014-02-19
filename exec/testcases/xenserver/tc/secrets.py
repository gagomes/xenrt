#
# XenRT: Test harness for Xen and the XenServer product family
#
# XenServer secrets test cases
#
# Copyright (c) 2009 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import xenrt, time

class TC10857(xenrt.TestCase):
    
    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        
    def run(self, arglist=None):
        xenrt.TEC().logverbose("Testing host %s" % self.host.getName())
        
        secret = 'TC10857_secret'
        
        xenrt.TEC().logverbose('Creating secret (%s)' % secret)
        uuid = self.host.createSecret(secret)
        
        secret = 'secret_TC10857'
        xenrt.TEC().logverbose('Modifying secret (uuid=%s newvalue=%s)' 
                    % (uuid, secret))

        self.host.modifySecret(uuid, secret)

        xenrt.TEC().logverbose('Destroying secret (uuid=%s)' 
                    % uuid)

        self.host.deleteSecret(uuid)
    

class TC10862(xenrt.TestCase):
    def prepare(self, arglist=None):
        self.pool = self.getDefaultPool()
        if len(self.pool.getHosts()) < 2:
            raise xenrt.XRTError("Need a pool of 2 hosts", data="Found %u" %
                                 (len(self.pool.getHosts())))
        
    def run(self, arglist=None):
        
        master = self.pool.master
        self.master = master
        slave = self.pool.getSlaves()[0]
        self.slave = slave
        cli = master.getCLIInstance()
        uuid = cli.execute('secret-create', 'value=%s' % 'TC10862_secret')
        uuid = uuid.strip()
        self.secret_uuid = uuid

        for h in self.pool.getHosts():
            xenrt.lib.xenserver.cli.clearCacheFor(h.machine)

        # Wait 2 minutes
        time.sleep(120)
        
        # Promote the slave to a new master
        self.pool.designateNewMaster(slave)
        self.pool.check()
        
        uuid_slave = slave.minimalList('secret-list', args='uuid=%s' % uuid)
        uuid_master = master.minimalList('secret-list', args='uuid=%s' % uuid)

        if len(uuid_slave) != 1:
            raise xenrt.XRTFailure('No secret with uuid=%s was created on slave' % uuid)
        if len(uuid_slave) != 1:
            raise xenrt.XRTFailure('No secret with uuid=%s was created on master' % uuid)
        if uuid_slave[0] != uuid or uuid_master[0] != uuid:
            xenrt.TEC().logverbose("orig uuid=%s master uuid=%s slave uuid=%s" 
                                   %  uuid, uuid_master[0], uuid_slave[0])
            raise xenrt.XRTFailure("Couldn't find uuid=%s on master or slave" % uuid)
        
    def postRun(self):
        self.pool.addHost(self.slave)
        self.pool.check()

        cli = self.master.getCLIInstance()
        cli.execute('secret-destroy', 'uuid=%s' % self.secret_uuid)
