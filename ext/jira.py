# JIRA SOAP Library
#
# Copyright (c) 2006-2007 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#
# Alex Brett, August 2007
# alex@xensource.com
# Anil Madhavapeddy, August 2007
# anil@xensource.com
#

import SOAPpy
import re, os.path, base64, urllib, urllib2
import sys, traceback
import xml.dom.minidom

class Jira:

    StatusResolved = 5
    STATUS = {}
    RESOLUTION = {}
    TYPES = {} 
    PRIORITIES = {}

    def __init__(self,url,username,password):
    
        self.url = url
        self.username = username
        self.password = password
        
        # Open JIRA connection and login
        self.jira = SOAPpy.WSDL.Proxy(
                        "%s/rpc/soap/jirasoapservice-v2?wsdl" % (url))
        if self.jira:
            self.auth = self.jira.login(username,password)
        else:
            raise Exception("Unable to connect to Jira")

        # Get statuses from Jira...
        statuses = self.jira.getStatuses(self.auth)
        for s in statuses:
            self.STATUS[s.id] = s.name
        # Get resolutions from Jira...
        resolutions = self.jira.getResolutions(self.auth)
        for r in resolutions:
            self.RESOLUTION[r.id] = r.name
        # Get types rrom Jira...
        types = self.jira.getIssueTypes(self.auth)
        for t in types:
            self.TYPES[t.id] = t.name
        # Get priorities from Jira...
        prios = self.jira.getPriorities(self.auth)
        for p in prios:
            self.PRIORITIES[p.id] = p.name

    def getUserFullName(self, user):
        return self.jira.getUser(self.auth, user)['fullname']
        
    def createIssue(self,project,summary,type,priority,description=None,
                    affectsVersions=None,assignee="-1",components=None,
                    customFields=None,environment=None):

        # Process priority and type
        for p in self.PRIORITIES:
            if self.PRIORITIES[p] == priority:
                priority = p
                break
        for t in self.TYPES:
            if self.TYPES[t] == type:
                type = t
                break

        fields = {'project': project, 'summary': summary, 'priority': priority, 'type': type, 'assignee': assignee}
        if description:
            fields['description'] = description
        if affectsVersions:
            fields['affectsVersions'] = affectsVersions
        if components:
            fields['components'] = components
        if environment:
            fields['environment'] = environment
        ri = JiraIssue(self, self.jira.createIssue(self.auth,fields))
        if customFields:
            for cf in customFields:
                ri.setCustomField(cf[0],cf[1],update=False)
            ri.updateCustomFields()
        return ri

    def deleteIssue(self,key):
        try:
            self.jira.deleteIssue(self.auth,key)
        except:
            raise Exception("Issue %s not found" % (key))
        
    def getIssue(self,key):
        try:
            ri = self.jira.getIssue(self.auth,key)
            return JiraIssue(self, ri)
        except:
            try:
                # Retry the connection, see what happens...
                sys.stderr.write("Failure during getIssue, attempting to "
                                 "reconnect to Jira...\n")
                self.__init__(self.url,self.username,self.password)
                ri = self.jira.getIssue(self.auth,key)
                return JiraIssue(self, ri)
            except Exception, e:
                sys.stderr.write(str(e))
                traceback.print_exc(file=sys.stderr)
                raise Exception("Issue %s not found" % (key))
        
    def getIssuesFromFilter(self,filterId):
        try:
            ris = self.jira.getIssuesFromFilter(self.auth,filterId);
            return [ JiraIssue(self, i) for i in ris ]
        except:
            raise Exception("Filter ID not found")

    def getProject(self,projectKey):
        """Check the project exists, if so, return it."""
        try:
            rp = self.jira.getProjectByKey(self.auth,projectKey)
            return JiraProject(self, rp, projectKey)
        except:
            raise Exception("Project not found")

    def addVersionToProject(self,projectKey,version):
        """Add a version to a project, given the project key string."""
        rv = self.jira.addVersion(self.auth, projectKey, {'name': version})
        return rv['id']

    def addFixedVersion(self, versionName, ticket, comment, force=False):
        """Given an ticket number, mark its issue Fixed in the named version.

        If the issue's status is not Resolved, don't add the version to FixedVersions.
        The optional force parameter overrides this. The comment is always added.
        """
        issue = self.getIssue(ticket)
        if force or issue.status == Jira.StatusResolved:
            issue.addFixedVersion(versionName)
        issue.addComment(comment)

    def getIssuesFromFilterName(self, filterName):
        """Given a filter name, return a list of JiraIssue objects that match"""
        filters = self.jira.getSavedFilters(self.auth)
        filterId = None
        for filter in filters:
            if filter['name'] == filterName:
                filterId = filter['id']
                break
        if not filterId:
            raise Exception("Filter not found")

        issues = self.jira.getIssuesFromFilter(self.auth, filterId)
        retissues = []
        for issue in issues:
            retissues.append(JiraIssue(self, issue))

        return retissues

class JiraObject:

    def __init__(self, jira):

        self.Jira = jira
        self.jira = jira.jira # These shouldn't be used
        self.auth = jira.auth # These shouldn't be used

class JiraProject(JiraObject):      

    def __init__(self,jira,RemoteProject,projectKey):
        JiraObject.__init__(self,jira)
        
        self.RemoteProject = RemoteProject
        self.projectKey = projectKey
        self.key = None

        # Parse the fields in the RemoteProject
        for k,v in RemoteProject.__dict__.items():
            self.__dict__[k] = v

    def archiveVersion(self,version,archive=True):
        self.Jira.jira.archiveVersion(self.Jira.auth,self.key,version,archive)

    def addVersion(self,version):
        self.Jira.jira.addVersion(self.Jira.auth, self.key, {'name': version})
       
    def getComponents(self):
        comps = self.Jira.jira.getComponents(self.Jira.auth, self.projectKey)
        return [ JiraComponent(self.Jira, c) for c in comps ]

class JiraComponent(JiraObject):

    def __init__(self,jira,RemoteComponent):
        JiraObject.__init__(self,jira)
        self.name = None
  
        for k,v in RemoteComponent.__dict__.items():
            self.__dict__[k] = v
        
    def getName(self):
        return self.name

class JiraIssue(JiraObject):

    def __init__(self,jira,RemoteIssue):
        JiraObject.__init__(self,jira)
        
        self.RemoteIssue = RemoteIssue
        self.id = None
        self.fixVersions = None
        self.key = None
        self.status = None
        self.resolution = None
        self.assignee = None
        self.type = None
        self.customFieldValues = None
        self.project = None

        # Parse the fields in the RemoteIssue
        for k,v in RemoteIssue.__dict__.items():
            self.__dict__[k] = v
    
        # Get priorities
        prios = self.Jira.jira.getPriorities(self.Jira.auth)
        # Parse them
        self.priorities = {}
        for prio in prios:
            self.priorities[prio['name']] = prio['id']
            
        # Get custom fields
        fs = self.Jira.jira.getFieldsForEdit(self.Jira.auth,self.key)
        self.customFields = {}
        for f in fs:
            if f['id'].startswith("customfield_"):
                self.customFields[f['name']] = f['id']

    def __cmp__(self, other):
        return cmp(int(self.priority), int(other.priority))

    # Accessor methods

    def getStatus(self):
        return self.Jira.STATUS[self.status]

    def getResolution(self):
        return self.Jira.RESOLUTION[self.resolution];
    
    def getSummary(self):
        return self.summary
    
    def getDescription(self):
        return self.description
    
    def getEnvironment(self):
        return self.environment

    def getComponents(self):
        return self.components

    def getAssignee(self):
        return self.assignee

    def getKey(self):
        return self.key

    def getPriority(self):
        return self.priority

    def getType(self):
        return self.Jira.TYPES[self.type]

    def getComments(self):
        """Returns an array of dictionaries"""
        cs = self.Jira.jira.getComments(self.Jira.auth, self.key)
        return_cs = []
        for c in cs:
            return_cs.append(c._asdict())
        
        return return_cs

    def getCodeComplete(self):
        return self.getCustomTextField("Code Complete Date")

    def getFeatureCommitted(self):
        return self.getCustomTextField("Feature Committed")

    def getSpecification(self):
        return self.getCustomTextField("Specification")

    def getTestImpact(self):
        return self.getCustomTextField("Test Impact")

    def getDocImpact(self):
        return self.getCustomTextField("Documentation Impact")

    def getReleaseNotes(self):
        return self.getCustomTextField("Release Notes")

    def getChangeLog(self):
        clog = {}
        clog['contents'] = self.getCustomTextField("Change Log Entry")
	status = self.getCustomTextField("Change Log Visibility")
	if status == None:
	  clog['status'] = "Internal"
	else:
	  clog['status'] = status
        clog['category'] = self.getCustomTextField("Change Log Category")
        return clog

    def getCustomTextField(self,name):
        """Returns the specified custom field, assuming it is a free-form text field"""

        f = self.getCustomField(name)
        if f != None:
            return f[0]

    def getCustomField(self,name):
        """Returns the specified custom field"""      

        if not self.customFields.has_key(name):
            return None

        cfs = self.customFieldValues
        for cf in cfs:
            if cf['customfieldId'] == self.customFields[name]:
                return cf['values']

    # Mutator methods


    def update(self,valuelist):
        """Update fields of an issue. Used internally and externally."""
        
        self.Jira.jira.updateIssue(self.Jira.auth, self.key, valuelist)

    def setSummary(self,summary):
        self.summary = summary
        self.update([{'id': 'summary','values': summary}])
    
    def setDescription(self,description):
        self.description = description
        self.update([{'id': 'description','values': description}])        
        
    def setEnvironment(self,environment):
        self.environment = environment
        self.update([{'id': 'environment','values': environment}])     
    
    def setPriority(self,priority):
        self.priority = priority
        self.update([{'id': 'priority','values': priority}])    
   
    def setComponents(self,components):
        self.update([{'id': 'components','values': components}])
        prjcomps = self.Jira.getProject(self.project).getComponents()
        self.components = []
        for c in prjcomps:
            if c.id in components:
                self.components.append({'id':c.id, 'name':c.getName()})

    def addComment(self,comment):
        self.Jira.jira.addComment(self.Jira.auth, self.key, {'body': comment})
    
    def setCustomField(self,name,value,update=True):
        """Sets the specified custom field"""

        for cf in self.customFieldValues:
            if cf['customfieldId'] == self.customFields[name]:
                self.customFieldValues.remove(cf)
                break

        newcf = {'customfieldId': self.customFields[name], 'values': value}
        self.customFieldValues.append(newcf)

        if update:
            self.update([{'id': self.customFields[name], 'values': value}])

    def updateCustomFields(self):
        updates = []
        for cf in self.customFieldValues:
            updates.append({'id': cf['customfieldId'],
                            'values': cf['values']})

        self.update(updates)

    def addFixedVersion(self,versionName):
        # Find the version id. Doesn't Jira provide this?
        versions = self.Jira.jira.getVersions(self.Jira.auth, self.project)
        id = [v.id for v in versions if v.name == versionName][0]
        
        fixedin = map(lambda v: v['id'], self.fixVersions) + [id]
        self.update([{'id': 'fixVersions', 'values': fixedin }])

    def attachFile(self,path,name=None):
        """Attach file to this issue"""

        # Get just the name of the file
        if name:
            filename = name
        else:
            filename = os.path.basename(path)

        # Read in the file
        f = file(path,"rb")
        data = f.read()
        f.close()
        data = base64.encodestring(data)

        # Make the call...
        self.Jira.jira.addAttachmentsToIssue(self.Jira.auth, self.key, [filename], 
                                        [[data]])
        
    def linkIssue(self,linkTo,linkType):
        """Link this issue to another"""

        postURL = "%s/secure/LinkExistingIssue.jspa" % (self.Jira.url)
        postdic = urllib.urlencode({'os_username': self.Jira.username, 
                                    'os_password': self.Jira.password, 
                                    'id': self.id, 'linkDesc': linkType, 
                                    'linkKey': linkTo})
        urllib2.urlopen(postURL,postdic)

    def getLinks(self):
        """Returns a dictionary of issue:linktype"""

        postURL = ("%s/si/jira.issueviews:issue-xml/%s/?os_username=%s&"
                  "os_password=%s" % (self.Jira.url,self.key,self.Jira.username,
                                      self.Jira.password))
        data = urllib2.urlopen(postURL).read()
        dom = xml.dom.minidom.parseString(data)
        ilts = dom.getElementsByTagName("issuelinktype")
        if len(ilts) < 1:
            return {}
        links = {}
        for ilt in ilts:
            for cn in ilt.childNodes:
                if cn.nodeName == "outwardlinks" or \
                   cn.nodeName == "inwardlinks":
                    desc = cn.attributes['description'].value
                    for cnn in cn.childNodes:
                        if cnn.nodeName == "issuelink":
                            for cnnn in cnn.childNodes:
                                if cnnn.nodeName == "issuekey":
                                    links[cnnn.childNodes[0].data] = desc
        return links

    def deleteLink(self, issue):
        """Deletes all links between this issue and the specified issue"""

        postURL = ("%s/si/jira.issueviews:issue-xml/%s/?os_username=%s&"
                  "os_password=%s" % (self.Jira.url,self.key,self.Jira.username,
                                      self.Jira.password))
        data = urllib2.urlopen(postURL).read()
        dom = xml.dom.minidom.parseString(data)
        key = dom.getElementsByTagName("key")[0].getAttribute("id")
        ilts = dom.getElementsByTagName("issuelinktype")
        deleted = False
        for ilt in ilts:
            linktype = ilt.getAttribute("id")
            for cn in ilt.childNodes:
                if cn.nodeName == "outwardlinks" or \
                   cn.nodeName == "inwardlinks":
                    desc = cn.attributes['description'].value
                    for cnn in cn.childNodes:
                        if cnn.nodeName == "issuelink":
                            for cnnn in cnn.childNodes:
                                if cnnn.nodeName == "issuekey":
                                    if cnnn.childNodes[0].data == issue:
                                        id = cnnn.getAttribute("id")
                                        self._deleteLink(key, id, linktype)
                                        deleted = True
        if not deleted:
            raise Exception("Issue not currently linked")

    def _deleteLink(self, id, destId, linkType):
        """Deletes the specified link"""

        postURL = ("%s/secure/DeleteLink.jspa?id=%s&destId=%s&linkType=%s&"
                   "confirm=true&os_username=%s&os_password=%s" %
                   (self.Jira.url,id,destId,linkType,self.Jira.username,
                    self.Jira.password))
        urllib2.urlopen(postURL)

    def copyAttachmentsTo(self, destination):
        """Copy attachments from the ticket to the destination dir"""
        if not os.path.isdir(destination):
            raise Exception("Destination must be a directory")

        # Get the attachment details
        attachments = self.Jira.jira.getAttachmentsFromIssue(self.Jira.auth,self.key)

        # Build authentication string
        auth = "os_username=%s&os_password=%s" % (self.Jira.username, 
                                                  self.Jira.password)

        # Grab each attachment
        for a in attachments:
            url = "%s/secure/attachment/%s/%s?%s" % (self.Jira.url,a.id,
                                                     urllib.quote(a.filename),
                                                     auth)
            data = urllib2.urlopen(url).read()
            f = file("%s/%s" % (destination,a.filename),"w")
            f.write(data)
            f.close()

    def resolve(self, resolution):
        """Resolve the issue with the specified resolution"""

        rid = None
        for r in self.Jira.RESOLUTION:
            if self.Jira.RESOLUTION[r] == resolution:
                rid = r 
                break
        if not rid:
            raise Exception("Unknown resolution %s" % (resolution))

        self.Jira.jira.progressWorkflowAction(self.Jira.auth, self.key, '5',
                                              [{'id': 'resolution',
                                                'values': [str(rid)]}])

