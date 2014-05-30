from app import XenRTPage
from server import PageFactory

import app.constants

import config

import string

class XenRTAPIPage(XenRTPage):

    def __init__(self, request):
        super(XenRTAPIPage, self).__init__(request)
        self.schedulercache = {"siteresources":{}, "siteprops": {}, "machineprops": {}}

    def scm_site_list(self, status=None,checkFull=False):
        """Return details of sites."""

        qry = []
        if status:
            qry.append("status = '%s'" % (status))
        if len(qry) == 0:
            qrystr = ""
        else:
            qrystr = "WHERE %s" % string.join(qry, " AND ")

        sql = """SELECT s.site, s.status, s.flags, s.descr, s.comment, s.ctrladdr,
                        s.adminid, s.maxjobs
                 FROM tblSites s %s ORDER BY site;""" % (qrystr)
        cur = self.getDB().cursor()
        cur.execute(sql)

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
        sql = """SELECT s.site, s.status, s.flags, s.descr, s.comment, s.ctrladdr,
                        s.adminid, s.maxjobs, s.sharedresources
                 FROM tblSites s WHERE s.site = '%s'
                 """ % (app.utils.sqlescape(site))
        cur.execute(sql)
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
        cur.execute("SELECT jobid FROM tblmachines WHERE site='%s' AND (status='scheduled' OR status='running');" % app.utils.sqlescape(site))
        rc = cur.fetchall()
        return map(lambda x: x[0], rc)

    def scm_machine_update(self, machine, site, cluster, pool, status, resources,
                           flags, descr, leasepolicy):
        if pool:
            dpool = "'%s'" % (app.utils.sqlescape(pool))
        else:
            dpool = "default"
        if status:
            dstatus = "'%s'" % (app.utils.sqlescape(status))
        else:
            dstatus = "default"
        db = self.getDB()
        cur = db.cursor()
        sql = "SELECT machine FROM tblMachines WHERE machine = '%s'" % (machine)
        cur.execute(sql)
        if cur.fetchone():
            u = []
            if site:
                u.append("site = '%s'" % (app.utils.sqlescape(site)))
            if cluster:
                u.append("cluster = '%s'" % (app.utils.sqlescape(cluster)))
            if pool:
                u.append("pool = '%s'" % (app.utils.sqlescape(pool)))
            if status:
                u.append("status = '%s'" % (app.utils.sqlescape(status)))
            if resources:
                u.append("resources = '%s'" % (app.utils.sqlescape(resources)))
            if flags:
                u.append("flags = '%s'" % (app.utils.sqlescape(flags)))
            if descr:
                u.append("descr = '%s'" % (app.utils.sqlescape(descr)))
            if leasepolicy != None:
                if leasepolicy == "":
                    u.append("leasepolicy = NULL")
                else:
                    u.append("leasepolicy = %d" % (int(leasepolicy)))
            sql = "UPDATE tblMachines SET %s WHERE machine = '%s'" % \
                  (string.join(u, ", "), app.utils.sqlescape(machine))
        else:
            sql = """INSERT into tblMachines (machine, site, cluster, pool,
                                              status, resources, flags, descr)
                     VALUES
            ('%s', '%s', '%s', %s, %s, '%s', '%s', '%s')""" % (app.utils.sqlescape(machine),
                                                               app.utils.sqlescape(site),
                                                               app.utils.sqlescape(cluster),
                                                               dpool,
                                                               dstatus,
                                                               app.utils.sqlescape(resources),
                                                               app.utils.sqlescape(flags),
                                                               app.utils.sqlescape(descr))
        cur.execute(sql)
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
        if site:
            qry.append("site = '%s'" % (site))
        if cluster:
            qry.append("cluster = '%s'" % (cluster))
        if machine:
            qry.append("machine = '%s'" % (machine))
        if status:
            qry.append("status = '%s'" % (status))
        if pool:
            qry.append("pool = '%s'" % (pool))
        if leasecheck != None:
            if leasecheck == True:
                qry.append("leaseTo IS NOT NULL")
            elif leasecheck == False:
                qry.append("leaseTo IS NULL")
            else:
                qry.append("leaseTo IS NOT NULL AND comment='%s'" % leasecheck)
        if len(qry) == 0:
            qrystr = ""
        else:
            qrystr = "WHERE %s" % string.join(qry, " AND ")
        sql = """SELECT m.machine, m.site, m.cluster, m.pool, m.status,
                        m.resources, m.flags, m.descr, m.comment, m.leaseTo,
                        m.jobid, m.leasefrom, m.leasereason
                 FROM tblMachines m %s ORDER BY machine;""" % (qrystr)
        cur = db.cursor()
        cur.execute(sql)

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
                    (app.utils.sqlescape(param), string.join(map(str, joblist), ",")))
        else:
            cur.execute("SELECT jobid, value FROM tblJobDetails WHERE jobid in (%s)"
                    " AND param = '%s'" %
                    (string.join(map(str, joblist), ","), app.utils.sqlescape(param)))
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
        cur.execute(("SELECT key, value FROM tblMachineData " +
                     "WHERE machine = '%s';") % (machine))
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
                 FROM tblMachines m WHERE m.machine = '%s'
                 """ % (app.utils.sqlescape(machine))
        cur.execute(sql)
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
            cur.execute(("UPDATE tbljobs SET jobstatus='%s' WHERE jobid=%u;") % (jobstatus,id))
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
                cur.execute("UPDATE tbljobs SET %s='%s' WHERE jobid=%u;" % 
                            (key,value,id))
                if commit:
                    db.commit()
            finally:
                cur.close()
        else:
            cur = db.cursor()
            try:
                if not details.has_key(key):
                    cur.execute("INSERT INTO tbljobdetails (jobid,param,value) "
                                "VALUES (%u,'%s','%s');" % (id, key, value))
                elif len(value) > 0:
                    cur.execute("UPDATE tbljobdetails SET value='%s' WHERE "
                                "jobid=%u AND param='%s';" % (value,id,key))
                else:
                    # Use empty string as a way to delete a property
                    cur.execute("DELETE FROM tbljobdetails WHERE jobid=%u "
                                "AND param='%s';" % (id, key))
                db.commit()
            finally:
                cur.close()

class XenRTMasterURL(XenRTAPIPage):
    def render(self):
        return config.masterurl

PageFactory(XenRTMasterURL, "masterurl", "/api/masterurl", compatAction="getmasterurl")

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
