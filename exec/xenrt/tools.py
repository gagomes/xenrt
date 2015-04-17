#
# XenRT: Test harness for Xen and the XenServer product family
#
# Miscellaneous tools (aux mode xrt commands)
#
# Copyright (c) 2008 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import sys, string, re, xml.dom.minidom, os, xmlrpclib, urllib, json, time
import xenrt
from xml.sax.saxutils import escape

global tccache
tccache = {}
global fasttccache
fasttccache = {}
global childrencache
childrencache = {}

global _jira
_jira = None
global _xmlrpcjira
_xmlrpcjira = None
global _xmlrpcjiraauth
_xmlrpcjiraauth = None

def testrunJSONLoad(tool, params):
    return json.load(urllib.urlopen("%s/rest/inquisitor/latest/%s?os_username=%s&os_password=%s&%s" %
                    (xenrt.TEC().lookup("JIRA_URL", None),
                    tool,
                    xenrt.TEC().lookup("JIRA_USERNAME"),
                    xenrt.TEC().lookup("JIRA_PASSWORD"),
                    params)))

def getIssue(j, issue):
    global tccache
    if issue not in tccache:#not tccache.has_key(issue):
        print "  Getting %s" % issue
        i = j.jira.issue(issue)
        tccache[issue] = i
    return tccache[issue]

def getIssues(j, issues):
    global tccache
    need = [x for x in issues if x not in tccache.keys()]
    pageSize = 25;
    i = 0
    while i < len(need):
        fetch = need[i:i+pageSize]
        print "  Getting %s" % ", ".join(fetch)
        try:
            found = j.jira.search_issues("key IN (%s)" % ",".join(fetch))
            for f in found:
                tccache[f.key] = f
        except:
            print "  Warning: could not get issues"
        i += pageSize

def getChildren(key):
    global childrencache
    if not childrencache.has_key(key):
        returnedDict = testrunJSONLoad("issuetree/%s" % key, "depth=1")[0]
        if 'children' in returnedDict:
            childrencache[key] = returnedDict['children']
        else:
            childrencache[key] = []
        #childrencache[key] = testrunJSONLoad("issuetree/%s" % key, "depth=1")[0]['children']
    return childrencache[key]

def flushChildrenCache(key):
    global childrencache
    if childrencache.has_key(key):
        del childrencache[key]

def _walkHierarchy(j, ticket):
    reply = []
    t = getIssue(j, ticket)
    links = t.fields.issuelinks
    for link in links:
        if link.type.name == "Contains" and hasattr(link, "outwardIssue"):
            c = link.outwardIssue
            if c.fields.status.name in ("New", "Open"):
                ty = c.fields.issuetype.name
                if ty == "Test Case":
                    reply.append(link.outwardIssue.key)
                elif ty == "Hierarchy":
                    reply.extend(_walkHierarchy(j, link))
    return reply

def getSuiteTickets(j, suite):
    suitetickets = []
    s = getIssue(j, suite)
    slinks = s.fields.issuelinks
    for slink in slinks:
        if slink.type.name == "Contains" and hasattr(slink, "outwardIssue"):
            suitetickets.append(slink.outwardIssue.key)
                
    return suitetickets

def cleanUpTickets():
    """Clean up any messes in tickets."""

    # Open a link to Jira
    j = J()
    tickets = _walkHierarchy(j, "TC-5783")
    for ticket in tickets:
        t = getIssue(j, ticket)
        # Check there are no newlines in the summary
        s = t.fields.summary
        if re.search(r"\n", s):
            s = string.replace(s, "\n", "")
            print "Removing newline from %s: %s" % (ticket, s)
            t.update(summary=s)
            

def J():
    global _jira
    if not _jira:
        # Open a link to Jira
        _jira = xenrt.getJiraLink()

    return _jira

def machineCSVs():
    [NICCSV(x) for x in xenrt.TEC().lookup("HOST_CONFIGS").keys()]

def NICCSV(machine):
    try:
        f = open("%s.csv" % machine,"w")
        mac = xenrt.TEC().lookupHost(machine,"MAC_ADDRESS")
        ip = xenrt.TEC().lookupHost(machine,"HOST_ADDRESS")
        ip6 = xenrt.TEC().lookupHost(machine,"HOST_ADDRESS6","")
        adapter = xenrt.TEC().lookupHost(machine,"OPTION_CARBON_NETS", "eth0")


        f.write("%s,NPRI,%s,%s,%s\n" % (adapter,mac,ip,ip6))

        bmcaddr = xenrt.TEC().lookupHost(machine,"BMC_ADDRESS",None)
        if bmcaddr:
            bmcmac = xenrt.TEC().lookupHost(machine,"BMC_MAC","")
            bmcuser = xenrt.TEC().lookupHost(machine,"IPMI_USERNAME")
            bmcpassword = xenrt.TEC().lookupHost(machine,"IPMI_PASSWORD")
            bmcint = xenrt.TEC().lookupHost(machine,"IPMI_INTERFACE","lan")
            f.write("BMC,,%s,%s,,%s,%s,%s\n" % (bmcmac,bmcaddr,bmcuser,bmcpassword,bmcint))

        i = 1
        while xenrt.TEC().lookupHost(machine,["NICS","NIC%d" % i],None):
            mac = xenrt.TEC().lookupHost(machine,["NICS","NIC%d" % i, "MAC_ADDRESS"], "")
            ip = xenrt.TEC().lookupHost(machine,["NICS","NIC%d" % i, "IP_ADDRESS"], "")
            ip6 = xenrt.TEC().lookupHost(machine,["NICS","NIC%d" % i, "IP_ADDRESS6"], "")
            network = xenrt.TEC().lookupHost(machine,["NICS","NIC%d" % i, "NETWORK"], "")
            if network in ("NPRI","NSEC","IPRI","ISEC"):
                f.write("eth%d,%s,%s,%s,%s\n" % (i,network,mac,ip,ip6))
            i+=1
        f.close()
    except Exception,e:
        print "Exception %s creating CSV for machine %s" % (str(e),machine)

def machineXML(machine=None):
    if machine:
        cfg = xenrt.TEC().lookup(["HOST_CONFIGS",machine],{})
        xml = "<xenrt>\n%s</xenrt>" % xenrt.dictToXML(cfg, "  ")
    else:
        cfg = xenrt.TEC().lookup("HOST_CONFIGS",{})
        xml = "<xenrt>\n  <HOST_CONFIGS>\n%s  </HOST_CONFIGS>\n</xenrt>" % xenrt.dictToXML(cfg, "    ")
    print xml

def productCodeName(version):
    print xenrt.TEC().lookup(["PRODUCT_CODENAMES",version], "ERROR: Could not find product codename")

def listGuests():
    print "\n".join(sorted(xenrt.TEC().lookup("GUEST_LIMITATIONS").keys() + [x + "-x64" for x in xenrt.TEC().lookup("GUEST_LIMITATIONS").keys() if xenrt.TEC().lookup(["GUEST_LIMITATIONS", x, "MAXMEMORY64"], None)]))

def netPortControl(machinename, ethid, enable):
    machine = xenrt.PhysicalHost(machinename, ipaddr="0.0.0.0")
    h = xenrt.GenericHost(machine)
    if enable:
        h._controlNetPort(h.getNICMACAddress(ethid), "CMD_PORT_ENABLE")
    else:
        h._controlNetPort(h.getNICMACAddress(ethid), "CMD_PORT_DISABLE")

def listHW(fn):
    nicfields = ['NIC0', 'NIC1', 'NIC2', 'NIC3', 'NIC4', 'NIC5', 'NIC6']
    hbafields = ['FC HBA 0', 'FC HBA 1']
    storagefields = ['Storage Controller', 'RAID Controller']
    rt = xenrt.getRackTablesInstance()
    machines = [x.split(",")[0] for x in open(fn).readlines()]
    models = []
    nics = []
    hbas = []
    storage = []
    for m in machines:
        try:
            o = rt.getObject(m)
        except:
            continue
        model = o.getAttribute("HW Type")
        if model and model not in models:
            models.append(model)
        for f in nicfields:
            v = o.getAttribute(f)
            if v and v not in nics:
                nics.append(v)
        for f in hbafields:
            v = o.getAttribute(f)
            if v and v not in hbas:
                hbas.append(v)
        for f in storagefields:
            v = o.getAttribute(f)
            if v and v not in storage:
                storage.append(v)

    print "==== Server Models ===="
    for v in sorted(models):
        print v
    print "\n==== NICs ====="
    for v in sorted(nics):
        print v
    print "\n==== HBAs ====="
    for v in sorted(hbas):
        print v
    print "\n==== Storage Controllers ====="
    for v in sorted(storage):
        print v

from lxml import etree
from pprint import pprint
import ast
def _getMarvinTestDocStrings(classname, testnames, marvinCodePath):
    pathToClass = os.path.join(marvinCodePath, *classname.split('.')[1:-1])+'.py'
    astData = ast.parse(open(pathToClass).read())
    classElement = filter(lambda x:isinstance(x, ast.ClassDef) and x.name == classname.split('.')[-1], astData.body)[0]
    classDocString = ast.get_docstring(classElement)
    classDocString = classDocString and classDocString.rstrip() or ''
    testMethodElements = filter(lambda x:isinstance(x, ast.FunctionDef) and x.name in testnames, classElement.body)
    testMethodDocStrings = []
    for testMethod in testMethodElements:
        docStr = ast.get_docstring(testMethod)
        docStr = docStr and docStr.rstrip() or ''
        testMethodDocStrings.append((testMethod.name, docStr))
    return (classDocString, testMethodDocStrings)

def createMarvinTCTickets(tags=[], marvinCodePath=None, mgmtSvrIP=None, testMode=False):
    if not (isinstance(tags, list) and len(tags) > 0):
        raise xenrt.XRTError('Must provide a list containing at least 1 tag')
    if not mgmtSvrIP:
        raise xenrt.XRTError('Must provide the IP address of a running CP/CS Management Server')

    # Create dummy marvin config
    marvinCfg = { 'mgtSvr': [ {'mgtSvrIp': mgmtSvrIP, 'port': 8096} ] }
    marvinConfig = xenrt.TEC().tempFile()
    fh = open(marvinConfig, 'w')
    json.dump(marvinCfg, fh)
    fh.close()

    # Get test list from nose
    noseTestList = xenrt.TEC().tempFile()
    tempLogDir = xenrt.TEC().tempDir()
    noseArgs = ['--with-marvin', '--marvin-config=%s' % (marvinConfig),
                '--with-xunit', '--xunit-file=%s' % (noseTestList),
                '--log-folder-path=%s' % (tempLogDir),
                '--load',
                marvinCodePath,
                '-a "%s"' % (','.join(map(lambda x:'tags=%s' % (x), tags))),
                '--collect-only']
    print 'Using nosetest args: %s' % (' '.join(noseArgs))
    xenrt.util.command('/usr/local/bin/nosetests %s' % (' '.join(noseArgs)))

    xmlData = etree.fromstring(open(noseTestList).read())
    testData = {}
    for element in xmlData.getchildren():
        classname = element.get('classname')
        testname = element.get('name')
        if testData.has_key(classname):
            if testname in testData[classname]:
                print 'Duplicate testname [%s] found in class [%s]' % (testname, classname)
            else:
                testData[classname].append(testname)
        else:
            testData[classname] = [ testname ]
    
    pprint(testData)
    testData.pop('nose.failure.Failure')

    jira = xenrt.JiraLink()
    maxResults = 200
    allMarvinTCTickets = jira.jira.search_issues('project = TC AND issuetype = "Test Case" AND "Test Case Type" = Marvin', maxResults=maxResults)
    print 'Total number Marvin TCs to fetch: %d' % (allMarvinTCTickets.total)
    while(len(allMarvinTCTickets) < allMarvinTCTickets.total):
        allMarvinTCTickets += jira.jira.search_issues('project = TC AND issuetype = "Test Case" AND "Test Case Type" = Marvin', maxResults=maxResults, startAt=len(allMarvinTCTickets))

    for key in testData.keys():
        (classDocString, testMethodDocStrings) = _getMarvinTestDocStrings(key, testData[key], marvinCodePath)
        title = key.split('.')[-1] + ' [%s]' % (', '.join(tags))
        tcMarvinMetaIdentifer = '%s' % ({ 'classpath': key, 'tags': tags })
        component = [{'id': '11606'}]
        testType = {'id': '12920', 'value': 'Marvin'}
        description  = 'Marvin tests in class %s matching tag(s): %s\n' % (key.split('.')[-1], ', '.join(tags))
        description += 'Full class-path: *%s*\n' % (key)
        if classDocString != '':
            description += '{noformat}\n%s\n{noformat}\n' % (classDocString)
        description += '\nThis class contains the following Marvin test(s)\n'
        for testMethodDocString in testMethodDocStrings:
            description += 'TestMethod: *%s*\n' % (testMethodDocString[0])
            if testMethodDocString[1] != '':
                description += '{noformat}\n%s\n{noformat}\n' % (testMethodDocString[1])
            description += '\n'
        description += '\n*WARNING: This testcase is generated - do not edit any field directly*'

        tcTkts = filter(lambda x:eval(x.fields.customfield_10121) == { 'classpath': key, 'tags': tags }, allMarvinTCTickets)
        if len(tcTkts) == 0:
            newTicketId = 'TestMode'
            if not testMode:
                newTicket = jira.jira.create_issue(project={'key':'TC'}, issuetype={'name':'Test Case'}, reporter={'name':'xenrt'},
                                                   summary=title, 
                                                   components=component, 
                                                   customfield_10121=tcMarvinMetaIdentifer,
                                                   customfield_10713=testType,
                                                   description=description)
                newTicketId = newTicket.key
            print 'Created new ticket [%s]' % (newTicketId)
        elif len(tcTkts) == 1:
            print 'Updating existing ticket [%s]' % (tcTkts[0].key)
            if not testMode:
                tcTkts[0].update(summary=title, components=component, customfield_10121=tcMarvinMetaIdentifer, description=description)
        else:
            raise xenrt.XRTError('%d tickets match classpath: %s, tags: %s [%s] aborting' % (key, tags, ','.join(map(lambda x:x.key, tcTkts))))

        if testMode:
            print title
            print tcMarvinMetaIdentifer
            print description
            print '-------------------------------------------------------------------------------------'

def createMarvinSequence(tags=[], classPathRoot=''):
    if not (isinstance(tags, list) and len(tags) > 0):
        raise xenrt.XRTError('Must provide a list containing at least 1 tag')

    jira = xenrt.JiraLink()
    maxResults = 20
    allMarvinTCTickets = jira.jira.search_issues('project = TC AND issuetype = "Test Case" AND "Test Case Type" = Marvin', maxResults=maxResults)
    print 'Total number Marvin TCs to fetch: %d' % (allMarvinTCTickets.total)
    while(len(allMarvinTCTickets) < allMarvinTCTickets.total):
        allMarvinTCTickets += jira.jira.search_issues('project = TC AND issuetype = "Test Case" AND "Test Case Type" = Marvin', maxResults=maxResults, startAt=len(allMarvinTCTickets))
    marvinTestsStrs = []
    for tkt in allMarvinTCTickets:
        marvinMetaData = eval(tkt.fields.customfield_10121)
        if marvinMetaData['tags'] == tags and marvinMetaData['classpath'].startswith(classPathRoot):
            marvinTestsStrs.append('      <marvintests path="%s" class="%s" tags="%s" tc="%s"/>' % (os.path.join(*marvinMetaData['classpath'].split('.')[1:-1])+'.py',
                                                                                                    marvinMetaData['classpath'].split('.')[-1],
                                                                                                    ','.join(tags),
                                                                                                    tkt.key))

    marvinTestsStrs.sort()
    for testStr in marvinTestsStrs:
        print testStr

def newGuestsMiniStress():
    # Tailor to your needs
    families = {"oel": "Oracle Enterprise Linux", "rhel": "RedHat Enterprise Linux", "centos": "CentOS"}

    template = """<xenrt>

  <!-- OS functional test sequence: %s and %s-x64 -->

  <variables>
    <PRODUCT_VERSION>Creedence</PRODUCT_VERSION>
  </variables>

  <default name="PARALLEL" value="2" />
  <default name="MIGRATEPAR" value="1" />

  <semaphores>
    <TCMigrate count="${MIGRATEPAR}" />
  </semaphores>

  <prepare>
    <host />
  </prepare>

  <testsequence>
    <parallel workers="${PARALLEL}">
%s
%s
    </parallel>
  </testsequence>
</xenrt>
"""

    for i in families.keys():
        for j in ["5.11", "6.6"]:
            osname = "%s%s" % (i, j.replace(".", ""))
            print osname
            a = defineOSTests(osname, "%s %s" % (families[i], j))
            b = defineOSTests(osname, "%s %s x64" % (families[i], j), arch="x86-64")
            seq = template % (osname, osname, a, b)

            with open("seqs/creedenceoslin%s.seq" % osname, "w") as f:
                f.write(seq)

def createHotfixSymlinks():
    hotfixpath = xenrt.TEC().lookup("HOTFIX_BASE_PATH")

    hfs = xenrt.TEC().lookup("HOTFIXES")

    hfdict = {}

    for r in hfs.keys():
        for v in hfs[r].keys():
            hfdict.update(dict(hfs[r][v].items()))


    for h in hfdict.keys():
        xenrt.command("ln -sf %s %s/%s.xsupdate" % (hfdict[h], hotfixpath, h))
