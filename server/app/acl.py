# ACL objects

class ACL(object):

    def __init__(self, aclid, name, parent, entries):
        self.aclid = aclid
        self.name = name
        self.parent = parent
        self.entries = entries

class ACLEntry(object):

    def __init__(self, entryType, userid, grouplimit, grouppercent, userlimit, userpercent, maxleasehours):
        self.entryType = entryType
        self.userid = userid
        self.grouplimit = grouplimit
        self.grouppercent = grouppercent
        self.userlimit = userlimit
        self.userpercent = userpercent
        self.maxleasehours = maxleasehours

