#
# XenRT: Test harness for Xen and the XenServer product family
#
# Kirkwood testcases
#
# Copyright (c) 2009 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

import re, string, time, traceback, sys, random, types, socket, copy, os
import xenrt, xenrt.lib.xenserver, xenrt.networkutils

class _KirkwoodBase(xenrt.TestCase):
    """Base class for Kirkwood Testcases"""
    MIN_POOL_SIZE = 1
    WLBSERVER = "VPXWLB"
    FORCE_FAKEKIRKWOOD = False

    def __init__(self, tcid=None):
        self.kirkwood = None
        self.kwserver = None
        self.vpx_os_version = xenrt.TEC().lookup("VPX_OS_VERSION", "CentOS5")
        self.wlbappsrv = xenrt.WlbApplianceFactory().create(None, self.vpx_os_version)
        xenrt.TestCase.__init__(self, tcid=tcid)

    def createFakeKirkwood(self, port=None):
        self.kirkwood = xenrt.lib.createFakeKirkwood(port)

        # Construct a random username and password to use
        # We use all valid HTTP basic characters as possibilities
        chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        chars += "abcdefghijklmnopqrstuvwxyz"
        chars += "0123456789"
        chars += "!\"#$%^&*()-_+[]{};'@|~\\/<>,.`"
        self.wlbUsername = "xenrt"
        for i in range(5):
            self.wlbUsername += random.choice(chars)
        self.wlbPassword = ""
        for i in range(10):
            self.wlbPassword += random.choice(chars)
        self.xs_username = self.wlbUsername
        self.xs_password = self.wlbPassword

    def createProxyKirkwood(self, vpxwlb_host, vpxwlb_port):
        self.kirkwood = xenrt.lib.createProxyKirkwood(vpxwlb_host, vpxwlb_port)
        self.wlbUsername = self.wlbappsrv.wlb_username #"wlbuser"
        self.wlbPassword = self.wlbappsrv.wlb_password # default password#
        self.xs_username = "root"
        self.xs_password = xenrt.TEC().lookup("DEFAULT_PASSWORD")

    def prepare(self, arglist):
        self.usevpxwlb = xenrt.TEC().lookup("USE_VPXWLB",False,boolean=True)
        if self.usevpxwlb:
            xenrt.TEC().logverbose("Using VPXWLB")
        # Look up if a VM named "VPXWLB" is installed and running the
        # Kirkwood service
        self.kwserver = self.getGuest(self.WLBSERVER)
        if self.usevpxwlb and not self.kwserver:
            raise xenrt.XRTError("Instructed to use VPXWLB but VPXWLB VM not available in pool")
        if self.kwserver and not self.FORCE_FAKEKIRKWOOD:
            self.getLogsFrom(self.kwserver)
            # Configure a Proxy Kirkwood instance
            vpxwlb_host = self.kwserver.getIP()
            vpxwlb_port = int(self.wlbappsrv.wlb_port) #8012
            xenrt.TEC().logverbose("Using ProxyKirkwood, VPXWLB VM at %s:%s" % (vpxwlb_host,vpxwlb_port))
            self.createProxyKirkwood(vpxwlb_host, vpxwlb_port)
        else:
            # Configure a Fake Kirkwood instance
            xenrt.TEC().logverbose("Using FakeKirkwood")
            self.createFakeKirkwood()

        self.pool = self.getDefaultPool()
        if len(self.pool.getHosts()) < self.MIN_POOL_SIZE:
            raise xenrt.XRTError("This testcase requires a pool of at least "
                                 "%d hosts" % (self.MIN_POOL_SIZE),
                                 data="Provided pool only has %d hosts" %
                                      (len(self.pool.getHosts())))

    def postRun(self):
        if self.pool:
            # Try and deconfigure WLB
            # Disabling it means that xapi doesn't try and talk to fake
            # kirkwood to disable it
            try:
                self.pool.setPoolParam("wlb-enabled", "false")
                self.pool.wlbEnabled = False
            except:
                pass            
            try:
                cli = self.pool.getCLIInstance()
                cli.execute("pool-deconfigure-wlb")
            except:
                pass
        if self.kirkwood:
            errs = self.kirkwood.getErrors()
            if len(errs) > 0:
                xenrt.TEC().warning("Found unhandled FakeKirkwood "
                                    "error(s): %s" % (errs))
            reqs = self.kirkwood.getRequests()
            if len(reqs) > 0:
                xenrt.TEC().logverbose("Unhandled FakeKirkwood "
                                       "request(s): %s" % (reqs))

            if self.kirkwood.isAlive():
                try:
                    self.kirkwood.shutdown()
                except:
                    xenrt.TEC().warning("Exception trying to shut down "
                                        "FakeKirkwood")

    def checkRequest(self, expectedCall, expectedParams):
        errs = self.kirkwood.getErrors()
        xenrt.TEC().logverbose("Found Kirkwood error(s): %s" % (errs))
        if len(errs) > 0:
            raise xenrt.XRTFailure("FakeKirkwood reported an erroneous call", data=str(errs))

        reqs = self.kirkwood.getRequests()
        xenrt.TEC().logverbose("Found Kirkwood request(s): %s" % (reqs))
        self.kirkwood.resetRequests()

        # Check there was only one request
        if len(reqs) > 1:
            raise xenrt.XRTFailure("Xapi made more than one call to Kirkwood")
        elif len(reqs) == 0:
            raise xenrt.XRTFailure("Xapi didn't call Kirkwood when expected")

        # Check it was the correct method
        req = reqs[0]
        if req[0] != expectedCall:
            raise xenrt.XRTFailure("Xapi called incorrect method",
                                   data="Expecting %s, found %s" %
                                        (expectedCall, req[0]))

        # Check it had the right parameters
        if req[1] != expectedParams:
            raise xenrt.XRTFailure("Xapi %s call did not have expected "
                                   "parameters" % (req[0]),
                                   data="Expecting %s, found %s" %
                                        (expectedParams, req[1]))

        # Check it authenticated properly
        if req[2][0] != self.wlbUsername or req[2][1] != self.wlbPassword:
            raise xenrt.XRTFailure("Xapi did not authenticate properly with "
                                   "WLB", data="Expecting %s:%s, found %s:%s" %
                     (self.wlbUsername, self.wlbPassword, req[2][0], req[2][1]))


    # Basic subcases for use in tests. Each one ensures the correct Kirkwood method call is made...

    def initialiseWLB(self):
        self.pool.initialiseWLB("%s:%d" % (self.kirkwood.ip,self.kirkwood.port),
                                self.wlbUsername, self.wlbPassword,
                                self.xs_username, self.xs_password)
        expectedParams = {'UserName':self.xs_username,
                          'Password':self.xs_password,
                          'PoolUuid':self.pool.getUUID(),
                          'XenServerUrl':'http://%s:80/' %
                                         (self.pool.master.getIP())}
        self.checkRequest("AddXenServer", expectedParams)

    def deconfigureWLB(self):
        self.pool.deconfigureWLB()
        expectedParams = {'PoolUuid':self.pool.getUUID()}
        self.checkRequest("RemoveXenServer", expectedParams)



class TC8513(_KirkwoodBase):
    """Verify that WLB can be initialised and deconfigured"""

    def run(self, arglist=None):
        # Initialise WLB
        if self.runSubcase("initialiseWLB", (), "Basic", "initialiseWLB") != xenrt.RESULT_PASS:
            return
        # Wait 1 minute and run a check to make sure everything is happy
        time.sleep(60)
        self.pool.checkWLB()
        # Now deconfigure it
        if self.runSubcase("deconfigureWLB", (), "Basic", "deconfigureWLB") != xenrt.RESULT_PASS:
            return
        # Wait 1 minute and run a check to make sure everything is happy
        time.sleep(60)
        self.pool.checkWLB()

class TC21444(_KirkwoodBase):
    """Verify that WLB service can be accessible through network"""
    def run(self, arglist=None):
        host = self.kwserver.getIP()
        port = self.wlbappsrv.wlb_port
        if not xenrt.networkutils.Telnet(host, port).run():
            raise xenrt.XRTError("WLB service is not up")

class _KirkwoodErrorBase(_KirkwoodBase):
    """Base class for error handling testcases"""
    FORCE_FAKEKIRKWOOD = True
    INITIALISE_FIRST = True
    VM_REQUIRED = False
    # Tests to run
    ERRORS = ["ConnectionRefused", "AuthenticationFailed", "MalformedResponse",
              "Timeout", "Error"]
    # Extra tests
    TCERRORS = []
    COMMAND_SHOULD_ERROR = True
    
    def run(self, arglist=None):

        if self.VM_REQUIRED:
            sruuid = self.pool.master.lookupDefaultSR()
            self.guest = self.pool.master.createGenericLinuxGuest(sr=sruuid)
            self.uninstallOnCleanup(self.guest)
            self.guest.shutdown()        

        self.error = None

        for err in self.ERRORS:
            if self.runSubcase("runErrorCase", (err), "WLBError", err) != xenrt.RESULT_PASS:
                return
        for err in self.TCERRORS:
            if self.runSubcase("runErrorCase", (err), "WLBError", err) != xenrt.RESULT_PASS:
                return

    def runErrorCase(self, err):
        self.error = err
        # Do we need to be initialised?
        if self.INITIALISE_FIRST:
            self.initialiseWLB()
        # Set up the error situation
        self.configureError(err)
        # Make the call and check we get the expected error code back
        allowed = False
        try:
            self.runCommand()
            allowed = True
        except xenrt.XRTFailure, e:
            if not self.COMMAND_SHOULD_ERROR:
                raise e
            else:
                pass
                # TODO: Check the exception is accurate
        if allowed and self.COMMAND_SHOULD_ERROR:
            raise xenrt.XRTFailure("Command unexpectedly returned successfully")
        # Run any specific checks for this command
        self.extraChecks()

        # Reset ready to go again
        self.resetError()

    def runCommand(self):
        raise xenrt.XRTError("Unimplemented")

    def extraChecks(self):
        pass

    def configureError(self, error):
        if error == "ConnectionRefused":
            # Stop fake Kirkwood
            self.kirkwood.shutdown()
        elif error == "AuthenticationFailed":
            self.kirkwood.returnForbidden = True
        elif error == "MalformedResponse":
            self.kirkwood.returnSpecial = "This is a garbage response!"
        elif error == "Timeout":
            # TODO: Try various timeouts
            self.kirkwood.delayReply = 35
        elif error == "Error":
            # TODO: Return other errors
            self.kirkwood.returnError = "InvalidParameter"

    def resetError(self):
        if not self.kirkwood.isAlive():
            self.createFakeKirkwood(port=self.kirkwood.port)
        else:
            self.kirkwood.returnForbidden = False
            self.kirkwood.returnSpecial = None
            self.kirkwood.delayReply = None
            self.kirkwood.returnError = None
        if self.pool.wlbEnabled:
            self.pool.deconfigureWLB()
        self.kirkwood.resetRequests()

class TC8541(_KirkwoodErrorBase):
    """Verify that Xapi handles errors from Kirkwood when initialising"""
    INITIALISE_FIRST = False
    TCERRORS = ["InvalidURL"]

    def runCommand(self):
        if self.error == "InvalidURL":
            url = "thisisaninvalidurl:1234"
        else:
            url = "%s:%d" % (self.kirkwood.ip, self.kirkwood.port)
        self.pool.initialiseWLB(url,self.wlbUsername, self.wlbPassword,
                                self.xs_username, self.xs_password)


class TC8542(_KirkwoodErrorBase):
    """Verify that Xapi handles errors from Kirkwood when deconfiguring"""
    
    def runCommand(self):
        host = self.pool.master
        self.COMMAND_SHOULD_ERROR = True
        # CA-60147 - TC8542 If WLB is not alive, it is okay; pool-deconfigure-wlb is still expected to succeed.
        if isinstance(host, xenrt.lib.xenserver.BostonHost):
            # CA-93312-TC8542-from Boston and forward (Sanibel, Tampa, Clearwater, etc), pool-deconfigure-wlb is still expected to succeed
            self.COMMAND_SHOULD_ERROR = False
        self.pool.deconfigureWLB()

class TC8539(_KirkwoodBase):
    """Verify that sending/receiving WLB configuration works"""
    # Try it with WLB disabled or not
    DISABLED = False
    FORCE_FAKEKIRKWOOD = True

    def run(self, arglist=None):
        # Initialise WLB
        self.initialiseWLB()

        if self.DISABLED:
            self.pool.disableWLB()

        # Send a configuration dictionary from XenServer to WLB, including some
        # 'awkward' strings
        # TODO: Make sure we're covering all possible awkward characters etc...
        configToSend = {'field1':'abcdefg',
                        'field2':'1234567',
                        '<awkward':'>field',
                        'amper':'&sand',
                        'others':'\\/!"$%^*()-_+[]{}#~@;:?<>,."\'',
                        'long':'fi' + ('e' * 154) + 'ld'}
        self.pool.sendWLBConfig(configToSend)
        # Check it was received correctly
        self.checkRequest("SetXenPoolConfiguration",
                          {'OptimizationParms': configToSend,
                           'PoolUuid': self.pool.getUUID()})

        # Change the data in WLB
        configToReceive = configToSend
        configToReceive['extra'] = 'added at wlb side'
        del(configToReceive['field1'])
        self.kirkwood.poolConfig = configToReceive

        # Now retrieve the dictionary
        receivedConfig = self.pool.retrieveWLBConfig()
        # Check the correct parameters were received in the request
        self.checkRequest("GetXenPoolConfiguration",
                          {'PoolUuid': self.pool.getUUID()})
        # Check the dictionaries match
        if receivedConfig != configToReceive:
            raise xenrt.XRTFailure("Received dictionary does not match WLB "
                                   "provided dictionary",
                                   data="Expecting %s, received %s" %
                                        (configToReceive, receivedConfig))

class TC8599(TC8539):
    """Verify that sending/receiving WLB configuration works if WLB disabled"""
    DISABLED = True

class TC8543(_KirkwoodErrorBase):
    """Verify that sending WLB configuration handles WLB errors"""

    def runCommand(self):
        self.pool.sendWLBConfig({'sample':'config'})

class TC8544(_KirkwoodErrorBase):
    """Verify that receiving WLB configuration handles WLB errors"""

    def runCommand(self):
        self.kirkwood.poolConfig = {'sample':'config'}
        data = self.pool.retrieveWLBConfig()

class TC21681(_KirkwoodErrorBase):
    """Verify that receiving WLB Pool Audit Log configuration"""

    def runCommand(self):
        self.kirkwood.poolConfig = {'PoolAuditLogGranularity':'Medium'}
        data = self.pool.retrieveWLBConfig()
        if data.get('PoolAuditLogGranularity') != 'Medium':
            raise xenrt.XRTFailure("set PoolAuditLogGranularity=Medium but return %r" % data.get('PoolAuditLogGranularity'))

class TC21450(_KirkwoodErrorBase):
    """Verify WLB service network connection failure under error condition"""
    ERRORS = ["ConnectionRefused"]

    def runCommand(self):
        host = self.kirkwood.ip
        port = self.kirkwood.port
        if not xenrt.networkutils.Telnet(host, port).run():
            raise xenrt.XRTFailure("Command is expected as failure.")

class TC21451(_KirkwoodBase):
    """Verify that Xapi handles errors from Kirkwood when do multi-initialising"""

    def run(self, arglist=None):
        url = "%s:%d" % (self.kirkwood.ip, self.kirkwood.port)
        for i in range(5):
            self.pool.initialiseWLB(url,self.wlbUsername, self.wlbPassword,
                                    self.xs_username, self.xs_password)

class _KirkwoodVMRecommendations(_KirkwoodBase):
    """Base class for VM recommendation testcases"""
    FORCE_FAKEKIRKWOOD = True
    MIN_POOL_SIZE = 1
    # RECOMMENDATIONS is a list of tuples, each one meaning:
    # (CanBootVM, Stars / Reason)
    # If CanBootVM is set to None, no recommendation will be sent,
    # and the reason will be checked straight off
    RECOMMENDATIONS = [(True, 1)]

    def installVM(self):
        return self.pool.master.createGenericEmptyGuest()

    def run(self, arglist=None):
        # Initialise WLB
        self.initialiseWLB()

        # Install a VM
        g = self.installVM()
        self.uninstallOnCleanup(g)
        # Set up some recommendations for it in FakeKirkwood
        recommendations = []
        hosts = self.pool.getHosts()
        expectedRecs = {}
        for i in range(self.MIN_POOL_SIZE):
            if self.RECOMMENDATIONS[i][0]:
                r = {'CanBootVM':'true',
                     'HostUuid':hosts[i].getMyHostUUID(),
                     'RecommendationId':str(i),
                     'Stars':self.RECOMMENDATIONS[i][1]}
                expectedRecs[hosts[i]] = "WLB %s %s" % (self.RECOMMENDATIONS[i][1], str(i))
                
            elif type(self.RECOMMENDATIONS[i][0]) == types.NoneType:
                # VM can't boot for some other reason
                r = {'HostUuid':hosts[i].getMyHostUUID(),
                     'RecommendationId':str(i),
                     'ZeroScoreReason':'Other'}
                expectedRecs[hosts[i]] = self.RECOMMENDATIONS[i][1]
            else:
                r = {'HostUuid':hosts[i].getMyHostUUID(),
                     'RecommendationId':str(i),
                     'ZeroScoreReason':self.RECOMMENDATIONS[i][1]}
                expectedRecs[hosts[i]] = "WLB 0.0 %s %s" % (str(i), self.RECOMMENDATIONS[i][1])
            recommendations.append(r)
        # Add zero score reasons for any remaining hosts (CA-25775)
        for i in range(self.MIN_POOL_SIZE, len(hosts)):
            r = {'HostUuid':hosts[i].getMyHostUUID(),
                 'RecommendationId':str(i),
                 'ZeroScoreReason':'NotRequired'}
            expectedRecs[hosts[i]] = "WLB 0.0 %s NotRequired" % (str(i))
            recommendations.append(r)
        self.kirkwood.recommendations[g.getUUID()] = recommendations
        
        # Now retrieve the recommendations
        receivedRecs = g.retrieveWLBRecommendations()
        # Check the correct request was made
        self.checkRequest("VMGetRecommendations",
                          {'PoolUuid':self.pool.getUUID(),
                           'VmUuid':g.getUUID()})                                            
        # We should have one recommendation per host, and they should match
        if len(receivedRecs) != len(hosts):
            raise xenrt.XRTFailure("Incorrect number of recommendations "
                                   "returned",
                                   data="Expecting %d, received %d" %
                                        (len(hosts), len(receivedRecs)))

        for h in hosts:
            if not receivedRecs.has_key(h.getName()):
                raise xenrt.XRTFailure("Cannot find recommendation for %s" %
                                       (h.getName()))
            if not re.search(expectedRecs[h], receivedRecs[h.getName()]):
                raise xenrt.XRTFailure("Recommendation for %s not as expected" %
                                        (h.getName()), data="Expecting '%s', "
                                        "found '%s'" % (expectedRecs[h],
                                                     receivedRecs[h.getName()]))

class TC8546(_KirkwoodVMRecommendations):
    """Test a single positive recommendation"""
    pass

class TC8547(_KirkwoodVMRecommendations):
    """Test multiple positive recommendations"""
    MIN_POOL_SIZE = 2
    RECOMMENDATIONS = [(True, 3.5), (True, 4.5)]

class TC8548(_KirkwoodVMRecommendations):
    """Test a single negative recommendation"""
    RECOMMENDATIONS = [(False, "CpuOvercommit")]

class TC8549(_KirkwoodVMRecommendations):
    """Test multiple negative recommendations"""
    MIN_POOL_SIZE = 2
    RECOMMENDATIONS = [(False, "CpuOvercommit"),
                       (False, "VmRequiresSr")]

class TC8550(_KirkwoodVMRecommendations):
    """Test mixed recommendations"""
    MIN_POOL_SIZE = 2
    RECOMMENDATIONS = [(True, 2.5),
                       (False, "CpuOvercommit")]

class TC8559(_KirkwoodVMRecommendations):
    """Verify that assert can boot here is honoured"""
    MIN_POOL_SIZE = 3
    RECOMMENDATIONS = [(None, "VM_REQUIRES_SR"),
                       (None, "VM_REQUIRES_SR"),
                       (True, 3)]

    def installVM(self):
        hosts = self.pool.getHosts()
        # Install to local storage of the second host...
        h = hosts[2]
        sr = h.getLocalSR()
        return h.createGenericLinuxGuest(start=False,sr=sr)

class TC8551(_KirkwoodErrorBase):
    """Verify that receiving VM recommendations handles WLB errors"""

    def runCommand(self):
        g = self.pool.master.createGenericEmptyGuest()
        self.uninstallOnCleanup(g)
        data = g.retrieveWLBRecommendations()


class _KirkwoodVMStart(_KirkwoodBase):
    """Base class for Kirkwood start/resume testcases"""
    FORCE_FAKEKIRKWOOD = True
    # Set START to true for vm-start, FALSE for vm-resume
    START = True
    # Number of hosts
    MIN_POOL_SIZE = 2
    # Recommendations to send (HostUuid's will be added automagically)
    RECOMMENDATIONS = []
    # Expected result (integer index to above list of recs)
    EXPECT_ON = None
    # Number of iterations to do
    LOOPS = 10
    # Install to a local SR
    INSTALL_ON_LOCAL = False

    def run(self, arglist=None):
        # Initialise Kirkwood
        self.initialiseWLB()

        # Install a VM (we assume the pool has a shared SR)
        g = self.installVM()
        self.uninstallOnCleanup(g)

        # Configure recommendations
        recommendations = []
        if len(self.RECOMMENDATIONS) > 0:
            hosts = self.pool.getHosts()
            xenrt.TEC().logverbose("DEBUG - hosts: %s" % repr(hosts))
            if len(hosts) > self.MIN_POOL_SIZE:
                raise xenrt.XRTError("Pool too large for testcase (not enough "
                                     "recommendations provided)")
            for i in range(self.MIN_POOL_SIZE):            
                r = self.RECOMMENDATIONS[i]
                r['HostUuid'] = hosts[i].getMyHostUUID()
                recommendations.append(r)
        self.kirkwood.recommendations[g.getUUID()] = recommendations

        success = 0
        try:
            for i in range(self.LOOPS):
                xenrt.TEC().logdelimit("loop iteration %u..." % (i))
                if self.START:
                    # Start the VM
                    g.lifecycleOperation("vm-start", specifyOn=False)
                else:
                    # Resume it, so we need to suspend it first
                    g.start()
                    g.suspend()
                    g.lifecycleOperation("vm-resume", specifyOn=False)
    
                # Check Kirkwood was queried
                # Check the correct request was made
                self.checkRequest("VMGetRecommendations",
                                  {'PoolUuid':self.pool.getUUID(),
                                   'VmUuid':g.getUUID()})
    
                # Check it's where we expect it to be
                host = g.findHost()
                xenrt.TEC().logverbose("DEBUG - host: %r" % host)
                if type(self.EXPECT_ON) == types.ListType:
                    validHosts = []
                    validHostNames = []
                    for h in self.EXPECT_ON:
                        validHosts.append(hosts[h])
                        validHostNames.append(hosts[h].getName())
                    if not host in validHosts:
                        raise xenrt.XRTFailure("Guest did not start/resume "
                                               "where expected",
                                               data="Expected on %s, found on"
                                                    "%s" % (validHostNames,
                                                            host.getName()))
                elif type(self.EXPECT_ON) != types.NoneType and \
                     host != hosts[self.EXPECT_ON]:
                    raise xenrt.XRTFailure("Guest did not start/resume where "
                                           "expected", data="Expected on %s, "
                                                            "found on %s" %
                                               (hosts[self.EXPECT_ON].getName(),
                                                host.getName()))
                g.shutdown()
                success += 1
        finally:
            xenrt.TEC().comment("%u/%u iterations successful" %
                                (success,self.LOOPS))

    def installVM(self):
        if self.INSTALL_ON_LOCAL:
            sruuid = self.pool.master.getLocalSR()
        else:
            sruuid = self.pool.master.lookupDefaultSR()
        g = self.pool.master.createGenericLinuxGuest(sr=sruuid)
        g.shutdown()
        self.pool.master.genParamClear("vm", g.getUUID(), "affinity")
        return g

class TC8561(_KirkwoodVMStart):
    """Verify a simple VM start honours WLB recommendations"""
    MIN_POOL_SIZE = 3
    RECOMMENDATIONS = [{'CanBootVM':'true',
                        'RecommendationId':'1',
                        'Stars':'4.8'},
                       {'CanBootVM':'true',
                        'RecommendationId':'2',
                        'Stars':'4.5'},
                       {'CanBootVM':'true',
                        'RecommendationId':'3',
                        'Stars':'4.3'}]
    EXPECT_ON = 0
class TC8562(TC8561):
    """Verify a simple VM resume honours WLB recommendations"""
    START = False

class TC8564(_KirkwoodVMStart):
    """Verify a VM start falls back if WLB gives no valid hosts"""
    MIN_POOL_SIZE = 3
    RECOMMENDATIONS = [{'RecommendationId':'1',
                        'ZeroScoreReason':'XenRT'},
                       {'RecommendationId':'2',
                        'ZeroScoreReason':'XenRT'},
                       {'RecommendationId':'3',
                        'ZeroScoreReason':'XenRT'}]
    EXPECT_ON = None
class TC8565(TC8564):
    """Verify a VM resume falls back if WLB gives no valid hosts"""
    START = False

class TC8566(_KirkwoodVMStart):
    """Verify a VM start falls back if WLB gives no recommendations"""
    RECOMMENDATIONS = []
    EXPECT_ON = None
class TC8567(TC8566):
    """Verify a VM resume falls back if WLB gives no recommendations"""
    START = False

class TC8571(_KirkwoodVMStart):
    """Verify a VM start falls back if Kirkwood's first choice is invalid"""
    MIN_POOL_SIZE = 3
    INSTALL_ON_LOCAL=True
    # XXX: This is slightly iffy, it's relying on the fact the master is
    # the last host in the list - must have a pool of 3 hosts...
    RECOMMENDATIONS = [{'CanBootVM':'true',
                        'RecommendationId':'1',
                        'Stars':'3.2'},
                       {'CanBootVM':'true',
                        'RecommendationId':'2',
                        'Stars':'2.2'},
                       {'CanBootVM':'true',
                        'RecommendationId':'3',
                        'Stars':'1.2'}]
    EXPECT_ON = 2
class TC8572(TC8571):
    """Verify a VM resume falls back if Kirkwood's first choice is invalid"""
    START = False

class TC8573(_KirkwoodVMStart):
    """Verify a VM starts if WLB returns a tie"""
    MIN_POOL_SIZE = 3
    RECOMMENDATIONS = [{'CanBootVM':'true',
                        'RecommendationId':'1',
                        'Stars':'3.45'},
                       {'CanBootVM':'true',
                        'RecommendationId':'2',
                        'Stars':'3.45'},
                       {'CanBootVM':'true',
                        'RecommendationId':'3',
                        'Stars':'2.34'}]
    EXPECT_ON = [0,1]
class TC8574(TC8573):
    """Verify a VM resumes if WLB returns a tie"""
    START = False


class TC8563(_KirkwoodBase):
    """Verify Kirkwood is not queried if a host is specified"""
    MIN_POOL_SIZE = 2

    def run(self, arglist=None):

        # Install to a shared SR
        sruuid = self.pool.master.lookupDefaultSR()
        g = self.pool.master.createGenericLinuxGuest(sr=sruuid,start=False)
        self.uninstallOnCleanup(g)

        # start / resume by default specify a host, so we just use those...
        g.start()
        if len(self.kirkwood.getRequests()) > 0:
            raise xenrt.XRTFailure("Request made to WLB for VM start when "
                                   "host specified",
                                   data=str(self.kirkwood.getRequests()))

        g.suspend()
        g.resume()
        if len(self.kirkwood.getRequests()) > 0:
            raise xenrt.XRTFailure("Request made to WLB for VM resume when "
                                   "host specified",
                                   data=str(self.kirkwood.getRequests()))

class TC8568(_KirkwoodErrorBase):
    """Verify VM start falls back if there is a WLB error"""
    COMMAND_SHOULD_ERROR = False
    VM_REQUIRED = True

    def runCommand(self):
        if self.guest.getState() == "UP":
            self.guest.shutdown()
        elif self.guest.getState() == "SUSPENDED":
            self.guest.resume()
            self.guest.shutdown()
        self.guest.lifecycleOperation("vm-start", specifyOn=False)

    def extraChecks(self):
        # Verify the guest is running
        self.guest.findHost()
        self.guest.check()

class TC8569(TC8568):
    """Verify VM resume falls back if there is a WLB error"""

    def runCommand(self):
        if self.guest.getState() == "DOWN":
            self.guest.start()
            self.guest.suspend()
        elif self.guest.getState() == "UP":
            self.guest.suspend()
        self.guest.lifecycleOperation("vm-resume", specifyOn=False)

class TC8600(_KirkwoodBase):
    """Verify WLB XenAPI calls fail when WLB not initialised"""
    # Methods that should fail
    METHODS = [("host-retrieve-wlb-evacuate-recommendations", "host"),
               ("vm-retrieve-wlb-recommendations", "guest"),
               ("pool-deconfigure-wlb", ""),
               ("pool-retrieve-wlb-recommendations", ""),
               ("pool-retrieve-wlb-report", "report"),
               ("pool-retrieve-wlb-configuration", ""),
               ("pool-send-wlb-configuration", "config")]
    EXPECT_TEXT = "No WLB connection is configured"
    ERROR_TEXT = "not initialised"
    INITIALISE = False

    def run(self, arglist=None):
        if self.INITIALISE:
            self.initialiseWLB()
            self.pool.disableWLB()
        else:
            # Verify it's not configured
            if self.pool.getPoolParam("wlb-url") != "":
                raise xenrt.XRTError("WLB unxpectedly configured before start")
        
        # Verify WLB is disabled
        if self.pool.getPoolParam("wlb-enabled") != "false":
            raise xenrt.XRTError("WLB unexpectedly enabled before start")

        g = self.pool.master.createGenericEmptyGuest()
        self.uninstallOnCleanup(g)
        h = self.pool.getHosts()[0]

        cli = self.pool.getCLIInstance()

        wrongErrorText = []
        for m in self.METHODS:
            if m[1] == "guest":
                args = "uuid=%s" % (g.getUUID())
            elif m[1] == "host":
                args = "uuid=%s" % (h.getMyHostUUID())
            elif m[1] == "config":
                args = "config:test=abcd"
            elif m[1] == "report":
                args = "report=test filename=/tmp/ignore"
            else:
                args = ""

            allowed = False
            try:
                self.pool.master.execdom0('rm -vf /tmp/ignore')
                cli.execute(m[0], args)
                allowed = True
            except xenrt.XRTFailure, e:
                if not self.EXPECT_TEXT in str(e):
                    wrongErrorText.append(m[0])

            if allowed:
                raise xenrt.XRTFailure("WLB method %s allowed when WLB %s" %
                                       (m, self.ERROR_TEXT))        

        if len(wrongErrorText) > 0:
            raise xenrt.XRTFailure("WLB methods %s failed with wrong text when "
                                   "WLB %s" % (wrongErrorText, self.ERROR_TEXT))

class TC8601(TC8600):
    """Verify WLB XenAPI calls fail when WLB disabled"""
    METHODS = [("host-retrieve-wlb-evacuate-recommendations", "host"),
               ("vm-retrieve-wlb-recommendations", "guest"),
               ("pool-retrieve-wlb-recommendations", "")]
    EXPECT_TEXT = "pool has wlb-enabled set to false"
    ERROR_TEXT = "disabled"
    INITIALISE = True


class _HostEvacuateRecBase(_KirkwoodBase):
    """Base class for host-retrieve-wlb-evacuate-recommendations testcases"""
    FORCE_FAKEKIRKWOOD = True
    EXPECT_FAIL = False
    USE_LOCAL_SR = False
    VM_OFF_HOST = False
    RECOMMEND_MIGRATE_TO_HOST = False

    def run(self, arglist=None):
        if self.EXPECT_FAIL:
            # No point testing this yet, as it might not be relevant
            raise xenrt.XRTFailure("Waiting on CA-26101")

        self.initialiseWLB()

        # Set up VMs
        sruuid = self.pool.master.lookupDefaultSR()
        if self.USE_LOCAL_SR:
            sruuid = self.pool.master.getLocalSR()

        xenrt.TEC().logverbose("SRUUID %r" % sruuid)

        g1 = self.pool.master.createGenericLinuxGuest(sr=sruuid)
        self.uninstallOnCleanup(g1)
        if self.VM_OFF_HOST:
            g2 = self.pool.getSlaves()[0].createGenericLinuxGuest(sr=sruuid)
        else:
            g2 = self.pool.master.createGenericLinuxGuest(sr=sruuid)
        self.uninstallOnCleanup(g2)

        # Build the recommendations
        if self.RECOMMEND_MIGRATE_TO_HOST:
            hUUID = self.pool.master.getMyHostUUID()
        else:
            hUUID = self.pool.getSlaves()[0].getMyHostUUID()

        hostRecommendations = [{'HostUuid':hUUID,
                                'RecommendationId':'1',
                                'VmUuid':g1.getUUID()},
                               {'HostUuid':hUUID,
                                'RecommendationId':'2',
                                'VmUuid':g2.getUUID()}]
        expectedRecs = {g1.getUUID():hUUID, g2.getUUID():hUUID}

        # Note the True is for the 'CanPlaceAllVMs' field, which xapi ignores...
        self.kirkwood.hostRecommendations[self.pool.master.getMyHostUUID()] = \
            (True, hostRecommendations)

        # Get the recommendations, and check the match what we expect
        try:
            recs = self.pool.master.retrieveWLBEvacuateRecommendations()
        except xenrt.XRTFailure, e:
            if self.EXPECT_FAIL:
                # XXX: Check the error message
                return
            else:
                raise e

        if self.EXPECT_FAIL:
            raise xenrt.XRTFailure("Retrieved recommendations while expecting "
                                   "a failure")

        parsedRecs = {}
        for r in recs:
            guuid = r.split()[0].strip()
            huuid = recs[r].split()[1].strip()
            parsedRecs[guuid] = huuid
        if parsedRecs != expectedRecs:
            raise xenrt.XRTFailure("Retrieved recommendations not as expected",
                                   data="Expecting %s, found %s" %
                                        (expectedRecs, parsedRecs))            

class TC8623(_HostEvacuateRecBase):
    """Verify host evacuate recommendations with valid recommendations"""
    pass
class TC8624(_HostEvacuateRecBase):
    """Verify host evacuate recommendations with a recommendation to migrate a
       VM to the host itself"""
    #EXPECT_FAIL = True #CA-26101 won't fix
    RECOMMEND_MIGRATE_TO_HOST = False
class TC8625(_HostEvacuateRecBase):
    """Verify host evacuate recommendations with a recommendation to migrate a
       VM that's not resident on the host"""
    #EXPECT_FAIL = True #CA-26101 won't fix
    VM_OFF_HOST = False
class TC8626(_HostEvacuateRecBase):
    """Verify host evacuate recommendations with a recommendation to migrate a
       non agile VM"""
    #EXPECT_FAIL = True #CA-26101 won't fix
    USE_LOCAL_SR = False

class TC8627(_KirkwoodErrorBase):
    """Verify that Xapi handles errors from Kirkwood when retrieving host
       evacuate recommendations"""

    def runCommand(self):
        self.pool.master.retrieveWLBEvacuateRecommendations()

class _HostEvacuateBase(_KirkwoodBase):
    """Base class for host-evacuate testcases"""
    FORCE_FAKEKIRKWOOD = True
    EXPECT_ERROR = False # Do we expect the evacuate call to error out
    OBEY_WLB = True # Do we expect it to obey the WLB recommendations
    USE_LOCAL_SR = False # Install one of the VMs to a local SR?
    VALID_RECS = True # Whether to send valid recommendations

    def run(self, arglist=None):
        self.initialiseWLB()

        # Set up 3 VMs running on the master, 2 on shared storage, 1 optionally
        # on local...
        sruuid = self.pool.master.lookupDefaultSR() 
        g1 = self.pool.master.createGenericLinuxGuest(sr=sruuid)
        self.uninstallOnCleanup(g1)
        g1.preCloneTailor()
        g1.shutdown()
        g2 = g1.cloneVM()
        self.uninstallOnCleanup(g2)
        if self.USE_LOCAL_SR:
            sruuid = self.pool.master.getLocalSR()
            g3 = g1.copyVM(sruuid=sruuid)
        else:
            g3 = g1.cloneVM()
        self.uninstallOnCleanup(g3)
        g1.start()
        g2.start()
        g3.start()

        # Configure the host evacuate recommendations for these VMs
        recs = []
        expect = {}
        if self.VALID_RECS:
            # Recommend migrating to alternate slaves
            slaves = self.pool.getSlaves()
            recs.append({'RecommendationId':'1',
                         'HostUuid':slaves[0].getMyHostUUID(),
                         'VmUuid':g1.getUUID()})
            expect[g1] = slaves[0]
            recs.append({'RecommendationId':'2',
                         'HostUuid':slaves[1 % len(slaves)].getMyHostUUID(),
                         'VmUuid':g2.getUUID()})
            expect[g2] = slaves[1 % len(slaves)]
            recs.append({'RecommendationId':'3',
                         'HostUuid':slaves[2 % len(slaves)].getMyHostUUID(),
                         'VmUuid':g3.getUUID()})
            expect[g3] = slaves[2 % len(slaves)]
        else:
            # Recommend all VMs move to the master (where they are already)
            master = self.pool.master
            recs.append({'RecommendationId':'1',
                         'HostUuid':master.getMyHostUUID(),
                         'VmUuid':g1.getUUID()})
            expect[g1] = master
            recs.append({'RecommendationId':'2',
                         'HostUuid':master.getMyHostUUID(),
                         'VmUuid':g2.getUUID()})
            expect[g2] = master
            recs.append({'RecommendationId':'3',
                         'HostUuid':master.getMyHostUUID(),
                         'VmUuid':g3.getUUID()})
            expect[g3] = master
        self.kirkwood.hostRecommendations[self.pool.master.getMyHostUUID()] = \
            (True, recs)

        # Now try the command
        allowed = False
        try:
            self.pool.master.evacuate()
            allowed = True
        except xenrt.XRTFailure, e:
            if self.EXPECT_ERROR:
                pass
            else:
                raise e

        if self.EXPECT_ERROR:
            if allowed:
                raise xenrt.XRTFailure("host-evacuate unexpectedly allowed")
            # Check that none of the VMs have migrated
            movedGuests = {}
            if g1.findHost() != self.pool.master:
                movedGuests[g1] = g1.getHost()
            if g2.findHost() != self.pool.master:
                movedGuests[g2] = g2.getHost()
            if g3.findHost() != self.pool.master:
                movedGuests[g3] = g3.getHost()

            if len(movedGuests.keys()) > 0:
                err = ""
                for g in movedGuests:
                    err += "%s now on %s" % (g.getName(), movedGuests[g].getName())
                raise xenrt.XRTFailure("Guests unexpectedly migrated after "
                                       "failed evacuate call", data=err)
        else:
            # Check a query was made to Kirkwood
            self.checkRequest("HostGetRecommendations",
                              {'HostUuid':self.pool.master.getMyHostUUID(),
                               'PoolUuid':self.pool.getUUID()})

            # It worked, so let's see where they moved to...
            if self.OBEY_WLB:
                # We expect it to have obeyed WLB
                wrongCount = 0
                if g1.findHost() != expect[g1]:
                    wrongCount += 1
                if g2.findHost() != expect[g2]:
                    wrongCount += 1
                if g3.findHost() != expect[g3]:
                    wrongCount += 1
                if wrongCount > 0:
                    raise xenrt.XRTFailure("Evacuate did not obey WLB "
                                           "recommendations",
                                           data="%d/3 guests in wrong place" %
                                                (wrongCount))
            else:
                # Won't have obeyed WLB, so just check they've evacuated
                wrongCount = 0
                if g1.findHost() == self.pool.master:
                    wrongCount += 1
                if g2.findHost() == self.pool.master:
                    wrongCount += 1
                if g3.findHost() == self.pool.master:
                    wrongCount += 1
                if wrongCount > 0:
                    raise xenrt.XRTFailure("Evacuate expected to disobey WLB "
                                           "reccomendations left guests on "
                                           "host", data="%d/3 guests left" %
                                                        (wrongCount))

    def postRun(self):
        try:
            if self.pool and self.pool.master:
                self.pool.master.enable()
        except:
            pass
        _KirkwoodBase.postRun(self)

class TC8702(_HostEvacuateBase):
    """Verify host-evacuate obeys valid WLB recommendations"""
    pass

class TC8703(_HostEvacuateBase):
    """Verify host-evacuate errors with VM on local storage"""
    EXPECT_ERROR = True
    USE_LOCAL_SR = True

class TC8704(_HostEvacuateBase):
    """Verify host-evacuate succeeds with invalid WLB recommendations"""
    OBEY_WLB = False
    VALID_RECS = False


class TC8705(_KirkwoodErrorBase):
    """Verify host-evacuate falls back if there is a WLB error"""
    COMMAND_SHOULD_ERROR = False
    VM_REQUIRED = True

    def __init__(self, tcid=None):
        self.sourceHost = None
        _KirkwoodErrorBase.__init__(self, tcid=tcid)

    def runCommand(self):
        if self.guest.getState() == "DOWN":
            self.guest.start()
        elif self.guest.getState() == "SUSPENDED":
            self.guest.resume()
        self.sourceHost = self.guest.host
        self.guest.host.evacuate()

    def extraChecks(self):
        # Check the sourceHost is empty
        if len(self.sourceHost.listGuests(running=True)) > 0:
            raise xenrt.XRTFailure("host-evacuate failed to evacuate host")

        # Verify the guest is running
        self.guest.findHost()
        self.guest.check()

        # Re-enable the host
        self.sourceHost.enable()

    def postRun(self):
        try:
            if self.sourceHost:
                self.sourceHost.enable()
        except:
            pass
        _KirkwoodErrorBase.postRun(self)


class _PoolRecommendationBase(_KirkwoodBase):
    """Base class for pool-retrieve-wlb-recommendations testcases"""
    FORCE_FAKEKIRKWOOD = True
    EXPECT_FAIL = False
    RECOMMEND_MIGRATE_TO_OFFLINE = False
    RECOMMEND_MIGRATE_TO_HOST = False
    USE_LOCAL_SR = False

    def run(self, arglist=None):
        if self.EXPECT_FAIL:
            # No point testing this yet, as it might not be relevant
            raise xenrt.XRTFailure("Waiting on CA-26101")

        self.initialiseWLB()

        # Set up VMs
        sruuid1 = self.pool.master.lookupDefaultSR()
        sruuid2 = sruuid1
        slave = self.pool.getSlaves()[0]
        if self.USE_LOCAL_SR:
            sruuid1 = self.pool.master.getLocalSR()
            sruuid2 = slave.getLocalSR()
        g1 = self.pool.master.createGenericLinuxGuest(sr=sruuid1)
        self.uninstallOnCleanup(g1)
        g2 = slave.createGenericLinuxGuest(sr=sruuid2)
        self.uninstallOnCleanup(g2)

        # Build the recommendations
        if self.RECOMMEND_MIGRATE_TO_HOST:
            hUUID1 = self.pool.master.getMyHostUUID()
            hUUID2 = self.pool.getSlaves()[0].getMyHostUUID()
        else:
            hUUID1 = self.pool.getSlaves()[0].getMyHostUUID()
            hUUID2 = self.pool.master.getMyHostUUID()

        poolRecommendations = [{'MoveToHostUuid':hUUID1,
                                'RecommendationId':'1',
                                'VmToMoveUuid':g1.getUUID(),
                                'Reason':'XenRT'},
                               {'MoveToHostUuid':hUUID2,
                                'RecommendationId':'2',
                                'VmToMoveUuid':g2.getUUID(),
                                'Reason':'XenRT'}]
        expectedRecs = {g1.getUUID():hUUID1, g2.getUUID():hUUID2}

        self.kirkwood.optimizations = (1, poolRecommendations, "Medium")

        if self.RECOMMEND_MIGRATE_TO_OFFLINE:
            # Shut down the slave
            self.pool.getSlaves()[0].shutdown()

        # Get the recommendations, and check the match what we expect
        try:
            recs = self.pool.retrieveWLBRecommendations()
        except xenrt.XRTFailure, e:
            if self.EXPECT_FAIL:
                # XXX: Check the error message
                return
            else:
                raise e

        if self.EXPECT_FAIL:
            raise xenrt.XRTFailure("Retrieved recommendations while expecting "
                                   "a failure")

        parsedRecs = {}
        for r in recs:
            guuid = r.split()[0].strip()
            huuid = recs[r].split()[1].strip()
            parsedRecs[guuid] = huuid
        if parsedRecs != expectedRecs:
            raise xenrt.XRTFailure("Retrieved recommendations not as expected",
                                   data="Expecting %s, found %s" %
                                        (expectedRecs, parsedRecs))

    def postRun(self):
        if self.RECOMMEND_MIGRATE_TO_OFFLINE:
            h = self.pool.getSlaves()[0]
            try:
                h.checkReachable(10)
            except:
                xenrt.TEC().logverbose("Attempting to boot up offline host")
                h.powerctl.cycle()
                h.waitForSSH(600, desc="Boot up of shutdown host")
        _KirkwoodBase.postRun(self)

class TC8629(_PoolRecommendationBase):
    """Verify pool recommendations with valid recommendations"""
    pass
class TC8631(_PoolRecommendationBase):
    """Verify pool recommendations with a recommendation to migrate a VM to an
       offline / unavailable host"""
    #EXPECT_FAIL = True #CA-26101 won't fix
    RECOMMEND_MIGRATE_TO_OFFLINE = True
class TC8632(_PoolRecommendationBase):
    """Verify pool recommendations with a recommendation to migrate a VM to a
       host it's already resident on"""
    #EXPECT_FAIL = True #CA-26101 won't fix
    RECOMMEND_MIGRATE_TO_HOST = True
class TC8634(_PoolRecommendationBase):
    """Verify pool recommendations with a recommendation to migrate a non agile
       VM"""
    #EXPECT_FAIL = True #CA-26101 won't fix
    USE_LOCAL_SR = True

class TC8633(_KirkwoodErrorBase):
    """Verify that Xapi handles errors from Kirkwood when retrieving pool
       optimization recommendations"""

    def runCommand(self):
        self.pool.retrieveWLBRecommendations()


class TC8635(_KirkwoodBase):
    """Verify the WLB reports functionality"""
    FORCE_FAKEKIRKWOOD = True

    def run(self, arglist=None):

        self.initialiseWLB()

        # Sort out the data we want to return
        # In real life this would be XML, but since no parsing is done by
        # xapi, we can use our own custom text to verify that xapi is correctly
        # de-escaping the data in the SOAP xml response
        data = """<> & ;
&gt;&lt;
"$%^&*()-_+=#!/\\@'[]{}"""
        self.kirkwood.reportXML = data
        xenrt.TEC().logverbose("Sample report: %s" % (data))

        # Request a report with no parameters
        report = self.pool.retrieveWLBReport("testreport1")
        if report.strip() != data.strip():
            raise xenrt.XRTFailure("Received report not as expected",
                                   data="No params")
        # Check the correct call was made
        self.checkRequest("ExecuteReport", {'ReportName':'testreport1',
                                            'ReportParms': {}})        

        # Request a report with difficult parameters
        paramsToSend = {'field1':'abcdefg',
                        'field2':'1234567',
                        '<awkward':'>field',
                        'others':'\\/!"$%^*()-_+[]{}#~@;:?<>,."\'',
                        'long':'fieeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeld'}
        report = self.pool.retrieveWLBReport("testreport2", params=paramsToSend)
        if report.strip() != data.strip():
            raise xenrt.XRTFailure("Received report not as expected",
                                   data="With params")
        # CHeck the correct call was made
        self.checkRequest("ExecuteReport", {'ReportName':'testreport2',
                                            'ReportParms': paramsToSend}) 

        # Make the report very long (to check there are no issues with length)
        # and verify the file output
        self.kirkwood.reportXML = ""
        for i in range(32000):
            self.kirkwood.reportXML += data
        fname = xenrt.TEC().tempFile()
        # CLI will complain if file already exists
        os.unlink(fname)
        report = self.pool.retrieveWLBReport("testreportlong", filename=fname)

        f = file(fname, "r")
        data2 = f.read()
        f.close()
        if self.kirkwood.reportXML.strip() != data2.strip():
            # Copy the received data to the logdir
            xenrt.TEC().copyToLogDir(fname, "testreportlong")
            raise xenrt.XRTFailure("Received report not as expected",
                                   data="Long report")


class TC21682(_KirkwoodBase):
    """Verify the WLB reports functionality"""
    FORCE_FAKEKIRKWOOD = True

    def run(self, arglist=None):
        self.initialiseWLB()
        cli = self.pool.getCLIInstance()
        pool_uuid = self.pool.getUUID()
        filename = os.path.join(xenrt.TEC().tempDir(), "TC21682.xml")
        argument = "report=pool_audit_history LocaleCode=en Start=-6 End=0 PoolID=%s ReportVersion=Creedence AuditUser=ALL AuditObject=ALL StartLine=1 EndLine=10000 UTCOffset=480 filename=%s" % (pool_uuid, filename)
        for i in xrange(100):
            if os.path.isfile(filename):
                os.remove(filename)
            time.sleep(2)
            data = cli.execute("pool-retrieve-wlb-report", argument)
            if 'succeeded' not in data.lower():
                raise xenrt.XRTFailure("execute %d pool-retrieve-wlb-report %s return %r" % (i+1, argument, data))



class TC8669(_KirkwoodErrorBase):
    """Verify that Xapi handles errors from Kirkwood when retrieving reports"""

    def configureError(self, error):
        # We have to update the timeout, since the report timeout is by default
        # 10 minutes (CA-37331)
        if error == "Timeout":
            self.pool.paramSet("other-config:wlb_reports_timeout", 30)

        _KirkwoodErrorBase.configureError(self, error)

    def runCommand(self):
        self.pool.retrieveWLBReport("TC8669")

class _KirkwoodSmoketest(_KirkwoodBase):
    """Base class for Kirkwood Smoketests"""
    FORCE_FAKEKIRKWOOD = True
    # Number of hosts to use
    HOSTS = 2
    # Number of VMs to use
    GUESTS = 6

    def run(self, arglist=None):
        # Initialise Kirkwood
        self.initialiseWLB()

        # Install some VMs
        sruuid = self.pool.master.lookupDefaultSR()
        templateGuest = self.pool.master.createGenericLinuxGuest(sr=sruuid)
        templateGuest.preCloneTailor()
        templateGuest.shutdown()
        self.uninstallOnCleanup(templateGuest)

        self.guests = []
        hosts = self.pool.getHosts()
        for i in range(self.GUESTS):
            h = hosts[i % self.HOSTS]
            g = templateGuest.cloneVM()
            g.host = h
            self.uninstallOnCleanup(g)
            self.guests.append(g)

        # Start them (with random recommendations)
        if self.runSubcase("sequential", (False), "Sequential", "Start") != xenrt.RESULT_PASS:
            return

        # Suspend them all
        for g in self.guests:
            g.suspend()

        # Resume them (with random recommendations)
        if self.runSubcase("sequential", (True), "Sequential", "Resume") != xenrt.RESULT_PASS:
            return

        # Shut them all down
        for g in self.guests:
            g.shutdown()

        # Attempt a parallel start of all the VMs
        if self.runSubcase("parallel", (False), "Parallel", "Start") != xenrt.RESULT_PASS:
            return

        # Suspend them all
        for g in self.guests:
            g.suspend()

        # Attempt a parallel resume of all the VMs
        if self.runSubcase("parallel", (True), "Parallel", "Resume") != xenrt.RESULT_PASS:
            return

    def makeRandomRecs(self):
        # For each guest, generate a random set of recommendations
        hosts = self.pool.getHosts()
        rID = 1
        for g in self.guests:
            xenrt.TEC().logverbose("Generating recommendations for %s" %
                                   (g.getName()))
            recs = []
            canBoot = False
            for h in hosts:
                # Randomly decide whether the VM can boot here
                cb = random.randint(0,100)
                if cb > 20:
                    # It can boot here
                    canBoot = True
                    # Decide on stars to use
                    stars = random.random() * 5
                    r = {'HostUuid': h.getMyHostUUID(), 'RecommendationId': rID,
                         'CanBootVM': 'true', 'Stars': str(stars)}
                else:
                    # It can't boot here
                    r = {'HostUuid': h.getMyHostUUID(), 'RecommendationId': rID,
                         'ZeroScoreReason': 'XenRT'}
                recs.append(r)
                rID += 1
            if not canBoot:
                # It has to boot somewhere - tweak a random recommendation
                toBootOn = random.randrange(len(hosts))
                r = recs[toBootOn]
                del(r['ZeroScoreReason'])
                r['CanBootVM'] = 'true'
                r['Stars'] = '3.141'
            # Determine where we expect it to boot
            top = None
            topScore = 0.0
            for r in recs:
                if r.has_key('Stars'):
                    if float(r['Stars']) > topScore:
                        top = r['HostUuid']
                        topScore = float(r['Stars'])
            # We have a UUID - now find which host it is
            for h in hosts:
                if h.getMyHostUUID() == top:
                    g.host = h
                    xenrt.TEC().logverbose("Expect to start on %s" % (h.getName()))
                    break
            xenrt.TEC().logverbose("Recommendations: %s" % (recs))
            self.kirkwood.recommendations[g.getUUID()] = recs
                
    def sequential(self, resume):
        # Generate random recommendations
        self.makeRandomRecs()

        # Perform the op on the VMs one by one
        for g in self.guests:
            if resume:
                g.lifecycleOperation("vm-resume", specifyOn=False)
            else:
                g.start(specifyOn=False)

        # Check them all
        for g in self.guests:
            g.check()

    def parallel(self, resume):
        # Generate random recommendations
        self.makeRandomRecs()

        c = copy.copy(self.guests)
        xenrt.lib.xenserver.startMulti(c,
                                       resume=resume,
                                       no_on=True)
        fail = 0
        for g in self.guests:
            if not g in c:
                fail += 1
        if fail > 0:
            raise xenrt.XRTFailure("%d guests failed to start/resume" % (fail))

        # Check them all
        for g in self.guests:
            g.check()

class TC8639(_KirkwoodSmoketest):
    """Test Kirkwood integration with 25s delay on the Kirkwood end"""
    HOSTS = 3
    GUESTS = 15

    def prepare(self, arglist):
        _KirkwoodSmoketest.prepare(self, arglist)
        self.kirkwood.delayReply = 25

class TC8643(_KirkwoodBase):
    """Verify that a failed pool-wlb-initialise call doesn't overwrite existing
       data"""

    def run(self, arglist=None):
        self.initialiseWLB()

        # Now try and initialise with invalid details (in a variety of ways),
        # each time checking that WLB remains configured as expected

        # Invalid URL
        self.tryInitialise("invalidurl:1234")

        # For the remaining tests, set up a second fake Kirkwood instance
        ip = xenrt.TEC().lookup("XENRT_SERVER_ADDRESS")
        # We use a port in the range 30000-40000, randomly chosen
        tries = 0
        fk2 = None
        while not fk2:
            port = random.randint(30000,40000)
            xenrt.TEC().logverbose("Trying to use port %d" % (port))
            try:
                fk2 = xenrt.lib.FakeKirkwood(ip, port)
            except socket.error, e:
                if e[0] == 98: # Address already in use - try again
                    xenrt.TEC().logverbose("Port appears to be in use")
                    fk2 = None
                else:
                    raise e
            tries += 1
            if tries > 5:
                raise xenrt.XRTError("Couldn't find an available port "
                                     "after 5 attempts")
        fk2.start()

        # Fake Kirkwood returns garbage
        fk2.returnSpecial = "ajklasdkljasldjaskdlajl"
        self.tryInitialise("%s:%s" % (ip, port))
        fk2.returnError = None

        # Fake Kirkwood returns access denied
        fk2.returnForbidden = True
        self.tryInitialise("%s:%s" % (ip, port))
        fk2.returnForbidden = False

        # Fake Kirkwood returns nothing
        fk2.returnNone = True
        self.tryInitialise("%s:%s" % (ip, port))
        fk2.returnNone = False

        # Fake Kirkwood times out
        fk2.delayReply = 45
        self.tryInitialise("%s:%s" % (ip, port))
        fk2.delayReply = None

        # Fake Kirkwood returns an error
        fk2.returnError = "InvalidParameter"
        self.tryInitialise("%s:%s" % (ip, port))
        fk2.returnError = None

        fk2.shutdown()

    def tryInitialise(self, url):        
        allowed = False
        try:
            self.pool.initialiseWLB(url, "wlbuser", "wlbpass",
                                    updateMetadata=False, check=False)
            allowed = True
        except:
            pass
        if allowed:
            raise xenrt.XRTError("Unexpectedly able to initialise WLB with bad "
                                 "data")
        self.pool.checkWLB()
        
class TC8982(xenrt.TestCase):
    """Smoketest XenServer WLB with the Kirkwood or later WLB service."""

    WLBSERVER = "KIRKWOOD"
    WLBUSERNAME = "kirkwood"
    WLBPASSWORD = "kirkwood"
    WLBPORT = 8012

    def prepare(self, arglist):
        self.pool = self.getDefaultPool()
        
        self.usevpxwlb = xenrt.TEC().lookup("USE_VPXWLB",False,boolean=True)
        if self.usevpxwlb:
            xenrt.TEC().logverbose("Using VPXWLB")
            self.vpx_os_version = xenrt.TEC().lookup("VPX_OS_VERSION", "CentOS5")
            self.wlbserver = xenrt.WlbApplianceFactory().create(g, self.vpx_os_version)
            self.WLBSERVER = _KirkwoodBase.WLBSERVER
            self.WLBUSERNAME = self.wlbappsrv.wlb_username #"wlbuser"
            self.WLBPASSWORD = self.wlbappsrv.wlb_password # default password
            # Look up if a VM named "VPXWLB" is installed and running the
            # Kirkwood service
            self.kwserver = self.getGuest(self.WLBSERVER)
            if not self.kwserver:
                raise xenrt.XRTError("Instructed to use VPXWLB but VPXWLB VM not available in pool")
        else:
            # Assumes we have a VM named "KIRKWOOD" installed and running the
            # Kirkwood service
            self.kwserver = self.getGuest(self.WLBSERVER)

    def initWLB(self):
        self.pool.initialiseWLB("%s:%u" % (self.kwserver.getIP(), self.WLBPORT),
                                self.WLBUSERNAME,
                                self.WLBPASSWORD)

    def checkWLB(self):
        self.pool.checkWLB()

    def retrWLB(self, n):
        if n == 1:
            self.pool.retrieveWLBConfig()
        elif n == 2:
            self.pool.retrieveWLBRecommendations()
        elif n == 3:
            self.pool.retrieveWLBDiagnostics()

    def disableWLB(self):
        self.pool.disableWLB()
        
    def enableWLB(self):
        self.pool.disableWLB()

    def deinitWLB(self):
        self.pool.deconfigureWLB()

    def run(self, arglist):
        if self.runSubcase("initWLB", (), "Init", "WLB") \
               != xenrt.RESULT_PASS:
            return
        if self.runSubcase("checkWLB", (), "Init", "Check") \
               != xenrt.RESULT_PASS:
            return
        if self.runSubcase("retrWLB", (1), "Init", "GetConf") \
               != xenrt.RESULT_PASS:
            return
        if self.runSubcase("retrWLB", (2), "Init", "GetRec") \
               != xenrt.RESULT_PASS:
            return
        if self.runSubcase("retrWLB", (3), "Init", "GetLog") \
               != xenrt.RESULT_PASS:
            return
        if self.runSubcase("disableWLB", (), "Disable", "WLB") \
               != xenrt.RESULT_PASS:
            return
        if self.runSubcase("enableWLB", (), "Enable", "WLB") \
               != xenrt.RESULT_PASS:
            return
        if self.runSubcase("deinitWLB", (), "DeConf", "WLB") \
               != xenrt.RESULT_PASS:
            return

    def postRun(self):
        if self.pool:
            if self.pool.wlbEnabled:
                self.pool.deconfigureWLB()

class TC9041(xenrt.TestCase):
    """Regression test for CA-28039"""

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.guest = self.host.createGenericEmptyGuest()
        self.uninstallOnCleanup(self.guest)

        # Configure guest with more memory than the host could possibly have (1TB)
        self.guest.memset(1048576)

    def run(self, arglist=None):
        # Get the current list of messages
        beforeCount = len(self.host.minimalList("message-list"))

        # Try and start the VM
        allowed = False
        try:
            self.guest.start()
            allowed = True
        except:
            pass
        if allowed:
            raise xenrt.XRTError("Allowed to start guest with 1TB of memory")

        # Check for any new messages
        afterCount = len(self.host.minimalList("message-list"))
        if afterCount > beforeCount:
            raise xenrt.XRTFailure("CA-28039 Alert generated when trying to "
                                   "start VM with more memory than available "
                                   "on host")
 
class _VPXWLB(_KirkwoodBase):
    """Base class for VM recommendation testcases for VPXWLB"""
    def installVM(self):
        return self.pool.master.createGenericEmptyGuest()

    def initialiseWLB(self):
        _KirkwoodBase.initialiseWLB(self)
        xenrt.TEC().logverbose("Waiting for VPXWLB server to settle and collect pool data...")
        time.sleep(300) #CA-55553
 

class TC13479(_VPXWLB):
    """Test a single positive recommendation"""
   
    def hostVMScores(self, recs):
        return dict(map(lambda x:(x,recs[x].split(" ")[1]), recs))

    def cmpVMScores(self, vms1, vms2, host, op, silentdiff=False, silentmatch=False):
        hvms1 = self.hostVMScores(vms1)
        hvms2 = self.hostVMScores(vms2)
        for h in self.pool.getHosts():
            if h != host:
                if hvms1[h.getName()] != hvms2[h.getName()]:
                    if silentdiff:
                        xenrt.TEC().logverbose("Returning DIFFERENT.")
                        return h.getName()
                    else:
                        raise xenrt.XRTFailure("Recommendation %s for %s is different from %s" %
                            (hvms1,h.getName(),hvms2))
            else:
                hvms1f = float(hvms1[h.getName()])
                hvms2f = float(hvms2[h.getName()])
                if not op(hvms1f,hvms2f):
                    if silentmatch:
                        xenrt.TEC().logverbose("Returning DID NOT MATCH.")
                        return h.getName()
                    else:
                        raise xenrt.XRTFailure("Recommendation %s for %s did not match expected change from %s" %
                            (hvms1,h.getName(),hvms2))
        return None
        
    def fromScoreToStar(self, score, raw=True):
        """Convert a star rating to actual number of stars
            score - actual score (example, 4.9920382165605091)
            raw - if True, then format of score looks like "WLB 4.9920382165605091 5" or like this "WLB 5 2".
        """
        if None == score:
            return 0.0
        if raw:
            m = re.search("""WLB (\d\.\d\d\d\d)""", score, re.IGNORECASE)
            if None == m:
                m = re.search("""WLB (\d)""", score, re.IGNORECASE)
                if None == m:
                    return 0.0
                score = float(m.group(1))
            else:
                score = float(m.group(1))
        if score < 0 or score > 5:
            # out of range
            return 0.0
        if score >= 4.75 and score <= 5.0:
            return 5.0
        if score >= 4.25 and score < 4.75:
            return 4.5
        if score >= 3.75 and score < 4.25:
            return 4.0
        if score >= 3.25 and score < 3.75:
            return 3.5
        if score >= 2.75 and score < 3.25:
            return 3.0
        if score >= 2.25 and score < 2.75:
            return 2.5
        if score >= 1.75 and score < 2.25:
            return 2.0
        if score >= 1.25 and score < 1.75:
            return 1.5
        if score >= 0.75 and score < 1.25:
            return 1.0
        if score > 0 and score < 0.75:
            return 0.5
        if 0 == score:
            return 0.0
        return 0.0

    def getHostNameMaster(self):
        """get name of master host"""
        self.pool = self.getDefaultPool()
        hosts = self.pool.getHosts()
        if None == hosts:
            xenrt.TEC().logverbose("Error finding hosts.")
            return None
        host_master = self.pool._getPoolMaster(hosts[0])
        if None == host_master:
            xenrt.TEC().logverbose("Error finding master host. None==host.")
            return None
        hostname = host_master.getName()
        if hostname:
            return hostname
        xenrt.TEC().logverbose("Error finding master host name. None==host.")
        return None

    def run(self, arglist=None):
        threshold_stars = 0.5
        hostname_master = self.getHostNameMaster()
        xenrt.TEC().logverbose("hostname_master = [%s]." % hostname_master)
        hosts = self.pool.getHosts()
        # Initialise WLB
        self.initialiseWLB()
        # Install a VM on host0
        g1 = hosts[0].createGenericLinuxGuest(vcpus=1,memory=256)
        self.uninstallOnCleanup(g1)
        g1.shutdown()
        t = 120
        xenrt.TEC().logverbose("Sleeping for %u seconds..." % (t))
        time.sleep(t)
        g1_recs = g1.retrieveWLBRecommendations()
        xenrt.TEC().logverbose("g1=[%s]" % g1_recs)

        # Install a VM2 on host0
        g2 = hosts[0].createGenericLinuxGuest(vcpus=1,memory=256)
        self.uninstallOnCleanup(g2)
        g2.shutdown()
        t = 120
        xenrt.TEC().logverbose("Sleeping for %u seconds..." % (t))
        time.sleep(t)
        g1b_recs = g1.retrieveWLBRecommendations()
        xenrt.TEC().logverbose("g1b=[%s]" % g1b_recs)
        hostname = self.cmpVMScores(g1_recs,g1b_recs,hosts[0],(lambda x,y:x==y), silentdiff=True, silentmatch=True)
        if hostname:
            stars_before = self.fromScoreToStar(g1_recs[hostname])
            stars_now    = self.fromScoreToStar(g1b_recs[hostname])
            diff = float(stars_before - stars_now)
            if stars_now > stars_before:
                diff = float(stars_now - stars_before)
            xenrt.TEC().logverbose("Star diff for host [%s] is [%3.2f]." % (hostname, diff))
            if diff >= threshold_stars:
                xenrt.TEC().logverbose("Diff outside range for host. Diff is greater than or equal to half star.")
                hvms1 = self.hostVMScores(g1_recs)
                hvms2 = self.hostVMScores(g1b_recs)
                raise xenrt.XRTFailure("Diff outside range. Recommendation %s for %s did not match expected change from %s" % (hvms1,hostname,hvms2))

        g2.host = hosts[0]
        self.uninstallOnCleanup(g2)
        t = 10
        xenrt.TEC().logverbose("Sleeping for %u seconds..." % (t))
        time.sleep(t)
        g2_recs = g2.retrieveWLBRecommendations()
        xenrt.TEC().logverbose("g2=[%s]" % g2_recs)
        hostname = self.cmpVMScores(g1b_recs,g2_recs,hosts[0],(lambda x,y:x==y), silentdiff=True, silentmatch=True)
        if hostname:
            stars_before = self.fromScoreToStar(g1b_recs[hostname])
            stars_now    = self.fromScoreToStar(g2_recs[hostname])
            diff = float(stars_before - stars_now)
            if stars_now > stars_before:
                diff = float(stars_now - stars_before)
            xenrt.TEC().logverbose("Star diff for host [%s] is [%3.2f]." % (hostname, diff))
            if diff >= threshold_stars:
                xenrt.TEC().logverbose("Diff outside range for host. Diff is greater than or equal to half star.")
                hvms1 = self.hostVMScores(g1b_recs)
                hvms2 = self.hostVMScores(g2_recs)
                raise xenrt.XRTFailure("Diff outside range. Recommendation %s for %s did not match expected change from %s" % (hvms1,hostname,hvms2))

        g1.start()
        t = 5*60
        xenrt.TEC().logverbose("Sleeping for %u seconds..." % (t))
        time.sleep(t)
        g2b_recs = g2.retrieveWLBRecommendations()
        xenrt.TEC().logverbose("g2b=[%s]" % (g2b_recs))
        hostname = self.cmpVMScores(g2_recs,g2b_recs,hosts[0],(lambda x,y:x>y), silentdiff=True, silentmatch=True)
        if hostname:
            stars_before = self.fromScoreToStar(g2_recs[hostname])
            stars_now    = self.fromScoreToStar(g2b_recs[hostname])
            diff = float(stars_before - stars_now)
            if stars_now > stars_before:
                diff = float(stars_now - stars_before)
            xenrt.TEC().logverbose("Star diff for host [%s] is [%3.2f]." % (hostname, diff))
            if diff >= threshold_stars:
                xenrt.TEC().logverbose("Diff outside range for host. Diff is greater than or equal to half star.")
                hvms1 = self.hostVMScores(g2_recs)
                hvms2 = self.hostVMScores(g2b_recs)
                raise xenrt.XRTFailure("Diff outside range. Recommendation %s for %s is different from %s" % (hvms1,hostname,hvms2))

        g2.start()
        t = 5*60
        xenrt.TEC().logverbose("Sleeping for %u seconds..." % (t))
        time.sleep(t)
        g2c_recs = g2.retrieveWLBRecommendations()
        xenrt.TEC().logverbose("g2c=[%s]" % g2c_recs)
        hostname = self.cmpVMScores(g2b_recs,g2c_recs,hosts[0],(lambda x,y:x>y), silentdiff=True, silentmatch=True)
        if hostname:
            stars_before = self.fromScoreToStar(g2b_recs[hostname])
            stars_now    = self.fromScoreToStar(g2c_recs[hostname])
            diff = float(stars_before - stars_now)
            if stars_now > stars_before:
                diff = float(stars_now - stars_before)
            xenrt.TEC().logverbose("Star diff for host [%s] is [%3.2f]." % (hostname, diff))
            if diff >= threshold_stars:
                xenrt.TEC().logverbose("Diff outside range for host. Diff is greater than or equal to half star.")
                hvms1 = self.hostVMScores(g2b_recs)
                hvms2 = self.hostVMScores(g2c_recs)
                raise xenrt.XRTFailure("Diff outside range. Recommendation %s for %s is different from %s" % (hvms1,hostname,hvms2))


class TC13480(_VPXWLB):
    """Test a ZeroScoreReason Memory from WLB"""
    def run(self, arglist=None):
        hosts = self.pool.getHosts()
        # Initialise WLB
        self.initialiseWLB()
        # Install a VM on host0 requiring lots of MiB
        g1 = hosts[0].createGenericEmptyGuest(vcpus=1,memory=100000000)
        self.uninstallOnCleanup(g1)
        t = 10
        xenrt.TEC().logverbose("Sleeping for %u seconds..." % (t))
        time.sleep(t)
        g1_recs = g1.retrieveWLBRecommendations()
        xenrt.TEC().logverbose("Recommendation for guest is %s" % g1_recs)
        expect_substr = "HOST_NOT_ENOUGH_FREE_MEMORY"
        for h in hosts:
            if not g1_recs.has_key(h.getName()):
                raise xenrt.XRTFailure("Cannot find recommendation for %s" % (h.getName()))
            if not re.search(expect_substr, g1_recs[h.getName()]):
                raise xenrt.XRTFailure("Recommendation for %s not as expected" %
                    (h.getName()), data="Expecting '%s', "
                    "found '%s'" % (expect_substr,g1_recs[h.getName()]))

class TC13481(_VPXWLB):
    """Test CA-54153: race condition between pool-initialize-wlb and vm-retrieve-wlb-recommendation"""
    def run(self, arglist=None):
        hosts = self.pool.getHosts()
        # make sure wlb is deconfigured
        try:
            self.deconfigureWLB()
        except:
            pass
        # Initialise WLB
        self.initialiseWLB()
        # Install a simple VM on host0
        g1 = hosts[0].createGenericEmptyGuest(vcpus=1,memory=128)
        self.uninstallOnCleanup(g1)
        # and quickly call vm-retrieve-wlb-recommendation
        g1_recs = g1.retrieveWLBRecommendations()
        # we should reach this point
        xenrt.TEC().logverbose("Recommendation for guest is %s" % g1_recs)

class TC13482(_VPXWLB):
    """Test a ZeroScoreReason NotEnoughCpus from WLB"""
    def run(self, arglist=None):
        hosts = self.pool.getHosts()
        # Initialise WLB
        self.initialiseWLB()
        # Install a VM on host0 requiring lots of CPUs
        g1 = hosts[0].createGenericEmptyGuest(vcpus=512,memory=64)
        self.uninstallOnCleanup(g1)
        t = 10
        xenrt.TEC().logverbose("Sleeping for %u seconds..." % (t))
        time.sleep(t)
        g1_recs = g1.retrieveWLBRecommendations()
        xenrt.TEC().logverbose("Recommendation for guest is %s" % g1_recs)
        expect_substr = "WLB 0"
        for h in hosts:
            if not g1_recs.has_key(h.getName()):
                raise xenrt.XRTFailure("Cannot find recommendation for %s" % (h.getName()))
            if not re.search(expect_substr, g1_recs[h.getName()]):
                raise xenrt.XRTFailure("Recommendation for %s not as expected" %
                    (h.getName()), data="Expecting NotEnoughCpus '%s', "
                    "found '%s'" % (expect_substr,g1_recs[h.getName()]))


class TC13483(_VPXWLB):
    """Test a ZeroScoreReason VM_REQUIRES_SR from WLB"""
    def run(self, arglist=None):
        hosts = self.pool.getHosts()
        # Initialise WLB
        self.initialiseWLB()
        # Install a VM on host0 requiring lots of CPUs
        #g1 = hosts[0].createGenericEmptyGuest(vcpus=1,memory=256)
        g1 = self.installVM()
        self.uninstallOnCleanup(g1)
        t = 10
        xenrt.TEC().logverbose("Sleeping for %u seconds..." % (t))
        time.sleep(t)
        g1_recs = g1.retrieveWLBRecommendations()
        xenrt.TEC().logverbose("Recommendation for guest is %s" % g1_recs)
        expect_substr = "VM_REQUIRES_SR"
        for h in hosts[0:-1]: #host0,host1
            if not g1_recs.has_key(h.getName()):
                raise xenrt.XRTFailure("Cannot find recommendation for %s" % (h.getName()))
            if not re.search(expect_substr, g1_recs[h.getName()]):
                raise xenrt.XRTFailure("Recommendation for %s not as expected" %
                    (h.getName()), data="Expecting '%s', "
                    "found '%s'" % (expect_substr,g1_recs[h.getName()]))

    def installVM(self):
        hosts = self.pool.getHosts()
        # Install to local storage of host2
        h = hosts[len(hosts)-1]
        sr = h.getLocalSR()
        return h.createGenericLinuxGuest(start=False,sr=sr)

class TC13484(_VPXWLB):
    """Test CA-54050: initialiseWLB allows using an invalid xenserver username"""
    def run(self, arglist=None):
        hosts = self.pool.getHosts()
        # Initialise WLB
        self.initialiseWLB()

    def initialiseWLB(self):
        self.xs_username = self.wlbUsername
        try:
            self.pool.initialiseWLB("%s:%d" % (self.kirkwood.ip,self.kirkwood.port),
                                self.wlbUsername, self.wlbPassword,
                                self.xs_username, self.xs_password)
            raise xenrt.XRTFailure("WLB server accepted invalid xenserver username during initialise")
        except:
            pass

class _VPXWLBReports(_VPXWLB):
    """Base class for WLB report testcases for VPXWLB"""
    def getFileList(self, directory):
        # Get file list for specified directory
        filelist = []
        files = None
        try:
            files = os.listdir(directory)
        except:
            xenrt.TEC().logverbose("Error getting file listing for directory: " + str(directory))
            return None
        for filename in files:
            fqp = directory + filename
            if os.path.isfile(fqp):
                filelist.append(fqp)
        if len(filelist) <= 0:
            return None
        return filelist

    def getFileContents(self, filename):
        # Get contents of specified file
        file_contents = None
        try:
            file = open(filename)
            file_contents = file.read()
            file_contents = file_contents.split("\n")
        except:
            xenrt.TEC().logverbose("Error getting file contents for: " + str(filename))
            return None
        file.close()
        return file_contents

    def argslistToDictionary(self, arglist):
        # Get arglist and make into dictionary
        if None == arglist:
            return None
        if len(arglist) <= 0:
            return None
        dictionary = {}
        for item in arglist:
            if re.search("=", item):
                key = item.split("=")[0]
                value = item.split("=")[1]
                dictionary[key] = value
        if len(dictionary) <=0:
            return None
        return dictionary

    def doVmLiveMigrate(self, args_dictionary):
        if None == args_dictionary:
            raise xenrt.XRTFailure("TEST_FAILED. No test arguments received.")
        host_uuid = args_dictionary["host_uuid"]
        vmuuid = args_dictionary["vmuuid"]
        command = "vm-migrate host=" + host_uuid + \
                  " vm=" + vmuuid + \
                  " --live" + \
                  " --force"
        try:
            cli = self.pool.getCLIInstance()
            xenrt.TEC().logverbose("command=" + str(command))
            cli.execute(command)
        except:
            raise xenrt.XRTFailure("Error while doing vm live migrate.")

    def doRunBase(self, args_dictionary):
        if None == args_dictionary:
            raise xenrt.XRTFailure("TEST_FAILED. No test arguments received.")
        tmp_dir = args_dictionary["tmp_dir"]
        pool_uuid = args_dictionary["pool_uuid"]
        host_uuid = args_dictionary["host_uuid"]
        report_name = args_dictionary["report_name"]
        minutes_per_iteration = int(args_dictionary["minutes_per_iteration"])
        iterations = int(args_dictionary["iterations"])
        t = minutes_per_iteration * 60
        found = False
        for i in range(iterations):
            # execute report every x minutes for a maximum of y hours
            xenrt.TEC().logverbose("Sleeping for %u seconds..." % (t))
            time.sleep(t)
            ran = str(random.randrange(99999))
            # prepare command line for report execution
            report_output_fqp = tmp_dir + report_name + "_" + ran + ".wordpad"
            command = "pool-retrieve-wlb-report report=" + report_name+ \
                      " LocaleCode=" + args_dictionary["LocaleCode"]  + \
                      " Start="      + args_dictionary["Start"]       + \
                      " End="        + args_dictionary["End"]         + \
                      " PoolID="     + pool_uuid
            if report_name in ["host_health_history", "vm_performance_history"]:
                command = command + " HostID=" + host_uuid
            if report_name in ["pool_audit_history"]:
                # add ReportVersion=creedence AuditUser=ALL AuditObject=ALL StartLine=1 EndLine=10000
                if 'report_version' in args_dictionary:
                    command = command + " ReportVersion=" + args_dictionary['report_version']
                if 'audit_user' in args_dictionary:
                    command = command + " AuditUser=" + args_dictionary['audit_user']
                if 'audit_object' in args_dictionary:
                    command = command + " AuditObject=" + args_dictionary['audit_object']
                if 'start_line' in args_dictionary:
                    command = command + " StartLine=" + args_dictionary['start_line']
                if 'end_line' in args_dictionary:
                    command = command + " EndLine=" + args_dictionary['end_line']
            command = command + \
                      " UTCOffset="  + args_dictionary["UTCOffset"] + \
                      " filename="   + report_output_fqp
            try:
                cli = self.pool.getCLIInstance()
                xenrt.TEC().logverbose("command=" + str(command))
                cli.execute(command)
                # get current file listing
                xenrt.TEC().logverbose("Current File listing for ["+tmp_dir+"]:")
                filelist = self.getFileList(tmp_dir)
                for filename in filelist:
                    xenrt.TEC().logverbose(filename + "\n")
            except:
                raise xenrt.XRTFailure("Error while executing report ["+report_name+"].")
            # get report contents
            report_contents = None
            try:
                report_contents = self.getFileContents(report_output_fqp)
                # cleanup/delete unneeded output file
                if os.path.exists(report_output_fqp):
                    xenrt.TEC().logverbose("Attempting to remove(delete) file ["+report_output_fqp+"].")
                    os.remove(report_output_fqp)
                    # get current file listing
                    xenrt.TEC().logverbose("Current File listing for ["+tmp_dir+"]:")
                    filelist = self.getFileList(tmp_dir)
                    for filename in filelist:
                        xenrt.TEC().logverbose(filename + "\n")
            except:
                raise xenrt.XRTFailure("Error while getting report content ["+report_name+"].")
            if None == report_contents:
                raise xenrt.XRTFailure("Empty report contents ["+report_name+"].")
            args_dictionary["current_iteration"] = i
            found = self.verifyTestPassed(report_contents, args_dictionary)
            if found:
                break

        if not found:
            xenrt.TEC().logverbose("TEST_FAILED: %r.verifyTestPassed not found keyword in %r" % (self, report_contents[:1024]))
            raise xenrt.XRTFailure("TEST_FAILED.")

    def verifyTestPassed(self, report_contents, args_dictionary):
        raise xenrt.XRTError("Unimplemented")

class TC18154(_VPXWLBReports):
    """Test pool audit trail report"""
    def verifyTestPassed(self, report_contents, args_dictionary):
        # check if test passed
        # 2012-OCT: the following method of determining if report succeeded
        # is sufficiently accurate for now. In the future, a more accurate determination
        # of WLB report success will be created/implemented.
        # look for eventobject
        vmname= args_dictionary["vmname"]
        found = False
        pattern = """<eventobject>vm</eventobject>"""
        for line in report_contents:
            if re.search(pattern, line, re.IGNORECASE):
                xenrt.TEC().logverbose("Found eventobject. line = " + str(line))
                found = True
            if found:
                break
        if not found:
            return False
        # look for eventobjectname
        found = False
        pattern = """<eventobjectname>"""+vmname+"""</eventobjectname>"""
        for line in report_contents:
            if re.search(pattern, line, re.IGNORECASE):
                xenrt.TEC().logverbose("Found eventobjectname. line = " + str(line))
                found = True
            if found:
                break
        if not found:
            return False
        # look for eventaction
        found = False
        pattern = """<eventaction>start_on</eventaction>"""
        for line in report_contents:
            if re.search(pattern, line, re.IGNORECASE):
                xenrt.TEC().logverbose("Found eventaction. line = " + str(line))
                found = True
            if found:
                break
        if not found:
            return False
        return True

    def run(self, arglist=None):
        # rather then use dictionary immediately, lets use list then convert to dictionary
        # since in the future, may use run(arglist) method directly.
        args_list = ["tmp_dir=/tmp/", "vmname=TestVM", "LocaleCode=en", "Start=-1", "End=0", "UTCOffset=-240", "report_name=pool_audit_history", "minutes_per_iteration=3", "iterations=5"]
        args_dictionary = self.argslistToDictionary(args_list)
        hosts = self.pool.getHosts()
        # Initialise WLB
        self.initialiseWLB()
        # Install a specific VM
        index = 0
        vmname = args_dictionary["vmname"]
        g1 = hosts[index].createGenericLinuxGuest(name=vmname,vcpus=1)
        self.uninstallOnCleanup(g1)
        host_name = str(hosts[index].getName())
        host_uuid = str(hosts[index].getMyHostUUID())
        pool_uuid = str(self.pool.getUUID())
        args_dictionary["host_name"] = host_name
        args_dictionary["host_uuid"] = host_uuid
        args_dictionary["pool_uuid"] = pool_uuid
        self.doRunBase(args_dictionary)


class TC21683(TC18154):
    """Test pool audit trail report in creedence"""
    def run(self, arglist=None):
        # rather then use dictionary immediately, lets use list then convert to dictionary
        # since in the future, may use run(arglist) method directly.
        args_list = ["tmp_dir=/tmp/", "vmname=TestVM", "LocaleCode=en", "Start=-1", "End=0", "UTCOffset=-240", "report_name=pool_audit_history", "minutes_per_iteration=3", "iterations=5"]
        args_dictionary = self.argslistToDictionary(args_list)
        hosts = self.pool.getHosts()
        # Initialise WLB
        self.initialiseWLB()
        # Install a specific VM
        index = 0
        vmname = args_dictionary["vmname"]
        g1 = hosts[index].createGenericLinuxGuest(name=vmname,vcpus=1)
        self.uninstallOnCleanup(g1)
        host_name = str(hosts[index].getName())
        host_uuid = str(hosts[index].getMyHostUUID())
        pool_uuid = str(self.pool.getUUID())
        args_dictionary["host_name"] = host_name
        args_dictionary["host_uuid"] = host_uuid
        args_dictionary["pool_uuid"] = pool_uuid
        #ReportVersion=creedence AuditUser=ALL AuditObject=ALL StartLine=1 EndLine=10000
        args_dictionary["report_version"] = 'creedence'
        args_dictionary["audit_user"] = 'ALL'
        args_dictionary["audit_object"] = 'ALL'
        args_dictionary["start_line"] = '1'
        args_dictionary["end_line"] = '10000'
        self.doRunBase(args_dictionary)


class TC18157(_VPXWLBReports):
    """Test VM chargeback report"""
    def verifyTestPassed(self, report_contents, args_dictionary):
        # 2012-OCT: the following method of determining if report succeeded
        # is sufficiently accurate for now. In the future, a more accurate determination
        # of WLB report success will be created/implemented.
        # look for VM uuid
        vmuuid = args_dictionary["vmuuid"]
        vmname = args_dictionary["vmname"]
        minutes = int(args_dictionary["minutes_per_iteration"])
        i = int(args_dictionary["current_iteration"])
        xenrt.TEC().logverbose("minutes = " + str(minutes))
        xenrt.TEC().logverbose("i = " + str(i))
        xenrt.TEC().logverbose("Expected VM uuid ["+vmuuid+"].")
        found = False
        pattern = """<uuid>"""+vmuuid+"""</uuid>"""
        for line in report_contents:
            if re.search(pattern, line, re.IGNORECASE):
                xenrt.TEC().logverbose("Found VM uuid. line = " + str(line))
                found = True
                break
        if not found:
            return False
        # look for vm_name
        found = False
        pattern = """<vm_name>"""+vmname+"""</vm_name>"""
        for line in report_contents:
            if re.search(pattern, line, re.IGNORECASE):
                xenrt.TEC().logverbose("Found vm_name. line = " + str(line))
                found = True
                break
        if not found:
            return False
        # look for uptime_minutes
        found = False
        pattern = """<uptime_minutes>(\d{1,3})</uptime_minutes>"""
        for line in report_contents:
            xenrt.TEC().logverbose("line = " + str(line))
            m = re.search(pattern, line, re.IGNORECASE)
            if m:
                xenrt.TEC().logverbose("Found uptime_minutes. line = " + str(line))
                actual_uptime_minutes = int(m.group(1))
                expected_uptime_minutes = int((i+1) * minutes)
                xenrt.TEC().logverbose("actual_uptime_minutes ["+str(actual_uptime_minutes)+"] expected to be >= ["+str(expected_uptime_minutes)+"].")
                if actual_uptime_minutes >= expected_uptime_minutes:
                    return True
        return False

    def run(self, arglist=None):
        # rather then use dictionary immediately, lets use list then convert to dictionary
        # since in the future, may use run(arglist) method directly.
        args_list = ["tmp_dir=/tmp/", "vmname=TestVM", "LocaleCode=en", "Start=-1", "End=0", "UTCOffset=-240", "report_name=vm_chargeback_history", "minutes_per_iteration=4", "iterations=4"]
        args_dictionary = self.argslistToDictionary(args_list)
        hosts = self.pool.getHosts()
        # Initialise WLB
        self.initialiseWLB()
        # Install a specific VM
        index = 0
        g1 = hosts[index].createGenericLinuxGuest(name=args_dictionary["vmname"],vcpus=1)
        args_dictionary["vmuuid"] = str(g1.getInfo()[5])
        self.uninstallOnCleanup(g1)
        args_dictionary["host_name"] = str(hosts[index].getName())
        args_dictionary["host_uuid"] = str(hosts[index].getMyHostUUID())
        args_dictionary["pool_uuid"] = str(self.pool.getUUID())
        self.doRunBase(args_dictionary)


class TC18158(_VPXWLBReports):
    """Test host health history report"""
    def verifyTestPassed(self, report_contents, args_dictionary):
        # 2012-OCT: the following method of determining if report succeeded
        # is sufficiently accurate for now. In the future, a more accurate determination
        # of WLB report success will be created/implemented.
        host_name = args_dictionary["host_name"]
        # look for host name
        xenrt.TEC().logverbose("Expected host_name ["+host_name+"].")
        pattern = """<name>"""+host_name+"""</name>"""
        for line in report_contents:
            xenrt.TEC().logverbose("line = " + str(line))
            if re.search(pattern, line, re.IGNORECASE):
                xenrt.TEC().logverbose("Found host_name line = " + str(line))
                return True
        return False

    def run(self, arglist=None):
        # rather then use dictionary immediately, lets use list then convert to dictionary
        # since in the future, may use run(arglist) method directly.
        args_list = ["tmp_dir=/tmp/", "vmname=TestVM", "LocaleCode=en", "Start=-1", "End=0", "UTCOffset=-240", "report_name=host_health_history", "minutes_per_iteration=6", "iterations=40"]
        args_dictionary = self.argslistToDictionary(args_list)
        hosts = self.pool.getHosts()
        # Initialise WLB
        self.initialiseWLB()
        # Install a specific VM
        index = 0
        g1 = hosts[index].createGenericLinuxGuest(name=args_dictionary["vmname"],vcpus=1)
        self.uninstallOnCleanup(g1)
        args_dictionary["vmuuid"] = str(g1.getInfo()[5])
        args_dictionary["host_name"] = str(hosts[index].getName())
        args_dictionary["host_uuid"] = str(hosts[index].getMyHostUUID())
        args_dictionary["pool_uuid"] = str(self.pool.getUUID())
        self.doRunBase(args_dictionary)

class TC18165(_VPXWLBReports):
    """Test pool health  report"""
    def verifyTestPassed(self, report_contents, args_dictionary):
        # 2012-OCT: the following method of determining if report succeeded
        # is sufficiently accurate for now. In the future, a more accurate determination
        # of WLB report success will be created/implemented.
        # look for hostname
        host_name = args_dictionary["host_name"]
        host_uuid = args_dictionary["host_uuid"]
        xenrt.TEC().logverbose("Expected host_name ["+host_name+"].")
        found = False
        pattern = """<name>"""+host_name+"""</name>"""
        for line in report_contents:
            xenrt.TEC().logverbose("line = " + str(line))
            if re.search(pattern, line, re.IGNORECASE):
                xenrt.TEC().logverbose("Found host_name. line = " + str(line))
                found = True
                break
        if not found:
            return False
        # look for host_uuid
        xenrt.TEC().logverbose("Expected host_uuid ["+host_uuid+"].")
        pattern = """<uuid>"""+host_uuid+"""</uuid>"""
        for line in report_contents:
            if re.search(pattern, line, re.IGNORECASE):
                xenrt.TEC().logverbose("Found host_uuid. line = " + str(line))
                return True
        return False

    def run(self, arglist=None):
        # rather then use dictionary immediately, lets use list then convert to dictionary
        # since in the future, may use run(arglist) method directly.
        args_list = ["tmp_dir=/tmp/", "vmname=TestVM", "LocaleCode=en", "Start=-1", "End=0", "UTCOffset=-240", "report_name=pool_health", "minutes_per_iteration=6", "iterations=40"]
        args_dictionary = self.argslistToDictionary(args_list)
        hosts = self.pool.getHosts()
        # Initialise WLB
        self.initialiseWLB()
        # Install a specific VM
        index = 0
        g1 = hosts[index].createGenericLinuxGuest(name=args_dictionary["vmname"],vcpus=1)
        self.uninstallOnCleanup(g1)
        args_dictionary["vmuuid"] = str(g1.getInfo()[5])
        args_dictionary["host_name"] = str(hosts[index].getName())
        args_dictionary["host_uuid"] = str(hosts[index].getMyHostUUID())
        args_dictionary["pool_uuid"] = str(self.pool.getUUID())
        self.doRunBase(args_dictionary)

class TC21445(_VPXWLBReports):
    """Test optimization performance history report"""
    def verifyTestPassed(self, report_contents, args_dictionary):
        # look for optimized_moves records
        xenrt.TEC().logverbose("Expected optimized_moves records.")
        pattern = """<optimized_moves>.*</optimized_moves>"""
        for line in report_contents:
            if re.search(pattern, line, re.IGNORECASE):
                xenrt.TEC().logverbose("Found optimized_moves record. line = " + str(line))
                return True
        return False
    
    def run(self, arglist=None):
        args_list = ["tmp_dir=/tmp/", "LocaleCode=en", "Start=-1", "End=0", "UTCOffset=-240", "report_name=optimization_performance_history", "minutes_per_iteration=5", "iterations=3"]
        args_dictionary = self.argslistToDictionary(args_list)
        hosts = self.pool.getHosts()
        # Initialise WLB
        self.initialiseWLB()
        # Install 2 VMs
        index = 0
        g1 = hosts[index].createGenericLinuxGuest(vcpus=2,memory=1024)
        self.uninstallOnCleanup(g1)
        index = 1
        g2 = hosts[index].createGenericLinuxGuest(vcpus=2,memory=1024)
        self.uninstallOnCleanup(g2)
        args_dictionary["vmuuid-1"] = str(g1.getInfo()[5])
        args_dictionary["vmuuid-2"] = str(g2.getInfo()[5])
        args_dictionary["host_name"] = str(hosts[index].getName())
        args_dictionary["host_uuid"] = str(hosts[index].getMyHostUUID())
        args_dictionary["pool_uuid"] = str(self.pool.getUUID())
        self.doRunBase(args_dictionary)

class TC21446(_VPXWLBReports):
    """Test pool optimization histroy report"""
    def verifyTestPassed(self, report_contents, args_dictionary):
        # look for move_time
        xenrt.TEC().logverbose("Expected move_time keyword.")
        pattern = "move_time"
        for line in report_contents:
            if re.search(pattern, line, re.IGNORECASE):
                xenrt.TEC().logverbose("Found move_time. line = " + str(line))
                return True
        return False
    
    def run(self, arglist=None):
        args_list = ["tmp_dir=/tmp/", "LocaleCode=en", "Start=-1", "End=0", "UTCOffset=-240", "report_name=pool_optimization_history", "minutes_per_iteration=5", "iterations=3"]
        args_dictionary = self.argslistToDictionary(args_list)
        hosts = self.pool.getHosts()
        # Initialise WLB
        self.initialiseWLB()
        # Install 2 VMs
        index = 0
        g1 = hosts[index].createGenericLinuxGuest(vcpus=2,memory=1024)
        self.uninstallOnCleanup(g1)
        index = 1
        g2 = hosts[index].createGenericLinuxGuest(vcpus=2,memory=1024)
        self.uninstallOnCleanup(g2)
        args_dictionary["vmuuid-1"] = str(g1.getInfo()[5])
        args_dictionary["vmuuid-2"] = str(g2.getInfo()[5])
        args_dictionary["host_name"] = str(hosts[index].getName())
        args_dictionary["host_uuid"] = str(hosts[index].getMyHostUUID())
        args_dictionary["pool_uuid"] = str(self.pool.getUUID())
        self.doRunBase(args_dictionary)

class TC21447(_VPXWLBReports):
    """Test pool health history report"""
    def verifyTestPassed(self, report_contents, args_dictionary):
        # look for host cpu/memory/net metrics.
        xenrt.TEC().logverbose("Expected host cpu/memory/net metrics.")
        founds = [False, False, False]
        for line in report_contents:
            if re.search("host_cpu", line, re.IGNORECASE):
                xenrt.TEC().logverbose("Found host_cpu metric. line = " + str(line))
                founds[0] = True
            if re.search("host_memory", line, re.IGNORECASE):
                xenrt.TEC().logverbose("Found host_memory metric. line = " + str(line))
                founds[1] = True
            if re.search("host_net", line, re.IGNORECASE):
                xenrt.TEC().logverbose("Found host_net metric. line = " + str(line))
                founds[2] = True
        result = reduce(lambda x,y: x and y, founds)
        return result
        
    def run(self, arglist=None):
        args_list = ["tmp_dir=/tmp/", "LocaleCode=en", "Start=-1", "End=0", "UTCOffset=-240", "report_name=pool_health_history", "minutes_per_iteration=5", "iterations=3"]
        args_dictionary = self.argslistToDictionary(args_list)
        hosts = self.pool.getHosts()
        # Initialise WLB
        self.initialiseWLB()
        # Install 2 VMs
        index = 0
        g1 = hosts[index].createGenericLinuxGuest(vcpus=2,memory=1024)
        self.uninstallOnCleanup(g1)
        index = 1
        g2 = hosts[index].createGenericLinuxGuest(vcpus=2,memory=1024)
        self.uninstallOnCleanup(g2)
        args_dictionary["vmuuid-1"] = str(g1.getInfo()[5])
        args_dictionary["vmuuid-2"] = str(g2.getInfo()[5])
        args_dictionary["host_name"] = str(hosts[index].getName())
        args_dictionary["host_uuid"] = str(hosts[index].getMyHostUUID())
        args_dictionary["pool_uuid"] = str(self.pool.getUUID())
        self.doRunBase(args_dictionary)

class TC21448(_VPXWLBReports):
    """Test vm movement history report"""
    def verifyTestPassed(self, report_contents, args_dictionary):
        # look for move_time
        xenrt.TEC().logverbose("Expected move_time keyword.")
        pattern = "move_time"
        for line in report_contents:
            if re.search(pattern, line, re.IGNORECASE):
                xenrt.TEC().logverbose("Found move_time. line = " + str(line))
                return True
        return False
    
    def run(self, arglist=None):
        args_list = ["tmp_dir=/tmp/", "LocaleCode=en", "Start=-1", "End=0", "UTCOffset=-240", "report_name=vm_movement_history", "minutes_per_iteration=5", "iterations=3"]
        args_dictionary = self.argslistToDictionary(args_list)
        hosts = self.pool.getHosts()
        # Initialise WLB
        self.initialiseWLB()
        # Install 2 VMs
        index = 0
        g1 = hosts[index].createGenericLinuxGuest(vcpus=2,memory=1024)
        self.uninstallOnCleanup(g1)
        index = 1
        g2 = hosts[index].createGenericLinuxGuest(vcpus=2,memory=1024)
        self.uninstallOnCleanup(g2)
        # Migrate 1 VM
        self.doVmLiveMigrate({"host_uuid":str(hosts[index].getMyHostUUID()),
                              "vmuuid":str(g1.getInfo()[5])})
        # Maybe 100 seconds are not enough
        time.sleep(100)
        args_dictionary["vmuuid-1"] = str(g1.getInfo()[5])
        args_dictionary["vmuuid-2"] = str(g2.getInfo()[5])
        args_dictionary["host_name"] = str(hosts[index].getName())
        args_dictionary["host_uuid"] = str(hosts[index].getMyHostUUID())
        args_dictionary["pool_uuid"] = str(self.pool.getUUID())
        self.doRunBase(args_dictionary)

class TC21449(_VPXWLBReports):
    """Test vm performance history report"""
    def verifyTestPassed(self, report_contents, args_dictionary):
        # look for avg_cpu/avg_free_mem/avg_vif/avg_vbd metrics.
        xenrt.TEC().logverbose("Expected host avg_cpu/avg_free_mem/avg_vif/avg_vbd metrics.")
        founds = [False, False, False, False]
        for line in report_contents:
            if re.search("avg_cpu", line, re.IGNORECASE):
                xenrt.TEC().logverbose("Found avg_cpu metric. line = " + str(line))
                founds[0] = True
            if re.search("avg_free_mem", line, re.IGNORECASE):
                xenrt.TEC().logverbose("Found avg_free_mem metric. line = " + str(line))
                founds[1] = True
            if re.search("avg_vif", line, re.IGNORECASE):
                xenrt.TEC().logverbose("Found avg_vif metric. line = " + str(line))
                founds[2] = True
            if re.search("avg_vbd", line, re.IGNORECASE):
                xenrt.TEC().logverbose("Found avg_vbd metric. line = " + str(line))
                founds[3] = True
        result = reduce(lambda x,y: x and y, founds)
        return result


    def run(self, arglist=None):
        args_list = ["tmp_dir=/tmp/", "LocaleCode=en", "Start=-1", "End=0", "UTCOffset=-240", "report_name=vm_performance_history", "minutes_per_iteration=5", "iterations=3"]
        args_dictionary = self.argslistToDictionary(args_list)
        hosts = self.pool.getHosts()
        # Initialise WLB
        self.initialiseWLB()
        # Install 2 VMs
        index = 0
        g1 = hosts[index].createGenericLinuxGuest(vcpus=2,memory=1024)
        self.uninstallOnCleanup(g1)
        index = 1
        g2 = hosts[index].createGenericLinuxGuest(vcpus=2,memory=1024)
        self.uninstallOnCleanup(g2)
        args_dictionary["vmuuid-1"] = str(g1.getInfo()[5])
        args_dictionary["vmuuid-2"] = str(g2.getInfo()[5])
        args_dictionary["host_name"] = str(hosts[index].getName())
        args_dictionary["host_uuid"] = str(hosts[index].getMyHostUUID())
        args_dictionary["pool_uuid"] = str(self.pool.getUUID())
        self.doRunBase(args_dictionary)
