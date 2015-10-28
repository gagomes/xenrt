from app.apiv2 import *
from pyramid.httpexceptions import *
import calendar
import app.utils
import json
import time
import jsonschema
import requests
import re

class _MachineBase(XenRTAPIv2Page):

    def getMachineStatus(self,
                  status,
                  leaseuser,
                  pool):
        broken = pool.endswith("x")
        if leaseuser:
            return "leased"
        else:
            if status == "idle":
                return "broken" if broken else "idle"
            elif status in ("running", "scheduled", "slaved"):
                return "running"
            else:
                return "offline"

    def getMachines(self,
                    pools=[],
                    clusters=[],
                    resources=None,
                    sites=[],
                    status=[],
                    users=[],
                    machines=[],
                    flags=[],
                    aclids=[],
                    groups=[],
                    limit=None,
                    offset=0,
                    pseudoHosts=False,
                    exceptionIfEmpty=False,
                    search=None,
                    include_forbidden=True,
                    only_restricted=False):
        cur = self.getDB().cursor()
        params = []
        conditions = []

        if pools:
            conditions.append(self.generateInCondition("m.pool", pools))
            params.extend(pools)

        if clusters:
            conditions.append(self.generateInCondition("m.cluster", clusters))
            params.extend(clusters)

        if groups:
            conditions.append(self.generateInCondition("m.mgroup", groups))
            params.extend(groups)

        if sites:
            conditions.append(self.generateInCondition("m.site", sites))
            params.extend(sites)

        if users:
            conditions.append(self.generateInCondition("m.comment", users))
            params.extend(users)

        if machines:
            conditions.append(self.generateInCondition("m.machine", machines))
            params.extend(machines)
            # Don't exclude psuedohosts if machines are specifued
            pseudoHosts=True

        if aclids:
            conditions.append(self.generateInCondition("m.aclid", aclids))
            params.extend(aclids)

        if status:
            statuscond = []
            for s in status:
                if s == "offline":
                    statuscond.append("(m.status not in ('idle', 'scheduled', 'running', 'slaved') AND m.comment IS NULL)")
                elif s == "idle":
                    statuscond.append("(m.status = 'idle' AND m.comment IS NULL AND right(m.pool, 1) != 'x')")
                elif s == "running":
                    statuscond.append("m.status in ('scheduled', 'running', 'slaved')")
                elif s == "broken":
                    statuscond.append("right(m.pool, 1) = 'x'")
                elif s == "leased":
                    statuscond.append("m.comment IS NOT NULL")
            if statuscond:
                conditions.append("(%s)" % " OR ".join(statuscond))

        if not pseudoHosts:
            conditions.append("m.machine != ('_' || s.site)")


        query = "SELECT m.machine, m.site, m.cluster, m.pool, m.status, m.resources, m.flags, m.comment, m.leaseto, m.leasereason, m.leasefrom, m.leasepolicy, s.flags, m.jobid, m.descr, m.aclid, s.ctrladdr, s.location, m.prio, m.mgroup, m.preemptablelease, j.userid FROM tblmachines m INNER JOIN tblsites s ON m.site=s.site LEFT OUTER JOIN tbljobs j ON m.jobid=j.jobid"
        if conditions:
            query += " WHERE %s" % " AND ".join(conditions)

        cur.execute(query, self.expandVariables(params))

        ret = {}

        aclForbiddenCache = {}
        aclRestrictedCache = {}
        getExtraData = []

        while True:
            rc = cur.fetchone()
            if not rc:
                break
            aclid = rc[15]
            if not aclid:
                forbidden = False
                restricted = False
            else:
                if aclid in aclForbiddenCache.keys():
                    forbidden = aclForbiddenCache[aclid]
                else:
                    forbidden = not self.getACLHelper().check_acl(aclid, self.getUser().userid, [None], ignoreCounts=True)[0]
                    aclForbiddenCache[aclid] = forbidden
                if aclid in aclRestrictedCache.keys():
                    restricted = aclRestrictedCache[aclid]
                else:
                    restricted = self.getACLHelper().is_acl_restricted(aclid)
                    aclRestrictedCache[aclid] = restricted
            if forbidden and not include_forbidden:
                continue
            if not restricted and only_restricted:
                continue
            if not forbidden or self.getUser().admin:
                getExtraData.append(rc[0].strip())


            machine = {
                "name": rc[0].strip(),
                "site": rc[1].strip(),
                "cluster": rc[2].strip() if rc[2] else 'default',
                "pool": rc[3].strip(),
                "group": rc[19].strip() if rc[19] else None,
                "rawstatus": rc[4].strip(),
                "status": self.getMachineStatus(rc[4].strip(), rc[7].strip() if rc[7] else None, rc[3].strip()),
                "flags": [],
                "description": rc[14].strip() if rc[14] and rc[14].strip() else None,
                "resources": {},
                "leaseuser": rc[7].strip() if rc[7] else None,
                "leaseto": calendar.timegm(rc[8].timetuple()) if rc[8] else None,
                "leasereason": rc[9].strip() if rc[9] else None,
                "leasefrom": calendar.timegm(rc[10].timetuple()) if rc[10] else None,
                "leasepolicy": rc[11],
                "jobid": rc[13],
                "broken": rc[3].strip().endswith("x"),
                "aclid": rc[15],
                "ctrladdr": rc[16].strip() if rc[16] else None,
                "location": rc[17].strip() if rc[17] else None,
                "prio": rc[18],
                "preemptablelease": bool(rc[20]) if rc[7] else None,
                "params": {},
                "forbidden": forbidden,
                "restricted": restricted
            }
            machine['leasecurrentuser'] = bool(machine['leaseuser'] and machine['leaseuser'] == self.getUser().userid)

            if machine['rawstatus'] in ("running", "slaved", "scheduled"):
                machine['jobuser'] = rc[21].strip() if rc[21] else None
            else:
                machine['jobuser'] = None

            machine['jobcurrentuser'] = machine['jobuser'] == self.getUser().userid if machine['jobuser'] else None

            for r in rc[5].strip().split("/"):
                if not "=" in r:
                    continue
                (key, value) = r.split("=", 1)
                machine['resources'][key] = value
                

            siteflags = rc[12].strip().split(",") if rc[12] and rc[12].strip() else []
            machine['flags'].extend(siteflags)

            ret[rc[0].strip()] = machine
        if len(ret.keys()) == 0:
            if exceptionIfEmpty:
                raise XenRTAPIError(HTTPNotFound, "Machine not found")

            return ret
        if len(getExtraData) > 0:
            query = "SELECT machine, key, value FROM tblmachinedata WHERE %s" % self.generateInCondition("machine", getExtraData)
            cur.execute(query, getExtraData)

            while True:
                rc = cur.fetchone()
                if not rc:
                    break
                if rc[2] and rc[2].strip():
                    ret[rc[0].strip()]["params"][rc[1].strip()] = rc[2].strip()
                if rc[1].strip() == "PROPS" and rc[2] and rc[2].strip():
                    ret[rc[0].strip()]['flags'].extend(rc[2].strip().split(","))

        if search:
            try:
                searchre = re.compile(search, flags=re.IGNORECASE)
            except Exception, e:
                raise XenRTAPIError(HTTPBadRequest, "Invalid regular expression: %s" % str(e))
        else:
            searchre = None

        for m in ret.keys():
            if flags:
                if not app.utils.check_attributes(",".join(ret[m]['flags']), ",".join(flags)):
                    del ret[m]
                    continue
            if resources:
                if not app.utils.check_resources("/".join(["%s=%s" % (x,y) for (x,y) in ret[m]['resources'].items()]), "/".join(resources)):
                    del ret[m]
                    continue

            if search:
                if not searchre.search(m) and \
                        not app.utils.check_resources("/".join(["%s=%s" % (x,y) for (x,y) in ret[m]['resources'].items()]), search) and \
                        not app.utils.check_attributes(",".join(ret[m]['flags']), search) and \
                        not (ret[m]['description'] and searchre.search(ret[m]['description'])):
                    del ret[m]
                    continue

        if limit:
            machinesToReturn = sorted(ret.keys())[offset:offset+limit]

            for m in ret.keys():
                if not m in machinesToReturn:
                    del ret[m]

        return ret

    def updateMachineField(self, machine, key, value, commit=True, allowReservedField=False):
        db = self.getDB()

        machines = self.getMachines(limit=1, machines=[machine], exceptionIfEmpty=True)

        if key.lower() == "description":
            key = "descr"
        elif key.lower() == "group":
            key = "mgroup"

        if key.lower() == "aclid" and value == "":
            value = None

        details = machines[machine]['params']
        if key.lower() in ("machine", "comment", "leaseto", "leasereason", "leasefrom"):
            raise XenRTAPIError(HTTPForbidden, "Can't update this field")
        if key.lower() in ("status", "jobid") and not allowReservedField:
            raise XenRTAPIError(HTTPForbidden, "Can't update this field")
        if key.lower() in ("site", "cluster", "pool", "status", "resources", "flags", "descr", "jobid", "leasepolicy", "aclid", "prio", "mgroup"):
            cur = db.cursor()
            try:
                cur.execute("UPDATE tblmachines SET %s=%%s WHERE machine=%%s;" % (key.lower()), (value, machine))
                # Check whether the pool has changed, or the status has switched to/from offline 
                oldpool = machines[machine]['pool']
                if machines[machine]['rawstatus'] == "offline":
                    oldpool += "__offline"
                newpool = oldpool
                if key.lower() == "pool":
                    newpool = value
                    if machines[machine]['rawstatus'] == "offline":
                        newpool += "__offline"
                if key.lower() == "status":
                    newpool = machines[machine]['pool']
                    if value == "offline":
                        newpool += "__offline"
                if newpool != oldpool:
                    timenow = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time()))
                    etype = "PoolChange"
                    subject = machine
                    edata = "%s:%s" % (oldpool, newpool)
                    cur.execute("INSERT INTO tblEvents (ts, etype, subject, edata) "
                                "VALUES (%s, %s, %s, %s);",
                                [timenow, etype, subject, edata])
                if commit:
                    db.commit()
            finally:
                cur.close()
        else:
            cur = db.cursor()
            try:
                # Use empty string as a way to delete a property
                cur.execute("DELETE FROM tblmachinedata WHERE machine=%s "
                            "AND key=%s;", [machine, key])
                if value:
                    cur.execute("INSERT INTO tblmachinedata (machine,key,value) "
                            "VALUES (%s,%s,%s);", [machine, key, str(value)])
                if commit:
                    db.commit()
            finally:
                cur.close()
    
    def return_machine(self, machine, user, force, canForce=True, commit=True):
        machines = self.getMachines(limit=1, machines=[machine], exceptionIfEmpty=True)

        leasedTo = machines[machine]['leaseuser']
        if not leasedTo:
            raise XenRTAPIError(HTTPPreconditionFailed, "Machine is not leased")
        elif leasedTo and leasedTo != user and not force:
            raise XenRTAPIError(HTTPUnauthorized, "Machine is leased to %s" % leasedTo, canForce=canForce)
        
        db = self.getDB()
        cur = db.cursor()
        cur.execute("UPDATE tblMachines SET leaseTo = NULL, comment = NULL, leasefrom = NULL, leasereason = NULL, preemptablelease = NULL "
                    "WHERE machine = %s",
                    [machine])

        timenow = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time()))
        
        cur.execute("INSERT INTO tblEvents(ts, etype, subject, edata) VALUES (%s, %s, %s, %s);",
                        [timenow, "LeaseEnd", machine, None])

        if commit:
            db.commit()
        cur.close()        

    def addMachine(self, name, site, pool, cluster, resources, description, commit=True):
        db = self.getDB()
        cur = db.cursor()
        try:
            query = "INSERT INTO tblmachines(machine, site, pool, cluster, status, resources, descr) VALUES (%s, %s, %s, %s, 'idle', %s, %s)"
            params = [name, site, pool, cluster, "/".join(["%s=%s" % (x,y) for (x,y) in resources.items()]), description]

            cur.execute(query, params)
            timenow = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time()))
            etype = "PoolChange"
            subject = name
            edata = "NULL:%s" % (pool)
            cur.execute("INSERT INTO tblEvents (ts, etype, subject, edata) "
                        "VALUES (%s, %s, %s, %s);",
                        [timenow, etype, subject, edata])

            if commit:
                db.commit()
        finally:
            cur.close()

    def lease(self, machine, user, duration, reason, force, besteffort, preemptable, adminoverride, commit=True):
        leaseFrom = time.strftime("%Y-%m-%d %H:%M:%S",
                                time.gmtime(time.time()))

        # Only XenRT admins can use admin override
        if adminoverride and not self.getUser(forceReal=True).admin:
            raise XenRTAPIError(HTTPUnauthorized, "Only XenRT admins can use the admin_override functionality")

        if duration:
            forever = False 
            leaseToTime = time.gmtime(time.time() + (duration * 3600))
            leaseTo = time.strftime("%Y-%m-%d %H:%M:%S", leaseToTime)
        else: 
            leaseTo = "2030-01-01 00:00:00"
            leaseToTime = time.strptime(leaseTo, "%Y-%m-%d %H:%M:%S")
            duration = (calendar.timegm(leaseToTime) - time.time()) / 3600
            forever = True 
        

        machines = self.getMachines(limit=1, machines=[machine], exceptionIfEmpty=True)

        leasePolicy = machines[machine]['leasepolicy']

        if preemptable: # Preemptable leases are limited to 6 hours
            leasePolicy = min(leasePolicy, 6)

        if leasePolicy and duration > leasePolicy and not adminoverride:
            if besteffort:
                duration = leasePolicy
                leaseToTime = time.gmtime(time.time() + (duration * 3600))
                leaseTo = time.strftime("%Y-%m-%d %H:%M:%S", leaseToTime)
            else:
                raise XenRTAPIError(HTTPUnauthorized, "The policy for this machine only allows leasing for %d hours, please contact QA if you need a longer lease" % leasePolicy, canForce=False)
        
        leasedTo = machines[machine]['leaseuser']
        if leasedTo and leasedTo != user and not force:
            raise XenRTAPIError(HTTPUnauthorized, "Machine is already leased to %s" % leasedTo, canForce=True)
        currentLeaseTime = machines[machine]['leaseto']
        if not forever and currentLeaseTime and time.gmtime(currentLeaseTime) > leaseToTime and not force:
            raise XenRTAPIError(HTTPNotAcceptable, "Machines is already leased for longer", canForce=True)

        if machines[machine]['aclid'] and not adminoverride:
            result, reason = self.getACLHelper().check_acl(machines[machine]['aclid'], user, [machine], duration, preemptable=preemptable)
            if not result:
                raise XenRTAPIError(HTTPUnauthorized, "ACL: %s" % reason, canForce=False)

        db = self.getDB()
        cur = db.cursor()
        cur.execute("UPDATE tblMachines SET leaseTo = %s, leasefrom = %s, comment = %s, leasereason = %s, preemptablelease = %s "
                    "WHERE machine = %s",
                    [leaseTo, leaseFrom, user, reason, preemptable, machine])
        
        timenow = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time()))
        
        cur.execute("INSERT INTO tblEvents(ts, etype, subject, edata) VALUES (%s, %s, %s, %s);",
                        [timenow, "LeaseStart", machine, user])
        if commit:
            db.commit()
        cur.close()        

    def removeMachine(self, machine, commit=True):
        db = self.getDB()
        cur = db.cursor()
        try:
            cur.execute("DELETE FROM tblmachines WHERE machine=%s", [machine])
            cur.execute("DELETE FROM tblmachinedata WHERE machine=%s", [machine])
            if commit:
                db.commit()
        finally:
            cur.close()


class ListMachines(_MachineBase):
    PATH = "/machines"
    REQTYPE = "GET"
    SUMMARY = "Get machines matching parameters"
    PARAMS = [
         {'collectionFormat': 'multi',
          'default': '',
          'description': 'Filter on machine status. Any of "idle", "running", "leased", "offline", "broken" - can specify multiple',
          'in': 'query',
          'items': {'enum': ['idle', 'running', 'leased', 'offline', 'broken'], 'type': 'string'},
          'name': 'status',
          'required': False,
          'type': 'array'},
         {'collectionFormat': 'multi',
          'description': 'Filter on site - can specify multiple',
          'in': 'query',
          'items': {'type': 'string'},
          'name': 'site',
          'required': False,
          'type': 'array'},
         {'collectionFormat': 'multi',
          'description': 'Filter on pool - can specify multiple',
          'in': 'query',
          'items': {'type': 'string'},
          'name': 'pool',
          'required': False,
          'type': 'array'},
         {'collectionFormat': 'multi',
          'description': 'Filter on cluster - can specify multiple',
          'in': 'query',
          'items': {'type': 'string'},
          'name': 'cluster',
          'required': False,
          'type': 'array'},
         {'collectionFormat': 'multi',
          'description': 'Filter on lease user - can specify multiple',
          'in': 'query',
          'items': {'type': 'string'},
          'name': 'user',
          'required': False,
          'type': 'array'},
         {'collectionFormat': 'multi',
          'description': 'Get a specific machine - can specify multiple',
          'in': 'query',
          'items': {'type': 'string'},
          'name': 'machine',
          'required': False,
          'type': 'array'},
         {'collectionFormat': 'multi',
          'description': 'Filter on a resource - can specify multiple',
          'in': 'query',
          'items': {'type': 'string'},
          'name': 'resource',
          'required': False,
          'type': 'array'},
         {'collectionFormat': 'multi',
          'description': 'Filter on a flag - can specify multiple',
          'in': 'query',
          'items': {'type': 'string'},
          'name': 'flag',
          'required': False,
          'type': 'array'},
         {'collectionFormat': 'multi',
          'description': 'Filter on an ACL id - can specify multiple',
          'in': 'query',
          'items': {'type': 'integer'},
          'name': 'aclid',
          'required': False,
          'type': 'array'},
         {'description': 'Limit the number of results. Defaults to unlimited',
          'in': 'query',
          'name': 'limit',
          'required': False,
          'default': 10,
          'type': 'integer'},
         {'description': 'Offset to start the results at, for paging with limit enabled.',
          'in': 'query',
          'name': 'offset',
          'required': False,
          'type': 'integer'},
         {'description': "Get pseudohosts, defaults to false",
          'in' : 'query',
          'name': 'pseudohosts',
          'required': False,
          'type': 'boolean'},
         {'description': "Regular expression to search for machines",
          'in': 'query',
          'name': 'search',
          'required': False,
          'type': 'string'},
         {'collectionFormat': 'multi',
          'description': 'Filter on group - can specify multiple',
          'in': 'query',
          'items': {'type': 'string'},
          'name': 'group',
          'required': False,
          'type': 'array'},
         {'description': "Include machines which are blocked by ACL",
          'in': 'query',
          'name': 'include_forbidden',
          'required': False,
          'default': False,
          'type': 'boolean'},
         {'description': "Only show machines which are not accessible to all users (i.e. do not have a default item in the ACL)",
          'in': 'query',
          'name': 'only_restricted',
          'required': False,
          'default': False,
          'type': 'boolean'}
          ]
    RESPONSES = { "200": {"description": "Successful response"}}
    TAGS = ["machines"]
   
    def render(self):
        if self.getUser().admin:
            default_forbidden="true"
        else:
            default_forbidden="false"
        return self.getMachines(pools = self.getMultiParam("pool"),
                                clusters = self.getMultiParam("cluster"),
                                resources = self.getMultiParam("resource"),
                                sites = self.getMultiParam("site"),
                                status = self.getMultiParam("status"),
                                users = self.getMultiParam("user"),
                                machines = self.getMultiParam("machine"),
                                flags = self.getMultiParam("flag"),
                                aclids = self.getMultiParam("aclid"),
                                groups = self.getMultiParam("group"),
                                pseudoHosts = self.request.params.get("pseudohosts") == "true",
                                limit=int(self.request.params.get("limit", 0)),
                                offset=int(self.request.params.get("offset", 0)),
                                search=self.request.params.get("search"),
                                include_forbidden=self.request.params.get("include_forbidden", default_forbidden) == "true",
                                only_restricted=self.request.params.get("only_restricted") == "true")

class GetMachine(_MachineBase):
    PATH = "/machine/{name}"
    REQTYPE = "GET"
    SUMMARY = "Gets a specific machine object"
    TAGS = ["machines"]
    PARAMS = [
        {'name': 'name',
         'in': 'path',
         'required': True,
         'description': 'Machine to fetch',
         'type': 'string'}]
    RESPONSES = { "200": {"description": "Successful response"}}

    def render(self):
        machine = self.request.matchdict['name']
        machines = self.getMachines(limit=1, machines=[machine], exceptionIfEmpty=True)
        return machines[machine]

class LeaseMachine(_MachineBase):
    WRITE = True
    PATH = "/machine/{name}/lease"
    REQTYPE = "POST"
    SUMMARY = "Lease a machine"
    TAGS = ["machines"]
    PARAMS = [
        {'name': 'name',
         'in': 'path',
         'required': True,
         'description': 'Machine to lease',
         'type': 'string'},
        {'name': 'body',
         'in': 'body',
         'required': True,
         'description': 'Details of the lease required',
         'schema': { "$ref": "#/definitions/lease" }
         }
         
        ]
    DEFINITIONS = { "lease": {
             "title": "Lease details",
             "type": "object",
             "required": ["duration", "reason"],
             "properties": {
                "duration": {
                    "type": "integer",
                    "description": "Time in hours to lease the machine. 0 means forever",
                    "default": 24},
                "reason": {
                    "type": "string",
                    "description": "Reason the machine is to be leased"},
                "force": {
                    "type": "boolean",
                    "description": "Whether to force lease if another use has the machine leased",
                    "default": False},
                "besteffort": {
                    "type": "boolean",
                    "description": "Borrow for as long as long as policy allows, don't fail if can't be borrowed",
                    "default": False},
                "preemptable": {
                    "type": "boolean",
                    "description": "Borrow on a preemptable basis - can be taken back for scheduled testing (ACL policy dependent)",
                    "default": False},
                "admin_override": {
                    "type": "boolean",
                    "description": "Override lease policy (only available to admins)",
                    "default": False}
                }
            }
        }
    RESPONSES = { "200": {"description": "Successful response"}}
    OPERATION_ID = "lease_machine"
    PARAM_ORDER = ['name', 'duration', 'reason', 'force', 'besteffort', 'preemptable', 'admin_override']

    def render(self):
        try: 
            params = json.loads(self.request.body)
            jsonschema.validate(params, self.DEFINITIONS['lease'])
        except Exception, e:
            raise XenRTAPIError(HTTPBadRequest, str(e).split("\n")[0])
        try:
            self.lease(self.request.matchdict['name'], self.getUser().userid, params['duration'], params['reason'], params.get('force', False), params.get('besteffort', False), params.get('preemptable', False), params.get('admin_override', False))
        except:
            if params.get('besteffort', False):
                return {}
            else:
                raise
        return {}
        
class ReturnMachine(_MachineBase):
    WRITE = True
    PATH = "/machine/{name}/lease"
    REQTYPE = "DELETE"
    SUMMARY = "Return a leased machine"
    TAGS = ["machines"]
    PARAMS = [
        {'name': 'name',
         'in': 'path',
         'required': True,
         'description': 'Machine to lease',
         'type': 'string'},
        {'name': 'body',
         'in': 'body',
         'required': True,
         'description': 'Details of the lease required',
         'schema': { "$ref": "#/definitions/leasereturn" }
         }
         
        ]
    DEFINITIONS = { "leasereturn": {
             "title": "Lease details",
             "type": "object",
             "properties": {
                "force": {
                    "type": "boolean",
                    "description": "Whether to force return if another use has the machine leased",
                    "default": False}
                }
            }
        }
    RESPONSES = { "200": {"description": "Successful response"}}
    OPERATION_ID = "return_leased_machine"

    def render(self):
        try:
            if self.request.body:
                params = json.loads(self.request.body)
            else:
                params = {}
            jsonschema.validate(params, self.DEFINITIONS['leasereturn'])
        except Exception, e:
            raise XenRTAPIError(HTTPBadRequest, str(e).split("\n")[0])
        self.return_machine(self.request.matchdict['name'], self.getUser().userid, params.get('force', False))
        return {}

class UpdateMachine(_MachineBase):
    REQTYPE="POST"
    WRITE = True
    PATH = "/machine/{name}"
    TAGS = ["machines"]
    PARAMS = [
        {'name': 'name',
         'in': 'path',
         'required': True,
         'description': 'Machine to update',
         'type': 'string'},
        {'name': 'body',
         'in': 'body',
         'required': True,
         'description': 'Details of the update',
         'schema': { "$ref": "#/definitions/updatemachine" }
        }
    ]
    RESPONSES = { "200": {"description": "Successful response"}}
    DEFINITIONS = {"updatemachine": {
        "title": "Update Macine",
        "type": "object",
        "properties": {
            "params": {
                "type": "object",
                "description": "Key-value pairs parameter:value of parameters to update (set value to null to delete a parameter)"
            },
            "status": {
                "type": "string",
                "description": "Status of the machine"
            },
            "broken": {
                "type": "object",
                "description": "Mark the machine as broken or fixed. Fields are 'broken' (boolean - whether or not the machine is broken), 'info' (string - notes about why the machine is broken), 'ticket' (string - ticket reference for this machine)",
                "properties": {
                    "broken": { "type": "boolean" },
                    "info": { "type": "string" },
                    "ticket": { "type": "string" }
                }
            },
            "addflags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Flags to add to this machine"
            },
            "delflags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Flags to remove from this machine"
            },
            "resources": {
                "type": "object",
                "description": "Key-value pair resource:value of resources to update. (set value to null to remove a resource)"
            },
            "prio": {
                "type": ["integer", "null"],
                "description": "Machine priority. Default is 3. E.g. a priority of 4 means that this machine will be only be selected by the scheduler if no machines with priority 3 are available"
            }
        }
    }}
    OPERATION_ID = "update_machine"
    PARAM_ORDER=["name", "params", "broken", "status", "resources", "addflags", "delflags", "prio"]
    SUMMARY = "Update machine details"

    def render(self):
        machine = self.request.matchdict['name']
        machines = self.getMachines(limit=1, machines=[machine], exceptionIfEmpty=True)
        try:
            j = json.loads(self.request.body)
            jsonschema.validate(j, self.DEFINITIONS['updatemachine'])
        except Exception, e:
            raise XenRTAPIError(HTTPBadRequest, str(e).split("\n")[0])
        if j.get('params'):
            for p in j['params'].keys():
                self.updateMachineField(machine, p, j['params'][p], commit=False)
        if j.get('status'):
            self.updateMachineField(machine, "status", j['status'], allowReservedField=True, commit=False)
        if "prio" in j:
            self.updateMachineField(machine, "prio", j['prio'], commit=False)
        if "broken" in j:

            pool = machines[machine]['pool']
            if j['broken']['broken']:
                if not pool.endswith("x"):
                    self.updateMachineField(machine, "POOL", pool + "x", commit=False)
                self.updateMachineField(machine, "BROKEN_INFO", j['broken'].get("info"), commit=False)
                self.updateMachineField(machine, "BROKEN_TICKET", j['broken'].get("ticket"), commit=False)
            else:
                if pool.endswith("x"):
                    self.updateMachineField(machine, "POOL", pool.rstrip("x"), commit=False)
                self.updateMachineField(machine, "BROKEN_INFO", None, commit=False)
                self.updateMachineField(machine, "BROKEN_TICKET", None, commit=False)
        if "addflags" in j:
            if not "PROPS" in machines[machine]['params']:
                props = []
            else:
                props = machines[machine]['params']['PROPS'].split(",")
            for f in j['addflags']:
                if not f in props:
                    props.append(f)
            self.updateMachineField(machine, "PROPS", ",".join(props), commit=False)
        if "delflags" in j:
            if "PROPS" in machines[machine]['params']:
                props = machines[machine]['params']['PROPS'].split(",")
                for f in j['delflags']:
                    if f in props:
                        props.remove(f)
                self.updateMachineField(machine, "PROPS", ",".join(props), commit=False)
        if "resources" in j:
            resources = machines[machine]['resources']

            for r in j['resources'].keys():
                if j['resources'][r] == None and r in resources:
                    del resources[r]
                elif j['resources'][r] != None:
                    resources[r] = str(j['resources'][r])

            self.updateMachineField(machine, "RESOURCES", "/".join(["%s=%s" % (x,y) for (x,y) in resources.items()]), commit=False)

        self.getDB().commit()
        return {}
    
class NewMachine(_MachineBase):
    REQTYPE="POST"
    WRITE = True
    PATH = "/machines"
    TAGS = ["machines"]
    PARAMS = [
        {'name': 'body',
         'in': 'body',
         'required': True,
         'description': 'Details of the machine',
         'schema': { "$ref": "#/definitions/newmachine" }
        }
    ]
    RESPONSES = { "200": {"description": "Successful response"}}
    DEFINITIONS = {"newmachine": {
        "title": "New Macine",
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name of the machine"
            },
            "site": {
                "type": "string",
                "description": "Site this machine belongs to"
            },
            "pool": {
                "type": "string",
                "description": "Pool this machine belongs to"
            },
            "cluster": {
                "type": "string",
                "description": "Cluster this machine belongs to"
            },
            "params": {
                "type": "object",
                "description": "Key-value pairs parameter:value of parameters to update (set value to null to delete a parameter)"
            },
            "flags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Flags for this machine"
            },
            "resources": {
                "type": "object",
                "description": "Key-value pair resource:value of resources to update. (set value to null to remove a resource)"
            },
            "description": {
                "type": "string",
                "description": "Description of the machine"
            }
        },
        "required": ["name", "pool", "site", "cluster"]
    }}
    OPERATION_ID = "new_machine"
    PARAM_ORDER=["name", "site", "pool", "cluster", "flags", "resources", "params"]
    SUMMARY = "Add new machine"

    def render(self):
        try:
            j = json.loads(self.request.body)
            jsonschema.validate(j, self.DEFINITIONS['newmachine'])
        except Exception, e:
            raise XenRTAPIError(HTTPBadRequest, str(e).split("\n")[0])

        self.addMachine(j.get("name"), j.get("site"), j.get("pool"), j.get("cluster"), j.get("resources", {}), j.get("description"))

        if j.get("flags"):
            self.updateMachineField(j.get("name"), "PROPS", ",".join(j['flags']), commit=False)

        if j.get('params'):
            for p in j['params'].keys():
                self.updateMachineField(j.get("name"), p, j['params'][p], commit=False)
   
        self.getDB().commit()
        return {}

class RemoveMachine(_MachineBase):
    PATH = "/machine/{name}"
    REQTYPE = "DELETE"
    SUMMARY = "Removes a machine"
    TAGS = ["machines"]
    PARAMS = [
        {'name': 'name',
         'in': 'path',
         'required': True,
         'description': 'Machine to remove',
         'type': 'string'}]
    RESPONSES = { "200": {"description": "Successful response"}}
    OPERATION_ID = "remove_machine"
    WRITE=True

    def render(self):
        machine = self.request.matchdict['name']
        self.getMachines(limit=1, machines=[machine], exceptionIfEmpty=True)
        self.removeMachine(machine)
        return {}

class PowerMachine(_MachineBase):
    REQTYPE="POST"
    WRITE = True
    PATH = "/machine/{name}/power"
    TAGS = ["machines"]
    PARAMS = [
        {'name': 'name',
         'in': 'path',
         'required': True,
         'description': 'Machine to set power',
         'type': 'string'},
        {'name': 'body',
         'in': 'body',
         'required': True,
         'description': 'Details of the power operation',
         'schema': { "$ref": "#/definitions/powermachine" }
        }
    ]
    RESPONSES = { "200": {"description": "Successful response"}}
    DEFINITIONS = {"powermachine": {
        "title": "Power Macine",
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["on", "off", "reboot", "nmi"],
                "description": "Status of the machine"
            },
            "bootdev": {
                "type": "string",
                "description": "IPMI boot device for the next boot"
            },
            "force": {
                "type": "boolean",
                "description": "Perform operation even if the machine is in use by someone else",
                "default": False
            },
            "admin_override": {
                "type": "boolean",
                "description": "Override ACL (only available to admins)",
                "default": False
            }
        },
        "required": ["operation"]
    }}
    OPERATION_ID = "power_machine"
    PARAM_ORDER=["name", "operation", "bootdev", "force", "admin_override"]
    SUMMARY = "Control the power on a machine"

    def render(self):
        machine = self.getMachines(limit=1, machines=[self.request.matchdict['name']], exceptionIfEmpty=True)[self.request.matchdict['name']]
       
        try:
            j = json.loads(self.request.body)
            jsonschema.validate(j, self.DEFINITIONS['powermachine'])
        except Exception, e:
            raise XenRTAPIError(HTTPBadRequest, str(e).split("\n")[0])
        
        adminoverride = j.get('admin_override', False)
        force = j.get('force', False)

        if adminoverride and not self.getUser(forceReal=True).admin:
            raise XenRTAPIError(HTTPUnauthorized, "Only XenRT admins can use the admin_override functionality")

        if not adminoverride:
            if machine['forbidden']:
                raise XenRTAPIError(HTTPUnauthorized, "You do not have access to this machine")
        if not force:
            if machine['leaseuser'] and not machine['leasecurrentuser']:
                raise XenRTAPIError(HTTPUnauthorized, "This machine is leased to %s" % machine['leaseuser'])
            if machine['jobuser'] and not machine['jobcurrentuser']:
                raise XenRTAPIError(HTTPUnauthorized, "This machine is running a job for %s" % machine['jobuser'])



        reqdict = {"machine": machine['name'], "powerop": j['operation']}

        if j.get('bootdev'):
            reqdict['bootdev'] = j['bootdev']

        r = requests.get("http://%s/xenrt/api/controller/power" % machine['ctrladdr'], params=reqdict)
        r.raise_for_status()
        if r.text.startswith("ERROR"):
            raise XenRTAPIError(HTTPInternalServerError, r.text)
        return {"output": r.text.strip()}

class GetMachineResources(_MachineBase):
    REQTYPE="GET"
    WRITE = False
    PATH = "/machine/{name}/resources"
    TAGS = ["machines"]
    PARAMS = [
        {'name': 'name',
         'in': 'path',
         'required': True,
         'description': 'Machine to list resources for',
         'type': 'string'}
    ]
    RESPONSES = { "200": {"description": "Successful response"}}
    OPERATION_ID="get_machine_resources"
    PARAM_ORDER=['name']
    SUMMARY = "List resources locked by a machine"

    def render(self):
        machine = self.getMachines(limit=1, machines=[self.request.matchdict['name']], exceptionIfEmpty=True)[self.request.matchdict['name']]
        reqdict = {"machine": machine['name']}
        r = requests.get("http://%s/xenrt/api/controller/listresources" % machine['ctrladdr'], params=reqdict)
        r.raise_for_status()
        if r.text.startswith("ERROR"):
            raise XenRTAPIError(HTTPInternalServerError, r.text)
        return r.json()

class ReleaseMachineResource(_MachineBase):
    REQTYPE="DELETE"
    WRITE = False
    PATH = "/machine/{name}/resources/{resource}"
    TAGS = ["machines"]
    PARAMS = [
        {'name': 'name',
         'in': 'path',
         'required': True,
         'description': 'Machine to release resource from',
         'type': 'string'},
        {'name': 'resource',
         'in': 'path',
         'required': True,
         'description': 'Resource to release',
         'type': 'string'}
    ]
    RESPONSES = { "200": {"description": "Successful response"}}
    OPERATION_ID="release_machine_resource"
    PARAM_ORDER=['name', 'resource']
    SUMMARY = "Release a resource locked by a machine"

    def render(self):
        machine = self.getMachines(limit=1, machines=[self.request.matchdict['name']], exceptionIfEmpty=True)[self.request.matchdict['name']]
        reqdict = {"resource": [self.request.matchdict['resource']]}
        r = requests.get("http://%s/xenrt/api/controller/releaseresources" % machine['ctrladdr'], params=reqdict)
        r.raise_for_status()
        if r.text.startswith("ERROR"):
            raise XenRTAPIError(HTTPInternalServerError, r.text)
        return {"output": r.text.strip()}

class LockMachineResource(_MachineBase):
    REQTYPE="POST"
    WRITE = False
    PATH = "/machine/{name}/resources"
    TAGS = ["machines"]
    PARAMS = [
        {'name': 'name',
         'in': 'path',
         'required': True,
         'description': 'Machine to lock resources for',
         'type': 'string'},
        {'name': 'body',
         'in': 'body',
         'required': True,
         'description': 'Details of the power operation',
         'schema': { "$ref": "#/definitions/lockmachineresources" }
        }
    ]
    RESPONSES = { "200": {"description": "Successful response"}}
    DEFINITIONS = {"lockmachineresources": {
        "title": "Lock Machine Resources",
        "type": "object",
        "properties": {
            "resource_type": {
                "type": "string",
                "description": "Type of resource to lock"
            },
            "args": {
                "type": "array",
                "description": "Optional args for this resource",
                "items": {"type": "string"}
            }
        },
        "required": ["resource_type"]
    }}
    OPERATION_ID="lock_machine_resource"
    PARAM_ORDER=['name', 'resource_type', 'args']
    SUMMARY = "List resources locked by a machine"

    def render(self):
        try:
            j = json.loads(self.request.body)
            jsonschema.validate(j, self.DEFINITIONS['lockmachineresources'])
        except Exception, e:
            raise XenRTAPIError(HTTPBadRequest, str(e).split("\n")[0])
        machine = self.getMachines(limit=1, machines=[self.request.matchdict['name']], exceptionIfEmpty=True)[self.request.matchdict['name']]
        reqdict = {"machine": machine['name'], "type": j['resource_type']}
        if j['args']:
            reqdict['args'] = " ".join(j['args'])
        r = requests.get("http://%s/xenrt/api/controller/getresource" % machine['ctrladdr'], params=reqdict)
        r.raise_for_status()
        if r.json()['result'] != ("OK"):
            raise XenRTAPIError(HTTPInternalServerError, r.text)
        return r.json()

class PowerMachineStatus(_MachineBase):
    REQTYPE="GET"
    WRITE = True
    PATH = "/machine/{name}/power"
    TAGS = ["machines"]
    PARAMS = [
        {'name': 'name',
         'in': 'path',
         'required': True,
         'description': 'Machine to get power status',
         'type': 'string'}]
    RESPONSES = { "200": {"description": "Successful response"}}
    OPERATION_ID = "power_machine_status"
    PARAM_ORDER=["name"]
    SUMMARY = "Get the power status for a machine"

    def render(self):
        machine = self.getMachines(limit=1, machines=[self.request.matchdict['name']], exceptionIfEmpty=True)[self.request.matchdict['name']]

        reqdict = {"machine": machine['name'], "powerop": "status"}
        r = requests.get("http://%s/xenrt/api/controller/power" % machine['ctrladdr'], params=reqdict)
        r.raise_for_status()
        if r.text.startswith("ERROR"):
            raise XenRTAPIError(HTTPInternalServerError, r.text)
        m = re.search("POWERSTATUS: \('(.+)', '(.+)'\)\n", r.text)
        if not m:
            raise XenRTAPIError(HTTPInternalServerError, r.text)
        return {"status": m.group(1), "source": m.group(2)}
    
class NotifyBorrow(_MachineBase):
    def run(self):
        borrowedMachines = [x for x in self.getMachines().values() if x['leaseuser']]

        for m in borrowedMachines:
            earlyTime = time.mktime(time.gmtime()) - 24 * 3600
            leaseFrom = m.get('leasefrom', 0)
            leaseTo = m['leaseto']

            if self.warningTime > leaseTo and leaseFrom < earlyTime:
                self.notifyUser(m['leaseuser'], m['name'], leaseTo)

    @property
    def warningTime(self):
        lt = time.mktime(time.gmtime())
        if time.gmtime().tm_wday >= 4: # Friday, Saturday Sunday
            return lt + 3600 * (24 * (7-time.localtime().tm_wday) + 6)
        else:
            return lt + 3600 * 30

    def notifyUser(self, user, machine, expiry):
        try:
            ftime = time.strftime("%H:%M %Z %A", time.gmtime(expiry))
            email = app.user.User(self, user).email
            if not email:
                return
            print "Emailing %s about %s" % (email, machine)
            msg = "Your lease on machine %s is due to expire soon (%s)" % (machine, ftime)
            app.utils.sendMail("XenServerQAXenRTAdmin-noreply@citrix.com", [email], "XenRT Lease expiring soon on %s" % machine, msg)
        except Exception, e:
            print "Could not notify for machine %s - %s" % (machine, str(e))


RegisterAPI(ListMachines)
RegisterAPI(GetMachine)
RegisterAPI(LeaseMachine)
RegisterAPI(ReturnMachine)
RegisterAPI(UpdateMachine)
RegisterAPI(NewMachine)
RegisterAPI(RemoveMachine)
RegisterAPI(PowerMachine)
RegisterAPI(PowerMachineStatus)
RegisterAPI(GetMachineResources)
RegisterAPI(ReleaseMachineResource)
RegisterAPI(LockMachineResource)
