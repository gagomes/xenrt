from server import PageFactory
from app.api import XenRTAPIPage

import app.utils

import config

import traceback, string

class XenRTSitePage(XenRTAPIPage):
    def scm_site_update(self,
                        site,
                        status,
                        flags,
                        descr,
                        comment,
                        ctrladdr,
                        adminid,
                        maxjobs,
                        sharedresources,
                        createNew=False):
        db = self.getDB()
        cur = db.cursor()
        cur.execute("SELECT site FROM tblSites WHERE site = %s", [site])
        if not cur.fetchone():
            if not createNew:
                raise Exception("Could not find site '%s'" % (site))
            # Need to create a new record
            cur.execute("INSERT into tblSites (site) VALUES (%s)", [site])
        
        u = []
        if status:
            u.append(("status", status))
        if flags:
            u.append(("flags", flags))
        if descr:
            u.append(("descr", descr))
        if comment:
            u.append(("comment", comment))
        if ctrladdr:
            u.append(("ctrladdr", ctrladdr))
        if adminid:
            u.append(("adminid", adminid))
        if maxjobs:
            u.append(("maxjobs", maxjobs))
        if sharedresources:
            u.append(("sharedresources", sharedresources))
        sqlset = []
        vals = []
        for field, val in u:
            sqlset.append("%s = %%s" % field)
            vals.append(val)
        vals.append(site)
        sql = "UPDATE tblSites SET %s WHERE site = %%s" % (string.join(sqlset, ", "))
        cur.execute(sql, vals)

        db.commit()
        cur.close()

class XenRTSList(XenRTSitePage):
    def render(self):
        form = self.request.params
        """Handle the slist CLI call"""
        try:
            quiet = False
            showdesc = True
            showprops = False
            chead = "Description"
            if form.has_key("quiet") and form["quiet"] == "yes":
                quiet = True
            if form.has_key("props") and form["props"] == "yes":
                showprops = True
                showdesc = False
                chead = "Properties"
            sites = self.scm_site_list()
            out = ""
            fmt = "%-8s %-7s %s\n"
            if not quiet:
                out += fmt % ("Site", "Status", chead)
                out += "============================================================================\n"
            for s in sites:
                item = ""
                if showdesc:
                    item = s[3]
                elif showprops:
                    item = s [2]
                out += (fmt % (s[0], s[1], item))
            return out
        except:
            traceback.print_exc()
            return "ERROR Error listing sites"

class XenRTSite(XenRTSitePage):
    def render(self):
        if not self.request.params.has_key("site"):
            return "ERROR No site supplied"
        site = self.request.params["site"]
        try:
            out = ""
            s = self.site_data(site)
            for key in s.keys():
                out += "%s=%s\n\n" % (key, s[key])
            
            availableresources = self.site_available_shared_resources(site)
            availableresourcestext = "/".join(map(lambda x:"%s=%s" % (x, availableresources[x]), availableresources.keys()))
            out += "AVAILABLERESOURCES='%s'\n" % availableresourcestext
            return out
        except:
            traceback.print_exc()
            return "ERROR Could not find site " + site

class XenRTSDefine(XenRTSitePage):
    WRITE = True

    def render(self):
        try:
            site = None
            status = None
            flags = ''
            descr = ''
            comment = None
            ctrladdr = None
            adminid = None
            maxjobs = None
            form = self.request.params
            if form.has_key("site"):
                site = form["site"]
            if form.has_key("status"):
                status = form["status"]
            if form.has_key("flags"):
                flags = form["flags"]  
            if form.has_key("descr"):
                descr = form["descr"]
            if form.has_key("comment"):
                comment = form["comment"]
            if form.has_key("ctrladdr"):
                ctrladdr = form["ctrladdr"]
            if form.has_key("adminid"):
                adminid = form["adminid"]
            if form.has_key("maxjobs"):
                maxjobs = int(form["maxjobs"])
            if not site:
                return "ERROR missing field"
            self.scm_site_update(site, status, flags, descr, comment, ctrladdr, adminid, maxjobs, None, createNew=True)
            # Add a pseudohost for running host-less jobs
            machine = "_%s" % (site)
            self.scm_machine_update(machine,
                               site,
                               "default",
                               "NOHOST",
                               None,
                               "",
                               "",
                               "Pseudohost for %s" % (site),
                               None)
            return "OK"
        except:
            traceback.print_exc()
            return "ERROR updating database"

class XenRTSUnDefine(XenRTSitePage):
    WRITE = True

    def render(self):
        """Handle the sundefine CLI call"""
        site = self.request.params["site"]
        try:
            db = self.getDB()
            cur = db.cursor()
            cur.execute("DELETE FROM tblSites WHERE site = %s;", [site])
            try:
                # Remove the pseudohost
                cur.execute("DELETE FROM tblMachines WHERE machine = %s;", ["_%s" % site])
            except:
                pass
            db.commit()
            cur.close()        
            return "OK"
        except:
            traceback.print_exc()
            return "ERROR Error undefining %s" % (site)

class XenRTSUpdate(XenRTSitePage):
    WRITE = True

    def render(self):
        form = self.request.params
        if not form.has_key("site"):
            return "ERROR No site supplied"
        site = form["site"]
        try:
            for key in form.keys():
                if key != 'action' and key != 'site':
                    if key == "STATUS":
                        self.scm_site_update(site,
                                        form[key],
                                        None,
                                        None,
                                        None,
                                        None,
                                        None,
                                        None,
                                        None)
                    elif key == "FLAGS":
                        self.scm_site_update(site,
                                        None,
                                        form[key],
                                        None,
                                        None,
                                        None,
                                        None,
                                        None,
                                        None)
                    elif key == "DESCRIPTION":
                        self.scm_site_update(site,
                                        None,
                                        None,
                                        form[key],
                                        None,
                                        None,
                                        None,
                                        None,
                                        None)
                    elif key == "COMMENT":
                        self.scm_site_update(site,
                                        None,
                                        None,
                                        None,
                                        form[key],
                                        None,
                                        None,
                                        None,
                                        None)
                    elif key == "CTRLADDR":
                        self.scm_site_update(site,
                                        None,
                                        None,
                                        None,
                                        None,
                                        form[key],
                                        None,
                                        None,
                                        None)
                    elif key == "ADMINID":
                        self.scm_site_update(site,
                                        None,
                                        None,
                                        None,
                                        None,
                                        None,
                                        form[key],
                                        None,
                                        None)
                    elif key == "MAXJOBS":
                        self.scm_site_update(site,
                                        None,
                                        None,
                                        None,
                                        None,
                                        None,
                                        None,
                                        int(form[key]),
                                        None)
                    elif key == "SHAREDRESOURCES":
                        self.scm_site_update(site,
                                        None,
                                        None,
                                        None,
                                        None,
                                        None,
                                        None,
                                        None,
                                        form[key])
                    elif key in ("+FLAGS", "-FLAGS"):
                        self.scm_flags_modify(site, key, form[key])
                    else:
                        return "ERROR Unknown site parameter '%s'" % (key)
            return "OK"
        except:
            traceback.print_exc()
            return "ERROR Internal error"

    def scm_flags_modify(self, site, operation, value):

        db = self.getDB()
        # If key starts with "+" or "-" then we are to add or remove the
        # value string from a comma separated list for that key.
        if operation[0] == "+":
            op = 1
        elif operation[0] == "-":
            op = 2
        else:
            raise Exception("Unknown operation %s" % (operation))
        
        cur = db.cursor()
        cur.execute("SELECT flags FROM tblSites WHERE site = %s", [site])
        rc = cur.fetchone()
        if not rc:
            raise Exception("Could not find site '%s'" % (site))
        else:
            prev = ""
            if rc[0]:
                prev = string.strip(rc[0])
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
            cur.execute("UPDATE tblSites SET flags = %s WHERE site = %s",
                        [value, site])

        db.commit()
        cur.close()


PageFactory(XenRTSList, "/api/site/list", compatAction="slist")
PageFactory(XenRTSite, "/api/site/details", compatAction="site")
PageFactory(XenRTSDefine, "/api/site/define", compatAction="sdefine")
PageFactory(XenRTSUpdate, "/api/site/update", compatAction="supdate")
PageFactory(XenRTSUnDefine, "/api/site/undefine", compatAction="sundefine")
