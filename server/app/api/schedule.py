from server import PageFactory
from app.api import XenRTAPIPage
from pyramid.httpexceptions import HTTPFound

import traceback, StringIO, string, time, random, sys, calendar, getopt
import psycopg2
import config, app

class XenRTSchedule(XenRTAPIPage):
    WRITE = True


    def __init__(self, request):
        super(XenRTSchedule, self).__init__(request)
        self.mutex = None
        self.mutex_held = False

    def cli(self):
        if not self.isDBMaster():
            print "Skipping schedule as this node is not the master"
            return
        dryrun = False
        ignore = False
        verbose = None

        try:
            optlist, optx = getopt.getopt(sys.argv[2:], "vdi")
            for argpair in optlist:
                (flag, value) = argpair
                if flag == "-d":
                    dryrun = True
                elif flag == "-i":
                    ignore = True
                elif flag == "-v":
                    verbose = sys.stdout
        except getopt.GetoptError:
            raise Exception("Unknown argument")

        self.schedule_jobs(sys.stdout, dryrun=dryrun, ignore=ignore, verbose=verbose)

        if self.mutex:
            if self.mutex_held:
                self.release_lock()
            self.mutex.close()


    def schedule_jobs(self, outfh, dryrun=False, ignore=False, verbose=None):
        """New world job scheduler - assigns machines to jobs"""
    
        # Generate a random integer to track in logs
        schedid = random.randint(0,1000)

        writeVerboseFile = False
        alsoPrintToVerbose = False

        if not verbose:
            verbose = StringIO.StringIO()
            writeVerboseFile = True
            alsoPrintToVerbose = True

        prelocktime = time.mktime(time.gmtime())

        verbose.write("Job scheduler ID %d started %s" % (schedid, time.strftime("%a, %d %b %Y %H:%M:%S +0000\n", time.gmtime())))
        try:
            self.get_lock()
        except psycopg2.OperationalError:
            outfh.write("Another schedule is already in progress, aborting\n")
            return
        verbose.write("%d acquired lock %s" % (schedid, time.strftime("%a, %d %b %Y %H:%M:%S +0000\n", time.gmtime())))
        postlocktime = time.mktime(time.gmtime())

        offline_sites = [x[0] for x in self.scm_site_list(status="offline")]
        sites = self.scm_site_list(checkFull=True)
        sitecapacity = {}
        for s in sites:
            sitecapacity[s[0]] = s[8]
            verbose.write("%s remaining capacity %d\n" % (s[0], s[8]))
        try:

            # Machines we have available
            self.scm_check_leases()
            if dryrun and ignore:
                machineslist = self.scm_machine_list()
            else:
                machineslist = self.scm_machine_list(status="idle", leasecheck=False)
            machines = {}
            for m in machineslist:
                # Don't include machine on sites marked as "offline"
                if m[1] in offline_sites or (not sitecapacity.has_key(m[1])) or sitecapacity[m[1]] <= 0:
                    continue
                machines[m[0]] = m

            # Jobs to be scheduled
            jobs = self.schedulable_jobs()

            sortlist = []
            sortmap = {}
            for jobid in jobs.keys():
                details = jobs[jobid]
                prio = 3
                if details.has_key("JOBPRIO"):
                    try:
                        prio = int(details["JOBPRIO"])
                    except:
                        pass
                sortkey = "P%03uJ%08u" % (prio, int(jobid))
                sortlist.append(sortkey)
                sortmap[sortkey] = jobid
            sortlist.sort()
            jobidlist = [sortmap[x] for x in sortlist]

            # For each job try to find suitable machine(s)
            for jobid in jobidlist:
                try:
                    details = jobs[jobid]
                    if details.has_key("JOBDESC"):
                        jobdesc = " (%s)" % (details["JOBDESC"])
                    else:
                        jobdesc = ""
                    preemptable = details.get("PREEMPTABLE", "").lower() == "yes"
                    verbose.write("New job %s%s\n" % (jobid, jobdesc))

                    # Variables to record the scheduling data
                    site = None      # All machines will be at the same site
                    cluster = None   # All machines will be from the same cluster
                    selected = []    # The machines we choose

                    # Check how many machines are needed
                    if details.has_key("MACHINES_REQUIRED"):
                        try:
                            machines_required = int(details["MACHINES_REQUIRED"])
                        except ValueError:
                            verbose.write("Warning: skipping job %s because of invalid MACHINES_REQUIRED value\n" % jobid)
                            continue
                    else:
                        machines_required = 1

                    # If the job explicitly asked for named machine(s) then check
                    # their availability.
                    if details.has_key("MACHINE"):
                        if details.has_key("USERID"):
                            leasedmachineslist = self.scm_machine_list(status="idle", leasecheck=details['USERID'])
                            leasedmachines = {}
                            for m in leasedmachineslist:
                                if not m[1] in offline_sites or details.get("IGNORE_OFFLINE", "").lower() == "yes":
                                    leasedmachines[m[0]] = m
                            verbose.write("Job specified specific machines, so machines (%s) available\n" % ",".join(leasedmachines.keys()))
                        else:
                            leasedmachines = {}
                        mxs = string.split(details["MACHINE"], ",")
                        if len(mxs) > 0:
                            if machines.has_key(mxs[0]) or leasedmachines.has_key(mxs[0]):
                                verbose.write("  wants %s, it is available\n" % (mxs[0]))
                                selected.append(mxs[0])
                                if leasedmachines.has_key(mxs[0]):
                                    site = leasedmachines[mxs[0]][1]
                                    cluster = leasedmachines[mxs[0]][2]
                                else:
                                    site = machines[mxs[0]][1]
                                    cluster = machines[mxs[0]][2]
                                if cluster == None:
                                    cluster = ""
                            else:
                                verbose.write("  wants %s, not available\n" % (mxs[0]))
                                # unscheduable at the moment
                                continue
                            # Any remaining machines have site and cluster ignored
                            schedulable = True
                            for mx in mxs[1:]:
                                if len(selected) == machines_required:
                                    break
                                if machines.has_key(mx) or leasedmachines.has_key(mx):
                                    selected.append(mx)
                                    verbose.write("  wants %s, it is available\n" % (mx))
                                else:
                                    verbose.write("  wants %s, not available\n" % (mx))
                                    # unscheduable at the moment
                                    schedulable = False

                            if not schedulable:
                                continue
                            # Do one ACL check at this stage
                            if not self.check_acl_for_machines(selected, details['USERID'], number=len(selected), preemptable=preemptable):
                                verbose.write("  at least one specified machine not allowed by ACL\n")
                                continue
                    else:
                        if details.has_key("SITE"):
                            site = details["SITE"]
                        if details.has_key("CLUSTER"):
                            cluster = details["CLUSTER"]

                    # If we get here then we may have found one or more machines
                    # explicitly requested by the job. Now find any remaining ones.
                    # We may also have found nothing at all so far which means we're
                    # not yet constrained by site or cluster
                    still_needed = machines_required - len(selected)

                    if still_needed > 0:

                        self.scm_select_machines(outfh, machines,
                                             still_needed,
                                             selected,
                                             site,
                                             cluster,
                                             details,
                                             preemptable,
                                             verbose=verbose)

                    if len(selected) < machines_required:
                        continue

                    # If we've been able to find all the machines we need, go ahead
                    # and schedule them all. The first machine is the primary,
                    # it is the one that triggers the site-controller to run
                    # the harness.
                    if dryrun:
                        outfh.write("  could schedule %u on %s\n" % (int(jobid), str(selected)))
                        continue
                    outfh.write("  scheduling %u on %s (%d)\n" % (int(jobid), str(selected), schedid))
                    if alsoPrintToVerbose:
                        verbose.write("  scheduling %u on %s (%d)\n" % (int(jobid), str(selected), schedid))
                    self.schedule_on(outfh, int(jobid), selected, details['USERID'], preemptable)
                    
                    if not site:
                        site = machines[selected[0]][1]
                    if self.schedulercache["siteresources"].has_key(site):
                        del self.schedulercache["siteresources"][site]

                    # And mark these machines as being unavailable
                    for m in selected:
                        if machines.has_key(m):
                            del machines[m]

                    if sitecapacity.has_key(site):
                        sitecapacity[site] -= 1
                        if sitecapacity[site] <= 0:
                            for m in machines.keys():
                                if machines[m][1] == site:
                                    del machines[m]
                except Exception, e:
                    print "WARNING: Could not schedule job %d - %s" % (int(jobid), str(e))
        finally:
            self.release_lock()

        verbose.write("Scheduler %d completed %s\n" % (schedid,time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime())))
        finishtime = time.mktime(time.gmtime())

        outfh.write("Scheduler took %ds to acquire lock and %ds to run\n" % (int(postlocktime-prelocktime), int(finishtime-postlocktime)))
        if alsoPrintToVerbose:
            verbose.write("Scheduler took %ds to acquire lock and %ds to run\n" % (int(postlocktime-prelocktime), int(finishtime-postlocktime)))
        if writeVerboseFile:
            with open("%s/schedule.log" % config.schedule_log_dir, "w") as f:
                f.write(verbose.getvalue())


    def get_lock(self):
        if self.mutex_held:
            self.mutex_held += 1
        else:
            if not self.mutex:
                self.mutex = app.db.dbWriteInstance()
            cur = self.mutex.cursor()
            cur.execute("LOCK TABLE scheduleLock NOWAIT")
            self.mutex_held = 1

    def release_lock(self):
        self.check_mutex_held()
        self.mutex_held = self.mutex_held - 1
        if not self.mutex_held:
            self.mutex.commit()

    def check_mutex_held(self):
        if not self.mutex_held:
            raise Exception("Mutex not held")
        else:
            if not self.mutex:
                raise Exception("Mutex claims to be held, but no DB connection")

    def scm_check_leases(self):
        """Check for any expired leases."""
        try:
            db = self.getDB()
            cur = db.cursor()
            cur.execute("SELECT m.machine, m.leaseTo FROM tblMachines m WHERE "
                        "m.leaseTo IS NOT NULL")

            exp = []
            exp1 = []
            while True:
                rc = cur.fetchone()
                if not rc:
                    break
                m = string.strip(rc[0])
                ut = calendar.timegm(rc[1].timetuple())
                if ut < time.time():
                    exp.append("'%s'" % (m))
                    exp1.append(m)
            if len(exp) > 0:
                cur.execute("UPDATE tblMachines SET leaseTo = NULL, "
                            "comment = NULL, leaseFrom = NULL, leaseReason = NULL WHERE machine in (%s)" %
                            (string.join(exp, ", ")))
                timenow = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time()))
                for e in exp1:
                    cur.execute("INSERT INTO tblEvents(ts, etype, subject, edata) VALUES (%s, %s, %s, %s);",
                                    [timenow, "LeaseEnd", e, None])
            db.commit()
            cur.close()
        except Exception, e:
            print "WARNING: Could not run scm_check_leases - %s" % str(e)

    def schedule_on(self, outfh, job, machines, userid, preemptable):
        db = self.getDB()
        debug = False
        if not debug:
            # Split the comma separated list of scheduled machines over
            # multiple SCHEDULEDON* variables to allow for strings that
            # exceed the database's 256 character limit for this field.
            schstrings = []
            for machine in machines:
                if len(schstrings) == 0 or \
                       len(schstrings[-1] + "," + machine) > 255:
                    schstrings.append(machine)
                else:
                    schstrings[-1] = schstrings[-1] + "," + machine
            if len(schstrings) == 0:
                raise "No SCHEDULEDON string set - job %u" % job
            if len(schstrings) > 3:
                raise "Machine list too long for the three SCHEDULEDON strings: " \
                      "%s" % (string.join(machines, ","))
            self.update_field(job, "SCHEDULEDON", schstrings[0], commit=False)
            if len(schstrings) > 1:
                self.update_field(job, "SCHEDULEDON2", schstrings[1], commit=False)
            if len(schstrings) > 2:
                self.update_field(job, "SCHEDULEDON3", schstrings[2], commit=False)
            self.update_field(job, "MACHINE", string.join(machines, ","), commit=False)
        # We may be rescheduling, in which case we don't want to update the status
        # of a machine if the job has already started, hence the check for status
        # being idle
        sql = """UPDATE tblMachines SET status = 'scheduled', jobid = %u
        WHERE machine = '%s' AND STATUS = 'idle';""" % (job, machines[0])
        if debug:
            outfh.write(sql + "\n")
        else:
            cur = db.cursor()
            cur.execute(sql)
            cur.close()
        for machine in machines[1:]:
            sql = """UPDATE tblMachines SET status = 'slaved', jobid = %u
            WHERE machine = '%s' AND STATUS = 'idle';""" % (job, machine)
            if debug:
                outfh.write(sql + "\n")
            else:
                cur = db.cursor()
                cur.execute(sql)
                cur.close()
        if not debug:
            # Update the ACL cache
            for m in machines:
                self.getACLHelper().update_acl_cache(m, userid, preemptable)
            # Now we're complete, mark the job as running
            self.set_status(job, app.constants.JOB_STATUS_RUNNING, commit=True)

    def fetch_jobid_list(self, sql):
        """Execute the SQL query and return a list of the first fields."""
        db = self.getDB()
        reply = []
        cur = db.cursor()
        cur.execute(sql)
        while True:
            rc = cur.fetchone()
            if not rc:
                break
            if rc[0] != None:
                reply.append(int(rc[0]))
        db.commit()
        cur.close()
        return reply

    def schedulable_jobs(self):
        """Get a list of job details that we need to schedule"""
        # All new jobs
        njids = self.fetch_jobid_list("SELECT jobid FROM tblJobs "
                                 "WHERE jobstatus = 'new' AND "
                                 "removed = ''")
        if len(njids) == 0:
            # No new jobs
            return {}
        newjobids = []
        for nji in njids:
            newjobids.append(str(nji))
        newjobs = njids

        nowspec = time.strftime("HOUR=%H/DAY=%w", time.gmtime())
        
        jobs = {}
        newjobs.sort()
        for job in newjobs:
            try:
                details = self.get_job(job)
                if not details:
                    sys.stderr.write("Could not read details for job %u.\n" %
                                     (job))
                    continue
                # Exclude any jobs that have a START_AFTER (defined as seconds
                # since the epoch) in the future.
                if details.has_key("START_AFTER"):
                    sa = int(details["START_AFTER"])
                    if sa > int(time.time()):
                        continue

                # Exclude any jobs with time windows that are not currently open
                if details.has_key("TIME_CONSTRAINTS"):
                    tconst = details["TIME_CONSTRAINTS"]
                    if not app.utils.check_resources(nowspec, tconst):
                        continue
                jobs[details["JOBID"]] = details
            except:
                pass
        return jobs

    def scm_select_machines(self, outfh, machines, number, selected, site, cluster, details, preemptable, verbose=None):
        """Select <number> machines from the <machines> dictionary.

        The job may be partly done already and the <selected> list will contain
        machines found so far. More machines found are added to this list.

        <site> and <cluster>, if not None, are constraints on machines we can
        choose. Even if no constraints are supplied, we will always pick
        all machines from the same site and cluster (except if the job specifies
        CROSS_CLUSTER=yes which causes the cluster to be ignored).

        <details> is the dictionary of job parameters.
        """

        cross_cluster = False
        if details.has_key("CROSS_CLUSTER") and \
               details['CROSS_CLUSTER'][0].lower() in ("y", "t", "1"):
            cross_cluster = True
            cluster = None

        clusters = {}

        # Find clusters that fit our criteria. If we're in CROSS_CLUSTER mode
        # then just put all machines in one cluster
        #print "  listing sites and clusters. constraints 's=%s' 'c=%s'" % (site,
        #                                                                 cluster)
        for m in machines.values():
            if m[0] in selected:
                # Already selected
                continue
            s = m[1]
            if cross_cluster:
                c = "(all)"
            else:
                c = m[2]
                if c == None:
                    c = ""
            #print "    checking %s on '%s/%s'" % (m[0], s, c)
            if site != None and s != site:
                #print "      site %s does not match constraint" % (s)
                continue
            if cluster != None and c != cluster:
                #print "      cluster %s does not match constraint" % (c)
                continue
            if not clusters.has_key((s, c)):
                clusters[(s, c)] = {}
            clusters[(s, c)][m[0]] = m

        clusterprios = {}
        for cluster in clusters.keys():
            clusterprios[cluster] = max([int(m[13]) for m in clusters[cluster].values()])

        # Check if we have any clusters to look at
        if len(clusters) == 0:
            verbose.write("  no clusters to check (likely no remaining capacity in site)\n")
            return False

        # Try each cluster
        # Randomise the list so we spread the load a bit (XRT-737)
        cs = clusters.keys()
        random.shuffle(cs)
        cs.sort(key=lambda x: clusterprios[x])
        for cluster in cs:
            s, c = cluster
            verbose.write("  checking site %s, cluster %s...\n" % (s, c))

            # Check the available shared resources on the site
            if details.has_key("SHAREDRESOURCES"):
                sharedresourcesavailable = self.site_available_shared_resources(s)
                sharedresourcesneeded = app.utils.parse_shared_resources(details["SHAREDRESOURCES"])
                verbose.write("Shared resources available: %s\n" % ("/".join(map(lambda x:"%s=%s" % (x, sharedresourcesavailable[x]), sharedresourcesavailable.keys()))))
                verbose.write("Shared resources needed: %s\n" % ("/".join(map(lambda x:"%s=%s" % (x, sharedresourcesneeded[x]), sharedresourcesneeded.keys()))))
                valid = True
                for r in sharedresourcesneeded.keys():
                    if (not sharedresourcesavailable.has_key(r)) or sharedresourcesavailable[r] < sharedresourcesneeded[r]:
                        verbose.write("Too small - not enough %s\n" % r)
                        valid = False
                if not valid:
                    continue
            
            # Check there are enough machines left in the cluster
            if len(clusters[cluster]) < number:
                verbose.write("    too small (%u < %u)\n" % (len(clusters[cluster]), number))
                continue

            # Check there are no ACL restrictions
            if not self.check_acl_for_machines(clusters[cluster].keys(), details['USERID'], selected, number, preemptable):
                verbose.write("    not allowed by ACL\n")
                continue

            selx = []
            needed = number

            # Get site properties
            if self.schedulercache["siteprops"].has_key(s):
                siteprops = self.schedulercache["siteprops"][s]
            else:
                siteprops = None
                try:
                    sd = self.site_data(s)
                    if sd and sd.has_key("FLAGS") and sd["FLAGS"]:
                        siteprops = sd["FLAGS"]
                except:
                    pass

                self.schedulercache["siteprops"][s] = siteprops

            ms = clusters[cluster].values()

            # Now consider each xindex requirement in turn
            for xindex in range(len(selected), len(selected) + needed):
                found = False
                # Consider each machine in this cluster
                # Randomise the list so we spread the load a bit (XRT-737)
                random.shuffle(ms)
                ms.sort(key=lambda x: int(x[13]))
                for m in ms:
                    if m[0] in selx:
                        # Machine already provisionally selected
                        continue
                    #print "    considering machine %s..." % (m[0])

                    # The pool the machine is in
                    subpool = m[3]
                    if subpool == "":
                        subpool = "DEFAULT"

                    # The machine's properties
                    props = m[6]

                    # Add properties stored in tblMachineData key PROPS
                    if self.schedulercache["machineprops"].has_key(m[0]):
                        props = self.schedulercache["machineprops"][m[0]]
                    else:
                        d = self.machine_data(m[0])
                        if d and d.has_key("PROPS"):
                            props = string.join([props, d["PROPS"]], ",")
                        self.schedulercache["machineprops"][m[0]] = props

                    # Add site properties
                    if siteprops:
                        props = string.join([props, siteprops], ",")

                    # Check the subpool matching
                    jobpool = ["DEFAULT"]
                    if details.has_key("POOL_%u" % (xindex)):
                        jobpool = string.split(details["POOL_%u" % (xindex)], ",")
                    elif details.has_key("POOL"):
                        jobpool = string.split(details["POOL"], ",")
                    if not subpool in jobpool and not "ANY" in jobpool:
                        # Wrong pool
                        continue

                    # Check the cluster matching
                    clusterreq = None
                    thiscluster = m[2] and m[2].strip() or ""
                    if details.has_key("CLUSTER_%u" % xindex):
                        clusterreq = string.split(details["CLUSTER_%u" % xindex], ",")
                    elif details.has_key("CLUSTER"):
                        clusterreq = string.split(details["CLUSTER"], ",")
                    if clusterreq and thiscluster not in clusterreq:
                        # job has requirements on cluster but this machine is not there
                        continue

                    # Check for resource matching
                    resreq = None
                    if details.has_key("RESOURCES_REQUIRED_%u" % (xindex)):
                        resreq = details["RESOURCES_REQUIRED_%u" % (xindex)]
                    elif details.has_key("RESOURCES_REQUIRED"):
                        resreq = details["RESOURCES_REQUIRED"]
                    if resreq:
                        if m[5] == "":
                            # No machine resource string, skip
                            continue
                        if not app.utils.check_resources(m[5], resreq):
                            continue

                    # Check for flags. We must do this even if no flags are specified
                    # because of the possibility of mandatory machine flags.
                    if details.has_key("FLAGS_%u" % (xindex)):
                        if not app.utils.check_attributes(props, details["FLAGS_%u" % (xindex)]):
                            continue
                    elif details.has_key("FLAGS"):
                        if not app.utils.check_attributes(props, details["FLAGS"]):
                            continue
                    else:
                        if not app.utils.check_attributes(props, None):
                            continue

                    # Check for short jobs
                    if "shortonly" in string.split(props, ","):
                        if not details.has_key("SHORTJOB") or \
                               details["SHORTJOB"] != "yes":
                            continue

                    # All OK
                    verbose.write("      %s suitable\n" % (m[0]))
                    found = True
                    selx.append(m[0])
                    needed -= 1
                    break

                if not found:
                    # No machines found that match the requirements for this xindex,
                    # so this cluster is not suitable, no point continuing
                    break

            # If we found enough machines in this pool then we're done
            if needed == 0:
                selected.extend(selx)
                verbose.write("    sufficient machines found (%u)\n" % (len(selected)))
                return True
            else:
                verbose.write("    insufficient machines found\n")

        # If we get here then we were not able to find sufficient machines
        # in any cluster.
        return False

    def get_acls_for_machines(self, machines):
        if len(machines) == 0:
            return {}

        db = self.getDB()
        policies = {}
        cur = db.cursor()

        # First identify the set of acls and the number of machines from 'machines' that are in that acl
        cur.execute("SELECT aclid, COUNT(machine) FROM tblmachines WHERE machine IN (%s) AND aclid IS NOT NULL GROUP BY aclid" %
                    (','.join(map(lambda m: "'%s'" % m, machines))))
        while True:
            rc = cur.fetchone()
            if not rc:
                break
            policies[int(rc[0])] = int(rc[1])

        if len(policies.keys()) == 0:
            return policies

        # Now identify any parent acls that we need to check
        cur.execute("SELECT a.parent, COUNT(m.machine) FROM tblmachines AS m INNER JOIN tblacls AS a ON m.aclid=a.aclid WHERE machine IN (%s) AND a.parent IS NOT NULL GROUP BY a.parent" %
                    (','.join(map(lambda m: "'%s'" % m, machines))))
        while True:
            rc = cur.fetchone()
            if not rc:
                break
            p = int(rc[0])
            if policies.has_key(p):
                # The ACL is in use both directly on some machines and as a parent, so we add the numbers together
                policies[p] += int(rc[1])
            else:
                policies[p] = int(rc[1])
        cur.close()

        return policies      

    def check_acl_for_machines(self, machines, userid, already_selected=[], number=1, preemptable=False):
        # Identify the policies we need to check
        policies = self.get_acls_for_machines(machines)
        if len(policies.keys()) == 0:
            # No policies for these machines, so all are OK
            return True

        existingPolicies = self.get_acls_for_machines(already_selected)

        # TODO: Currently if scheduling from a cluster which has
        #       machines from different ACLs we take a pessimistic
        #       view where we assume all machines will be coming
        #       from that ACL (capped to the number of machines in the ACL).
        #       This is overly limiting, particularly in a CROSS_CLUSTER
        #       situation!

        # Go through each policy and check if we're OK
        for p in policies.keys():
            machineCount = min(number, policies[p]) # We want 'number' extra machines
            if existingPolicies.has_key(p):
                # We do however have to add on any already selected machines in the same ACL as these won't
                # be taken into account otherwise
                machineCount += existingPolicies[p]

            if not self.getACLHelper().check_acl(p, userid, machines[:machineCount], ignoreParent=True, preemptable=preemptable)[0]:
                return False

        return True

