#
# XenRT: Test harness for Xen and the XenServer product family
#
# JIRA Link Functions
#
# Copyright (c) 2007 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import xenrt
import os, os.path, re, urllib, urllib2, string, inspect, traceback, sys, fcntl, xml.dom.minidom
import glob
import jirarest.client

__all__ = ["JiraLink", "getJiraLink"]

class JiraLink(object):
    """XenRT Jira Link"""

    TRIAGE = "10760"
    TRIAGEDEV = "11891"
    DEFAULT_ASSIGNEE = "svcacct_xs_xenrt"

    def __init__(self):
        # JIRA settings
        self.JIRA_URL = xenrt.TEC().lookup("JIRA_URL", None) 
        self.JIRA_USER = xenrt.TEC().lookup("JIRA_USERNAME")
        self.JIRA_PASS = xenrt.TEC().lookup("JIRA_PASSWORD")

        self.FAIL_PROJ = xenrt.TEC().lookup("JIRA_FAIL", "CA")
        self.ERR_PROJ = xenrt.TEC().lookup("JIRA_ERROR", "CA")

        self.TRACK_FIELD = xenrt.TEC().lookup("JIRA_TRACK", "autofileRef")
        self.TRACK_TAG = xenrt.TEC().lookup("JIRA_TRACK_TAG", None)

        self.XENRT_WEB = xenrt.TEC().lookup("JIRA_XENRT_WEB", 
                              "https://xenrt.citrite.net/control/queue.cgi")

        self.TESTRUN_URL = xenrt.TEC().lookup("TESTRUN_URL", None)
        self.customFields = None

        self.connected = False
        self.tickets = {}

        self._bufferdir = xenrt.GEC().config.lookup("JIRA_BUFFER_DIR", None)
        if self._bufferdir and not os.path.exists(self._bufferdir):
            os.makedirs(self._bufferdir)

    def getJiraExceptionText(self, exception):
        try:
            return str(exception)
        except UnicodeEncodeError:
            return 'HTTP {0}: "{1}"\n{2}'.format(exception.status_code, exception.text.encode('ascii', 'ignore'), exception.url)

    @property
    def jira(self):
        self.attemptToConnect()
        return self._jira

    def attemptToConnect(self):
        """If we've not already established a 'connection' with Jira then
        try again. Return the connected status."""
        if not self.connected:
            try:
                self._jira = jirarest.client.JIRA(options={'server': self.JIRA_URL}, basic_auth=(self.JIRA_USER, self.JIRA_PASS))
                self._jira.session()
                self.connected = True
            except jirarest.exceptions.JIRAError, e:
                traceback.print_exc(file=sys.stderr)
                xenrt.TEC().logverbose("JiraLink Exception: %s" % (self.getJiraExceptionText(e)))
            except Exception, e:
                traceback.print_exc(file=sys.stderr)
                xenrt.TEC().logverbose("JiraLink Exception on connect: %s" %
                                       (str(e)))
        return self.connected

    def isIssueOpen(self, issueKey):
        """Returns a boolean indicating if the provided issue is open"""
        i = self.jira.issue(issueKey)
        return i.fields.resolution is None

    def getSnippet(self, logfilename, pattern, patterndesc, startPoint=0, endPoint=4096):
        """Returns a snippet string containing log matched in logfile"""
        noformattext = str(xenrt.command("pcregrep -M '%s' %s" % (pattern, logfilename) , level=xenrt.RC_OK))
        noformattext = noformattext.strip()
        if noformattext!="1":
            if(len(noformattext)) > (endPoint - startPoint) and abs(endPoint) <= (len(noformattext)) and abs(startPoint) <=(len(noformattext)):
                noformattext = noformattext[startPoint:endPoint] + "\n\n..."
            snippet = ("Found '%s' in '%s':- \n{noformat}\n%s\n{noformat}" % (patterndesc,logfilename.replace(xenrt.TEC().getLogdir()+"/", ""),noformattext.strip()))
            return snippet
        return ""

    def getFailedLogSnippetsFromPattern(self):
        """Returns a string containing possible reason of failure from logs"""

        failurepatterns =   [
            ## Log files to be pathed with reference to TEC.logdir
            # xenrt.log
            {'file':"xenrt.log", 'desc':"Generic Failure Log",
                'pattern':r'(?:.*\n){0,4}(?:\[VERBOSE\].*Traceback.*\n)(?:.*\n){0,24}(?:\[REASON.*\n)(?:.*\n){0,2}'},

            # console*
            {'file':"console*", 'desc':"Host Out of memory",
                'pattern':r'(?:.*\n){0,4}.*\] Out of memory\: Kill process.*(?:.*\n){0,4}'},
            {'file':"console*", 'desc':"INFO",
                'pattern':r'(?:.*\n){0,5}.*\] INFO\: .*(?:.*\n){0,10}'},
            {'file':"console*", 'desc':"Call Trace",
                'pattern':r'(?:.*\n){0,6}.* [cC]all [tT]race(?:.*\n){0,24}'},

            # host-serial-log-*
            {'file':"host-serial-log-*", 'desc':"Blocked Tasks",
                'pattern':r'(?:.*\n){0,4}.*INFO\: task .*? blocked for more than \d*? seconds\.(?:.*\n){0,4}'},
            {'file':"host-serial-log-*", 'desc':"Kernel BUG",
                'pattern':r'(?:.*\n){0,4}.*\] kernel BUG at .*(?:.*\n){0,6}'},
            {'file':"host-serial-log-*", 'desc':"Stacked Call Trace",
                'pattern':r'(?:.*\n){0,6}.*\] Call Trace\:(?:.*\n){0,14}'},
            {'file':"host-serial-log-*", 'desc':"CPU stuck",
                'pattern':r'(?:.*\n){0,6}.*\] Watchdog timer detects that .* is stuck!(?:.*\n){0,14}'},
            {'file':"host-serial-log-*", 'desc':"cut here",
                'pattern':r'\n.*\] ------------\[ cut here \]------------(?:.*\n)*?.*\] ---\[ end trace .*---.*'},

            # [HOST_NAME]/kern.log
            {'file':"*/kern.log", 'desc':"cut here",
                'pattern':r'\n.*\] ------------\[ cut here \]------------(?:.*\n)*?.*\] ---\[ end trace .*---.*'},

            # [HOST_NAME]/daemon.log
            {'file':"*/daemon.log", 'desc':"BUGCHECK",
                'pattern':r'\n.*BUGCHECK: ====>(?:.*\n)*?.*BUGCHECK: <====.*'},

            # [GUEST_NAME]/messages
            {'file':"*/messages", 'desc':"cut here",
                'pattern':r'\n.*: ------------\[ cut here \]------------(?:.*\n)*?.*: ---\[ end trace .*---.*'},

            # [GUEST_NAME]/guest-console-logs/console*
            {'file':"*/guest-console-logs/console*", 'desc':"cut here",
                'pattern':r'\n.*\] ------------\[ cut here \]------------(?:.*\n)*?.*\] ---\[ end trace .*---.*'},
            {'file':"*/guest-console-logs/console*", 'desc':"Network autoconfig using DHCP failed",
                'pattern':r'(?:.*\n){0,1}(?:.*Network autoconfiguration failed.*)(?:.*\n){0,4}'},
#            {'file':"*/guest-console-logs/console*", 'desc':"Guest Stacked Call Trace", 'ignoreAfter': "SysRq :",
#                'pattern':r'(?:.*\n){0,2}(?:.*Call Trace\:.*)(?:.*\n){0,10}'},
            {'file':"*/guest-console-logs/console*", 'desc':"Guest GRUB Installation failure",
                'pattern':r'(?:.*\n){0,20}(?:.*GRUB installation failed.*)(?:.*\n){0,4}'},
            {'file':"*/guest-console-logs/console*", 'desc':"Guest BUG",
                'pattern':r'(?:.*\n){0,2}(?:.*BUG\:.*)(?:.*\n){0,3}'},
            {'file':"*/guest-console-logs/console*", 'desc':"Kernel Panic",
                'pattern':r'(?:.*\n){0,4}(?:.*Kernel panic.*)(?:.*\n){0,4}'},

#            {'file':"*/cloudstack/management/management-server.log*", 'desc':"Management server Exception logs",
#                'pattern':r'(?:.*\n){0,1}(?:.*Exception\:.+)(?:.*\n){0,4}','type':"CLOUD",'startPoint':-8192,'endPoint':-1},

#            {'file':"*/cloudstack/management/management-server.log*", 'desc':"Management server Error logs",
#                'pattern':r'(?:.*\n){0,1}(?:.*ERROR.+)(?:.*\n){0,4}','type':"CLOUD",'startPoint':-8192,'endPoint':-1},

#            {'file':"*/cloudstack/management/apilog.log*", 'desc':"API logs",
#                'pattern':r'(?:.*\n){0,5}(?:.*exception.+)(?:.*\n){0,5}','type':"CLOUD"},

            {'file':"*/cloudstack/management/localhost*", 'desc':"Local Host log",
                'pattern':r'(?:.*\n){0,1}(?:.*SEVERE\:.+)(?:.*\n){0,10}','type':"CLOUD",'startPoint':-8192,'endPoint':-1},

#            {'file':"*/cloudstack/agent.log*", 'desc':"Agent logs",
#                'pattern':r'(?:.*\n){0,1}(?:.*Exception\:.+)(?:.*\n){0,4}','type':"CLOUD",'startPoint':-8192,'endPoint':-1}
        ]
        desc = "\n"
        for fp in failurepatterns:
            try:
                clogfiles = glob.glob("%s/%s" % (xenrt.TEC().getLogdir(),fp['file']))
            except Exception, e:
                if not fp.has_key('type'):
                    xenrt.TEC().warning("Failed to get logfile list matching '%s': %s" %(fp['file'],str(e)))
            for file in clogfiles:
                try:
                    if fp.has_key('startPoint'):
                        desc += self.getSnippet(file, fp['pattern'], fp['desc'],startPoint=fp['startPoint'], endPoint=fp['endPoint'])
                    else:
                        desc += self.getSnippet(file, fp['pattern'], fp['desc'])
                    desc += "\n"
                except Exception, e:
                    xenrt.TEC().warning("Failed to get snippet from file %s: %s" %(file,str(e)))
        return desc

    def processPrepare(self,tec,reason):
        """Handle an error during a prepare action"""
        if not self.attemptToConnect():
            xenrt.GEC().logverbose("Jira not connected, not filing bug",
                                   pref='WARNING')
            return

        if not self.JIRA_URL:
            xenrt.GEC().logverbose("No Jira URL found, not filing bug",
                                   pref='WARNING')
            return

        ikey = None
        seq = tec.lookup("SEQUENCE_NAME","Unknown")
        jobid = xenrt.GEC().dbconnect.jobid()
        ver = tec.lookup("VERSION","")
        rev = tec.lookup(["CLIOPTIONS", "REVISION"], "Unknown")
        revision = "%s-%s" % (ver,rev)
        hosts = xenrt.GEC().config.getWithPrefix("RESOURCE_HOST_")
        jobdesc = tec.lookup("JOBDESC", None)
        
        hostsStr = ""
        if len(hosts) > 0:
            for h in hosts:
                hostsStr += "%s, " % (h[1])
            hostsStr = hostsStr[:-2]
        environment = "XenRT JobID: %s, seq: %s, revision: %s, host(s): " \
                      "%s" % (jobid,seq,revision,hostsStr)
        if jobdesc:
            environment += "\n%s" % (jobdesc)
        inputdir = xenrt.TEC().lookup(xenrt.TEC().lookup("AUTO_BUG_INPUTDIR", "INPUTDIR"), None)
        if inputdir:
            environment += "\nInput Directory: %s" % (inputdir)
        tsr = xenrt.TEC().lookup("TESTRUN_SR",None)
        if tsr:
            environment += "\nTestRun Suite Run ID: %s" % (tsr)
        jenkins = xenrt.TEC().lookup("JENKINS_URL", None)
        if jenkins:
            environment += "\nJenkins URL: %s" % jenkins
        ccpCommit = xenrt.TEC().lookup("CCP_EXPECTED_COMMIT", None)
        if ccpCommit:
            environment += "\nCCP Commit: %s" % ccpCommit
        environment += "\nXenRT Job URL: https://xenrt.citrite.net/xenrt/minimalframe?jobs=%s" % jobid
        seenagain = ("Seen again on %s\n" % (environment))

        assignee = xenrt.TEC().lookup("AUTO_BUG_ASSIGNEE",None)

        sstr = "Prepare: %s" % (reason)
        (i, new) = self.fileTicket("error",("Prepare","Error",reason),
                                   sstr,"",environment,seenagain,assignee,hosts,None)

        if i:
            xenrt.GEC().prepareticket = i.key

        if i and new:
            # Created a new ticket, attach xenrt.log (or what we have of it)
            tec.flushLogs()
            f = open("%s/xenrt.log" % (tec.getLogdir()))
            self.jira.add_attachment(i.key, f)
            f.close()

            try:
                clogfiles = glob.glob("%s/host-serial-log-*" %
                                      (tec.getLogdir()))
                clogfiles.extend(glob.glob("%s/console.*.log" %
                                           (tec.getLogdir())))
                clogfiles.extend(glob.glob("%s/support-*.tar.bz2" %
                                           (tec.getLogdir())))
                for clogfile in clogfiles:
                    statinfo = os.stat(clogfile)
                    if statinfo.st_size > 20971520 and not clogfile.endswith(".bz2"):
                        # Greater than 20M, compress it first
                        tmpFile = xenrt.TEC().tempFile()
                        xenrt.command("gzip -c %s > %s" %
                                      (clogfile, tmpFile))
                        f = open(tmpFile)
                        self.jira.add_attachment(i.key, f, os.path.basename("%s.gz" % (clogfile)))
                        f.close()
                    else:
                        f = open(clogfile)
                        self.jira.add_attachment(i, f)
                        f.close()
            except Exception, e:
                xenrt.TEC().warning("Jira attach exception: %s" % (str(e)))
                traceback.print_exc(file=sys.stderr)

    def processTC(self,tec,jiratc,tcsku=None):
        xenrt.GEC().logverbose("processTC tec=%s, jiratc=%s, tcsku=%s" % ((tec or ""), (jiratc or ""), (tcsku or "")))
        
        if not self.attemptToConnect():
            xenrt.GEC().logverbose("Jira not connected, not filing bug",
                                   pref='WARNING')
            return

        if not self.JIRA_URL:
            xenrt.GEC().logverbose("No Jira URL found, not filing bug", 
                                   pref='WARNING')
            return

        ikey = None

        tcResult = tec.tc.getResult()
        if tcResult == "fail" or tcResult == "error":
            xenrt.GEC().logverbose("JiraLink processing test")
            # Generate the fields we need
            if len(tec.tc.results.reasons) > 0:
                reason = tec.tc.results.reasons[0]
            else:
                reason = "Unknown"

            bnsplit = string.split(tec.tc.basename,".")
            if re.match("\d+",bnsplit[-1]):
                # Its just numbers, split it off
                tname = string.join(bnsplit[:-1],".")
            else:
                tname = tec.tc.basename
            
            seq = tec.lookup("SEQUENCE_NAME","Unknown")
            jobid = xenrt.GEC().dbconnect.jobid()
            ver = tec.lookup("VERSION","")
            rev = tec.lookup(["CLIOPTIONS", "REVISION"], "Unknown")
            revision = "%s-%s" % (ver,rev)
            hosts = xenrt.GEC().config.getWithPrefix("RESOURCE_HOST_")
            jobdesc = tec.lookup("JOBDESC", None)
            fullName = "%s/%s" % (tec.tc.group,tec.tc.basename)

            if tec.tc.group:
                phase = tec.tc.group.replace(" ","%20")
            else:
                phase = "Phase%2099"
            test = tec.tc.basename.replace(" ","%20")
            description = ""
            tcdoc = inspect.getdoc(tec.tc)
            if tcdoc:
                description += "Testcase: %s\n\n" % (tcdoc)
            commfile = None
            if len(tec.tc.results.comments) > 100:
                description += "Comments: see attachment comments.txt for " \
                               "%u comments\n" % (len(tec.tc.results.comments))
                try:
                    commfile = xenrt.TEC().tempFile()
                    f = file(commfile, "w")
                    try:
                        for c in tec.tc.results.comments:
                            f.write(c + "\n")
                    finally:
                        f.close()
                except Exception, e:
                    description += "Exception writing comments file: %s" % \
                                   (str(e))
                description += "\n"
            elif len(tec.tc.results.comments) > 0:
                description += "Comments:\n"
                for c in tec.tc.results.comments:
                    description += "%s\n" % (c)
                description += "\n"
            warnfile = None
            if len(tec.tc.results.warnings) > 100:
                description += "Warnings: see attachment warnings.txt for " \
                               "%u warnings\n" % (len(tec.tc.results.warnings))
                try:
                    warnfile = xenrt.TEC().tempFile()
                    f = file(warnfile, "w")
                    try:
                        for w in tec.tc.results.warnings:
                            f.write(w + "\n")
                    finally:
                        f.close()
                except Exception, e:
                    description += "Exception writing warnings file: %s" % \
                                   (str(e))
                description += "\n"
            elif len(tec.tc.results.warnings) > 0:
                description += "Warnings:\n"
                for w in tec.tc.results.warnings:
                    description += "%s\n" % (w)
                description += "\n"
            try:
                description += self.getFailedLogSnippetsFromPattern()
            except Exception, e:
                description += "Exception creating Failed logs Snippets: %s" % (str(e))
            description += ("Remaining XenRT logs available at "
                            "%s?action=testlogs&id=%s&phase=%s&test=%s" %
                            (self.XENRT_WEB,jobid,phase,test))

            hostsStr = ""
            if len(hosts) > 0:
                for h in hosts:
                    hostsStr += "%s, " % (h[1])
                hostsStr = hostsStr[:-2]
            environment = "XenRT JobID: %s, seq: %s, revision: %s, host(s): " \
                          "%s" % (jobid,seq,revision,hostsStr)
            environment += "\n%s" % (fullName)
            if jobdesc:
                environment += "\n%s" % (jobdesc)
            inputdir = xenrt.TEC().lookup(xenrt.TEC().lookup("AUTO_BUG_INPUTDIR", "INPUTDIR"), None)
            if inputdir:
                environment += "\nInput Directory: %s" % (inputdir)
            tsr = xenrt.TEC().lookup("TESTRUN_SR",None)
            if tsr:
                environment += "\nTestRun Suite Run ID: %s" % (tsr)
            jenkins = xenrt.TEC().lookup("JENKINS_URL", None)
            if jenkins:
                environment += "\nJenkins URL: %s" % jenkins
            environment += "\nXenRT Job URL: https://xenrt.citrite.net/xenrt/minimalframe?jobs=%s" % jobid
            seenagain = ("Seen again on %s\nXenRT logs available at "
                         "%s?action=testlogs&id=%s&phase=%s&test=%s" %
                         (environment,self.XENRT_WEB,jobid,phase,test))

            # Is this a reference to an existing ticket
            if re.match("^[A-Z][A-Z]+-\d+$",reason.strip()):
                try:
                    self.comment(reason,seenagain)
                    return
                except:
                    pass # An exception means the ticket didn't exist...

            # See if we should assign tickets to anybody in particular
            assignee = tec.tc.ticketAssignee()
            if not assignee:
                assignee = xenrt.TEC().lookup("AUTO_BUG_ASSIGNEE",None)

            if not jiratc:
                # See if this is a TC style test
                m = re.match("TC(\d{3,4}\d*)",tec.tc.basename)
                if m:
                    jiratc = "TC-%s" % (m.group(1))
            
            if tec.tc.SUBCASE_TICKETS:
                xenrt.GEC().logverbose("Test wants seperate tickets for each subcase")
                # We have subcases, gather the results
                allresults = []
                tec.tc.results.gather(allresults,"","")
                for result in allresults:
                    i = None
                    new = False
                    if result[4] in (xenrt.RESULT_FAIL, xenrt.RESULT_ERROR):
                        reasons = tec.tc.results.groups[result[2]].tests[result[3]].reasons
                        if reasons:
                            reason = reasons[0]
                        else:
                            reason = "Unknown"

                        msg = tec.tc.getSubCaseTicketDescription(result[2], result[3])
                        if msg:
                            description = "Remaining XenRT logs available at %s?action=testlogs&id=%s&phase=%s&test=%s\n\n" % (self.XENRT_WEB,jobid,phase,test)
                            description += msg
                            try:
                                description += self.getFailedLogSnippetsFromPattern()
                            except Exception, e:
                                description += "Exception creating Failed logs Snippets: %s" % (str(e))

                        sstr = "%s/%s: %s" % (result[2], result[3], reason)
                        (i, new) = self.fileTicket(result[4],
                                                   (result[2],
                                                    result[3],
                                                    reason),
                                                   sstr,
                                                   description,
                                                   environment,
                                                   seenagain,
                                                   assignee,
                                                   hosts,
                                                   jiratc
                                                   )
                        if i and new:
                            self.attachFileToTicket(i, "%s/xenrt.log" % (tec.getLogdir()))
                            for f in tec.tc.ticketAttachments():
                                self.attachFileToTicket(i, f)
                    
                    ikey = i and i.key or None
                    self.recordSubcase(tec, result, ikey, tcsku)
                   
                i = None
                new = False

            # Check for subcases
            elif len(tec.tc.results.getTestCases("","")) > 1:
                xenrt.GEC().logverbose("Test has subcases")
                # We have subcases, gather the results
                allresults = []
                tec.tc.results.gather(allresults,"","")

                # Find the ones relevant to our overall state
                relevant = []         
                for result in allresults:
                    if result[3] == None:   # Ignore the root TC
                        continue
                    if result[4] == xenrt.RESULT_FAIL and tcResult == "fail":
                        relevant.append((result[2],result[3]))
                    if result[4] == xenrt.RESULT_ERROR and tcResult == "error":
                        relevant.append((result[2],result[3]))
            
                # Now build up the tracking string (used with multiple subcases)
                tstr = ""
                # Also keep track of the most recent relevant thing we found so
                # in the event we only find one we can use it...
                lastReason = None
                for r in relevant:
                    # Filter out allowed failures
                    if tec.tc.results.groups[r[0]].tests[r[1]].allowed:
                        relevant.remove(r)
                        continue
                    reasons = tec.tc.results.groups[r[0]].tests[r[1]].reasons
                    if len(reasons) > 0:
                        reason = reasons[0]
                    else:
                        reason = "Unknown"
                    tstr += "%s/%s-%s " % (r[0],r[1],reason)
                    lastReason = reason
                tstr = tstr.strip()

                # Now build up the summary string
                sstr = "%s/%s: " % (tec.tc.group,tname)
                if len(relevant) == 0:
                    # This shouldn't happen!
                    xenrt.GEC().logverbose("No relevant subcases found for bug"
                                           " filing, using overall result...", 
                                           pref='WARNING')
                    sstr += reason
                    (i,new) = self.fileTicket(tcResult,(tec.tc.group,tname,
                                                        reason),sstr,
                                              description,environment,seenagain,
                                              assignee,hosts,jiratc)
                elif len(relevant) == 1:
                    sstr += "%s/%s %sed: %s" % (relevant[0][0],relevant[0][1],
                                                tcResult,lastReason)
                    (i, new) = self.fileTicket(tcResult,
                                       (tec.tc.group,tname,"%s/%s-%s" % 
                                                           (relevant[0][0],
                                                            relevant[0][1],
                                                            lastReason)),
                                        sstr,description,environment,seenagain,
                                        assignee,hosts,jiratc)

                else:
                    sstr += "Multiple subcases %sed" % (tcResult)
                    (i, new) = self.fileTicket(tcResult,(tec.tc.group,tname,tstr),sstr,
                                        description,environment,seenagain,
                                        assignee,hosts,jiratc,multipleSubcases=True)

            else:
                sstr = "%s/%s: %s" % (tec.tc.group,tname,reason)
                (i, new) = self.fileTicket(tcResult,(tec.tc.group,
                                                     tname,reason),
                                           sstr,description,environment,
                                           seenagain,assignee,hosts,jiratc)

            if i and new:
                # We created a new ticket, attach xenrt.log, any bug-reports,
                # bluescreens and minidumps, and serial console logs
                try:
                    statinfo = os.stat("%s/xenrt.log" % (tec.getLogdir()))
                    if statinfo.st_size > 20971520:
                        # Greater than 20M, compress it first
                        tmpFile = xenrt.TEC().tempFile()
                        xenrt.command("gzip -c %s/xenrt.log > %s" %
                                      (tec.getLogdir(), tmpFile))
                        f = open(tmpFile)
                        self.jira.add_attachment(i.key, f, "xenrt.log.gz")
                        f.close()
                    else:
                        f = open("%s/xenrt.log" % (tec.getLogdir()))
                        self.jira.add_attachment(i.key, f)
                        f.close()
                except Exception, e:
                    xenrt.TEC().warning("Jira attach exception: %s" % (str(e)))
                    traceback.print_exc(file=sys.stderr)
                try:
                    clogfiles = glob.glob("%s/host-serial-log-*" %
                                          (tec.getLogdir()))
                    clogfiles.extend(glob.glob("%s/console.*.log" %
                                               (tec.getLogdir())))
                    clogfiles.extend(glob.glob("%s/support-*.tar.bz2" %
                                               (tec.getLogdir())))
                    for clogfile in clogfiles:
                        statinfo = os.stat(clogfile)
                        if statinfo.st_size > 20971520 and not clogfile.endswith(".bz2"):
                            # Greater than 20M, compress it first
                            tmpFile = xenrt.TEC().tempFile()
                            xenrt.command("gzip -c %s > %s" %
                                          (clogfile, tmpFile))
                            f = open(tmpFile)
                            self.jira.add_attachment(i.key, f, os.path.basename("%s.gz" % (clogfile)))
                            f.close()
                        elif statinfo.st_size > 0:
                            f = open(clogfile)
                            self.jira.add_attachment(i.key, f)
                            f.close()
                except Exception, e:
                    xenrt.TEC().warning("Jira attach exception: %s" % (str(e)))
                    traceback.print_exc(file=sys.stderr)
                for hTuple in hosts:
                    h = hTuple[1]
                    if os.path.exists("%s/%s" % (tec.getLogdir(),h)):
                        if not os.path.isdir("%s/%s" % (tec.getLogdir(),h)):
                            # Probably a PXE file
                            continue
                        # See if there's a bug-report
                        logs = os.listdir("%s/%s" % (tec.getLogdir(),h))
                        cds = []
                        for log in logs:
                            if log.startswith("bug-report-"):
                                # Check it's not too big
                                st = os.stat("%s/%s/%s" % (tec.getLogdir(),h,
                                                           log))
                                if (st.st_size / 1048576) > 30:
                                    xenrt.TEC().logverbose("%s_%s is too large "
                                                           "to attach" % (h,log))
                                    continue
                                try:
                                    f = open("%s/%s/%s" % (tec.getLogdir(),h,
                                                               log))
                                    self.jira.add_attachment(i.key, f, "%s_%s" % (h,log))
                                    f.close()
                                except Exception, e:
                                    xenrt.TEC().warning("Jira attach exception: %s" % (str(e)))
                                    traceback.print_exc(file=sys.stderr)
                                xenrt.GEC().logverbose("Attached %s as %s_%s to"
                                                       " %s" % (log,h,log,i.key))                             
                            elif re.match("crash-\d{8}-\d{6}-\S+",log):
                                if os.path.isdir("%s/%s/%s" % (tec.getLogdir(),
                                                               h,log)):
                                    cds.append(log)
                        if len(cds) > 0:
                            cds.sort()
                            cdfiles = os.listdir("%s/%s/%s" % (tec.getLogdir(),
                                                               h,cds[-1]))
                            for cdf in cdfiles:
                                if cdf.endswith(".log"):
                                    toAttach = ("%s/%s/%s/%s" % 
                                                (tec.getLogdir(),h,cds[-1],cdf))
                                    attachName = "%s_%s_%s" % (h,cds[-1],cdf)
                                else:
                                    # gzip the file, and then attach that
                                    tf = xenrt.TEC().tempFile()
                                    xenrt.util.command("gzip -c %s/%s/%s/%s"
                                                       " > %s" %
                                             (tec.getLogdir(),h,cds[-1],cdf,tf),
                                                       timeout=60)
                                    toAttach = tf
                                    attachName = "%s_%s_%s.gz" % (h,cds[-1],cdf)

                                try:
                                    f = open(toAttach)
                                    self.jira.add_attachment(i.key, f, attachName)
                                    f.close()
                                except Exception, e:
                                    xenrt.TEC().warning("Jira attach exception: %s" % (str(e)))
                                    traceback.print_exc(file=sys.stderr)
                                xenrt.GEC().logverbose("Attached %s as %s to "
                                                       "%s" % (toAttach,
                                                              attachName,i.key))

                # See if there's any guest minidumps
                ldirs = os.listdir(tec.getLogdir())
                for a,h in hosts:
                    if h in ldirs:
                        ldirs.remove(h)
                for ld in ldirs:
                    if os.path.isdir("%s/%s" % (tec.getLogdir(),ld)):
                        # See if there's a minidump in it
                        logs = os.listdir("%s/%s" % (tec.getLogdir(),ld))
                        mds = []
                        for log in logs:
                            if re.match("Mini\d{6,6}-\d{2,2}\.dmp",log):
                                mds.append(log)
                        if len(mds) > 0:
                            mds.sort()
                            try:
                                f = open("%s/%s/%s" % (tec.getLogdir(),ld,
                                                           mds[-1]))
                                self.jira.add_attachment(i.key, f, "%s_%s" % (ld,mds[-1]))
                            except Exception, e:
                                xenrt.TEC().warning("Jira attach exception: %s" % (str(e)))
                                traceback.print_exc(file=sys.stderr)
                    # XRT-2467 If we detect a BSOD, attach the screenshot
                    if ld == "bsod.jpg" or ld == "bootfail.jpg":
                        try:
                            f = open("%s/%s" % (tec.getLogdir(),ld))
                            self.jira.add_attachment(i.key, f, ld)
                            f.close()
                        except Exception, e:
                            xenrt.TEC().warning("Jira attach exception: %s" % (str(e)))
                            traceback.print_exc(file=sys.stderr)

                # If we created a comments file attach it
                if commfile:
                    try:
                        f = open(commfile)
                        self.jira.add_attachment(i.key, f, "comments.txt")
                        f.close()
                    except Exception, e:
                        xenrt.TEC().warning("Jira attach exception: %s" % (str(e)))
                        traceback.print_exc(file=sys.stderr)
                # If we created a warnings file attach it
                if warnfile:
                    try:
                        f = open(warnfile)
                        self.jira.add_attachment(i.key, f, "warnings.txt")
                        f.close()
                    except Exception, e:
                        xenrt.TEC().warning("Jira attach exception: %s" % (str(e)))
                        traceback.print_exc(file=sys.stderr)
                try:
                    if jiratc:
                        line = self._lookupTAAssignee(jiratc)
                        # Set the reporter to be the TA owner
                        i.update(reporter={'name':line})
                        # If this is a triage ticket, set the assignee to be the TA owner
                        if self.TRIAGE in [x.id for x in i.fields.components]:
                            self.jira.assign_issue(i,line)
                except Exception, e:
                    xenrt.TEC().warning("Set reporter exception: %s" % (str(e)))
                    traceback.print_exc(file=sys.stderr)

            ikey = i and i.key or None
             
        return ikey

    def recordSubcase(self, tec, result, ikey, tcsku): 
        tsr = tec.lookup("TESTRUN_SR",None)
        if tsr:
            xenrt.GEC().logverbose("Logging result against SR %s" % tsr) 
            ident = tec.tc.getSubCaseJiraIdent(result[2], result[3])
            xenrt.GEC().logverbose("Ident = %s" % ident)
            tcid = self.lookupTCFromIdent(ident)
            xenrt.GEC().logverbose("TC = %s" % tcid)
            if tcid:
                if tec.tc.group:
                    phase = tec.tc.group
                else:
                    phase = "Phase 99"
                test = tec.tc.basename
                detailid = None
                try:
                    detailid = xenrt.GEC().dbconnect.detailid(phase,test)
                except:
                    # This might happen if we've e.g. lost connectivity
                    xenrt.TEC().warning("Unable to retrieve detailid")
                self.recordRun(tsr,tcid,xenrt.resultDisplay(result[4]),ikey,detailid,tcsku)

    def processTR(self,tec,ikey,jiratc,tcsku=None):
        xenrt.TEC().logverbose("processTR ikey=%s jiratc=%s tcsku=%s" % (str(ikey or ""), str(jiratc or ""), str(tcsku or "")))
        # Testrun bits - returns True if it updates a ticket
        tsr = xenrt.TEC().lookup("TESTRUN_SR",None)
        if tsr:
            tcResult = tec.tc.getResult()
            if tec.tc.SUBCASE_TICKETS:
                alreadyRecorded = False
                # If the testcase failed we would have done this with bug filing
                if tcResult in ("fail", "error"):
                    alreadyRecorded = True
                # Unless we weren't filing tickets
                if not xenrt.TEC().lookup("AUTO_BUG_FILE", False, boolean=True):
                    alreadyRecorded = False
                if not alreadyRecorded:
                    xenrt.GEC().logverbose("Test wants seperate tickets for each subcase")
                    # We have subcases, gather the results
                    allresults = []
                    tec.tc.results.gather(allresults,"","")
                    for result in allresults:
                        self.recordSubcase(tec, result, None, tcsku)
                return True
            else:
                if not jiratc:
                    # See if this is a TC style test
                    m = re.match("TC(\d{3,4}\d*)",tec.tc.basename)
                    if m:
                        jiratc = "TC-%s" % (m.group(1))
                    else:
                        return False

                if tec.tc.group:
                    phase = tec.tc.group
                else:
                    phase = "Phase 99"
                test = tec.tc.basename
                detailid = None
                try:
                    detailid = xenrt.GEC().dbconnect.detailid(phase,test)
                except:
                    # This might happen if we've e.g. lost connectivity
                    xenrt.TEC().warning("Unable to retrieve detailid")
                self.recordRun(tsr,jiratc,tcResult,ikey,detailid,tcsku)
                subresults = []
                tec.tc.gather(subresults)
                if len(subresults) > 1:
                    # We have some subcases
                    for r in subresults:
                        self.recordSubResult(tsr,jiratc,r,tcsku)
                return True

        return False

    def processJT(self,tec,tcid,reason,data):
        if not self.attemptToConnect():
            xenrt.GEC().logverbose("Jira not connected, not filing bug",
                                   pref='WARNING')
            return

        if not self.JIRA_URL:
            xenrt.GEC().logverbose("No Jira URL found, not filing bug",
                                   pref='WARNING')
            return

        ikey = None

        xenrt.GEC().logverbose("JiraLink processing job test")
        seq = tec.lookup("SEQUENCE_NAME","Unknown")
        jobid = xenrt.GEC().dbconnect.jobid()
        ver = tec.lookup("VERSION","")
        rev = tec.lookup(["CLIOPTIONS", "REVISION"], "Unknown")
        revision = "%s-%s" % (ver,rev)
        hosts = xenrt.GEC().config.getWithPrefix("RESOURCE_HOST_")
        jobdesc = tec.lookup("JOBDESC", None)
        fullName = "JobTest/%s" % tcid
        phase = "JobTest"
        test = tcid
        description = """Job level testcase

This ticket represents a failed job level testcase. To avoid spam, XenRT's seen again functionality is disabled - to determine the extent of this issue, please visit %s/jobtests/%s or to see all job level failures, visit %s/jobtests
""" % (self.TESTRUN_URL, tcid, self.TESTRUN_URL)
        hostsStr = ""
        if len(hosts) > 0:
            for h in hosts:
                hostsStr += "%s, " % (h[1])
            hostsStr = hostsStr[:-2]
        environment = "XenRT JobID: %s, seq: %s, revision: %s, host(s): " \
                      "%s" % (jobid,seq,revision,hostsStr)
        environment += "\n%s" % (fullName)
        if jobdesc:
            environment += "\n%s" % (jobdesc)
        inputdir = xenrt.TEC().lookup(xenrt.TEC().lookup("AUTO_BUG_INPUTDIR", "INPUTDIR"), None)
        if inputdir:
            environment += "\nInput Directory: %s" % (inputdir)
        tsr = xenrt.TEC().lookup("TESTRUN_SR",None)
        if tsr:
            environment += "\nTestRun Suite Run ID: %s" % (tsr)
        jenkins = xenrt.TEC().lookup("JENKINS_URL", None)
        if jenkins:
            environment += "\nJenkins URL: %s" % jenkins
        environment += "\nXenRT Job URL: https://xenrt.citrite.net/xenrt/minimalframe?jobs=%s" % jobid
        assignee = xenrt.TEC().lookup("AUTO_BUG_ASSIGNEE", None)

        sstr = "JobTest/%s: %s" % (tcid, reason)
        (i, new) = self.fileTicket("fail", ("JobTest", tcid, reason),
                                   sstr,description,environment,None,assignee,hosts,tcid)

        if i and new:
            tec.flushLogs()
            f = open("%s/xenrt.log" % (tec.getLogdir()))
            self.jira.add_attachment(i.key, f)
            f.close()

            try:
                clogfiles = glob.glob("%s/host-serial-log-*" %
                                      (tec.getLogdir()))
                clogfiles.extend(glob.glob("%s/console.*.log" %
                                           (tec.getLogdir())))
                clogfiles.extend(glob.glob("%s/support-*.tar.bz2" %
                                           (tec.getLogdir())))
                for clogfile in clogfiles:
                    statinfo = os.stat(clogfile)
                    if statinfo.st_size > 20971520 and not clogfile.endswith(".bz2"):
                        # Greater than 20M, compress it first
                        tmpFile = xenrt.TEC().tempFile()
                        xenrt.command("gzip -c %s > %s" %
                                      (clogfile, tmpFile))
                        f = open(tmpFile)
                        self.jira.add_attachment(i.key, f, os.path.basename("%s.gz" % (clogfile)))
                        f.close()
                    else:
                        f = open(clogfile)
                        self.jira.add_attachment(i, f)
                        f.close()
            except Exception, e:
                xenrt.TEC().warning("Jira attach exception: %s" % (str(e)))
                traceback.print_exc(file=sys.stderr)
            for hTuple in hosts:
                h = hTuple[1]
                if os.path.exists("%s/%s" % (tec.getLogdir(),h)):
                    if not os.path.isdir("%s/%s" % (tec.getLogdir(),h)):
                        # Probably a PXE file
                        continue
                    # See if there's a bug-report
                    logs = os.listdir("%s/%s" % (tec.getLogdir(),h))
                    for log in logs:
                        if log.startswith("bug-report-"):
                            # Check it's not too big
                            st = os.stat("%s/%s/%s" % (tec.getLogdir(),h,
                                                       log))
                            if (st.st_size / 1048576) > 30:
                                xenrt.TEC().logverbose("%s_%s is too large "
                                                       "to attach" % (h,log))
                                continue
                            try:
                                f = open("%s/%s/%s" % (tec.getLogdir(),h,
                                                           log))
                                self.jira.add_attachment(i.key, f, "%s_%s" % (h,log))
                                f.close()
                            except Exception, e:
                                xenrt.TEC().warning("Jira attach exception: %s" % (str(e)))
                                traceback.print_exc(file=sys.stderr)
                            xenrt.GEC().logverbose("Attached %s as %s_%s to"
                                                   " %s" % (log,h,log,i.key))
            try:
                line = self._lookupTAAssignee(tcid)
                # Set the reporter to be the TA owner
                i.update(reporter={'name':line})
                # If this is a triage ticket, set the assignee to be the TA owner
                if self.TRIAGE in [x.id for x in i.fields.components]:
                    self.jira.assign_issue(i,line)
            except Exception, e:
                xenrt.TEC().warning("Set reporter exception: %s" % (str(e)))
                traceback.print_exc(file=sys.stderr)


        if i and tsr:
            self.testrunRecordJobTest(tsr,tcid,jobid,data,i.key)

    def recordSubResult(self,sr,tc,result,tcsku=None):
        subcasename = string.join(result[0:4], "/")
        xenrt.GEC().logverbose("Updating TC %s, subcase %s" % (tc, subcasename))
        result = xenrt.resultDisplay(result[4])
        try:
            self.testrunRecordSubResult(sr,tc,subcasename,result,tcsku=tcsku)
        except Exception, e:
            traceback.print_exc(file=sys.stderr)
            xenrt.GEC().logverbose("JiraLink Exception: %s" % (str(e)))
            if self._bufferdir:
                xenrt.TEC().logverbose("Buffering TestRun Submission: "
                                       "%s,%s,%s" % (sr,tc,result))
                f = file("%s/bufferedruns" % (self._bufferdir), "a")
                try:
                    fcntl.flock(f, fcntl.LOCK_EX)
                    x = ["Subcase", str(sr), str(tc), str(subcasename), str(result)]
                    if tcsku:
                        x.append(str(tcsku))
                    f.write("%s\n" % (string.join(x, "\t")))
                finally:
                    f.close()           
            
    def recordRun(self,sr,tc,result,ticket,detailid=None,tcsku=None):
        xenrt.GEC().logverbose("recordRun sr=%s, tc=%s, result=%s, ticket=%s, detailid=%s tcsku=%s" % (str(sr or ""), str(tc or ""), str(result or ""), str(ticket or ""), str(detailid or ""), str(tcsku or "")))
        try:
            self.testrunRecordRun(sr,tc,result,ticket,detailid,tcsku)
        except Exception, e:
            traceback.print_exc(file=sys.stderr)
            xenrt.GEC().logverbose("JiraLink Exception: %s" % (str(e)))            
            if self._bufferdir:
                xenrt.TEC().logverbose("Buffering TestRun Submission: "
                                           "%s,%s,%s,%s,%s" % (sr,tc,result,ticket,
                                                           detailid))
                f = file("%s/bufferedruns" % (self._bufferdir), "a")
                try:
                    fcntl.flock(f, fcntl.LOCK_EX)
                    x = ["Test", str(sr), str(tc), str(result), str(ticket),
                         str(detailid)]
                    if tcsku:
                        x.append(str(tcsku))
                    f.write("%s\n" % (string.join(x, "\t")))
                finally:
                    f.close()           

    def replay(self):
        """Replay any buffered Jira connection"""
        if not self.attemptToConnect():
            xenrt.TEC().logverbose("Jira not connected so aborting replay "
                                   "attempt")
            return

        # Currently only cope with test run submission
        if not self._bufferdir:
            raise xenrt.XRTError("No buffer directory")
        fn = "%s/bufferedruns" % (self._bufferdir)
        if not os.path.exists(fn):
            return
        items = []
        f = file(fn, "r+")
        try:
            fcntl.flock(f, fcntl.LOCK_EX)
            while True:
                line = f.readline()
                if not line:
                    break
                line = string.strip(line)
                l = string.split(line, "\t")
                if len(l) == 0:
                    continue
                items.append(l)
            f.seek(0)
            f.truncate(0)
        finally:
            f.close()
        notdone = []
        for item in items:
            try:
                fitem = []
                for i in item:
                    if i == "None":
                        fitem.append(None)
                    else:
                        fitem.append(i)
                recordtype = fitem[0]
                if recordtype == "Test":
                    sr = fitem[1]
                    tc = fitem[2]
                    result = fitem[3]
                    ticket = fitem[4]
                    detailid = fitem[5]
                    if len(fitem) > 6:
                        tcsku = fitem[6]
                    else:
                        tcsku = None
                    xenrt.TEC().logverbose("Replaying %s on SR %s" % (tc,sr))
                    try:
                        self.testrunRecordRun(sr,tc,result,ticket,detailid,tcsku)
                    except: # Fix for buggy saved runs
                        self.testrunRecordRun(sr,tc,result,ticket,None,detailid)
                elif recordtype == "Subcase":
                    sr = fitem[1]
                    tc = fitem[2]
                    subcase  = fitem[3]
                    result = fitem[4]
                    if len(fitem) > 5:
                        tcsku = fitem[5]
                    else:
                        tcsku = None
                    self.testrunRecordSubResult(sr,tc,subcase,result,tcsku)
            except Exception, e:
                notdone.append(item)
                xenrt.TEC().logverbose("Replayed submission failed with %s" %
                                       (e))
        # Write back any we didn't replay
        f = file(fn, "a")
        try:
            fcntl.flock(f, fcntl.LOCK_EX)
            for item in notdone:
                f.write("%s\n" % (string.join(item, "\t")))
        finally:
            f.close()

    def processFragment(self,jiratc,blocker,ticket=None,ticketIsFailure=True,blockedticket=None,tcsku=None):
        tsr = xenrt.TEC().lookup("TESTRUN_SR",None)
        xenrt.TEC().logverbose("Processing fragment, ticket = %s, blockedticket = %s" % (ticket, blockedticket))
        if tsr:
            if ticket:
                if ticketIsFailure:
                    self.recordRun(tsr,jiratc,"fail",ticket,None,tcsku)
                else:
                    self.recordRun(tsr,jiratc,"error",ticket,None,tcsku)
            elif blocker:
                self.recordRun(tsr,jiratc,"notrun",blockedticket,None,tcsku)
            else:
                self.recordRun(tsr,jiratc,"pass",None,None,tcsku)

    def fileTicket(self,result,track,summary,description,environment,seenagain,
                   assignee,hosts,jiratc,multipleSubcases=False):

        xenrt.GEC().logverbose("fileTicket called")

        j = self.jira

        # Determine which project we're using
        if result == "fail":
            project = self.FAIL_PROJ
        else:
            project = self.ERR_PROJ

        # Remove varying things like UUIDs,IPs,hostnames etc. from the track
        track2 = re.sub(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                        "[0-9a-fA-F]{12}",
                        "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
                        track[2])
        track2 = re.sub(r"ovs-vswitchd\.\d+\.ctl", "ovs-vswitchd.xxxx.ctl", track2)
        track2 = re.sub(r"\d+\.\d+\.\d+\.\d+", "xxx.xxx.xxx.xxx", track2)
        track2 = re.sub(r"pid \d+", "pid xxxxx", track2)
        track2 = re.sub(r"/xe-cli-[0-9\.]+-.*\.rpm",
                        "/xe-cli-x.x.x-xxxxx.xxx.rpm",
                        track2)
        track2 = re.sub(r"/\d+-xenrt[-]?\w+/", "/xxxxxx-xenrtxxxxxx/", track2)
        track2 = re.sub(r"=xenrt\w+", "=xenrtxxxxxx", track2)
        track2 = re.sub(r" xenrt\w+", " xenrtxxxxxx", track2)
        track2 = re.sub(r"/tmp/xenrt\w+", "/tmp/xenrtxxxxxx", track2)
        track2 = re.sub(r"job\d+", "jobxxxxxx", track2)
        track2 = re.sub(r"/tmp/dist[A-Za-z0-9]+/", "/tmp/distxxxxxx/", track2)
        # A half-hearted attempt to match IPv6 addresses!
        track2 = re.sub("[A-Fa-f0-9]{4}:[A-Fa-f0-9]{4}:[A-Fa-f0-9:]+", "xxxx:xxxx:xxxx:xxxx:xxxx:xxxx:xxxx:xxxx", track2)
        track2 = re.sub("create_nfs_sr xxx.xxx.xxx.xxx \S+", "create_nfs_sr xxx.xxx.xxx.xxx xxxxxx", track2)
        # some dates
        track2 = re.sub("\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", "xxxx-xx-xxTxx:xx:xx", track2)
        # mac addresses
        track2 = re.sub("[0-9a-zA-z]{2}:[0-9a-zA-z]{2}:[0-9a-zA-z]{2}:[0-9a-zA-z]{2}:[0-9a-zA-z]{2}:[0-9a-zA-z]{2}", "xx:xx:xx:xx:xx:xx", track2)

        # JQL can't escape square brackets
        track2 = re.sub("\[", "", track2)
        track2 = re.sub("\]", "", track2)
        if len(hosts) > 0:
            for h in hosts:
                # Replace host, unless we see !host, in which case remove !
                track2 = re.sub(r"(\A|[^!])%s(\W|$)" % (h[1]), r'\1<host>\2',
                                track2)
                track2 = re.sub(r"!%s(\W|$)" % (h[1]), r'%s\1' % (h[1]), track2)
                summary = re.sub(r"!%s(\W|$)" % (h[1]), r'%s\1' % (h[1]), summary)

        # We look for a tracking match in this order:
        # group/testcase: reason
        # testcase: reason
        # reason

        # Create the 3 strings
        fullTrack = "%s/%s: %s" % (track[0],track[1],track2)
        halfTrack = "%s: %s" % (track[1],track2)
        miniTrack = track2

        if len(fullTrack) > 255:
            fullTrack = fullTrack[:255]
        if len(halfTrack) > 255:
            halfTrack = halfTrack[:255]
        if len(miniTrack) > 255:
            miniTrack = miniTrack[:255]

        if track[0] != None:
            issuesCheck0 = track[0][:255]
        else:
            issuesCheck0 = None
        if track[1] != None:
            issuesCheck1 = track[1][:255]
        else:
            issuesCheck1 = None
        if track2 != None:
            issuesCheck2 = track2[:255]
        else:
            issuesCheck2 = None

        try:
            issues = self.findIssuesMatchingAutoFile(issuesCheck0,
                                                issuesCheck1,
                                                issuesCheck2,
                                                self.TRACK_TAG)
        except Exception, e:
            xenrt.TEC().warning("Exception fetching list of issues: %s" %
                                (str(e)))
            # Continue anyway and file a fresh ticket
            issues = []

        # Now rebuild the tracking string in case we file a new ticket
        if self.TRACK_TAG:
            track = "%s_%s" % (self.TRACK_TAG, fullTrack)
            if len(track) > 255:
                track = track[:255]
        else:
            track = fullTrack

        xenrt.GEC().logverbose("Retrieved list of %u issues" % (len(issues)))

        # First pass, look for open tickets or closed duplicates
        issueToComment = None
        issuesToLink = []
        createNew = True
        bestmatch = 0
        bestknownmatch = 0
        bestknown = None

        # match levels
        # <=0 = no match (may be some links though)
        # 1 = duplicate match
        # 2 = mini match
        # 3 = half match
        # 4 = full match
        for i in issues:
            issueTrack = self.getCustomField(i, self.TRACK_FIELD)
            if self.TRACK_TAG:
                if issueTrack.startswith("%s_" % self.TRACK_TAG):
                    trackLen = len("%s_" % self.TRACK_TAG)
                    truncate = 255-trackLen
                    issueTrack = issueTrack[trackLen:]
                    fullTrack = fullTrack[:truncate]
                    halfTrack = halfTrack[:truncate]
                    miniTrack = miniTrack[:truncate]

            match = -1 # No match
            if issueTrack == fullTrack:
                match = 4 # Full match (potentially)
            elif issueTrack == halfTrack:
                match = 3 # Half match (potentially)
            elif issueTrack == miniTrack:
                match = 2 # mini match (potentially)

            # Did we get any match at all
            if match > 0:
                if i.fields.resolution is None:
                    if match > bestmatch: # We care about this match
                        issueToComment = i
                        bestmatch = match
                        createNew = False
                elif i.fields.resolution.name == "Duplicate":
                    match = 1
                    if match > bestmatch or match > bestknownmatch:
                        links = i.fields.issuelinks
                        for link in links:
                            if link.type.name == "Duplicate" and hasattr(link, "outwardIssue"):
                                linkedIssue = self.jira.issue(link.outwardIssue.key)
                                if linkedIssue.fields.resolution is None:
                                    if match > bestmatch:
                                        issueToComment = linkedIssue
                                        bestmatch = match
                                        createNew = False
                                else:                                    
                                    if xenrt.GEC().isKnownIssue(\
                                        linkedIssue.key):
                                        if match > bestknownmatch:
                                            createNew = False
                                            bestknown = linkedIssue
                                            bestknownmatch = match
                                            continue
                                    if not linkedIssue in issuesToLink:
                                        issuesToLink.append(linkedIssue)
                else:
                    # Its a closed one, so we'll link it, but not do any more
                    # Is this a known issue for this run
                    if xenrt.GEC().isKnownIssue(i.key):
                        if match > bestknownmatch:
                            createNew = False
                            bestknown = i
                            bestknownmatch = match
                    else:
                        issuesToLink.append(i)

        xenrt.GEC().logverbose("Finished searching existing issues")

        triageComponents = [self.TRIAGE, self.TRIAGEDEV]

        componentName = xenrt.TEC().lookup("JIRA_TICKET_COMPONENT", None)
        if componentName:
            try:
                component = [x.id for x in j.project(project).components if x.name.lower() == componentName.lower()][0]
            except:
                component = self.TRIAGE
        else:
            component = xenrt.TEC().lookup("JIRA_TICKET_COMPONENT_ID", self.TRIAGE)

        jiraTicketLabel = xenrt.TEC().lookup("JIRA_TICKET_LABEL", None)
        if createNew:
            xenrt.GEC().logverbose("Decided to create new issue")
            if not assignee:
                assignee = "-1"
            tickettitle = summary
            # Optional title tag for tickets. This is only used for
            # fresh files, it is not included in the autofileref
            tag = xenrt.TEC().lookup("JIRA_TICKET_TAG", None)
            if tag:
                tickettitle = "[%s] %s" % (tag, tickettitle)
                
            # New lines aren't allowed by Jira API
            tickettitle = tickettitle.replace("\n", "\\n")
           
            # Temporary hack to figure out the branch name so unstable
            # branches can be tagged. This needs to be propogated from
            # xenbuilder in a cleaner way in the future.
            r = re.search("\/usr\/groups\/xen\/carbon\/([^\/]+)\/",
                          xenrt.TEC().lookup("INPUTDIR", ""))
            if (not tag) and r and r.group(1) in ["mnr-newkernel", "mnr-newxen", "ballooning",
                                    "mnr-vswitch", "v6", "centos-upgrade",
                                    "george-update-1", "bodie", "laurie",
                                    "cowley-newkernel", "boston-newxen"]:
                tickettitle = "[%s] %s" % (r.group(1), tickettitle)
            if not isinstance(tickettitle, unicode):
                tickettitle = unicode(tickettitle, errors='ignore')
            if not isinstance(description, unicode):
                description = unicode(description, errors='ignore')

            issueType = xenrt.TEC().lookup("JIRA_ISSUE_TYPE", "Bug")
            fields = {"project": {"key":project},
                      "summary": tickettitle[0:255],
                      "issuetype": {"name":issueType},
                      "priority": {"name":"Major"},
                      "environment": environment,
                      "description": description,
                      "components": [{'id':component}],
                      "assignee": {'name':assignee}}

            version = xenrt.TEC().lookup("JIRA_TICKET_VERSION", None)
            if version:
                fields['versions'] = [{"name": version}]
            # Cloudstack project needs custom field setting 
            if project == "CS" and issueType == "Bug":
                fields['customfield_13232'] = {"value": "Internal"}

            issue = j.create_issue(**fields)
            xenrt.GEC().logverbose("Created JIRA issue %s" % (issue.key))
            if jiraTicketLabel is not None:
                issue.update(labels=[jiraTicketLabel])
                xenrt.GEC().logverbose("Added label to JIRA issue - %s" % (jiraTicketLabel))
            try:
                self.setCustomField(issue,self.TRACK_FIELD,track)
            except Exception, e:
                xenrt.GEC().logverbose("Exception setting Jira tracking field:"
                                       " %s" % (e),pref='WARNING')
            if len(issuesToLink) > 0:
                comment = "May be related to issue(s): "
                for i in issuesToLink:
                    comment += "%s, " % (i.key)
                comment = comment[:-2]
                j.add_comment(issue.key, comment)
            return (issue,True)
        elif issueToComment:

            # Handle the case where we don't want to add a seen again comment
            if seenagain is None:
                xenrt.GEC().logverbose("Not commenting on existing issue %s" % (issueToComment.key))
            elif hasattr(issueToComment.fields, "labels") and "NoSeenAgain" in issueToComment.fields.labels:
                xenrt.GEC().logverbose("NoSeenAgain label present, not commenting on existing issue %s" % (issueToComment.key))
            else:
                xenrt.GEC().logverbose("Decided to comment on existing issue")
                j.add_comment(issueToComment.key, seenagain)
                xenrt.GEC().logverbose("Commented on JIRA issue %s" % (issueToComment.key))
                if jiraTicketLabel is not None:
                    issueToComment.fields.labels.append(jiraTicketLabel)
                    issueToComment.update(fields={"labels": issueToComment.fields.labels})
                    xenrt.GEC().logverbose("Added label to JIRA issue - %s" % (jiraTicketLabel))

            try:
                comps = [x.id for x in issueToComment.fields.components]
                if component not in comps:
                    needToAddComponent = True
                    for c in comps:
                        if c not in triageComponents:
                            needToAddComponent = False
                    if needToAddComponent:
                        comps.append(component)
                        issueToComment.update(components=[{"id":x} for x in comps])
                        # If we're adding the Triage component, we might need to set the assignee to the TA owner
                        if component == self.TRIAGE and issueToComment.fields.assignee is None:
                            taAssignee = self._lookupTAAssignee(jiratc)
                            j.assign_issue(issueToComment, taAssignee)
            except Exception, e:
                xenrt.GEC().logverbose("Couldn't add component/assign ticket: %s" % str(e))

            return (issueToComment,False)
        elif bestknownmatch > 0:
            xenrt.GEC().logverbose("Known closed issue %s, not creating new" %
                                   (bestknown.key))
            return (bestknown, False)
        else:
            xenrt.GEC().logverbose("Not created new ticket but found no "
                                   "issues to comment on", pref='WARNING')

    def lookupTCFromIdent(self, ident):
        xenrt.GEC().logverbose("lookupTCFromIdent ident=%s" % ident)
        postURL = "%s/backend/tcfromident" % self.TESTRUN_URL
        dict = {'ident': ident}
        postdic = urllib.urlencode(dict)
        u = urllib2.urlopen(postURL, postdic)
        tc = u.readline().strip()
        u.close()
        xenrt.GEC().logverbose("Got %s as TC" % tc)
        if re.match("TC-\d+", tc):
            return tc
        else:
            return None

    def _lookupTAAssignee(self,jiratc):
        if jiratc:
            postURL = "%s/tools/techareaownerfortc" % (self.TESTRUN_URL)
            dict = {'tc': jiratc }
            postdic = urllib.urlencode(dict)
            u = urllib2.urlopen(postURL, postdic)
            line = u.readline().strip()
            if line != "UNKNOWN":
                return line
        return self.DEFAULT_ASSIGNEE

    def comment(self,issue,comment):
        j = self.jira

        j.add_comment(issue, comment)

        xenrt.GEC().logverbose("Commented on JIRA issue %s" % (issue))

    def linkCrashdump(self,issue,cdticket):
        self.jira.create_issue_link(type="Relates", inwardIssue=issue, outwardIssue=cdticket)

    def fileCrashDump(self,cd,path,place):
        if not self.attemptToConnect():
            xenrt.GEC().logverbose("Jira not connected so cannot file "
                                   "crash dump ticket")
            return

        # Get some details about the job
        seq = xenrt.TEC().lookup("SEQUENCE_NAME","Unknown")
        jobid = xenrt.GEC().dbconnect.jobid()
        ver = xenrt.TEC().lookup("VERSION","")
        rev = xenrt.TEC().lookup(["CLIOPTIONS", "REVISION"], "Unknown")
        revision = "%s-%s" % (ver,rev)
        hosts = xenrt.GEC().config.getWithPrefix("RESOURCE_HOST_")
        jobdesc = xenrt.TEC().lookup("JOBDESC", None)
        fullName = "%s/%s" % (xenrt.TEC().tc.group,xenrt.TEC().tc.basename)

        if xenrt.TEC().tc.group:
            phase = xenrt.TEC().tc.group.replace(" ","%20")
        else:
            phase = "Phase%2099"
        test = xenrt.TEC().tc.basename.replace(" ","%20")
        description = ""
        tcdoc = inspect.getdoc(xenrt.TEC().tc)
        if tcdoc:
            description += "Testcase: %s\n\n" % (tcdoc)
        description += ("Remaining XenRT logs available at "
                        "%s?action=testlogs&id=%s&phase=%s&test=%s" %
                        (self.XENRT_WEB,jobid,phase,test))

        hostsStr = ""
        if len(hosts) > 0:
            for h in hosts:
                hostsStr += "%s, " % (h[1])
            hostsStr = hostsStr[:-2]
        environment = "XenRT JobID: %s, seq: %s, revision: %s, host(s): " \
                      "%s" % (jobid,seq,revision,hostsStr)
        environment += "\n%s" % (fullName)
        inputdir = xenrt.TEC().lookup(xenrt.TEC().lookup("AUTO_BUG_INPUTDIR", "INPUTDIR"), None)
        if inputdir:
            environment += "\nInput Directory: %s" % (inputdir)
        tsr = xenrt.TEC().lookup("TESTRUN_SR",None)
        if tsr:
            environment += "\nTestRun Suite Run ID: %s" % (tsr)
        jenkins = xenrt.TEC().lookup("JENKINS_URL", None)
        if jenkins:
            environment += "\nJenkins URL: %s" % jenkins
        environment += "\nXenRT Job URL: https://xenrt.citrite.net/xenrt/minimalframe?jobs=%s" % jobid

        j = self.jira
        componentName = xenrt.TEC().lookup("JIRA_TICKET_COMPONENT", None)
        if componentName:
            try:
                component = [x.id for x in j.project(self.FAIL_PROJ).components if x.name.lower() == componentName.lower()][0]
            except:
                component = self.TRIAGE
        else:
            component = xenrt.TEC().lookup("JIRA_TICKET_COMPONENT_ID", self.TRIAGE)

        i = j.create_issue(project={'key': self.FAIL_PROJ},summary = "Crashdump %s found on %s" % (cd, place.getName()),issuetype={"name": "Bug"},
                          priority={"name":"Major"},components=[{'id':component}],
                          environment=environment,description=description)
        # Create a tarball of the dump and try uploading it (it might be too
        # big, but worth a try)
        td = xenrt.TEC().tempDir()
        try:
            xenrt.command("cd %s/../ && tar -cjf %s/crash-%s.tar.bz2 crash-%s" % (path,td,cd,cd))
            f = open("%s/crash-%s.tar.bz2" % (td,cd))
            self.jira.add_attachment(i.key, f)
            f.close()
        except:
            pass
            
        try:
            # add contents of xen.log and dom0.log to ticket comments
            for f in xenrt.command("""(cd / && find %s) | grep "xen.log\|dom0.log\|domain0.log" """ % path).strip().splitlines():
                j.add_comment(i.key, "%s:\n{noformat}\n%s\n{noformat}" % (f, xenrt.command("cat " + f)))
        except Exception, e:
            xenrt.GEC().logverbose("Exception commenting on Jira ticket: " + str(e))
        
        return i.key

    def createTRTickets(self,suite,version,priority,findold,branch=None,devrun=False):

        postURL = "%s/backend/newsuiterun" % (self.TESTRUN_URL)
        dict = {'suite': suite, 'version': version }
        if priority:
            dict['priority'] = priority
        if findold:
            dict['findold'] = 'yes'
        if branch:
            dict['branch'] = branch
        if devrun:
            dict['devrun'] = "yes"
        postdic = urllib.urlencode(dict)
        u = urllib2.urlopen(postURL,postdic)
        line = u.readline()
        if not line:
            return None

        return line.strip()

    def addTestsToSuiteRun(self,suiterun,tests):
        if len(tests) == 0:
            return
        postURL = "%s/backend/addtests" % (self.TESTRUN_URL)
        dict = {'suiterun': suiterun, 'tcs': ",".join(tests) }
        postdic = urllib.urlencode(dict)
        u = urllib2.urlopen(postURL,postdic)
        line = u.readline().strip()
        if line != "OK":
            print line
            print u.read()
            raise xenrt.XRTError("Couldn't add TCs to testrun")


    def xenrtResultToTestrunResult(self, result):
        # Convert result into db format
        if result == "pass" or result == "partial":
            trresult = "passed"
        elif result == "fail":
            trresult = "failed"
        elif result == "error":
            trresult = "error"
        elif result == "notrun":
            trresult = "blocked"
        elif result == "skipped":
            trresult = "skipped"
        else:
            raise xenrt.XRTFailure("Unknown result type %s" % (result))
        return trresult

    def testrunRecordSubResult(self,suiterun,tc,subcase,result,tcsku=None):
        # Don't record skipped tests
        if result == "skipped":
            return
        result = self.xenrtResultToTestrunResult(result)
       

        postURL = "%s/backend/recordsubresult" % (self.TESTRUN_URL)
        postdic = {'suiterun': suiterun,
                   'tc': tc,
                   'subcase': subcase,
                   'result': result}
        
        if tcsku:
            postdic['tcsku'] = tcsku

        u = urllib2.urlopen(postURL,urllib.urlencode(postdic))


    def testrunRecordRun(self,suiterun,tc,result,ticket,detailid,tcsku):
        result = self.xenrtResultToTestrunResult(result)

        if not ticket:
            ticket = ""

        # Send it in
        postURL = "%s/backend/recordrun" % (self.TESTRUN_URL)
        postdic = {'suiterun': suiterun,
                   'tc': tc,
                   'result': result,
                   'ticket': ticket}
        if detailid:
            postdic['xrt_detailid'] = detailid

        if tcsku:
            postdic['tcsku'] = tcsku

        u = urllib2.urlopen(postURL,urllib.urlencode(postdic))

    def testrunRecordJobTest(self,suiterun,tc,jobid,reason,ticket):
        postURL = "%s/backend/recordjobtestfailure" % (self.TESTRUN_URL)
        postdic = {'suiterun': suiterun,
                   'tc': tc,
                   'jobid': jobid,
                   'reason': reason,
                   'ticket': ticket}
        u = urllib2.urlopen(postURL,urllib.urlencode(postdic))

    def findIssuesMatchingAutoFile(self,group,tc,reason,tag):
        autoref = "%s/%s: %s" % (group, tc, reason)

        xenrt.TEC().logverbose("Calling _searchJiraIssues(\"%s\")" % (autoref))
        issues = self._searchJiraIssues(autoref)
        if tag:
            tagautoref = "%s_%s/%s: %s" % (tag, group, tc, reason)
            tagissues = self._searchJiraIssues(tagautoref)
            for i in tagissues:
                if i.key not in [x.key for x in issues]:
                    issues.append(i)

        return issues

    def _searchJiraIssues(self,autoref):
        ar = autoref[:255]
        ar = ar.replace("\\", "\\\\")

        #Fix for CA-162858 to explicitly escape '"'
        ar = ar.replace('\"', '\\\"')

        arShort = ar.split("/")[1]
        longref = "\\\"%s\\\"" % ar
        shortref = "\\\"%s\\\"" % arShort
        issues = self.jira.search_issues('autoFileRef ~ "%s"' % longref)
        shortIssues = self.jira.search_issues('autoFileRef ~ "%s"' % shortref)
        for i in shortIssues:
            if i.key not in [x.key for x in issues]:
                issues.append(i)

        return issues

    def getCustomField(self, issue, field):
        if not self.customFields:
            self.customFields = self.jira.fields()
        try:
            return getattr(issue.fields, [x['id'] for x in self.customFields if x['name']==field][0])
        except:
            return None
    
    def setCustomField(self, issue, field, value, choice=False):
        if not self.customFields:
            self.customFields = self.jira.fields()
        fieldid = [x['id'] for x in self.customFields if x['name']==field][0]
        if choice:
            issue.update(fields={fieldid: {"value":value}})
        else:
            issue.update(fields={fieldid: value})
    
    def attachFileToTicket(self, issue, fname):
        try:
            statinfo = os.stat(fname)
            if statinfo.st_size > 20971520 and not fname.endswith(".bz2") and not fname.endswith(".gz"):
                # Greater than 20M, compress it first
                tmpFile = xenrt.TEC().tempFile()
                xenrt.command("gzip -c %s > %s" %
                              (fname, tmpFile))
                f = open(tmpFile)
                self.jira.add_attachment(issue.key, f, os.path.basename("%s.gz" % (fname)))
                f.close()
            elif statinfo.st_size > 0:
                f = open(fname)
                self.jira.add_attachment(issue.key, f)
                f.close()
        except Exception, e:
            xenrt.TEC().warning("Jira attach exception: %s" % (str(e)))
            traceback.print_exc(file=sys.stderr)

_theJiralink = None
def getJiraLinkCached():
    global _theJiralink
    if not _theJiralink:
        _theJiralink = JiraLink()
    return _theJiralink

def getJiraLink():
    return JiraLink()

