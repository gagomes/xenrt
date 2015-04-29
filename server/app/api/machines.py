from server import PageFactory
from app.api import XenRTAPIPage

import config, app

import traceback, StringIO, string, time, json, sys, calendar

class XenRTMachinePage(XenRTAPIPage):
    pass

class XenRTMList(XenRTMachinePage):
    def render(self):
        form = self.request.params
        try:
            outfh = StringIO.StringIO()
            site = None
            cluster = None
            pool = None
            quiet = False
            csv = False
            showres = False
            showdesc = False
            showprops = False
            chead = "Comment/Leased to"
            rfilter = None
            pfilter = None
            ffilter = None
            verbose = False
            iscontroller = False
            leasefilter = None
            broken = False
            if form.has_key("site"):
                site = form["site"]
            if form.has_key("cluster"):
                cluster = form["cluster"]
            if form.has_key("pool"):
                pool = form["pool"]
            if form.has_key("quiet") and form["quiet"] == "yes":
                quiet = True
            if form.has_key("res") and form["res"] == "yes":
                showres = True
                chead = "Resources"
            elif form.has_key("desc") and form["desc"] == "yes":
                showdesc = True
                chead = "Description"
            if form.has_key("controller") and form["controller"] == "yes":
                quiet = True
                csv = True
                iscontroller = True
                fields = [0, 4, 10]
            if form.has_key("rfilter"):
                rfilter = form["rfilter"]
            if form.has_key("props") and form["props"] == "yes":
                showprops = True
                chead = "Properties"
            if form.has_key("pfilter"):
                pfilter = form["pfilter"]
            if form.has_key("ffilter"):
                ffilter = form["ffilter"]
            if form.has_key("leasefilter"):
                leasefilter = form["leasefilter"]
            if form.has_key("notleased"):
                leasefilter = False
            if form.has_key("leased"):
                leasefilter = True 
            if form.has_key("verbose") and form["verbose"] == "yes":
                verbose = True
            if form.has_key("broken") and form["broken"] == "yes":
                broken = True
            machines = self.scm_machine_list(site, cluster, pool=pool, leasecheck=leasefilter)
            if showprops or pfilter:
                machineprops = {}
                cur = self.getDB().cursor()
                cur.execute("SELECT machine, value FROM tblMachineData "
                            "WHERE key = 'PROPS';")
                while 1:
                    rc = cur.fetchone()
                    if not rc:
                        break
                    if rc[0] and rc[1] and string.strip(rc[0]) != "" and \
                           string.strip(rc[1]) != "":
                        machineprops[string.strip(rc[0])] = string.strip(rc[1])
                cur.close()
                siteprops = dict([(x[0], x[2]) for x in self.scm_site_list()])
            cur = self.getDB().cursor()
            cur.execute("SELECT machine, value FROM tblMachineData "
                        "WHERE key IN ('BROKEN_TICKET', 'BROKEN_INFO');")
            machinebrokeninfo = {}
            while 1:
                rc = cur.fetchone()
                if not rc:
                    break
                if rc[0] and rc[1] and string.strip(rc[0]) != "" and \
                       string.strip(rc[1]) != "":
                    if not machinebrokeninfo.has_key(rc[0].strip()):
                        machinebrokeninfo[string.strip(rc[0])] = "Broken -"
                    machinebrokeninfo[string.strip(rc[0])] += " %s" % string.strip(rc[1])
            cur.close()
            fmt = "%-12s %-7s %-8s %-9s %-8s %s\n"
            if not quiet:
                outfh.write(fmt %
                                 ("Machine", "Site", "Cluster", "Status", "Pool",
                                  chead))
                outfh.write("==============================================="
                                 "=============================\n")
            if not csv:
                joblist = []
                for m in machines:
                    if m[10] and m[4] != "idle":
                        if not m[10] in joblist:
                            joblist.append(m[10])
                descs = self.get_param_for_jobs("JOBDESC", joblist)
                deps = self.get_param_for_jobs("DEPS", joblist)
                users = self.get_param_for_jobs("USERID", joblist)
            for m in machines:
                if not iscontroller and not verbose and m[0] == "_%s" % (m[1]):
                    continue
                # Add in siteprops
                if showprops or pfilter:
                    if siteprops.has_key(m[1]) and siteprops[m[1]]:
                        if machineprops.has_key(m[0]):
                            machineprops[m[0]] += "," + siteprops[m[1]]
                        else:
                            machineprops[m[0]] = siteprops[m[1]]
                if rfilter:
                    if not app.utils.check_resources(m[5], rfilter):
                        continue

                if m[3].endswith("x"):
                    mbroken = True
                else:
                    mbroken = False
                    
                if broken and not mbroken:
                    continue
                if pfilter:
                    if machineprops.has_key(m[0]):
                        avail = machineprops[m[0]]
                    else:
                        avail = ""
                    if not app.utils.check_attributes(avail, pfilter):
                        continue
                if ffilter:
                    if not app.utils.check_attributes(m[6], ffilter):
                        continue
                if csv:
                    x = []
                    for f in fields:
                        x.append(m[f])
                    outfh.write("%s\n" % (string.join(x, ",")))
                else:
                    if m[4] == "scheduled":
                        status = "%s (S)" % (m[10])
                    elif m[4] == "running":
                        status = "%s" % (m[10])
                    elif m[4] == "slaved":
                        status = "(%s)" % (m[10])
                    else:
                        status = m[4]
                    if showres:
                        comment = m[5]
                    elif showdesc:
                        comment = m[7]
                    elif showprops:
                        if machineprops.has_key(m[0]):
                            comment = machineprops[m[0]]
                        else:
                            comment = ""
                    else:
                        if mbroken:
                            if machinebrokeninfo.has_key(m[0]):
                                comment = machinebrokeninfo[m[0]]
                            else:
                                comment = "Broken"
                        else:
                            if m[8]:
                                c = string.strip(m[8])
                                if m[12]:
                                    c += " - %s" % m[12]
                            else:
                                c = None
                            if m[9]:
                                ts = string.strip(str(m[9]))
                            else:
                                ts = None
                            if ts:
                                if c:
                                    comment = "%s (%s)" % (ts, c)
                                else:
                                    comment = "%s" % (ts)
                            elif c:
                                comment = c
                            elif m[10] and descs.has_key(int(m[10])) and \
                                     status != "idle" and status != "offline":
                                comment = descs[int(m[10])]
                            elif m[10] and deps.has_key(int(m[10])) and users.has_key(int(m[10])) and \
                                     status != "idle" and status != "offline":
                                comment = "%s - %s" % (deps[int(m[10])], users[int(m[10])])
                            else:
                                comment = ""
                    if m[2]:
                        cluster = string.strip(m[2])
                    else:
                        cluster = "default"
                    outfh.write(fmt % (m[0], m[1], cluster, status, m[3],
                                            comment))
            ret = outfh.getvalue()
            outfh.close()
            return ret
        except:
            traceback.print_exc()
            return "ERROR Error listing machines"

class XenRTMStatus(XenRTMachinePage):
    WRITE = True

    def render(self):
        try:
            form = self.request.params
            db = self.getDB()
            machine = form["machine"]
            status = form["status"]
            cur = db.cursor()
            cur.execute("UPDATE tblMachines SET status = %s WHERE machine = %s;",
                        [status, machine])
            db.commit()
            cur.close()        
            return "OK"
        except:
            traceback.print_exc()
            return "ERROR"

class XenRTMDefine(XenRTMachinePage):
    WRITE = True

    def render(self):
        """handle the mdefine CLI call"""
        try:
            form = self.request.params
            machine = None
            site = None
            cluster = ''
            pool = None
            status = None
            resources = ''
            flags = ''
            descr = ''
            if form.has_key("machine"):
                machine = form["machine"]
            if form.has_key("site"):
                site = form["site"]
            if form.has_key("cluster"):
                cluster = form["cluster"]
            if form.has_key("pool"):
                pool = form["pool"]
            if form.has_key("status"):
                status = form["status"]
            if form.has_key("resources"):
                resources = form["resources"]
            if form.has_key("flags"):
                flags = form["flags"]  
            if form.has_key("descr"):
                descr = form["descr"]
            if not machine or not site:
                return "ERROR missing field(s)"    
            self.scm_machine_update(machine, site, cluster, pool, status, resources,
                               flags, descr, None)
            return "OK"
        except:
            traceback.print_exc()
            return "ERROR updating database"

class XenRTMUnDefine(XenRTMachinePage):
    WRITE = True

    def render(self):
        """Handle the mundefine CLI call"""
        machine = self.request.params["machine"]
        try:
            db = self.getDB()
            cur = db.cursor()
            cur.execute("DELETE FROM tblMachines WHERE machine = %s;", [machine])
            cur.execute("DELETE FROM tblMachineData WHERE machine = %s;", [machine])
            db.commit()
            cur.close()        
            return "OK"
        except:
            traceback.print_exc()
            return "ERROR Error undefining %s" % (machine)

class XenRTBorrow(XenRTMachinePage):
    WRITE = True

    def render(self):
        """Handle the borrow CLI call"""
        return "ERROR: This API is superseded"

class XenRTReturn(XenRTMachinePage):
    WRITE = True

    def render(self):
        """handle the return CLI call"""
        return "ERROR: This API is superseded"

class XenRTMachine(XenRTMachinePage):
    def render(self):
        form = self.request.params
        if not form.has_key("machine"):
            return "ERROR No machine supplied"
        machine = form["machine"]
        try:
            m = self.machine_data(machine)
            out = ""
            for key in m.keys():
                out += "%s=%s\n" % (key, m[key])

            return out

        except:
            return "ERROR Could not find machine " + machine

class XenRTMUpdate(XenRTMachinePage):
    WRITE = True

    def render(self):
        form = self.request.params
        if not form.has_key("machine"):
            return "ERROR No machine supplied"
        machine = form["machine"]
        try:
            for key in form.keys():
                if key != 'action' and key != 'machine':
                    if key == "SUBPOOL" or key == "POOL":
                        self.scm_machine_update(machine,
                                           None,
                                           None,
                                           form[key],
                                           None,
                                           None,
                                           None,
                                           None,
                                           None)
                    elif key == "SITE":
                        self.scm_machine_update(machine,
                                           form[key],
                                           None,
                                           None,
                                           None,
                                           None,
                                           None,
                                           None,
                                           None)
                    elif key == "CLUSTER":
                        self.scm_machine_update(machine,
                                           None,
                                           form[key],
                                           None,
                                           None,
                                           None,
                                           None,
                                           None,
                                           None)
                    elif key == "RESOURCES":
                        self.scm_machine_update(machine,
                                           None,
                                           None,
                                           None,
                                           None,
                                           form[key],
                                           None,
                                           None,
                                           None)
                    elif key == "FLAGS":
                        self.scm_machine_update(machine,
                                           None,
                                           None,
                                           None,
                                           None,
                                           None,
                                           form[key],
                                           None,
                                           None)
                    elif key == "DESCRIPTION":
                        self.scm_machine_update(machine,
                                           None,
                                           None,
                                           None,
                                           None,
                                           None,
                                           None,
                                           form[key],
                                           None)
                    elif key == "LEASEPOLICY":
                        self.scm_machine_update(machine,
                                           None,
                                           None,
                                           None,
                                           None,
                                           None,
                                           None,
                                           None,
                                           form[key])
                    else:
                        self.update_machine_param(machine, key, form[key])
            return "OK"
        except:
            traceback.print_exc(file=sys.stderr)
            return "ERROR Internal error"

    def update_machine_param(self, machine, key, value):

        db = self.getDB()

        # If key starts with "+" or "-" then we are to add or remove the
        # value string from a comma separated list for that key.
        op = 0
        if key[0] == "+":
            op = 1
            key = key[1:]
        if key[0] == "-":
            op = 2
            key = key[1:]
        
        cur = db.cursor()
        cur.execute("SELECT value FROM tblMachineData WHERE machine= %s "
                    "AND key = %s;", [machine, key])
        rc = cur.fetchone()
        if not rc:
            if op == 0 or op == 1:
                cur.execute("INSERT INTO tblMachineData (machine, key, value)"
                            " VALUES (%s, %s, %s);",
                            [machine, key, value])
        else:
            prev = ""
            if rc[0]:
                prev = string.strip(rc[0])
            if op == 1 or op == 2:
                ll = string.split(prev, ",")
                llnew = []
                match = 0
                for item in ll:
                    if item == '':
                        continue
                    if op == 1:
                        if item == value:
                            match = 1
                        llnew.append(item)
                    else:
                        if item != value:
                            llnew.append(item)
                if op == 1 and match == 0:
                    llnew.append(value)
                value = string.join(llnew, ",")
            cur.execute("UPDATE tblMachineData SET value = %s WHERE "
                        "machine = %s AND key = %s;",
                        [value, machine, key])
        db.commit()
        cur.close()

class XenRTUtilisation(XenRTMachinePage):
    def render(self):
        form = self.request.params
        if not form.has_key("period"):
            return "ERROR No period supplied"
        else:
            # Period can be specified in 2 ways, either a single integer which
            # is treated as a number of days to look at, or as a pair of comma
            # separated values, which are treated as timestamps
            period = string.strip(form['period'])
            if ',' in period:
                sp = period.split(',')
                start = int(sp[0])
                end = int(sp[1])
            else:
                start = (int(time.time()) - (86400 * int(period)))
                end = int(time.time())

        if form.has_key("verbose") and form['verbose'] == "yes":
            verbose = True
        else:
            verbose = False

        cur = self.getDB().cursor()

        if form.has_key("pools"):
            pl = string.strip(form['pools'])
            pools = pl.split(',')
        else:
            pools = []
            cur.execute("SELECT DISTINCT pool FROM tblMachines")
            while 1:
                rc = cur.fetchone()
                if not rc:
                    break
                pools.append(string.strip(rc[0]))
                
        period = end - start

        pool_data = {}

        allmax = 0
        alltime = 0
        alljobs = 0

        for pool in pools:
            results = []

            machineslist = self.scm_machine_list(pool=pool)
            machines = map(lambda x:x[0], machineslist)        
            machines.sort()
            pooltime = 0
            pooljobs = 0
            for machine in machines:
                data = {}
                data['machine'] = machine
                data['pool'] = pool

                # Get the statistics for this machine
                cur.execute("SELECT extract(epoch FROM ts),etype,edata FROM tblevents "
                            "WHERE subject=%s AND (etype='JobStart' OR etype='"
                            "JobEnd') AND ts > ('epoch'::timestamptz + interval "
                            "'%s seconds') AND ts < ('epoch'::timestamptz + "
                            "interval '%s seconds') ORDER BY ts;",
                            [machine,start,end])

                started = False
                st_time = 0
                data['timespent'] = 0
                data['jobs'] = 0
                jobsToTimeSpent = {}
                while 1:
                    rc = cur.fetchone()
                    if not rc:
                        break
                    if string.strip(rc[1]) == "JobEnd":
                        if started:
                            # Find the jobid to get the number of machines involved
                            jobid = int(rc[2])
                            jobsToTimeSpent[jobid] = rc[0] - st_time
                            started = False
                    else:
                        started = True
                        st_time = rc[0]
                        data['jobs'] += 1

                machineCounts = self.get_param_for_jobs("MACHINES_REQUIRED", jobsToTimeSpent.keys())
                for j in jobsToTimeSpent.keys():
                    if machineCounts.has_key(j):
                        data['timespent'] += int(machineCounts[j]) * jobsToTimeSpent[j]
                    else:
                        data['timespent'] += jobsToTimeSpent[j]

                data['percentage'] = (data['timespent'] / period) * 100

                # Format timespent nicely
                data['timespent_str'] = self.pretty_print_utilisation(data['timespent'])
                pooltime += data['timespent']
                pooljobs += data['jobs']
                results.append(data)

            # Work out overall pool utilisation
            poolutil = (pooltime / (len(results) * period)) * 100
            pooltime_str = self.pretty_print_utilisation(pooltime)
            pdata = {'poolutil' : poolutil,
                     'pooljobs' : pooljobs,
                     'results'  : results,
                     'pooltime' : pooltime_str}
            pool_data[pool] = pdata

            alltime += pooltime
            alljobs += pooljobs
            allmax += len(results) * period

        allutil = (alltime / allmax) * 100
        alltime_str = self.pretty_print_utilisation(alltime)
        cur.close()

        out = ""
        out += string.join(["ALL",
                           "Total",
                           "%u%%" % (allutil),
                           alltime_str,
                           "%u" % (alljobs)], ",")
        out += "\n"
        for pool in pools:
        
            results = pool_data[pool]['results']
            util = pool_data[pool]['poolutil']
            jobs = pool_data[pool]['pooljobs']
            pooltime = pool_data[pool]['pooltime']
            out += string.join(["POOL",
                               pool,
                               "%u%%" % (util),
                               pooltime,
                               "%u" % (jobs)], ",")
            out += "\n"

            if verbose:
                for data in results:
                    out += string.join(["MACHINE",
                                       data['machine'],
                                       "%u%%" % (data['percentage']),
                                       data['timespent_str'],
                                       "%u" % (data['jobs'])], ",")
                    out += "\n"
        return out

    def pretty_print_utilisation(self, ts):
        days = int(ts / 86400)
        ts -= (days * 86400)
        hours = int(ts / 3600)
        ts -= (hours * 3600)
        mins = int(ts / 60)
        ts -= (mins * 60)
        if days:
            if days > 1:
                return "%u days %02u:%02u:%02u" % (days,hours,mins,ts)
            else:
                return "%u day %02u:%02u:%02u" % (days,hours,mins,ts)
        else:
            return "%02u:%02u:%02u" % (hours,mins,ts)

class XenRTMachineDashboardJSON(XenRTMachinePage):
    def render(self):
        machineslist = self.scm_machine_list()
        ret = {}
        for m in machineslist:
            ret[m[0]] = {}
            i = ret[m[0]]
            i['site'] = m[1]
            i['cluster'] = m[2]
            i['pool'] = m[3]
            i['runstate'] = m[4]
            if m[8]:
                i['borrowed'] = m[8]
                i['borrowreason'] = m[12]
            else:
                i['borrowed'] = None
                i['borrowreason'] = None
        return json.dumps(ret, indent=2)
            
    

PageFactory(XenRTMList, "/api/machine/list", compatAction="mlist2")
PageFactory(XenRTMStatus, "/api/machine/setstatus", compatAction="mstatus")
PageFactory(XenRTMDefine, "/api/machine/define", compatAction="mdefine")
PageFactory(XenRTMUnDefine,"/api/machine/undefine", compatAction="mundefine")
PageFactory(XenRTBorrow, "/api/machine/borrow", compatAction="borrow")
PageFactory(XenRTReturn, "/api/machine/return", compatAction="return")
PageFactory(XenRTMachine, "/api/machine/details", compatAction="machine")
PageFactory(XenRTMUpdate, "/api/machine/update", compatAction="mupdate")
PageFactory(XenRTUtilisation, "/api/machine/utilisation", compatAction="utilisation")
PageFactory(XenRTMachineDashboardJSON, "/api/machine/dashboardjson", contentType="application/json")
