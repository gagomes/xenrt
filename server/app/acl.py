# ACL objects
import math, copy

class ACL(object):

    def __init__(self, aclid, name, parent, owner, entries, machines):
        self.aclid = aclid
        self.name = name
        self.parent = parent
        self.owner = owner
        self.entries = entries
        self.machines = machines

    def toDict(self):
        """Return a dictionary representation ready for JSON"""
        acl = {
            "parent": self.parent,
            "owner": self.owner,
            "name": self.name
        }

        entries = []
        for e in self.entries:
            entry = {
                "prio": e.prio,
                "type": e.entryType,
                "userid": e.userid,
                "grouplimit": e.grouplimit,
                "grouppercent": e.grouppercent,
                "userlimit": e.userlimit,
                "userpercent": e.userpercent,
                "maxleasehours": e.maxleasehours,
                "preemptableuse": e.preemptableuse
            }
            if e.machinecount is not None:
                entry['machinecount'] = e.machinecount
                entry['usermachines'] = e.usermachines
            entries.append(entry)
        acl['entries'] = entries

        return acl

class ACLEntry(object):

    def __init__(self, prio, entryType, userid, grouplimit, grouppercent, userlimit, userpercent, maxleasehours, preemptableuse):
        self.prio = prio
        self.entryType = entryType
        self.userid = userid
        self.grouplimit = grouplimit
        self.grouppercent = grouppercent
        self.userlimit = userlimit
        self.userpercent = userpercent
        self.maxleasehours = maxleasehours
        self.machinecount = None
        self.usermachines = None
        self.preemptableuse = preemptableuse

class ACLHelper(object):

    def __init__(self, page):
        self.page = page
        self._groupCache = {}
        self._userGroupCache = {}
        self._aclCache = {}

    def get_acl(self, aclid, withCounts=False):
        if withCounts:
            return self._get_acl_counts(aclid)

        if not aclid in self._aclCache:
            self._get_acl(aclid)
        return self._aclCache[aclid]

    def _get_acl(self, aclid):
        db = self.page.getDB()
        cur = db.cursor()

        cur.execute("SELECT name, parent, owner FROM tblacls WHERE aclid=%s", [aclid])
        rc = cur.fetchone()
        if not rc:
            raise KeyError("ACL not found")
        name = rc[0].strip()
        parent = rc[1]
        owner = rc[2].strip()

        entries = []
        cur.execute("SELECT type, userid, grouplimit, grouppercent, userlimit, userpercent, maxleasehours, prio, preemptableuse FROM tblaclentries WHERE aclid=%s ORDER BY prio", [aclid])
        while True:
            rc = cur.fetchone()
            if not rc:
                break
            def __int(data):
                if data is None:
                    return data
                return int(data)

            entries.append(ACLEntry(rc[7], rc[0].strip(), rc[1].strip(), __int(rc[2]), __int(rc[3]), __int(rc[4]), __int(rc[5]), __int(rc[6]), bool(rc[8])))

        self._aclCache[aclid] = ACL(aclid, name, parent, owner, entries, self._get_machines_in_acl(aclid))

    def _get_machines_in_acl(self, aclid, preemptableUse=False):
        db = self.page.getDB()
        machines = {}
        cur = db.cursor()
        cur.execute("SELECT m.machine, m.status, m.comment, j.userid, j.preemptable, m.preemptablelease FROM tblmachines AS m INNER JOIN tblacls AS a ON m.aclid = a.aclid LEFT JOIN tbljobs AS j ON m.jobid = j.jobid WHERE (m.aclid = %s OR a.parent = %s)",
                    (aclid, aclid))
        while True:
            rc = cur.fetchone()
            if not rc:
                break

            machines[rc[0].strip()] = self._get_user_for_machine(rc[1].strip(),
                                                             rc[2].strip() if rc[2] else None, 
                                                             rc[3].strip() if rc[3] else None,
                                                             rc[4],
                                                             rc[5],
                                                             preemptableUse)
        cur.close()

        return machines

    def _get_user_for_machine(self, status, leaseuser, jobuser, jobpreemptable, leasepreemptable, preemptableUse=False):
        # Machine is considered in use if there's either a non-preemptable job running or a non-preemptable lease
        if leaseuser is not None and ((leasepreemptable and preemptableUse) or not (leasepreemptable or preemptableUse)):
            return leaseuser.lower()
        elif status in ["scheduled", "slaved", "running"] and ((jobpreemptable and preemptableUse) or not (jobpreemptable or preemptableUse)):
            return jobuser.lower()
        else:
            return None

    def update_acl_cache(self, machine, userid, preemptable):
        """Update any ACLs for the given machine to note it is in use by userid"""
        if preemptable:
            # We haven't really used any machines
            return
        for aclid in self._aclCache:
            if machine in self._aclCache[aclid].machines:
                if userid:
                    self._aclCache[aclid].machines[machine] = userid.lower()
                else:
                    self._aclCache[aclid].machines[machine] = None

    def _get_acl_counts(self, aclid):
        acl = self.get_acl(aclid, withCounts=False)
        machines = copy.copy(acl.machines)
        preemptableMachines = self._get_machines_in_acl(aclid, preemptableUse=True)
        preemptableUsers = filter(None, preemptableMachines.values())
        for e in acl.entries:
            count = 0
            userMachines = {}
            if e.entryType == 'user':
                # Identify all machines used by this user
                userMachines[e.userid] = []
                for m in machines:
                    if machines[m] == e.userid:
                        machines[m] = None
                        count += 1
                        userMachines[e.userid].append(m)
            elif e.entryType == 'group':
                # Identify all machines used by this group
                groupUsers = self._userids_for_group(e.userid)
                for m in machines:
                    if machines[m] and machines[m] in groupUsers:
                        user = machines[m]
                        machines[m] = None
                        count += 1
                        if not user in userMachines.keys():
                            userMachines[user] = []
                        userMachines[user].append(m)
                for u in groupUsers:
                    if not u in userMachines.keys() and u in preemptableUsers:
                        userMachines[u] = []

            elif e.entryType == 'default':
                # Identify all other in use machines
                for m in machines:
                    if machines[m] is not None:
                        user = machines[m]
                        if not user in userMachines.keys():
                            userMachines[user] = []
                        userMachines[user].append(m)
                        count += 1
                    elif preemptableMachines[m] is not None:
                        user = preemptableMachines[m]
                        if not user in userMachines.keys():
                            userMachines[user] = []
            else:
                raise Exception("Unknown entryType %s" % e.entryType)

            # Set the properties on the ACL
            e.machinecount = count
            e.usermachines = userMachines
        return acl

    def check_acl(self, aclid, userid, machines, leaseHours=None, ignoreParent=False, preemptable=False, ignoreCounts=False):
        """Returns a tuple (allowed, reason_if_false) if the given user can have machines under this acl"""
        acl = self.get_acl(aclid)
        result, reason = self._check_acl(acl, userid.lower(), machines, leaseHours, preemptable, ignoreCounts)
        if result and acl.parent and not ignoreParent:
            # We have to check the parent ACL as well
            return self._check_acl(self.get_acl(acl.parent), userid.lower(), machines, leaseHours, preemptable, ignoreCounts)
        return result, reason 

    def _check_acl(self, acl, userid, machines, leaseHours=None, preemptable=False, ignoreCounts=False):
        """Returns True if the given user can have machines under this acl"""
        aclMachines = copy.copy(acl.machines)
        extraMachines = copy.copy(machines)
        usergroups = self.groups_for_userid(userid)
        usercount = 0
        for m in aclMachines:
            if aclMachines[m] == userid:
                usercount += 1
                if m in extraMachines:
                    # The machine is already in use by the user, so we don't need to double count it
                    extraMachines.remove(m)

        skipQuantityChecks = ignoreCounts
        if len(extraMachines) == 0:
            # All machines the user is asking for are already theirs, so no need
            # to check the rest of the ACL, unless this is a lease when we need
            # to verify they are within their allowed time
            if leaseHours:
                skipQuantityChecks = True
            else:
                return True, None

        usercount += len(extraMachines)
        userpercent = int(math.ceil((usercount * 100.0) / len(aclMachines)))

        # Go through the acl entries
        for e in acl.entries:
            if e.entryType == 'user':
                if e.userid != userid:
                    # Another user - remove their usage from our data
                    # otherwise we might double count them if they're a member of a group as well
                    for m in aclMachines:
                        if aclMachines[m] == e.userid:
                            aclMachines[m] = None
                    continue
                else:
                    if preemptable:
                        if e.preemptableuse:
                            return True, None
                        else:
                            # TODO improve error message here to use a term other than preemptable
                            return False, "ACL does now allow preemptable use for this user"
                    # Our user - check their usage
                    if not skipQuantityChecks or e.userlimit == 0 or e.userpercent == 0:
                        if e.userlimit is not None and usercount > e.userlimit:
                            return False, "%s limited to %d machines" % (e.userid, e.userlimit)
                        if e.userpercent is not None and userpercent > e.userpercent:
                            return False, "%s limited to %d%% of machines" % (e.userid, e.userpercent)
                    if e.maxleasehours is not None and leaseHours and leaseHours > e.maxleasehours:
                        return False, "Maximum lease time allowed for %s is %d hours" % (e.userid, e.maxleasehours)

                    # We've hit an exact user match, so we ignore any further rules
                    return True, None
            elif e.entryType == 'group' or e.entryType == 'default':
                if e.entryType == 'default' or e.userid in usergroups:
                    if preemptable:
                        if e.preemptableuse:
                            return True,None
                        else:
                            # TODO improve error message here to use a term other than preemptable
                            return False, "ACL does now allow preemptable use for this group"
                    # A group our user is in - identify overall usage and per user usage for users in the acl
                    groupcount = usercount
                    if e.entryType == 'default':
                        groupcount += len(filter(lambda m: m and m != userid, aclMachines.values()))
                    else:
                        for u in self._userids_for_group(e.userid):
                            if u == userid:
                                continue # Don't count our user as we've already accounted for that
                            groupcount += len(filter(lambda m: m == u, aclMachines.values()))
                    grouppercent = int(math.ceil((groupcount * 100.0) / len(aclMachines)))

                    groupname = e.entryType == 'default' and "default" or e.userid
                    if not skipQuantityChecks or e.userlimit == 0 or e.userpercent == 0 or e.grouplimit == 0 or e.grouppercent == 0:
                        if e.grouplimit is not None and groupcount > e.grouplimit:
                            return False, "%s limited to %d machines" % (groupname, e.grouplimit)
                        if e.grouppercent is not None and grouppercent > e.grouppercent:
                            return False, "%s limited to %d%% of machines" % (groupname, e.grouppercent)

                        # Check the user limits as well
                        if e.userlimit is not None and usercount > e.userlimit:
                            return False, "Members of %s limited to %d machines" % (groupname, e.userlimit)
                        if e.userpercent is not None and userpercent > e.userpercent:
                            return False, "Members of %s limited to %d%% of machines" % (groupname, e.userpercent)

                    # Check lease restrictions
                    if e.maxleasehours is not None and leaseHours and leaseHours > e.maxleasehours:
                        return False, "Maximum lease time allowed for members of %s is %d hours" % (groupname, e.maxleasehours)

                    # We've hit a successful group match, so we ignore any further rules
                    return True, None
                else:
                    # A group our user isn't in, remove it's usage so we don't count it in later rules
                    userids = self._userids_for_group(e.userid)
                    for m in aclMachines:
                        if aclMachines[m] in userids:
                            aclMachines[m] = None
            else:
                raise Exception("Unknown entryType %s" % e.entryType)

        return False, "User is not listed in ACL"

    def _userids_for_group(self, group):
        if group in self._groupCache:
            return self._groupCache[group]
        db = self.page.getDB()
        cur = db.cursor()
        cur.execute("SELECT gu.userid FROM tblgroupusers gu INNER JOIN tblgroups g ON gu.groupid = g.groupid WHERE g.name=%s", [group])
        results = []
        while True:
            rc = cur.fetchone()
            if not rc:
                break
            results.append(rc[0].strip())
        self._groupCache[group] = results
        return results

    def groups_for_userid(self, userid):
        if userid in self._userGroupCache:
            return self._userGroupCache[userid]
        db = self.page.getDB()
        cur = db.cursor()
        cur.execute("SELECT g.name FROM tblgroups g INNER JOIN tblgroupusers gu ON g.groupid = gu.groupid WHERE gu.userid=%s", [userid.lower()])
        results = []
        while True:
            rc = cur.fetchone()
            if not rc:
                break
            results.append(rc[0].strip())
        self._userGroupCache[userid] = results
        return results

