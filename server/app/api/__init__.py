from app import XenRTPage
from server import PageFactory

import app.constants

import config

import string
from pyramid.httpexceptions import *
import requests

class XenRTAPIPage(XenRTPage):

    def __init__(self, request):
        super(XenRTAPIPage, self).__init__(request)
        self.schedulercache = {"siteresources":{}, "siteprops": {}, "machineprops": {}}

    def scm_site_list(self, status=None,checkFull=False):
        """Return details of sites."""

        sql = """SELECT s.site, s.status, s.flags, s.descr, s.comment, s.ctrladdr,
                        s.adminid, s.maxjobs
                 FROM tblSites s WHERE 1=1"""
        params = []
        if status:
            sql += " AND status = %s"
            params.append(status)

        sql += " ORDER BY site;"
        cur = self.getDB().cursor()
        cur.execute(sql, params) 

        reply = []
        while 1:
            rc = cur.fetchone()
            if not rc:
                break
            rep = map(app.utils.mystrip, rc)
            if checkFull:
                # Only include sites that are full (defined as having >= 20 active
                # jobs)

                # Each job has one 'running' machine, as any other machines are
                # 'slaved', so filtering on 'running' gets us the count of jobs
                currentActive = len(self.scm_machine_list(site=rep[0],status='running')) + len(self.scm_machine_list(site=rep[0],status='scheduled'))
                rep.append(int(rep[7]) - currentActive)
            reply.append(rep)
                
        cur.close()
        return reply

    def site_data(self, site):

        maindata = self.scm_site_get(site)
        if not maindata:
            return {}

        d = {}
        if maindata[0]:
            d["SITE"] = maindata[0]
        if maindata[1]:
            d["STATUS"] = maindata[1]
        if maindata[2]:
            d["FLAGS"] = maindata[2]
        if maindata[3]:
            d["DESCRIPTION"] = maindata[3]
        if maindata[4]:
            d["COMMENT"] = maindata[4]
        if maindata[5]:
            d["CTRLADDR"] = maindata[5]
        if maindata[6]:
            d["ADMINID"] = maindata[6]
        if maindata[7]:
            d["MAXJOBS"] = maindata[7]
        if maindata[8]:
            d["SHAREDRESOURCES"] = maindata[8]

        return d

    def scm_site_get(self, site):
        """Get details of a site"""
        cur = self.getDB().cursor()
        cur.execute("""SELECT s.site, s.status, s.flags, s.descr, s.comment, s.ctrladdr,
                              s.adminid, s.maxjobs, s.sharedresources
                       FROM tblSites s WHERE s.site = %s""",
                    [site])
        rc = cur.fetchone()
        cur.close()
        if not rc:
            return None
        return map(app.utils.mystrip, rc)

    def site_available_shared_resources(self, site):
        
        if self.schedulercache["siteresources"].has_key(site):
            return self.schedulercache["siteresources"][site]
        sitedata = self.site_data(site)
        resources = {}
        if sitedata.has_key("SHAREDRESOURCES"):
            resstring = sitedata["SHAREDRESOURCES"]
            resources = app.utils.parse_shared_resources(resstring)
            jobs = self.list_jobs_for_site(site)
            for j in jobs:
                details = self.get_job(j)
                if details.has_key("SHAREDRESOURCES"):
                    usedresources = app.utils.parse_shared_resources(details["SHAREDRESOURCES"])
                    for r in usedresources.keys():
                        if resources.has_key(r):
                            resources[r] = resources[r] - usedresources[r]
        self.schedulercache["siteresources"][site] = resources
        return resources

    def list_jobs_for_site(self, site):
        cur = self.getDB().cursor()
        cur.execute("SELECT jobid FROM tblmachines WHERE site=%s AND (status='scheduled' OR status='running');", [site])
        rc = cur.fetchall()
        return map(lambda x: x[0], rc)

    def scm_machine_update(self, machine, site, cluster, pool, status, resources,
                           flags, descr, leasepolicy):
        if pool:
            dpool = pool
        else:
            dpool = "default"
        if status:
            dstatus = status
        else:
            dstatus = "idle"
        db = self.getDB()
        cur = db.cursor()
        cur.execute("SELECT machine FROM tblMachines WHERE machine = %s", [machine])
        if cur.fetchone():
            u = []
            if site is not None:
                u.append(("site", site))
            if cluster is not None:
                u.append(("cluster", cluster))
            if pool is not None:
                u.append(("pool", pool))
            if status is not None:
                u.append(("status", status))
            if resources is not None:
                u.append(("resources", resources))
            if flags is not None:
                u.append(("flags", flags))
            if descr is not None:
                u.append(("descr", descr))
            if leasepolicy is not None:
                if leasepolicy == "":
                    u.append(("leasepolicy", None))
                else:
                    u.append(("leasepolicy", int(leasepolicy)))

            sqlset = []
            params = []
            for param, val in u:
                sqlset.append("%s = %%s" % param)
                params.append(val)
            sql = "UPDATE tblMachines SET %s WHERE machine = %%s" % (string.join(sqlset, ", "))
            params.append(machine)
            cur.execute(sql, params)
        else:
            sql = """INSERT into tblMachines (machine, site, cluster, pool,
                                              status, resources, flags, descr)
                     VALUES
            (%s, %s, %s, %s, %s, %s, %s, %s)"""
            cur.execute(sql, [machine, site, cluster, dpool, dstatus, resources, flags, descr])
        db.commit()
        cur.close()

    def scm_machine_list(self,
                         site=None,
                         cluster=None,
                         machine=None,
                         status=None,
                         leasecheck=None,
                         pool=None):
        """Return details of machines. If set, cluster and site will filter
        the results on that parameter"""
        db = self.getDB()

        qry = []
        params = []
        if site:
            qry.append("site = %s")
            params.append(site)
        if cluster:
            qry.append("cluster = %s")
            params.append(cluster)
        if machine:
            qry.append("machine = %s")
            params.append(machine)
        if status:
            qry.append("status = %s")
            params.append(status)
        if pool:
            qry.append("pool = %s")
            params.append(pool)
        if leasecheck != None:
            if leasecheck == True:
                qry.append("leaseTo IS NOT NULL")
            elif leasecheck == False:
                qry.append("leaseTo IS NULL")
            else:
                qry.append("leaseTo IS NOT NULL AND comment=%s")
                params.append(leasecheck)
        if len(qry) == 0:
            qrystr = ""
        else:
            qrystr = "WHERE %s" % string.join(qry, " AND ")
        sql = """SELECT m.machine, m.site, m.cluster, m.pool, m.status,
                        m.resources, m.flags, m.descr, m.comment, m.leaseTo,
                        m.jobid, m.leasefrom, m.leasereason
                 FROM tblMachines m %s ORDER BY machine;""" % (qrystr)
        cur = db.cursor()
        cur.execute(sql, params)
        reply = []
        while 1:
            rc = cur.fetchone()
            if not rc:
                break
            reply.append(map(app.utils.mystrip, rc))
                
        cur.close()
        return reply

    def get_param_for_jobs(self, param, joblist):
        if len(joblist) == 0:
            return {}
        db = self.getDB()
        cur = db.cursor()
        
        if param in app.constants.core_params:
            cur.execute("SELECT jobid, %s FROM tblJobs WHERE jobid in (%s)" %
                        (param, string.join(map(str, joblist), ",")))
        else:
            cur.execute("SELECT jobid, value FROM tblJobDetails WHERE jobid in (%s)"
                        " AND param = %%s" %
                        (string.join(map(str, joblist), ",")), [param])
        reply = {}
        while True:
            rc = cur.fetchone()
            if not rc:
                break
            reply[rc[0]] = string.strip(rc[1])
        cur.close()
        return reply

    def machine_data(self, machine):

        db = self.getDB()

        maindata = self.scm_machine_get(machine)
        if not maindata:
            return {}

        d = {}
        if maindata[1]:
            d["SITE"] = maindata[1]
        if maindata[2]:
            d["CLUSTER"] = maindata[2]
        if maindata[3]:
            d["POOL"] = maindata[3]
        if maindata[4]:
            d["STATUS"] = maindata[4]
        if maindata[5]:
            d["RESOURCES"] = maindata[5]
        if maindata[6]:
            d["FLAGS"] = maindata[6]
        if maindata[7]:
            d["DESCRIPTION"] = maindata[7]
        if maindata[8]:
            d["COMMENT"] = maindata[8]
            d["LEASEUSER"] = maindata[8]
        if maindata[9]:
            d["LEASETO"] = maindata[9]
        if maindata[10]:
            d["JOBID"] = maindata[10]
        if maindata[11]:
            d["LEASEFROM"] = maindata[11]
        if maindata[12]:
            d["LEASEREASON"] = maindata[12]
        if maindata[13]:
            d["LEASEPOLICY"] = maindata[13]

        cur = db.cursor()
        cur.execute("SELECT key, value FROM tblMachineData " +
                    "WHERE machine = %s;", [machine])
        while 1:
            rc = cur.fetchone()
            if not rc:
                 break
            if rc[0] and rc[1] and string.strip(rc[0]) != "" and \
                string.strip(rc[1]) != "":
                d[string.strip(rc[0])] = string.strip(rc[1])
        cur.close()
        return d

    def scm_machine_get(self, machine):
        """Get details of a named machine"""
        cur = self.getDB().cursor()
        sql = """SELECT m.machine, m.site, m.cluster, m.pool, m.status,
                        m.resources, m.flags, m.descr, m.comment, m.leaseTo,
                        m.jobid, m.leasefrom, m.leasereason, m.leasepolicy
                 FROM tblMachines m WHERE m.machine = %s
                 """
        cur.execute(sql, [machine])
        rc = cur.fetchone()
        cur.close()
        if not rc:
            return None
        return map(app.utils.mystrip, rc)

    def set_status(self, id, status, commit=True):

        db = self.getDB()

        try:
            jobstatus = app.constants.job_status_desc[status]
       
            cur = db.cursor()
            cur.execute("UPDATE tbljobs SET jobstatus=%s WHERE jobid=%s;", [jobstatus,id])
            if commit:
                db.commit()

        finally:
            cur.close()

    def update_field(self, id, key, value, commit=True):

        db = self.getDB()

        details = self.get_job(id)
        if not details:
            raise Exception("Could not find job %u" % (id))

        if key in app.constants.core_params:
            cur = db.cursor()
            try:
                cur.execute("UPDATE tbljobs SET %s=%%s WHERE jobid=%%s;" % (key), 
                            [value,id])
                if commit:
                    db.commit()
            finally:
                cur.close()
        else:
            cur = db.cursor()
            try:
                if not details.has_key(key):
                    cur.execute("INSERT INTO tbljobdetails (jobid,param,value) "
                                "VALUES (%s,%s,%s);", [id, key, value])
                elif len(value) > 0:
                    cur.execute("UPDATE tbljobdetails SET value=%s WHERE "
                                "jobid=%s AND param=%s;", [value,id,key])
                else:
                    # Use empty string as a way to delete a property
                    cur.execute("DELETE FROM tbljobdetails WHERE jobid=%s "
                                "AND param=%s;", [id, key])
                db.commit()
            finally:
                cur.close()
    
    def isDBMaster(self):
        try:
            readDB = app.db.dbReadInstance()
            readLoc = self.getReadLocation(readDB)
            if not readLoc:
                if not config.partner_ha_node:
                    return "This node is connected to the master database - no partner node exists to check for split brain"
                try:
                    r = requests.get("http://%s/xenrt/api/dbchecks/takeovertime" % config.partner_ha_node)
                    r.raise_for_status()
                    remote_time = int(r.text.strip())
                except Exception, e:
                    return "This node is connected the master database - partner does not seem to be the master database - %s" % str(e)
                cur = readDB.cursor()
                cur.execute("SELECT value FROM tblconfig WHERE param='takeover_time'")
                local_time = int(cur.fetchone()[0].strip())
                if local_time > remote_time:
                    return "This node is connected the master database - remote is talking to a writable database, but local database is newer"
                else:
                    print "This node is connected to a writable database, but remote database is newer"
                    raise HTTPServiceUnavailable()
            else:
                return None
        finally:
            readDB.rollback()
            readDB.close()

        

class XenRTLogServer(XenRTAPIPage):
    def render(self):
        return config.log_server

class DumpHeaders(XenRTAPIPage):
    def render(self):
        out = ""
        for h in self.request.headers.items():
            out += "%s: %s\n" % h
        return out


PageFactory(XenRTLogServer, "/api/logserver", compatAction="getlogserver")
PageFactory(DumpHeaders, "/api/dumpheaders")

import app.api.jobs
import app.api.sites
import app.api.machines
import app.api.schedule
import app.api.suite
import app.api.controller
import app.api.files
import app.api.results
import app.api.guestfile
import app.api.resources
import app.api.dbchecks
