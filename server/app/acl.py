# ACL objects
import math, copy

class ACL(object):

    def __init__(self, aclid, name, parent, entries, machines):
        self.aclid = aclid
        self.name = name
        self.parent = parent
        self.entries = entries
        self.machines = machines

class ACLEntry(object):

    def __init__(self, entryType, userid, grouplimit, grouppercent, userlimit, userpercent, maxleasehours):
        self.entryType = entryType
        self.userid = userid
        self.grouplimit = grouplimit
        self.grouppercent = grouppercent
        self.userlimit = userlimit
        self.userpercent = userpercent
        self.maxleasehours = maxleasehours

class ACLHelper(object):

    def __init__(self, page):
        self.page = page
        self._groupCache = {}
        self._userGroupCache = {}
        self._aclCache = {}

    def get_acl(self, aclid):
        if not aclid in self._aclCache:
            self._get_acl(aclid)
        return self._aclCache[aclid]

    def _get_acl(self, aclid):
        db = self.page.getDB()
        cur = db.cursor()

        cur.execute("SELECT name, parent FROM tblacls WHERE aclid=%s", [aclid])
        rc = cur.fetchone()
        if not rc:
            raise KeyError("ACL not found")
        name = rc[0].strip()
        parent = rc[1]

        entries = []
        cur.execute("SELECT type, userid, grouplimit, grouppercent, userlimit, userpercent, maxleasehours FROM tblaclentries WHERE aclid=%s ORDER BY prio", [aclid])
        while True:
            rc = cur.fetchone()
            if not rc:
                break
            def __int(data):
                if data is None:
                    return data
                return int(data)

            entries.append(ACLEntry(rc[0].strip(), rc[1].strip(), __int(rc[2]), __int(rc[3]), __int(rc[4]), __int(rc[5]), __int(rc[6])))

        self._aclCache[aclid] = ACL(aclid, name, parent, entries, self._get_machines_in_acl(aclid))

    def _get_machines_in_acl(self, aclid):
        db = self.page.getDB()
        machines = {}
        cur = db.cursor()
        cur.execute("SELECT m.machine, m.status, m.comment, j.userid FROM tblmachines AS m INNER JOIN tblacls AS a ON m.aclid = a.aclid LEFT JOIN tbljobs AS j ON m.jobid = j.jobid WHERE (m.aclid = %s OR a.parent = %s)",
                    (aclid, aclid))
        while True:
            rc = cur.fetchone()
            if not rc:
                break
            if rc[1].strip() in ["scheduled", "slaved", "running"]:
                machines[rc[0]] = rc[3].strip()
            elif rc[2] is not None:
                machines[rc[0]] = rc[2].strip()
            else:
                machines[rc[0]] = None
        cur.close()

        return machines

    def check_acl(self, aclid, userid, number, leaseHours=None, ignoreParent=False):
        """Returns a tuple (allowed, reason_if_false) if the given user can have 'number' additional machines under this acl"""
        acl = self.get_acl(aclid)
        result, reason = self._check_acl(acl, userid, number, leaseHours)
        if result and acl.parent and not ignoreParent:
            # We have to check the parent ACL as well
            return self._check_acl(self.get_acl(acl.parent), userid, number, leaseHours)
        return result, reason 

    def _check_acl(self, acl, userid, number, leaseHours=None):
        """Returns True if the given user can have 'number' additional machines under this acl"""
        machines = copy.copy(acl.machines)
        usergroups = self._groups_for_userid(userid)
        usercount = number # Count of machines this user has
        for m in machines:
            if machines[m] == userid:
                usercount += 1
        userpercent = int(math.ceil((usercount * 100.0) / len(machines)))

        # Go through the acl entries
        for e in acl.entries:
            if e.entryType == 'user':
                if e.userid != userid:
                    # Another user - remove their usage from our data
                    # otherwise we might double count them if they're a member of a group as well
                    for m in machines:
                        if machines[m] == e.userid:
                            machines[m] = None
                    continue
                else:
                    # Our user - check their usage
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
                    # A group our user is in - identify overall usage and per user usage for users in the acl
                    groupcount = usercount
                    if e.entryType == 'default':
                        groupcount += len(filter(lambda m: m and m != userid, machines.values()))
                    else:
                        for u in self._userids_for_group(e.userid):
                            if u == userid:
                                continue # Don't count our user as we've already accounted for that
                            groupcount += len(filter(lambda m: m == u, machines.values()))
                    grouppercent = int(math.ceil((groupcount * 100.0) / len(machines)))

                    groupname = e.entryType == 'default' and "default" or e.userid
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
                    for m in machines:
                        if machines[m] in userids:
                            machines[m] = None
            else:
                raise Exception("Unknown entryType %s" % e.entryType)

        return True, None

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

    def _groups_for_userid(self, userid):
        if userid in self._userGroupCache:
            return self._userGroupCache[userid]
        db = self.page.getDB()
        cur = db.cursor()
        cur.execute("SELECT g.name FROM tblgroups g INNER JOIN tblgroupusers gu ON g.groupid = gu.groupid WHERE gu.userid=%s", [userid])
        results = []
        while True:
            rc = cur.fetchone()
            if not rc:
                break
            results.append(rc[0].strip())
        self._userGroupCache[userid] = results
        return results

