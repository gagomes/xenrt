from server import PageFactory
from app.api import XenRTAPIPage

import config, app.constants

import string, time, smtplib, traceback, StringIO, re, sys, calendar

class XenRTJobPage(XenRTAPIPage):
    def showlog(self, id, wide, verbose, times=False):
        text = ""

        cur = self.getDB().cursor()
        cur2 = self.getDB().cursor()

        if wide != "no":
            cur.execute("SELECT options FROM tblJobs WHERE jobid = %s",
                        [id])
            rc = cur.fetchone()
            if rc:
                if rc[0]:
                    options = string.strip(rc[0])
                else:
                    options = "-"
                pref = options + " "
            else:
                pref = ""
        else:
            pref = ""

        cur.execute("SELECT phase, test, result, detailid FROM tblresults " +
                    "WHERE jobid = %s",
                    [id])
        while 1:
            rc = cur.fetchone()
            if not rc:
                break
            line = "%s%-10s %-12s %-10s" % \
                  (pref, string.strip(rc[0]), string.strip(rc[1]),
                   string.strip(rc[2]))
            text = text + line
            detailid = int(rc[3])
            if verbose != "no" or times:
                cur2.execute("SELECT ts, key, value FROM tblDetails WHERE " +
                             "detailid = %s ORDER BY ts;", [detailid])
                detailedtext = ""
                started = None
                finished = None
                while 1:
                    rc2 = cur2.fetchone()
                    if not rc2:
                        break
                    fts = rc2[0]
                    fkey = string.strip(rc2[1])
                    fvalue = string.strip(rc2[2])
                    if fkey == "result" and times:
                        if fvalue == "started":
                            started = calendar.timegm(fts.timetuple())
                        if fvalue in ("pass", "fail", "error", "partial"):
                            finished = calendar.timegm(fts.timetuple())
                    if verbose != "no":
                        line = "...[%-19s] %-10s %s" % (fts, fkey, fvalue)
                        detailedtext = detailedtext + line + "\n"
                if times and started and finished:
                    text = text + " (Duration %6us)" % (int(finished-started))
                text = text + "\n" + detailedtext
            else:
                text = text + "\n"
        cur2.close()
        cur.close()

        return text

class XenRTStatus(XenRTJobPage):
    def render(self):
        if not self.request.params.has_key("id"):
            return "ERROR No job ID supplied"

        id = string.atoi(self.request.params["id"])
        parsed = self.get_job(id)

        if len(parsed) == 0:
            return "ERROR Could not find job " + `id`

        out = ""
        if parsed.has_key('CHECK'):
            out += "%s='%s'\n" % ("CHECK", parsed["CHECK"])                  
        for key in parsed.keys():
            if key != "CHECK":
                out += "%s='%s'\n" % (key, parsed[key])
        return out

class XenRTEmail(XenRTJobPage):
    # Send an email message
    # toaddrs = is a list of email addresses
    def send_mail(self, fromaddr, toaddrs, subject, message, reply=None):
        if not config.smtp_server:
            return
        now = time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime())
        msg = ("Date: %s\r\nFrom: %s\r\nTo: %s\r\nSubject: %s\r\n"
               % (now, fromaddr, ", ".join(toaddrs), subject))
        if reply:
            msg = msg + "Reply-To: %s\r\n" % (reply)
        msg = msg + "\r\n" + message

        server = smtplib.SMTP(config.smtp_server)
        server.sendmail(fromaddr, toaddrs, msg)
        server.quit()

class XenRTRawEmail(XenRTEmail):
    def render(self):
        try:
            sender = config.email_sender
            recipients = string.split(self.request.params["recipients"], ",")
            for r in recipients:
                if not re.match(config.email_recipient_regex, r):
                    raise Exception("Email recipient does not match regex")
            subject = self.request.params["subject"]
            message = self.request.params["message"]
            
            self.send_mail(sender, recipients, subject, message)
            return "OK"
        except:
            traceback.print_exc(file=sys.stderr)
            return "ERROR Could not send email"

class XenRTJobEmail(XenRTEmail):
    def render(self):
        if not config.email_sender:
            return "ERROR No email configuration"
        if not self.request.params.has_key("id"):
            return "ERROR No job ID supplied"
        id = string.atoi(self.request.params["id"])
        try:
            parsed = self.get_job(id)
            if parsed.has_key("EMAIL"):
                if parsed.has_key("SCHEDULEDON"):
                    machine = parsed["SCHEDULEDON"]
                    if parsed.has_key("SCHEDULEDON2"):
                        machine = machine + "," + parsed["SCHEDULEDON2"]
                    if parsed.has_key("SCHEDULEDON3"):
                        machine = machine + "," + parsed["SCHEDULEDON3"]
                elif parsed.has_key("MACHINE"):
                    machine = parsed["MACHINE"]
                else:  
                    machine = "unknown"
                if parsed.has_key("CHECK"):
                    result = parsed["CHECK"]
                elif parsed.has_key("RETURN"):
                    result = parsed["RETURN"]
                else:
                    result = "unknown"
                if parsed.has_key("JOBDESC"):
                    jobdesc = "%s (JobID %u)" % (parsed["JOBDESC"], id)
                else:
                    jobdesc = "JobID %u" % (id)
                emailto = string.split(parsed["EMAIL"], ",")
                subject = "[xenrt] %s %s %s" % (jobdesc, machine, result)
                summary = self.showlog(id, "yes", "yes")
                message = """
================ Summary =============================================
%s/frame?jobs=%u
======================================================================
%s
======================================================================
""" % (config.url_base, id, summary)
                for key in parsed.keys():
                    message =  message + "%s='%s'\n" % (key, parsed[key])
                self.send_mail(config.email_sender, emailto, subject, message, reply=emailto[0])
            return "OK"
        except:
            traceback.print_exc()
            return "ERROR Could not send summary email"

class XenRTList(XenRTJobPage):

    def get_jobs(self, status, activeonly=True):

        jobstatus = app.constants.job_status_desc[status]
        db = self.getDB()
        cur = db.cursor()
        cur2 = db.cursor()
        params = []
        conditions = ["jobstatus = %s"]
        params.append(jobstatus)
        if activeonly:
            conditions.append("removed = ''")
        cur.execute("SELECT jobid, jobStatus, version, revision,  " 
                    "userId FROM tbljobs WHERE %s ORDER BY jobid DESC;" %
                    (string.join(conditions, " AND ")), params)
        reply = []
        while 1:
            rc = cur.fetchone()
            if not rc:
                break
            d = {}
            if rc[0]:
                d['JOBID'] = str(rc[0])
            if rc[1] and string.strip(rc[1]) != "":
                d['JOBSTATUS'] = string.strip(rc[1])
            if rc[2] and string.strip(rc[2]) != "":
                d['VERSION'] = string.strip(rc[2])
            if rc[3] and string.strip(rc[3]) != "":
                d['REVISION'] = string.strip(rc[3])
            if rc[4] and string.strip(rc[4]) != "":
                d['USERID'] = string.strip(rc[4])
            reply.append(d)

            # Look up other variables
            cur2.execute("SELECT param, value FROM tblJobDetails WHERE jobid = "
                         "%s AND param in ('DEPS', 'JOBDESC', 'TESTRUN_SR', 'MACHINE', 'STARTED');", [d['JOBID']])
            while 1:
                rd = cur2.fetchone()
                if not rd:
                    break
                if rd[0] and rd[1]:
                    d[string.strip(rd[0])] = string.strip(rd[1])           
            if d['JOBSTATUS'] == "running":
                cur2.execute("SELECT COUNT(result) FROM tblresults WHERE jobid=%s AND result='paused';", [d['JOBID']])
                rd = cur2.fetchone()
                if rd[0] > 0:
                    d['PAUSED'] = "yes"
                else:
                    d['PAUSED'] = "no"
            else:
                d['PAUSED'] = "no"

        cur.close()
        cur2.close()

        return reply

    def render(self):
        form = self.request.params
        if form.has_key("fields"):
            fields = string.split(form["fields"], ",")
        else:
            fields = []
        filter = {}
        for f in form.keys():
            if f[0:7] == "filter_":
                filter[f[7:]] = form[f]
        outfh = StringIO.StringIO()
        try:
            self.list_job_details(fields, filter, outfh)
            ret = outfh.getvalue()
            outfh.close()
            return ret
        except:
            traceback.print_exc()
            return"ERROR Error listing jobs"

    def list_job_details(self, fields, filter, fd):
        
        ss = [app.constants.JOB_STATUS_NEW, app.constants.JOB_STATUS_RUNNING]
        if filter.has_key("JOBSTATUS"):
            if filter['JOBSTATUS'] == "running":
                ss = [app.constants.JOB_STATUS_RUNNING]
            elif filter['JOBSTATUS'] == "new":
                ss = [app.constants.JOB_STATUS_NEW]

        for s in ss:
            jobs = self.get_jobs(s)
            for job in jobs:
                show = 1
                for f in filter.keys():
                    if not job.has_key(f):
                        show = 0
                    elif job[f] != filter[f]:
                        show = 0
                if not show:
                    continue
                jobid = ""
                jobstatus = ""
                if job.has_key("JOBID"):
                    jobid = job["JOBID"]
                if job.has_key("JOBSTATUS"):
                    jobstatus = job["JOBSTATUS"]
                if jobstatus == "running" and job.has_key("PAUSED") and job['PAUSED'] == "yes":
                    jobstatus = "paused"
                rl = [jobid, jobstatus]
                for f in fields:
                    if job.has_key(f):
                        rl.append(job[f])
                    else:
                        rl.append("")
                fd.write(string.join(rl, "\t") + "\n")

class XenRTSubmit(XenRTJobPage):
    WRITE = True

    def render(self):
        form = self.request.params
        details = {}
        for key in form.keys():
            if key != 'action':
                details[key] = form[key]
        details['JOB_FILES_SERVER'] = config.log_server
        details['LOG_SERVER'] = config.log_server
        if details.has_key("MACHINE") and details["MACHINE"] == "ALL":
            # XRT-127
            allto = 86400
            if details.has_key("ALLTIMEOUT"):
                try:
                    allto = int(details["ALLTIMEOUT"])
                except:
                    pass
            alltimenow = time.time()
            details["ALLTIMEOUT"] = "%u" % (int(alltimenow) + allto)
        try:
            id = self.new_job(details)
        except:
            return "ERROR Internal error"
            traceback.print_exc()
        if id == -1:
            return "ERROR Could not create new job"
        else:
            return "OK " + `id`

    def split_params(self, params):
        # Split the params into two dictionaries, one containing core parameters
        # (i.e. ones that go in tbljobs), and one containing extra parameters
        # (i.e. ones that go in tbljobdetails). Return these two in a dictionary
        # as core and extra

        core = {}
        extra = {}

        for p in params.keys():
            if p in app.constants.core_params:
                core[p] = params[p]
            else:
                extra[p] = params[p]
     
        result = {}
        result["core"] = core
        result["extra"] = extra

        return result
        

    def new_job(self, params):

        db = self.getDB()
        
        splitparams = self.split_params(params)
        c = splitparams["core"]
        e = splitparams["extra"]
        e["JOB_SUBMITTED"] = time.asctime(time.gmtime()) + " UTC"

        for cp in app.constants.core_params:
            if not c.has_key(cp):
                if cp == "JOBSTATUS":
                    c[cp] = "new"
                else:
                    c[cp] = ""  

        cur = db.cursor()
        cur.execute("LOCK TABLE tbljobs IN EXCLUSIVE MODE")
        cur.execute("INSERT INTO tbljobs (version,revision,options,"
                    "jobstatus,userid,uploaded,removed) VALUES "
                    "(%s,%s,%s,%s,%s,%s,%s);",
                    [c["VERSION"], c["REVISION"], c["OPTIONS"], c["JOBSTATUS"], \
                     c["USERID"], c["UPLOADED"], c["REMOVED"]])

        # Lookup jobid
        cur.execute("SELECT last_value FROM jobid_seq")
        rc = cur.fetchone()
        id = int(rc[0])
        db.commit() # Commit to release the lock

        for key in e.keys():
            cur.execute("INSERT INTO tbljobdetails (jobid,param,value) " +
                        "VALUES (%s,%s,%s);", [id, key, e[key]])

        # If we have specifed a jobgroup and tag then update the jobgroup
        if params.has_key("JOBGROUP") and params.has_key("JOBGROUPTAG"):
            jobgroup = params["JOBGROUP"]
            jobtag = params["JOBGROUPTAG"]
            try:
                cur.execute("DELETE FROM tblJobGroups WHERE "
                            "gid = %s AND description = %s",
                            [jobgroup, jobtag])
            except:
                pass
            cur.execute("INSERT INTO tblJobGroups (gid, jobid, description) VALUES " \
                        "(%s, %s, %s);", [jobgroup, id, jobtag])

        db.commit()
        cur.close()
        return id

class XenRTComplete(XenRTJobPage):
    WRITE = True

    def render(self):
        form = self.request.params
        if not form.has_key("id"):
            return "ERROR No job ID supplied"
        id = string.atoi(form["id"])
        try:
            self.set_status(id, app.constants.JOB_STATUS_DONE, commit=True)
            return "OK"
        except:
            traceback.print_exc()
            return "ERROR Could not mark job as complete"


class XenRTUpdate(XenRTJobPage):
    WRITE = True

    def render(self):
        form = self.request.params
        if not form.has_key("id"):
            return "ERROR No job ID supplied"
        id = string.atoi(form["id"])
        try:
            for key in form.keys():
                if key != 'action' and key != 'id':
                    self.update_field(id, key, form[key])
            return "OK"
        except:
            traceback.print_exc()
            return "ERROR Internal error"

class XenRTRemove(XenRTJobPage):
    WRITE = True

    def render(self):
        form = self.request.params
        if not form.has_key("id"):
            return "ERROR No job ID supplied"
        id = string.atoi(form["id"])
        try:
            # We leave the job as it is but mark it as "removed" so it
            # doesn't show in lists. This is becauses users keep on
            # removing running jobs thereby confusing the daemon
            self.update_field(id, "REMOVED", "yes")
            return "OK"
        except:
            traceback.print_exc()
            return "ERROR Could not remove job"

class XenRTDetailID(XenRTJobPage):
    def render(self):
        form = self.request.params
        if not form.has_key("id"):
            return "ERROR No job ID supplied"

        if not form.has_key("phase"):
            return "ERROR No phase supplied"

        if not form.has_key("test"):
            return "ERROR No test supplied"

        jobid = string.atoi(form["id"])
        phase = form["phase"]
        test = form["test"]

        # Find the detailid
        detailid = self.lookup_detailid(jobid, phase, test)
        if detailid == -1:
            return "ERROR No detailid found for %s/%s" % (phase,test)

        # Redirect
        return detailid

class XenRTJobIDFromDetailID(XenRTJobPage):
    def render(self):
        return self.lookup_jobid(self.request.params["detailid"])


class XenRTJobIDsFromDetailIDs(XenRTJobPage):
    def render(self):
        form = self.request.params
        out = ""
        for key in form.keys():
            if not key in ("USERID", "action"):
                out+= "%s:%s\n" % (form[key], self.lookup_jobid(form[key]))
        return out

class XenRTShowLog(XenRTJobPage):
    def render(self):
        form = self.request.params
        if not form.has_key("id"):
            return "ERROR No job ID supplied"
        id = string.atoi(form["id"])
        if not form.has_key("verbose"):
            verbose = "no"
        else:
            verbose = form["verbose"]
        if not form.has_key("wide"):
            wide = "no"
        else:
            wide = form["wide"]
        if form.has_key("times") and form['times'][0] == 'y':
            times = True
        else:
            times = False
        return self.showlog(id, wide, verbose, times=times)

class XenRTJobGroup(XenRTJobPage):
    WRITE = True

    def render(self):
        form = self.request.params
        if not form.has_key("command"):
            return "ERROR No command supplied"
        if not form.has_key("gid"):
            return "ERROR No gid supplied"

        command = form['command']
        gid = form['gid']

        if form.has_key('desc'):
            desc = string.replace(form['desc'], "'", '"')        
        else:
            desc = ""

        params = []
        if command == "reset":
            sql = "DELETE FROM tblJobGroups WHERE gid = %s;"
            params.append(gid)
        elif command == "add":
            if not form.has_key("jobid"):
                return "ERROR No jobid supplied"
            jobid = form['jobid']
            sql = "INSERT INTO tblJobGroups (gid, jobid, description) VALUES " \
                  "(%s, %s, %s);"
            params += [gid, jobid, desc]
        else:
            return "ERROR Unknown command '%s'" % (command)

        db = self.getDB()
        cur = db.cursor()

        try:
            cur.execute(sql, params)
        except:
            return "ERROR database insert error"

        db.commit()
        cur.close()

        return "OK "

class XenRTWarnings(XenRTJobPage):
    def render(self):
        form = self.request.params
        if not form.has_key("jobid") and not form.has_key("jobgroup"):
            return "ERROR No job ID or group specified"
        if form.has_key("key"):
            fieldkey = form["key"]
        else:
            fieldkey = "warning"
        jobids = []
        db = self.getDB()
        out = ""
        try:
            cur = db.cursor()
            if form.has_key("jobid"):
                jobids.append(form["jobid"])
            else:
                cur.execute("SELECT jobid FROM tblJobGroups WHERE gid = %s",
                            [form["jobgroup"]])
                while True:
                    rc = cur.fetchone()
                    if not rc:
                        break
                    jobids.append(str(rc[0]))
        
            for jobid in jobids:
                cur.execute("SELECT detailid, value FROM tblDetails WHERE "
                            "  detailid IN (SELECT detailid FROM tblResults "
                            "    WHERE jobid = %s) AND key = %s",
                            [jobid, fieldkey])
                while True:
                    rc = cur.fetchone()
                    if not rc:
                        break
                    detailid = str(rc[0])
                    warning = rc[1].strip()
                    out += "%s\n" % string.join([jobid, detailid, warning], "\t")
        finally:
            cur.close()
        
        return out

PageFactory(XenRTStatus, "/api/job/status", compatAction="status")
PageFactory(XenRTJobEmail, "/api/job/email", compatAction="email")
PageFactory(XenRTRawEmail, "/api/email_raw")
PageFactory(XenRTList, "/api/job/list", compatAction="list")
PageFactory(XenRTSubmit, "/api/job/submit", compatAction="submit")
PageFactory(XenRTComplete, "/api/job/complete", compatAction="complete")
PageFactory(XenRTUpdate, "/api/job/update", compatAction="update")
PageFactory(XenRTRemove, "/api/job/remove", compatAction="remove")
PageFactory(XenRTDetailID, "/api/job/detailid", compatAction="detailid")
PageFactory(XenRTJobIDFromDetailID, "/api/job/jobidfromdetailid", compatAction="jobidfromdetailid")
PageFactory(XenRTJobIDsFromDetailIDs, "/api/job/jobidsfromdetailids", compatAction="jobidsfromdetailids")
PageFactory(XenRTShowLog, "/api/job/log", compatAction="showlog")
PageFactory(XenRTJobGroup, "/api/job/group", compatAction="jobgroup")
PageFactory(XenRTWarnings, "/api/job/warnings", compatAction="warnings")

