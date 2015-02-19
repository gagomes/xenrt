#!/usr/bin/python

import requests
import json
import httplib
import os.path
import base64
import sys

class XenRTAPIException(Exception):
    def __init__(self, code, reason, canForce):
        self.code = code
        self.reason = reason
        self.canForce = canForce

    def __str__(self):
        ret = "%s %s: %s" % (self.code, httplib.responses[self.code], self.reason)
        if self.canForce:
            ret += " (can force override)"
        return ret

class XenRT(object):
    def __init__(self, apikey=None, user=None, password=None, server=None):
        if not server:
            server ="xenrt.citrite.net"
        self.base = "http://%s/xenrt/api/v2" % server

        self.customHeaders = {}
        if apikey:
            self.customHeaders['x-api-key'] = apikey
        elif user and password:
            base64string = base64.encodestring('%s:%s' % (user, password)).replace('\n', '')
            self.customHeaders["Authorization"] = "Basic %s" % base64string

    def __serializeForQuery(self, data):
        if isinstance(data, bool):
            return str(data).lower()
        elif isinstance(data, (list, tuple)):
            return ",".join([str(x) for x in data])
        else:
            return str(data)

    def __serializeForPath(self, data):
        return str(data)

    def __raiseForStatus(self, response):
        try:
            if response.status_code >= 400:
                j = response.json()
                reason = j['reason']
                canForce = j.get('can_force')
            else:
                reason = None
                canForce = False
        except:
            pass
        else:
            if reason:
                raise XenRTAPIException(response.status_code,
                                        reason,
                                        canForce)
        response.raise_for_status()

    def lock_global_resource(self, restype, site, job):
        """ Locks a global resource
            Parameters:
                 restype: string - Type of lock required
                 site: string - Site where the lock is required
                 job: integer - Job ID requesting the lock
        """
        path = "%s/globalresources/lock" % (self.base)
        paramdict = {}
        files = {}
        payload = {}
        j = {}
        if job != None:
            j['job'] = job
        if restype != None:
            j['restype'] = restype
        if site != None:
            j['site'] = site
        payload = json.dumps(j)
        myHeaders = {'content-type': 'application/json'}
        myHeaders.update(self.customHeaders)
        r = requests.post(path, params=paramdict, data=payload, files=files, headers=myHeaders)
        self.__raiseForStatus(r)
        return r.json()


    def release_global_resource(self, name=None, job=None):
        """ Releases a global resource lock
            Parameters:
                 name: string - Release the lock on this named resource
                 job: integer - Release the locks on all resources from this job
        """
        path = "%s/globalresources/lock" % (self.base)
        paramdict = {}
        files = {}
        payload = {}
        j = {}
        if job != None:
            j['job'] = job
        if name != None:
            j['name'] = name
        payload = json.dumps(j)
        myHeaders = {'content-type': 'application/json'}
        myHeaders.update(self.customHeaders)
        r = requests.delete(path, params=paramdict, data=payload, files=files, headers=myHeaders)
        self.__raiseForStatus(r)
        return r.json()


    def update_machine(self, name, params=None, broken=None, status=None, resources=None, addflags=None, delflags=None):
        """ Update machine details
            Parameters:
                 name: integer - Machine to update
                 params: dictionary - Key-value pairs parameter:value of parameters to update (set value to null to delete a parameter)
                 broken: dictionary - Mark the machine as broken or fixed. Fields are 'broken' (boolean - whether or not the machine is broken), 'info' (string - notes about why the machine is broken), 'ticket' (string - ticket reference for this machine)
                 status: string - Status of the machine
                 resources: dictionary - Key-value pair resource:value of resources to update. (set value to null to remove a resource)
                 addflags: list - Flags to add to this machine
                 delflags: list - Flags to remove from this machine
        """
        path = "%s/machine/{name}" % (self.base)
        path = path.replace("{name}", self.__serializeForPath(name))
        paramdict = {}
        files = {}
        payload = {}
        j = {}
        if status != None:
            j['status'] = status
        if broken != None:
            j['broken'] = broken
        if params != None:
            j['params'] = params
        if addflags != None:
            j['addflags'] = addflags
        if delflags != None:
            j['delflags'] = delflags
        if resources != None:
            j['resources'] = resources
        payload = json.dumps(j)
        myHeaders = {'content-type': 'application/json'}
        myHeaders.update(self.customHeaders)
        r = requests.post(path, params=paramdict, data=payload, files=files, headers=myHeaders)
        self.__raiseForStatus(r)
        return r.json()


    def remove_machine(self, name):
        """ Removes a machine
            Parameters:
                 name: string - Machine to remove
        """
        path = "%s/machine/{name}" % (self.base)
        path = path.replace("{name}", self.__serializeForPath(name))
        paramdict = {}
        files = {}
        payload = {}
        myHeaders = {'content-type': 'application/json'}
        myHeaders.update(self.customHeaders)
        r = requests.delete(path, params=paramdict, data=payload, files=files, headers=myHeaders)
        self.__raiseForStatus(r)
        return r.json()


    def get_machine(self, name):
        """ Gets a specific machine object
            Parameters:
                 name: string - Machine to fetch
        """
        path = "%s/machine/{name}" % (self.base)
        path = path.replace("{name}", self.__serializeForPath(name))
        paramdict = {}
        files = {}
        payload = {}
        r = requests.get(path, params=paramdict, headers=self.customHeaders)
        self.__raiseForStatus(r)
        return r.json()


    def upload_perfdata(self, filepath):
        """ Add performance data from XML file
            Parameters:
                 filepath: file path - File to upload
        """
        path = "%s/perfdata" % (self.base)
        paramdict = {}
        files = {}
        payload = {}
        if filepath != None:
            files['file'] = (os.path.basename(filepath), open(filepath, 'rb'))
        else:
            files['file'] = ('stdin', sys.stdin)
        myHeaders = {}
        myHeaders.update(self.customHeaders)
        r = requests.post(path, params=paramdict, data=payload, files=files, headers=myHeaders)
        self.__raiseForStatus(r)
        return r.json()


    def new_machine(self, name, site, pool, cluster, flags=None, resources=None, params=None, description=None):
        """ Add new machine
            Parameters:
                 name: string - Name of the machine
                 site: string - Site this machine belongs to
                 pool: string - Pool this machine belongs to
                 cluster: string - Cluster this machine belongs to
                 flags: list - Flags for this machine
                 resources: dictionary - Key-value pair resource:value of resources to update. (set value to null to remove a resource)
                 params: dictionary - Key-value pairs parameter:value of parameters to update (set value to null to delete a parameter)
                 description: string - Description of the machine
        """
        path = "%s/machines" % (self.base)
        paramdict = {}
        files = {}
        payload = {}
        j = {}
        if cluster != None:
            j['cluster'] = cluster
        if name != None:
            j['name'] = name
        if site != None:
            j['site'] = site
        if pool != None:
            j['pool'] = pool
        if params != None:
            j['params'] = params
        if flags != None:
            j['flags'] = flags
        if resources != None:
            j['resources'] = resources
        if description != None:
            j['description'] = description
        payload = json.dumps(j)
        myHeaders = {'content-type': 'application/json'}
        myHeaders.update(self.customHeaders)
        r = requests.post(path, params=paramdict, data=payload, files=files, headers=myHeaders)
        self.__raiseForStatus(r)
        return r.json()


    def get_machines(self, status=None, site=None, pool=None, cluster=None, user=None, machine=None, resource=None, flag=None, limit=None, offset=None, pseudohosts=None):
        """ Get machines matching parameters
            Parameters:
                 status: list - Filter on machine status. Any of "idle", "running", "leased", "offline", "broken" - can specify multiple
                 site: list - Filter on site - can specify multiple
                 pool: list - Filter on pool - can specify multiple
                 cluster: list - Filter on cluster - can specify multiple
                 user: list - Filter on lease user - can specify multiple
                 machine: list - Get a specific machine - can specify multiple
                 resource: list - Filter on a resource - can specify multiple
                 flag: list - Filter on a flag - can specify multiple
                 limit: integer - Limit the number of results. Defaults to unlimited
                 offset: integer - Offset to start the results at, for paging with limit enabled.
                 pseudohosts: boolean - Get pseudohosts, defaults to false
        """
        path = "%s/machines" % (self.base)
        paramdict = {}
        files = {}
        if status != None:
            paramdict['status'] = self.__serializeForQuery(status)
        if site != None:
            paramdict['site'] = self.__serializeForQuery(site)
        if pool != None:
            paramdict['pool'] = self.__serializeForQuery(pool)
        if cluster != None:
            paramdict['cluster'] = self.__serializeForQuery(cluster)
        if user != None:
            paramdict['user'] = self.__serializeForQuery(user)
        if machine != None:
            paramdict['machine'] = self.__serializeForQuery(machine)
        if resource != None:
            paramdict['resource'] = self.__serializeForQuery(resource)
        if flag != None:
            paramdict['flag'] = self.__serializeForQuery(flag)
        if limit != None:
            paramdict['limit'] = self.__serializeForQuery(limit)
        if offset != None:
            paramdict['offset'] = self.__serializeForQuery(offset)
        if pseudohosts != None:
            paramdict['pseudohosts'] = self.__serializeForQuery(pseudohosts)
        payload = {}
        r = requests.get(path, params=paramdict, headers=self.customHeaders)
        self.__raiseForStatus(r)
        return r.json()


    def update_site(self, name, description=None, ctrladdr=None, maxjobs=None, flags=None, addflags=None, delflags=None, sharedresources=None):
        """ Update a site
            Parameters:
                 name: integer - Site to update
                 description: string - Description of the site
                 ctrladdr: string - IP address of the site controller
                 maxjobs: integer - Maximum concurrent jobs on this site
                 flags: list - Flags for this site
                 addflags: list - Flags to add to this site
                 delflags: list - Flags to remove from this site
                 sharedresources: dictionary - Key-value pair resource:value of resources to update. (set value to null to remove a resource)
        """
        path = "%s/site/{name}" % (self.base)
        path = path.replace("{name}", self.__serializeForPath(name))
        paramdict = {}
        files = {}
        payload = {}
        j = {}
        if description != None:
            j['description'] = description
        if ctrladdr != None:
            j['ctrladdr'] = ctrladdr
        if sharedresources != None:
            j['sharedresources'] = sharedresources
        if flags != None:
            j['flags'] = flags
        if addflags != None:
            j['addflags'] = addflags
        if delflags != None:
            j['delflags'] = delflags
        if maxjobs != None:
            j['maxjobs'] = maxjobs
        payload = json.dumps(j)
        myHeaders = {'content-type': 'application/json'}
        myHeaders.update(self.customHeaders)
        r = requests.post(path, params=paramdict, data=payload, files=files, headers=myHeaders)
        self.__raiseForStatus(r)
        return r.json()


    def remove_site(self, name):
        """ Removes a site
            Parameters:
                 name: string - Machine to remove
        """
        path = "%s/site/{name}" % (self.base)
        path = path.replace("{name}", self.__serializeForPath(name))
        paramdict = {}
        files = {}
        payload = {}
        myHeaders = {'content-type': 'application/json'}
        myHeaders.update(self.customHeaders)
        r = requests.delete(path, params=paramdict, data=payload, files=files, headers=myHeaders)
        self.__raiseForStatus(r)
        return r.json()


    def get_site(self, name):
        """ Gets a specific site object
            Parameters:
                 name: string - Site to fetch
        """
        path = "%s/site/{name}" % (self.base)
        path = path.replace("{name}", self.__serializeForPath(name))
        paramdict = {}
        files = {}
        payload = {}
        r = requests.get(path, params=paramdict, headers=self.customHeaders)
        self.__raiseForStatus(r)
        return r.json()


    def get_loggedinuser(self):
        """ Get the currently logged in user
            Parameters:
        """
        path = "%s/loggedinuser" % (self.base)
        paramdict = {}
        files = {}
        payload = {}
        r = requests.get(path, params=paramdict, headers=self.customHeaders)
        self.__raiseForStatus(r)
        return r.json()['user']


    def get_test(self, id, logitems=None):
        """ Gets a specific test object
            Parameters:
                 id: integer - Job ID to fetch
                 logitems: boolean - Return the log items for all testcases in the job. Defaults to false
        """
        path = "%s/test/{id}" % (self.base)
        path = path.replace("{id}", self.__serializeForPath(id))
        paramdict = {}
        files = {}
        if logitems != None:
            paramdict['logitems'] = self.__serializeForQuery(logitems)
        payload = {}
        r = requests.get(path, params=paramdict, headers=self.customHeaders)
        self.__raiseForStatus(r)
        return r.json()


    def get_logserver(self):
        """ Get default log server
            Parameters:
        """
        path = "%s/logserver" % (self.base)
        paramdict = {}
        files = {}
        payload = {}
        r = requests.get(path, params=paramdict, headers=self.customHeaders)
        self.__raiseForStatus(r)
        return r.json()['server']


    def set_result(self, id, phase, test, result):
        """ Set the result of a test
            Parameters:
                 id: integer - Job ID to add result to
                 phase: string - Test phase to add result to
                 test: string - Testcase to add result to
                 result: string - Result of the test
        """
        path = "%s/job/{id}/tests/{phase}/{test}" % (self.base)
        path = path.replace("{id}", self.__serializeForPath(id))
        path = path.replace("{phase}", self.__serializeForPath(phase))
        path = path.replace("{test}", self.__serializeForPath(test))
        paramdict = {}
        files = {}
        payload = {}
        j = {}
        if result != None:
            j['result'] = result
        payload = json.dumps(j)
        myHeaders = {'content-type': 'application/json'}
        myHeaders.update(self.customHeaders)
        r = requests.post(path, params=paramdict, data=payload, files=files, headers=myHeaders)
        self.__raiseForStatus(r)
        return r.json()


    def update_job(self, id, params=None, complete=None):
        """ Update job details
            Parameters:
                 id: integer - Job ID to update
                 params: dictionary - Key-value pairs of parameters to update (set null to delete a parameter)
                 complete: boolean - Set to true to complete the job
        """
        path = "%s/job/{id}" % (self.base)
        path = path.replace("{id}", self.__serializeForPath(id))
        paramdict = {}
        files = {}
        payload = {}
        j = {}
        if params != None:
            j['params'] = params
        if complete != None:
            j['complete'] = complete
        payload = json.dumps(j)
        myHeaders = {'content-type': 'application/json'}
        myHeaders.update(self.customHeaders)
        r = requests.post(path, params=paramdict, data=payload, files=files, headers=myHeaders)
        self.__raiseForStatus(r)
        return r.json()


    def remove_job(self, id, return_machines=None):
        """ Removes a job
            Parameters:
                 id: integer - Job ID to remove
                 return_machines: boolean - Whether to return the machines borrowed by this job
        """
        path = "%s/job/{id}" % (self.base)
        path = path.replace("{id}", self.__serializeForPath(id))
        paramdict = {}
        files = {}
        payload = {}
        j = {}
        if return_machines != None:
            j['return_machines'] = return_machines
        payload = json.dumps(j)
        myHeaders = {'content-type': 'application/json'}
        myHeaders.update(self.customHeaders)
        r = requests.delete(path, params=paramdict, data=payload, files=files, headers=myHeaders)
        self.__raiseForStatus(r)
        return r.json()


    def get_job(self, id, logitems=None):
        """ Gets a specific job object
            Parameters:
                 id: integer - Job ID to fetch
                 logitems: boolean - Return the log items for all testcases in the job. Defaults to false
        """
        path = "%s/job/{id}" % (self.base)
        path = path.replace("{id}", self.__serializeForPath(id))
        paramdict = {}
        files = {}
        if logitems != None:
            paramdict['logitems'] = self.__serializeForQuery(logitems)
        payload = {}
        r = requests.get(path, params=paramdict, headers=self.customHeaders)
        self.__raiseForStatus(r)
        return r.json()


    def new_job(self, machines=None, pools=None, flags=None, resources=None, specified_machines=None, sequence=None, custom_sequence=None, params=None, deployment=None, job_group=None, email=None, inputdir=None, lease_machines=None):
        """ Submits a new job
            Parameters:
                 machines: integer - Number of machines required for this job
                 pools: list - Pools this job can run on
                 flags: list - List of flags required. Can negate by prefixing a flag with '!'
                 resources: list - List of resources required. One such item might be memory>=4G
                 specified_machines: list - Specified list of machines for this job to run on
                 sequence: string - Sequence file name
                 custom_sequence: boolean - Whether the sequence is in xenrt.git (false) or a custom sequence (true)
                 params: dictionary - Key/value pair of job parameters
                 deployment: dictionary - JSON deployment spec to just create a deployment
                 job_group: dictionary - Job group details. Members are 'id' (integer - id of job group), 'tag' (string - tag for this job
                 email: string - Email address to notify on completion
                 inputdir: string - Input directory for the job
                 lease_machines: dictionary - Machine lease details. Members are 'duration' (integer - length of lease in hours), 'reason' (string -  reason that will be associated with the machine lease)
        """
        path = "%s/jobs" % (self.base)
        paramdict = {}
        files = {}
        payload = {}
        j = {}
        if custom_sequence != None:
            j['custom_sequence'] = custom_sequence
        if sequence != None:
            j['sequence'] = sequence
        if job_group != None:
            j['job_group'] = job_group
        if deployment != None:
            j['deployment'] = deployment
        if lease_machines != None:
            j['lease_machines'] = lease_machines
        if machines != None:
            j['machines'] = machines
        if specified_machines != None:
            j['specified_machines'] = specified_machines
        if inputdir != None:
            j['inputdir'] = inputdir
        if params != None:
            j['params'] = params
        if pools != None:
            j['pools'] = pools
        if flags != None:
            j['flags'] = flags
        if email != None:
            j['email'] = email
        if resources != None:
            j['resources'] = resources
        payload = json.dumps(j)
        myHeaders = {'content-type': 'application/json'}
        myHeaders.update(self.customHeaders)
        r = requests.post(path, params=paramdict, data=payload, files=files, headers=myHeaders)
        self.__raiseForStatus(r)
        return r.json()


    def get_jobs(self, status=None, user=None, excludeuser=None, suiterun=None, machine=None, jobid=None, detailid=None, limit=None, params=None, results=None, logitems=None):
        """ Get jobs matching parameters
            Parameters:
                 status: list - Filter on job status. Any of "new", "running", "removed", "done" - can specify multiple
                 user: list - Filter on user - can specify multiple
                 excludeuser: list - Exclude jobs from this user from the results. Can specify multiple
                 suiterun: list - Filter on suite run - can specify multiple
                 machine: list - Filter on machine the job was executed on - can specify multiple
                 jobid: list - Get a specific job - can specify multiple
                 detailid: list - Find a job with a specific detail ID - can specify multiple
                 limit: integer - Limit the number of results. Defaults to 100, hard limited to 10000
                 params: boolean - Return all job parameters. Defaults to false
                 results: boolean - Return the results from all testcases in the job. Defaults to false
                 logitems: boolean - Return the log items for all testcases in the job. Must also specify results. Defaults to false
        """
        path = "%s/jobs" % (self.base)
        paramdict = {}
        files = {}
        if status != None:
            paramdict['status'] = self.__serializeForQuery(status)
        if user != None:
            paramdict['user'] = self.__serializeForQuery(user)
        if excludeuser != None:
            paramdict['excludeuser'] = self.__serializeForQuery(excludeuser)
        if suiterun != None:
            paramdict['suiterun'] = self.__serializeForQuery(suiterun)
        if machine != None:
            paramdict['machine'] = self.__serializeForQuery(machine)
        if jobid != None:
            paramdict['jobid'] = self.__serializeForQuery(jobid)
        if detailid != None:
            paramdict['detailid'] = self.__serializeForQuery(detailid)
        if limit != None:
            paramdict['limit'] = self.__serializeForQuery(limit)
        if params != None:
            paramdict['params'] = self.__serializeForQuery(params)
        if results != None:
            paramdict['results'] = self.__serializeForQuery(results)
        if logitems != None:
            paramdict['logitems'] = self.__serializeForQuery(logitems)
        payload = {}
        r = requests.get(path, params=paramdict, headers=self.customHeaders)
        self.__raiseForStatus(r)
        return r.json()


    def new_site(self, name, description=None, ctrladdr=None, maxjobs=None, flags=None, sharedresources=None):
        """ Create a new site
            Parameters:
                 name: string - Name of the site
                 description: string - Description of the site
                 ctrladdr: string - IP address of the site controller
                 maxjobs: integer - Maximum concurrent jobs on this site
                 flags: list - Flags for this site
                 sharedresources: dictionary - Key-value pair resource:value of resources to update. (set value to null to remove a resource)
        """
        path = "%s/sites" % (self.base)
        paramdict = {}
        files = {}
        payload = {}
        j = {}
        if name != None:
            j['name'] = name
        if ctrladdr != None:
            j['ctrladdr'] = ctrladdr
        if description != None:
            j['description'] = description
        if sharedresources != None:
            j['sharedresources'] = sharedresources
        if flags != None:
            j['flags'] = flags
        if maxjobs != None:
            j['maxjobs'] = maxjobs
        payload = json.dumps(j)
        myHeaders = {'content-type': 'application/json'}
        myHeaders.update(self.customHeaders)
        r = requests.post(path, params=paramdict, data=payload, files=files, headers=myHeaders)
        self.__raiseForStatus(r)
        return r.json()


    def get_sites(self, site=None, flag=None):
        """ Get sites matching parameters
            Parameters:
                 site: list - Get a specific site - can specify multiple
                 flag: list - Filter on a flag - can specify multiple
        """
        path = "%s/sites" % (self.base)
        paramdict = {}
        files = {}
        if site != None:
            paramdict['site'] = self.__serializeForQuery(site)
        if flag != None:
            paramdict['flag'] = self.__serializeForQuery(flag)
        payload = {}
        r = requests.get(path, params=paramdict, headers=self.customHeaders)
        self.__raiseForStatus(r)
        return r.json()


    def get_global_resource(self, name):
        """ Get details of one global resource
            Parameters:
                 name: string - Resource to fetch
        """
        path = "%s/globalresource/{name}" % (self.base)
        path = path.replace("{name}", self.__serializeForPath(name))
        paramdict = {}
        files = {}
        payload = {}
        r = requests.get(path, params=paramdict, headers=self.customHeaders)
        self.__raiseForStatus(r)
        return r.json()


    def new_event(self, event_type, subject, data):
        """ Add an event to the database
            Parameters:
                 event_type: string - Event type
                 subject: string - Subject
                 data: string - Data
        """
        path = "%s/events" % (self.base)
        paramdict = {}
        files = {}
        payload = {}
        j = {}
        if data != None:
            j['data'] = data
        if event_type != None:
            j['event_type'] = event_type
        if subject != None:
            j['subject'] = subject
        payload = json.dumps(j)
        myHeaders = {'content-type': 'application/json'}
        myHeaders.update(self.customHeaders)
        r = requests.post(path, params=paramdict, data=payload, files=files, headers=myHeaders)
        self.__raiseForStatus(r)
        return r.json()


    def lease_machine(self, name, duration, reason, force=None):
        """ Lease a machine
            Parameters:
                 name: string - Machine to lease
                 duration: integer - Time in hours to lease the machine. 0 means forever
                 reason: string - Reason the machine is to be leased
                 force: boolean - Whether to force lease if another use has the machine leased
        """
        path = "%s/machine/{name}/lease" % (self.base)
        path = path.replace("{name}", self.__serializeForPath(name))
        paramdict = {}
        files = {}
        payload = {}
        j = {}
        if duration != None:
            j['duration'] = duration
        if reason != None:
            j['reason'] = reason
        if force != None:
            j['force'] = force
        payload = json.dumps(j)
        myHeaders = {'content-type': 'application/json'}
        myHeaders.update(self.customHeaders)
        r = requests.post(path, params=paramdict, data=payload, files=files, headers=myHeaders)
        self.__raiseForStatus(r)
        return r.json()


    def return_leased_machine(self, name, force=None):
        """ Return a leased machine
            Parameters:
                 name: string - Machine to lease
                 force: boolean - Whether to force return if another use has the machine leased
        """
        path = "%s/machine/{name}/lease" % (self.base)
        path = path.replace("{name}", self.__serializeForPath(name))
        paramdict = {}
        files = {}
        payload = {}
        j = {}
        if force != None:
            j['force'] = force
        payload = json.dumps(j)
        myHeaders = {'content-type': 'application/json'}
        myHeaders.update(self.customHeaders)
        r = requests.delete(path, params=paramdict, data=payload, files=files, headers=myHeaders)
        self.__raiseForStatus(r)
        return r.json()


    def get_job_attachment_post_run(self, id, filepath):
        """ Get URL for job attachment, uploaded after job ran
            Parameters:
                 id: integer - Job ID to get file from
                 filepath: string - File to download
        """
        path = "%s/job/{id}/attachment/postrun/{file}" % (self.base)
        path = path.replace("{id}", self.__serializeForPath(id))
        path = path.replace("{file}", self.__serializeForPath(filepath))
        paramdict = {}
        files = {}
        payload = {}
        r = requests.get(path, params=paramdict, headers=self.customHeaders)
        self.__raiseForStatus(r)
        return r.json()['url']


    def replace_apikey(self):
        """ Replace API key for logged in User
            Parameters:
        """
        path = "%s/apikey" % (self.base)
        paramdict = {}
        files = {}
        payload = {}
        myHeaders = {'content-type': 'application/json'}
        myHeaders.update(self.customHeaders)
        r = requests.put(path, params=paramdict, data=payload, files=files, headers=myHeaders)
        self.__raiseForStatus(r)
        return r.json()


    def remove_apikey(self):
        """ Remove API key for logged in User
            Parameters:
        """
        path = "%s/apikey" % (self.base)
        paramdict = {}
        files = {}
        payload = {}
        myHeaders = {'content-type': 'application/json'}
        myHeaders.update(self.customHeaders)
        r = requests.delete(path, params=paramdict, data=payload, files=files, headers=myHeaders)
        self.__raiseForStatus(r)
        return r.json()


    def get_apikey(self):
        """ Get API key for logged in User
            Parameters:
        """
        path = "%s/apikey" % (self.base)
        paramdict = {}
        files = {}
        payload = {}
        r = requests.get(path, params=paramdict, headers=self.customHeaders)
        self.__raiseForStatus(r)
        return r.json()['key']


    def get_job_attachment_pre_run(self, id, filepath):
        """ Get URL for job attachment, uploaded before job ran
            Parameters:
                 id: integer - Job ID to get file from
                 filepath: string - File to download
        """
        path = "%s/job/{id}/attachment/prerun/{file}" % (self.base)
        path = path.replace("{id}", self.__serializeForPath(id))
        path = path.replace("{file}", self.__serializeForPath(filepath))
        paramdict = {}
        files = {}
        payload = {}
        r = requests.get(path, params=paramdict, headers=self.customHeaders)
        self.__raiseForStatus(r)
        return r.json()['url']


    def get_job_deployment(self, id):
        """ Get deployment for job
            Parameters:
                 id: integer - Job ID to get file from
        """
        path = "%s/job/{id}/deployment" % (self.base)
        path = path.replace("{id}", self.__serializeForPath(id))
        paramdict = {}
        files = {}
        payload = {}
        r = requests.get(path, params=paramdict, headers=self.customHeaders)
        self.__raiseForStatus(r)
        return r.json()


    def send_job_email(self, id):
        """ Gets a specific job object
            Parameters:
                 id: integer - Job ID to fetch
        """
        path = "%s/job/{id}/email" % (self.base)
        path = path.replace("{id}", self.__serializeForPath(id))
        paramdict = {}
        files = {}
        payload = {}
        myHeaders = {'content-type': 'application/json'}
        myHeaders.update(self.customHeaders)
        r = requests.post(path, params=paramdict, data=payload, files=files, headers=myHeaders)
        self.__raiseForStatus(r)
        return r.json()


    def get_global_resources(self):
        """ List all of the global resources
            Parameters:
        """
        path = "%s/globalresources" % (self.base)
        paramdict = {}
        files = {}
        payload = {}
        r = requests.get(path, params=paramdict, headers=self.customHeaders)
        self.__raiseForStatus(r)
        return r.json()


    def upload_subresults(self, id, phase, test, filepath):
        """ Add sub results to a test from an XML file
            Parameters:
                 id: integer - Job ID to add subresults to
                 phase: string - Test phase to add subresults to
                 test: string - Testcase to add subresults to
                 filepath: file path - File to upload
        """
        path = "%s/job/{id}/tests/{phase}/{test}/subresults" % (self.base)
        path = path.replace("{id}", self.__serializeForPath(id))
        path = path.replace("{phase}", self.__serializeForPath(phase))
        path = path.replace("{test}", self.__serializeForPath(test))
        paramdict = {}
        files = {}
        payload = {}
        if filepath != None:
            files['file'] = (os.path.basename(filepath), open(filepath, 'rb'))
        else:
            files['file'] = ('stdin', sys.stdin)
        myHeaders = {}
        myHeaders.update(self.customHeaders)
        r = requests.post(path, params=paramdict, data=payload, files=files, headers=myHeaders)
        self.__raiseForStatus(r)
        return r.json()


    def new_logdata(self, id, phase, test, key, value):
        """ Add log data to a test
            Parameters:
                 id: integer - Job ID to add result to
                 phase: string - Test phase to add result to
                 test: string - Testcase to add result to
                 key: string - Log data key
                 value: string - Log data value
        """
        path = "%s/job/{id}/tests/{phase}/{test}/logdata" % (self.base)
        path = path.replace("{id}", self.__serializeForPath(id))
        path = path.replace("{phase}", self.__serializeForPath(phase))
        path = path.replace("{test}", self.__serializeForPath(test))
        paramdict = {}
        files = {}
        payload = {}
        j = {}
        if value != None:
            j['value'] = value
        if key != None:
            j['key'] = key
        payload = json.dumps(j)
        myHeaders = {'content-type': 'application/json'}
        myHeaders.update(self.customHeaders)
        r = requests.post(path, params=paramdict, data=payload, files=files, headers=myHeaders)
        self.__raiseForStatus(r)
        return r.json()


