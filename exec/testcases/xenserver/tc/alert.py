
# XenRT: Test harness for Xen and the XenServer product family
#
# Events and alerting
#
# Copyright (c) 2008 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import socket, re, string, time, traceback, sys, random, copy, calendar, math
import xenrt, xenrt.lib.xenserver

class TC8172(xenrt.TestCase):
    """Creation of event messages using the CLI."""

    def doMessage(self, etype):
        host = self.getDefaultHost()
        uuids = host.minimalList("%s-list" % (etype))
        if len(uuids) == 0:
            raise xenrt.XRTError("No entities of type '%s' found" % (etype))
        uuid = uuids[0]
        name = "TC8172_%s_%u" % (etype, xenrt.timenow())
        body = "Test message in TC-8172 for %s [%s]" % (etype, uuid)
        time1 = xenrt.timenow() - 1
        host.messageGeneralCreate(etype, uuid, name, body)
        time2 = xenrt.timenow() + 1
        
        # Check the message
        messages = host.minimalList("message-list", "uuid", "name=%s" % (name))
        if len(messages) == 0:
            raise xenrt.XRTFailure("Could not find message in list")
        if len(messages) > 1:
            raise xenrt.XRTFailure("Found multiple messages in list")
        m = messages[0] 
        h = host.genParamGet("message", m, "class")
        if h.lower() != etype:
            raise xenrt.XRTFailure("Message has incorrect class")
        u = host.genParamGet("message", m, "obj-uuid")
        if u != uuid:
            raise xenrt.XRTFailure("Message has incorrect UUID")
        b = host.genParamGet("message", m, "body")
        if b != body:
            raise xenrt.XRTFailure("Message has incorrect body")
        ts = host.genParamGet("message", m, "timestamp")
        tsint = xenrt.parseXapiTime(ts)
        if tsint < time1 or tsint > time2:
            raise xenrt.XRTFailure("Message timestamp does not match the time "
                                   "it was created",
                                   "TS %u created in [%u, %u]" %
                                   (tsint, time1, time2))

    def run(self, arglist=None):
        self.runSubcase("doMessage", ("vm"), "Message", "VM")
        self.runSubcase("doMessage", ("host"), "Message", "Host")
        self.runSubcase("doMessage", ("sr"), "Message", "SR")
        self.runSubcase("doMessage", ("pool"), "Message", "Pool")

class TC8173(xenrt.TestCase):
    """Validation of the type of a message created via the CLI."""

    def run(self, arglist=None):
        
        host = self.getDefaultHost()
        uuid = host.getMyHostUUID()
        name = "TC8173_%u" % (xenrt.timenow())
        body = "Test message in TC-8173"
        failed = False
        try:
            host.messageGeneralCreate("vm", uuid, name, body)
            failed = True
        except xenrt.XRTFailure, e:
           version = xenrt.TEC().lookup("PRODUCT_VERSION")
           if version == "Orlando":
                xenrt.TEC().logverbose(" Orlando Detected")
                if not re.search(r"Error code: UUID_INVALID", e.data):
                    raise xenrt.XRTFailure("Invalid uuid error for Orlando Host")
           else :                
                if not re.search(r"type: VM", e.data):
                    raise xenrt.XRTFailure("Error did not contain type: VM")
                if not re.search(r"uuid: %s" % (uuid), e.data):
                    raise xenrt.XRTFailure("Error did not contain the invalid UUID")

class TC8175(xenrt.TestCase):
    """VM lifecycle events should generate event messages."""

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.guest = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guest)
        self.events = []
        self.guest.shutdown()

        time1 = xenrt.timenow() - 1
        self.guest.start()
        time2 = xenrt.timenow() + 1
        self.events.append(("VM_STARTED", time1, time2))
        xenrt.sleep(30)

        time1 = xenrt.timenow() - 1
        self.guest.reboot()
        time2 = xenrt.timenow() + 1
        self.events.append(("VM_REBOOTED", time1, time2))
        xenrt.sleep(30)

        time1 = xenrt.timenow() - 1
        self.guest.suspend()
        time2 = xenrt.timenow() + 1
        self.events.append(("VM_SUSPENDED", time1, time2))
        xenrt.sleep(30)

        time1 = xenrt.timenow() - 1
        self.guest.resume()
        time2 = xenrt.timenow() + 1
        self.events.append(("VM_RESUMED", time1, time2))
        xenrt.sleep(30)

        time1 = xenrt.timenow() - 1
        self.guest.shutdown()
        time2 = xenrt.timenow() + 1
        self.events.append(("VM_SHUTDOWN", time1, time2))
        xenrt.sleep(30)

    def checkEvent(self, name, time1, time2):

        # Check the message
        messages = self.host.minimalList("message-list",
                                         "uuid",
                                         "name=%s class=VM obj-uuid=%s" %
                                         (name, self.guest.getUUID()))
        if len(messages) == 0:
            raise xenrt.XRTFailure("Could not find message in list")
        for m in messages:
            ts = self.host.genParamGet("message", m, "timestamp")
            tsint = xenrt.parseXapiTime(ts)
            if tsint >= time1 and tsint <= time2:
                # This is our message
                return
        raise xenrt.XRTFailure("Could not find a message within the time "
                               "window for this operation")

    def run(self, arglist=None):
        for e in self.events:
            self.runSubcase("checkEvent", (e[0], e[1], e[2]), "VM", e[0])

class TC8176(xenrt.TestCase):
    """Alerts can be sent via email. Use TC8176PrioPostTampa for Dundee and later."""

    def __init__(self, tcid=None):
        self.smtpServer = None
        self.pool = None
        xenrt.TestCase.__init__(self, tcid=tcid)
        self.newPriority = False

    def prepare(self, arglist=None):
        self.smtpServer = xenrt.util.SimpleSMTPServer()
        self.smtpServer.start()

    def run(self, arglist=None):
        host = self.getDefaultHost()
        pool = xenrt.lib.xenserver.poolFactory(host.productVersion)(host)
        self.host = host
        self.pool = pool
        pool.setPoolParam("other-config:mail-destination", "test@mail.xenrt")
        pool.setPoolParam("other-config:ssmtp-mailhub", "%s:%s" % 
                                    (xenrt.TEC().lookup("XENRT_SERVER_ADDRESS"),
                                     self.smtpServer.port))

        # This functionality has changed from Dundee onwards. if condition is done to support both versions
        # https://confluence.uk.xensource.com/display/engp/XenServer+alert+proposal+%28was+audit%29
        if self.newPriority == True:
            self.prioMsgEmailChk(host, pool, testname="TC8176_a", testPriority=3, isReceived=True )
            self.prioMsgEmailChk(host, pool, testname="TC8176_b", testPriority=4, isReceived=False)
            self.prioMsgEmailChk(host, pool, testname="TC8176_c", testPriority=4, isReceived=True , mailMinPriority=4 )
            self.prioMsgEmailChk(host, pool, testname="TC8176_d", testPriority=3, isReceived=False, mailMinPriority=2 )
        else:
            self.prioMsgEmailChk(host, pool, testname="TC8176_aLegacy", testPriority=5, isReceived=True )
            self.prioMsgEmailChk(host, pool, testname="TC8176_bLegacy", testPriority=4, isReceived=False)
            self.prioMsgEmailChk(host, pool, testname="TC8176_cLegacy", testPriority=4, isReceived=True , mailMinPriority=4 )
            self.prioMsgEmailChk(host, pool, testname="TC8176_dLegacy", testPriority=3, isReceived=False)
       
    # Function to create message, send it based on prioity and verify if received or not.
    def prioMsgEmailChk(self, host, pool, testname, testPriority, isReceived, mailMinPriority= None):

        # Set other-config:mail-min-priority to options.get("mail-min-priority")
        if mailMinPriority != None:
            pool.setPoolParam("other-config:mail-min-priority", mailMinPriority)
        
        # Create a message of priority level 'priority'
        host.messageCreate(testname, "Test message (priority %d)" % testPriority, priority=testPriority)
        
        #wait then check for mail and clear mailbox.
        xenrt.sleep(30) 
        mail = self.smtpServer.getMail()
        self.smtpServer.clearMail()
        
        if isReceived == True:        
            # verify an email is received 
            if len(mail) == 0:
                raise xenrt.XRTFailure("%s : No email sent for priority %d message" % (testname, testPriority))
            elif len(mail) > 1:
                raise xenrt.XRTFailure("%s : Received multiple emails for one message" % testname)
            self.check(host, mail[0], testname)
        else:
            # verify email is not recieved 
            if len(mail) > 0:
                raise xenrt.XRTFailure("%s : Received email for priority %d message" % (testname, testPriority))
            
    def check(self, host, mail, msgName):
        # Get the actual message details
        matchingMessages = host.minimalList("message-list", "uuid", 
                                            "name=%s" % (msgName))
        if len(matchingMessages) != 1:
            raise xenrt.XRTError("Found %u messages, expecting 1" % 
                                 (len(matchingMessages)))
        msgDetails = {}
        msgDetails['uuid'] = matchingMessages[0]
        msgDetails['name'] = msgName
        ts = host.genParamGet("message", msgDetails['uuid'], "timestamp")
        msgDetails['ts'] = ts
        msgDetails['time'] = xenrt.parseXapiTime(ts)
        msgDetails['priority'] = host.genParamGet("message", 
                                                  msgDetails['uuid'],
                                                  "priority")
        msgDetails['body'] = host.genParamGet("message", msgDetails['uuid'],
                                              "body")

        # Verify the sender + receiver are correct
        expectedSenders = ["mail-alarm@%s" % (host.getName()), 
                           "noreply@%s" % (host.getName())]
        found = False
        for s in expectedSenders:
            if mail['sender'].startswith(s):
                found = True
                break
        if not found:
            raise xenrt.XRTFailure("SMTP sender incorrect, %s vs %s" %
                                   (mail['sender'], expectedSenders))
        if mail['recipient'] != "test@mail.xenrt":
            raise xenrt.XRTFailure("SMTP recipient incorrect, %s vs "
                                   "test@mail.xenrt" % (mail['recipient']))

        # Log the actual message for debugging
        xenrt.TEC().logverbose("Message received:\n%s" % (mail['data']))

        # Parse the email
        inHeaders = True
        headers = {}
        bodyLines = []
        for line in mail['data'].split("\r\n"):
            l = line.strip()
            if inHeaders:
                if l == "":
                    inHeaders = False
                elif ":" in l:
                    h = l.split(":", 1)
                    headers[h[0].strip()] = h[1].strip()
            else:
                bodyLines.append(l)

        # Check the headers we care about
        expectedHeaders = ["Date", "From", "Subject", "To"]
        for e in expectedHeaders:
            if not e in headers:
                raise xenrt.XRTFailure("Didn't find expected header %s in "
                                       "email message" % (e))

        # Date
        # Convert it to a time object, so we can compare it to the message time,
        # it should be >= it up to a max of 5 seconds out.
        t = time.strptime(headers['Date'], "%a, %d %b %Y %H:%M:%S +0000")
        difference = int(calendar.timegm(t) - msgDetails['time'])
        if difference < 0 or difference > 5:
            raise xenrt.XRTFailure("Unexpected date (< 0 or > 5 seconds out "
                                   "as compared to message timestamp) %s (%u "
                                   "difference)" % (headers['Date'],difference))
        # From
        found = False
        for s in expectedSenders:
            if headers['From'].startswith(s):
                found = True
                break                
        if not found:
            raise xenrt.XRTFailure("From header incorrect, %s vs %s" %
                                   (headers['From'], expectedSenders))
        # Subject
        expectedSubjects = ["[%s] XenServer Message: Host %s %s" % \
                            (host.getMyHostName(), host.getMyHostUUID(),
                            msgDetails['name']),
                            "XenServer Message: Host %s %s" % \
                            (host.getMyHostUUID(), msgDetails['name'])]

        if not headers['Subject'] in expectedSubjects:
            raise xenrt.XRTFailure("Subject incorrect, %s vs %s" %
                                   (headers['Subject'], expectedSubjects))
        # To
        if headers['To'] != "test@mail.xenrt":
            raise xenrt.XRTFailure("To header incorrect, %s vs %s" %
                                   (headers['To'], "test@mail.xenrt"))

        # Parse the body
        bodyFields = {}
        for l in bodyLines:
            if ":" in l:
                h = l.split(":", 1)
                bodyFields[h[0].strip()] = h[1].strip()

        expectedFields = ["Name", "Priority", "Class", "Object UUID", 
                          "Timestamp", "Message UUID", "Body"]
        for e in expectedFields:
            if not e in bodyFields:
                raise xenrt.XRTFailure("Didn't find expected field %s in "
                                       "email body" % (e))

        if bodyFields['Name'] != msgDetails['name']:
            raise xenrt.XRTFailure("Name in email body incorrect %s vs %s" %
                                   (bodyFields['Name'], msgDetails['name']))
        if bodyFields['Priority'] != msgDetails['priority']:
            raise xenrt.XRTFailure("Priority in email body incorrect %s vs %s" %
                                   (bodyFields['Priority'], 
                                    msgDetails['priority']))
        if bodyFields['Class'] != "Host":
            raise xenrt.XRTFailure("Class in email body incorrect %s vs Host" %
                                   (bodyFields['Class']))
        if bodyFields['Object UUID'] != host.getMyHostUUID():
            raise xenrt.XRTFailure("Obj UUID in email body incorrect %s vs %s" %
                                   (bodyFields['Object UUID'], 
                                    host.getMyHostUUID()))
        if bodyFields['Timestamp'] != msgDetails['ts']:
            raise xenrt.XRTFailure("Timestamp in email body incorrect %s vs %s" %
                                   (bodyFields['Timestamp'], msgDetails['ts']))
        if bodyFields['Message UUID'] != msgDetails['uuid']:
            raise xenrt.XRTFailure("Msg UUID in email body incorrect %s vs %s" %
                                   (bodyFields['Message UUID'],
                                    msgDetails['uuid']))
        if bodyFields['Body'] != msgDetails['body'].strip():
            raise xenrt.XRTFailure("Msg body in email body incorrect %s vs %s" %
                                   (bodyFields['Body'], 
                                    msgDetails['body'].strip()))

    def postRun(self):
        if self.pool:
            self.pool.removePoolParam("other-config", "mail-destination")
            self.pool.removePoolParam("other-config", "ssmtp-mailhub")
            self.pool.removePoolParam("other-config", "mail-min-priority")
        if self.smtpServer and self.smtpServer.isAlive():
            self.smtpServer.stop()

class TC8176PrioPostTampa(TC8176):
    """Alerts can be sent via email. New Priority applies to Dundee and later."""

    def __init__(self, tcid=None):
        TC8176.__init__(self, tcid=tcid)
        self.newPriority = True

class TC8426(xenrt.TestCase):
    """Verify guest creation of messages is blocked"""

    def prepare(self, arglist=None):
        self.host = self.getDefaultHost()
        self.guest = self.host.createGenericLinuxGuest()

    def run(self, arglist=None):
        beforeCount = len(self.host.minimalList("message-list"))
        self.guest.execguest("xenstore-write "
              "/local/domain/$(xenstore-read domid)/messages/foo/XENRT/1/body"
              " \"Testing\"")
        afterCount = len(self.host.minimalList("message-list"))

        if afterCount > beforeCount:
            raise xenrt.XRTFailure("Guest appears to be allowed to create a "
                                   "message")

class _AlertBase(xenrt.TestCase):

    PERFMON = None
    CLASS="Host"
    MESSAGES=[]
    VARIANCE=150
    INTELLICACHE=False  # Required only for storage alerts
    PRIORITY=3

    def enableAlertonHost(self, host, perfmon=PERFMON, alarmLevel="4E30", alarmTriggerPeriod="60", alarmAutoInhibitPeriod="300"):
        """This defaults to setting an alert with repeat time of 1 min and perfmon poll time of 5 min 
        xe host-param-set other-config:
        perfmon='<config><variable><name value="network_usage" /><alarm_trigger_level value="2" />
        <alarm_trigger_period value="30" /><alarm_auto_inhibit_period value="300" /></variable></config>' """

        # Start on a clean slate
        self.deleteAllAlarms(host)

        # Check if alarm of requested type is already enabled
        try:
            enableFlag=host.getHostParam("other-config","perfmon")
        except:
            enableFlag = ""
        if re.search(perfmon, enableFlag, re.IGNORECASE):
            self.origXrtTime = xenrt.timenow()
            return

        cmdXML ="<config><variable><name value=\'%s\' />" \
                "<alarm_trigger_level value=\'%s\' />" \
                "<alarm_trigger_period value=\'%s\' />" \
                "<alarm_auto_inhibit_period value=\'%s\' />" \
                "</variable></config>" % \
                (perfmon, alarmLevel, alarmTriggerPeriod, alarmAutoInhibitPeriod)
        param="other-config:perfmon"
        host.setHostParam(param, cmdXML)

        self.origXrtTime = xenrt.timenow()
        xenrt.log("Alert enabled at time - %s" % self.origXrtTime)

        xenrt.log("Verify the other-config parameters for perfmon")
        self.verifyOtherConfigCmd(host)
        
    def enableAlertonSR(self, host, sruuid, perfmon=PERFMON, alarmLevel="0.0009765625", alarmTriggerPeriod="60", alarmAutoInhibitPeriod="300"):
        """This defaults to setting an alert with repeat time of 1 min and perfmon poll time of 5 min for 1 KB/min
        xe sr-param-set other-config:
        perfmon='<config><variable><name value="sr_io_throughput_total_per_host" /><alarm_trigger_level value="0.0009765625" />
        <alarm_trigger_period value="60" /><alarm_auto_inhibit_period value="300" /></variable></config>' """

        cli = host.getCLIInstance()
        # Start on a clean slate
        self.deleteAllAlarms(host)

        # Check if alarm of requested type is already enabled
        try:
            enableFlag=cli.execute('sr-param-get',
                                    'param-key="other-config" param-name="perfmon" uuid=%s' %
                                    sruuid)
        except:
            # We dont really want to do anything with the exception
            enableFlag=""

        if re.search(perfmon, enableFlag, re.IGNORECASE):
            return

        cmdXML ="<config><variable><name value=\'%s\' />" \
                "<alarm_trigger_level value=\'%s\' />" \
                "<alarm_trigger_period value=\'%s\' />" \
                "<alarm_auto_inhibit_period value=\'%s\' />" \
                "</variable></config>" % \
                (perfmon, alarmLevel, alarmTriggerPeriod, alarmAutoInhibitPeriod)
        param="other-config:perfmon"
        # Set param on sr
        cli.execute("sr-param-set",
                    "uuid=%s %s=\"%s\"" % 
                    (sruuid, param, cmdXML))
        self.origXrtTime = xenrt.timenow()
        xenrt.log("Alert enabled at time - %s" % self.origXrtTime)
        
        xenrt.log("Verify the other-config parameters for perfmon")
        self.verifyOtherConfigCmd(host, alertClass="sr", uuid=sruuid)
        
    def verifyOtherConfigCmd(self, host, alertClass=CLASS, uuid=None):
        """Verify if the xml in the other-config:perfmon param set is valid"""
        if alertClass.lower() == "host":
            uuid = host.uuid
        elif not uuid:
            raise xenrt.XRTError("UUID of the object not specified")
                
        out=host.execdom0("xe %s-param-get uuid=%s param-name=other-config param-key=perfmon | xmllint --format -" % 
                            (alertClass.lower(), uuid))
        
        if re.search("parser error", out):
            raise xenrt.XRTError("xml parser error - the other-config perfmon xml not formed well %s" % out)

    def verifyAlertMsgs(self, host, alarmAutoInhibitPeriod="200", perfmon=PERFMON, aClass=CLASS, priority=PRIORITY):
        """Make sure that we wait for the alert repeat time interval and then check for alert listings"""
        xenrt.log("verifyAlertMsgs: The time that the alert was enabled is %s" %
                    self.origXrtTime)
        timeDiff =  xenrt.timenow() - self.origXrtTime
        temp=alarmAutoInhibitPeriod - timeDiff
        xenrt.log("verifyAlertMsgs: The time difference is %s, will need to sleep" % 
                    (temp) )

        # Allow 100 as a variance
        while (timeDiff < alarmAutoInhibitPeriod+self.VARIANCE):
            if (timeDiff < 0 or alarmAutoInhibitPeriod < timeDiff):
                break

            # Allow the configured interval to complete before we check for ALARM messages
            xenrt.sleep(alarmAutoInhibitPeriod+self.VARIANCE - timeDiff)
            timeDiff =  xenrt.timenow() - self.origXrtTime
            temp=alarmAutoInhibitPeriod - timeDiff
            xenrt.log("verifyAlertMsgs: Inside while: The time difference is %s, will need to sleep" %
                        (temp))

        self.messageGet(host, aClass=aClass, perfmon=perfmon, priority=priority)
        if len(self.MESSAGES) >= 2:
            self.verifyAlertIntervals(host=host, 
                                        mesages=self.MESSAGES, 
                                        alarmAutoInhibitPeriod=alarmAutoInhibitPeriod)
            # Verify the difference in the timestamps to be around 5 min - 300 secs
            xenrt.TEC().logverbose("verifyAlertMessages, inside len(MESSAGES) >1: Returning true")
            return True
        elif len(self.MESSAGES) == 1:
            xenrt.log("Number of alerts available are %s" %
                        len(self.MESSAGES))
            self.waitForAlert(alarmAutoInhibitPeriod=alarmAutoInhibitPeriod)
            self.messageGet(host=host, aClass=aClass, perfmon=perfmon, priority=priority)

            # Verify the difference in the timestamps to be around 5 min - 300 secs
            self.verifyAlertIntervals(host, 
                                        mesages=self.MESSAGES, 
                                        alarmAutoInhibitPeriod=alarmAutoInhibitPeriod)
            xenrt.TEC().logverbose("verifyAlertMessages, inside len(MESSAGES)==1: Returning true")
            return True
            
        xenrt.TEC().logverbose("MessageGet: Returning False")
        return False

    def verifyAlertIntervals(self, host, alarmAutoInhibitPeriod, mesages=MESSAGES):
        if len(self.MESSAGES)<2:
            # Fail if alerts generated is less than 2
            raise xenrt.XRTFailure("Alerts not getting generated at the configured interval, only one present so far")
        cli = host.getCLIInstance()
        xenrt.log("Alerts available for the specified perfmon, verifying repeat interval %s sec" % 
                    alarmAutoInhibitPeriod)
                    
        t1=cli.execute("message-param-get", "param-name=timestamp uuid=%s" %
                            self.MESSAGES[0]).strip()
        t2=cli.execute("message-param-get", "param-name=timestamp uuid=%s" %
                            self.MESSAGES[1]).strip()
            
        xenrt.TEC().logverbose("Timestamps for the first and second alert are %s and %s " % (t1,t2))
        # Get the relevant substring out of the timestamps for minutes passed
        interval=int(t1[t1.find("T")+1:t1.find("Z")].split(":")[1])-int(t2[t2.find("T")+1:t2.find("Z")].split(":")[1])

        if interval <= (alarmAutoInhibitPeriod+self.VARIANCE)/60:
            xenrt.TEC().logverbose("verifyAlertIntervals: Check passed, alerts are getting generated at the right" \
                                    "interval (includng the variance of %s secs" % self.VARIANCE)
        else :
            xenrt.TEC().warning("Expected alert interval of %s seconds, instead they are generated at %s minutes" %
                                    (alarmAutoInhibitPeriod, interval))

    def setPerfmonDebugMode(self, host):
        perfmLog = "/etc/sysconfig/perfmon"
        debugFlag = self.getPerfmonMode(host)

        if not debugFlag:
            host.execdom0('echo "PERFMON_FLAGS=\\"\$PERFMON_FLAGS --debug\\"" >> %s' % perfmLog)
            host.execdom0('service perfmon restart')
            return self.getPerfmonMode(host)
        return debugFlag

    def getPerfmonMode(self, host):
        # Verify perfmon start mode
        retVal = host.execdom0("ps -ef | grep '[p]erfmon'")
        if retVal and re.search("--debug", retVal):
            return True
        return False

    def deleteAllAlarms(self, host):
        alarms = host.minimalList("message-list name=ALARM class=Host")
        for id in alarms:
            host.execdom0('xe message-destroy uuid=%s' % id)

        xenrt.log("Checking if all the messages of type ALARM are deleted")
        alarms = host.minimalList("message-list name=ALARM class=Host")
        if alarms:
            raise xenrt.XRTFailure("Messages of type ALARM are not entirely removed")

    def messageGet(self, host, name="ALARM", aClass=CLASS, priority=PRIORITY, perfmon=PERFMON):
        """ Check if there is an alert of type perfmon"""
        cli = host.getCLIInstance()
        if not perfmon:
            raise xenrt.XRTError("Please specify perfmon type")
        out=cli.execute("message-list", "name=%s class=%s priority=%s --minimal" % 
                            (name, aClass, priority)).strip()
        for uuid in out.split(','):
            trueFlag = cli.execute('message-list', 'uuid=%s params=body | grep %s' % 
                                        (uuid, perfmon), ignoreerrors=True)
            if trueFlag:
                if uuid in self.MESSAGES:
                    return

                xenrt.log(cli.execute('message-list', 'uuid=%s' % uuid))
                self.MESSAGES.append(uuid)

    def createWindowsVM(self, host, distro="win7-x64", memory=4000, arch="x86-64", disksize=28843545600, srtype="DEFAULT", waitForStart=False):
        """Trigger a windows install without having to wait for it to install completely"""
        if not waitForStart:
            template = xenrt.lib.xenserver.getTemplate(host, distro=distro, arch=arch)
            xenrt.TEC().logverbose("Setup for %s" % (distro))
            guest=host.createGenericEmptyGuest(memory=memory, name=xenrt.randomGuestName())
            device=guest.createDisk(sizebytes=disksize, bootable=True, sruuid=srtype)
            guest.changeCD(distro + ".iso")
            guest.start()
            # Allow some time for the vm to start
            xenrt.sleep(20)
        else:
            device=0
            disksize=disksize/xenrt.MEGA
            guest=host.createGenericWindowsGuest(sr=srtype, distro=distro,disksize=disksize,memory=memory)

        if self.INTELLICACHE:
            cli=host.getCLIInstance()
            if guest.getState() != "DOWN":
                guest.shutdown(force=True)
            vbd=cli.execute("vbd-list", "userdevice=%s vm-uuid=%s --minimal" % 
                            (device, guest.uuid)).strip()
            vdi=cli.execute("vdi-list","vbd-uuids=%s --minimal" % vbd).strip()
            cli.execute("vdi-param-set","allow-caching=true uuid=%s" % vdi)
            guest.start()

    def waitForAlert(self, alarmAutoInhibitPeriod):
        xenrt.sleep(alarmAutoInhibitPeriod+self.VARIANCE)


class MemoryAlerts(_AlertBase):

    ALARMLEVEL=None
    ALARMTRIGGERPERIOD=60
    ALARMAUTOINHIBITPERIOD=300
    PERFMON="memory_free_kib"
    VARIANCE=200

    def prepare(self, arglist=None):
        """Fill up the host so that alerts can get generated"""
        self.host = self.getHost("RESOURCE_HOST_0")
        self.MESSAGES=[]
        cli=self.host.getCLIInstance()
        # Set the alarm level to the maximum possible
        self.ALARMLEVEL=int(self.host.getMaxMemory())*1024
        numVMs=6
        mem=self.host.getMaxMemory()/numVMs-70

        # check if there is sufficient memory to even install a single VM, return if no sufficient resource
        if mem < 1024:
            raise xenrt.XRTError("Machine memory not sufficient to run this test")

        # Setup
        self.setPerfmonDebugMode(self.host)
        self.enableAlertonHost(host=self.host, 
                                perfmon=self.PERFMON,
                                alarmLevel=self.ALARMLEVEL,
                                alarmTriggerPeriod=self.ALARMTRIGGERPERIOD,
                                alarmAutoInhibitPeriod=self.ALARMAUTOINHIBITPERIOD)
        # Get disk size and divide by num VMs to be installed
        srSize=cli.execute('sr-param-get', 'param-name=physical-size uuid=%s' % 
                                    self.host.getLocalSR()).strip()
        diskSize=int(float(srSize)/(numVMs))-xenrt.GIGA
        xenrt.TEC().logverbose("Disk size of each VM %s" % diskSize)

        if diskSize < (23*xenrt.GIGA):
            raise xenrt.XRTError("Machine local SR not sufficient to run this test")

        # Check Product version, for clearwater priority=5, post CLW, priority=3
        if not isinstance(self.host, xenrt.lib.xenserver.DundeeHost) and not isinstance(self.host, xenrt.lib.xenserver.CreedenceHost):
            self.PRIORITY=5

        # Setup required to generate memory alerts
        for i in range(numVMs-1):
            self.createWindowsVM(host=self.host, memory=mem, disksize=diskSize)
        memLeft=self.host.getMaxMemory()-500
        xenrt.TEC().logverbose("Host memory at this point is %s " % self.host.getMaxMemory())
        xenrt.TEC().logverbose("Installing the last VM with memory %s " % memLeft)
        if memLeft > 1024:
            #Install the last VM
            self.createWindowsVM(host=self.host, memory=memLeft, disksize=diskSize, waitForStart=True)
        xenrt.TEC().logverbose("Memory left after install %s" % str(memLeft-500))

    def run(self, arglist=None):
        ret=self.verifyAlertMsgs(host=self.host, 
                                    alarmAutoInhibitPeriod=self.ALARMAUTOINHIBITPERIOD, 
                                    perfmon=self.PERFMON, priority=self.PRIORITY)

        if not ret:
            # Force a read of the perfmon
            self.host.execdom0("xe host-call-plugin host-uuid=%s plugin=perfmon fn=refresh" % self.host.uuid)
            time.sleep(60)

            ret=self.verifyAlertMsgs(host=self.host, 
                                        alarmAutoInhibitPeriod=self.ALARMAUTOINHIBITPERIOD, 
                                        perfmon=self.PERFMON, priority=self.PRIORITY)
            if not ret:
                raise xenrt.XRTFailure('No alerts raised even after the force read of perfmon %s' % self.PERFMON)

    def postRun(self):
        self.host.uninstallAllGuests()
        cli = self.host.getCLIInstance()
        # Disable alerts
        cli.execute('host-param-remove','param-name="other-config" param-key="perfmon" uuid=%s' % self.host.uuid)


class MemoryAlertsonUpgrade(MemoryAlerts):

    def prepare(self, arglist=None):
        old = xenrt.TEC().lookup("OLD_PRODUCT_VERSION")
        oldversion = xenrt.TEC().lookup("OLD_PRODUCT_INPUTDIR")
        # start with a n-1 host
        self.host = xenrt.lib.xenserver.createHost(id=0,
                                                   version=oldversion,
                                                   productVersion=old,
                                                   withisos=True)
        # Upgrade
        self.host.upgrade()
        self.VARIANCE=200
        MemoryAlerts.prepare(self)

class _GenerateIOonSR(xenrt.XRTThread):
    """This thread run in the background on dom0 and moves/copys VDIs to generate SR activity, 
    supports only 1 host, and 1 SR at a time"""

    def __init__(self, host, sruuid):
        xenrt.XRTThread.__init__(self, name="GenerateIOonSR")

        self.host = host
        self.sr=sruuid
        self.daemon = True
        # Keep track of the created vdis
        self.created = []
        self.cli = self.host.getCLIInstance()

    def getAvailableSpace(self, sruuid):
        srType=self.cli.execute("sr-param-get", "uuid=%s param-name=type" % self.sr)
        return True

    def shutdownAllVMs(self):
        vmuuids=self.cli.execute("vm-list", "is-control-domain=\"false\" --minimal").strip().split(",")
        for vms in vmuuids:
            vmstate = self.cli.execute("vm-param-get", "param-name=power-state uuid=%s" % vms)
            if re.search("running", vmstate, re.IGNORECASE):
                self.cli.execute("vm-shutdown", "uuid=%s --force" % vms)
        return True

    def deleteVDIs(self):
        for uuid in self.created:
            xenrt.TEC().logverbose("Deleting created vdis to make more space")
            xenrt.log("Remaining vdis: %s " % self.created)
            try:
                self.cli.execute("vdi-destroy", "uuid=%s" % uuid)
            except Exception, e:
                xenrt.TEC().logverbose("Caught exception in delete vdi " + str(e))
            finally:
                self.created.remove(uuid)

    def run(self):
        xenrt.sleep(90)
        self.shutdownAllVMs()
        while self.getAvailableSpace(self.sr):
            xenrt.TEC().logverbose("Starting to move vdis to generate IO on SR %s" % self.sr)

            vdis=self.cli.execute("vdi-list", "name-label=\"Created by XenRT\" sr-uuid=%s --minimal" %
                           self.sr ).strip()
            xenrt.TEC().logverbose("Found the following vdis to be moved - %s " % vdis)
            if not vdis:
                sys.exit()
            try:
                vdis=vdis.split(",")
                for uuid in vdis:
                    newvdi=self.cli.execute("vdi-copy", "sr-uuid=%s uuid=%s" %
                                                (self.sr, uuid)).strip()
                    self.created.append(newvdi)
                    xenrt.sleep(20)
                    xenrt.TEC().logverbose("Created so many vdis - %s " % self.created)
                    if len(self.created) > 10:
                        # Delete vdis
                        self.deleteVDIs()
            except SystemExit, e:
                xenrt.log("Thread is here, it is a stale thread")
                return
            except Exception, e:
                xenrt.TEC().logverbose("Caught exception in thread " + str(e))
                # Delete all the created vdis to create more space
                self.deleteVDIs()


class StorageAlerts(_AlertBase):

    SRTYPE="Local"  #lvm
    ALARMLEVEL="0.0009765625"   # 1 KB
    ALARMTRIGGERPERIOD=60
    ALARMAUTOINIHIBITPERIOD=300
    PERFMON="sr_io_throughput_total_per_host"

    def prepare(self, arglist=None):
        self.MESSAGES=[]
        self.VARIANCE=250
        """Fill up the host so that alerts can get generated"""
        self.host = self.getHost("RESOURCE_HOST_0")
        numVDIs=2

        # Enable the non-default DS
        self.host.execdom0("xe-enable-all-plugin-metrics true")
        # Verify Xapi is running, because a xe-toolstack-restart is performed
        self.host.waitForXapi(300, desc="Waiting for Xapi....")

        # Setup
        self.setPerfmonDebugMode(self.host)
        if self.SRTYPE.lower() == "local":
            self.uuid=self.host.getLocalSR()
        else:
            if self.SRTYPE.lower() == "nfs":
                srToTest="nfs"
            elif self.SRTYPE.lower() == "iscsi":
                srToTest = "lvmoiscsi"
            self.uuid=self.host.execdom0("xe sr-list type=%s --minimal" % 
                                    srToTest).strip()
        if not self.uuid:
            raise xenrt.XRTError("SR Alerts: Setup failed, no SR of type %s available" % 
                                    srToTest)
        self.enableAlertonSR(sruuid=self.uuid, 
                            host=self.host, 
                            perfmon=self.PERFMON,
                            alarmLevel=self.ALARMLEVEL,
                            alarmTriggerPeriod=self.ALARMTRIGGERPERIOD,
                            alarmAutoInhibitPeriod=self.ALARMAUTOINIHIBITPERIOD)

        #Create a generic linux guest
        guest = self.host.createGenericLinuxGuest(sr = self.uuid)
        self.uninstallOnCleanup(guest)
        
        for i in range(numVDIs):
            #Create VDI of size 10GB to generate storage alerts by copying and destroying it multiple times.
            device = guest.createDisk(sizebytes=2*xenrt.GIGA, sruuid=self.uuid, returnDevice=True)
            time.sleep(5)
            #Fill some space on the VDI 
            guest.execguest("mkfs.ext3 /dev/%s" % device)
            guest.execguest("mount /dev/%s /mnt" % device)
            xenrt.TEC().logverbose("Creating some random data on VDI.")
            guest.execguest("dd if=/dev/zero of=/mnt/random oflag=direct bs=1M count=1000")

        if self.INTELLICACHE:
            cli=self.host.getCLIInstance()
            if guest.getState() != "DOWN":
                guest.shutdown(force=True)
            for vdi in self.host.minimalList("vdi-list",
                                                 args="sr-uuid=%s" % (self.uuid)): 
                cli.execute("vdi-param-set","allow-caching=true uuid=%s" % vdi)
            guest.start()
        
        memLeft=self.host.getMaxMemory()
        xenrt.TEC().logverbose("SR Alerts: Memory left after install %s" % memLeft)
        # Check Product version, for clearwater priority=5, post CLW, priority=3
        if not isinstance(self.host, xenrt.lib.xenserver.DundeeHost):
            self.PRIORITY=5

        # Start the sr spammer thread here
        self.srSpammer = _GenerateIOonSR(self.host, self.uuid)
        self.srSpammer.start()

    def additionalVerification(self, host, msglist):
        xenrt.log("Additional check to ensure the alerts"
                                "are generated for the SR under test")
        xenrt.log(msglist)
        perfmon1=host.execdom0('xe message-param-get param-name=body uuid=%s | grep "configured_on" | cut -d\'"\' -f4' % 
                                msglist[0]).strip()
        xenrt.log("Perfmon name retrieved %s" %
                                perfmon1)
        perfmon2=host.execdom0('xe message-param-get param-name=body uuid=%s | grep "configured_on" | cut -d\'"\' -f4' % 
                                msglist[1]).strip()
        xenrt.TEC().logverbose("Perfmon name retrieved %s" %
                                perfmon2)
        # Verify uuid of sr in the perfmon
        if not re.search(perfmon1, self.uuid, re.IGNORECASE):
            xenrt.log(host.execdom0("xe message-list uuid=%s" % 
                                    msglist[0]))
            raise xenrt.XRTFailure("Generated alerts are not for the configured SR")
        if not re.search(perfmon2, self.uuid, re.IGNORECASE):
            xenrt.log(host.execdom0("xe message-list uuid=%s" % 
                                    msglist[1]))
            raise xenrt.XRTFailure("Generated alerts are not for the configured SR")

    def run(self, arglist=None):
        # Let the srspammer run for a while and generate some traffic on the SR
        xenrt.sleep(self.VARIANCE+self.VARIANCE)
        # Hack to fool the test that the alert was enabled now
        self.origXrtTime=xenrt.timenow()

        ret=self.verifyAlertMsgs(host=self.host,
            alarmAutoInhibitPeriod=self.ALARMAUTOINIHIBITPERIOD,
            perfmon="sr_io_throughput")
        if not ret:
            # Force a read of the perfmon
            xenrt.TEC().logverbose("Trying a force read of the perfmon to see if any alerts present")
            self.host.execdom0("xe host-call-plugin host-uuid=%s plugin=perfmon fn=refresh" % self.host.uuid)
            time.sleep(60)

            ret=self.verifyAlertMsgs(host=self.host,
                                    alarmAutoInhibitPeriod=self.ALARMAUTOINIHIBITPERIOD,
                                    perfmon="sr_io_throughput",
                                    priority=self.PRIORITY)
            if not ret:
                raise xenrt.XRTFailure('No alerts raised even after the force read of perfmon %s' % self.PERFMON)
        if not "local" in self.SRTYPE.lower():
            self.additionalVerification(host=self.host, msglist=self.MESSAGES)

    def postRun(self):
        self.host.uninstallAllGuests()
        cli = self.host.getCLIInstance()
        # Disable alerts
        cli.execute('sr-param-remove','param-name="other-config" param-key="perfmon" uuid=%s' % self.uuid)
        # Clear up all the vdis
        for uuid in cli.execute('vdi-list', 'sr-uuid=%s --minimal' % self.uuid).strip().split(','):
            cli.execute('vdi-destroy', 'uuid=%s --force' % uuid)

class TC19830(StorageAlerts):
    """SR Alerts after upgrade from an older version (Tampa)"""
    
    def prepare(self, arglist=None):
        old = xenrt.TEC().lookup("OLD_PRODUCT_VERSION")
        oldversion = xenrt.TEC().lookup("OLD_PRODUCT_INPUTDIR")
        # start with a n-1 host
        self.host = xenrt.lib.xenserver.createHost(id=0,
                                                   version=oldversion,
                                                   productVersion=old,
                                                   withisos=True)
        # Upgrade
        self.host.upgrade()
        StorageAlerts.prepare(self)
        
    
class TC18678(StorageAlerts):
    """SR alerts on EXT"""
    SRTYPE="NFS" #ext

class TC18679(StorageAlerts):
    """SR alerts on lvmoiscsi"""
    SRTYPE="ISCSI" #lvmosiscsi

class TC18680(StorageAlerts):
    """SR alerts with Intellicache enabled"""
    SRTYPE="NFS"
    INTELLICACHE=True

    def prepare(self, arglist=None):
        self.host = self.getHost("RESOURCE_HOST_0")
        cli = self.host.getCLIInstance()
        # Verify is the local SR of the machine is thin provisioned,
        # only then intellicache is supported
        srType=cli.execute("sr-param-get","param-name=type uuid=%s" %
                            self.host.getLocalSR()).strip()
        if not "ext" in srType:
            raise xenrt.XRTError("Local storage of the host does not support thin provisioning")
        try:
            xenrt.sleep(50)
            self.host.disable()
            self.host.enableCaching(self.host.getLocalSR())
        except Exception, e:
            raise xenrt.XRTFailure("Enabling intellicache failed with exception %s" % e)
        finally:
            self.host.enable()
        StorageAlerts.prepare(self, arglist)
