from app.apiv2 import *
from pyramid.httpexceptions import *
import calendar
import app.utils
import json
import time
import jsonschema

class _MachineBase(XenRTAPIv2Page):

    def getStatus(self,
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
                    limit=None,
                    offset=0,
                    pseudoHosts=False):
        cur = self.getDB().cursor()
        params = []
        conditions = []

        if pools:
            conditions.append(self.generateInCondition("m.pool", pools))
            params.extend(pools)

        if clusters:
            conditions.append(self.generateInCondition("m.cluster", clusters))
            params.extend(clusters)

        if sites:
            conditions.append(self.generateInCondition("m.site", sites))
            params.extend(sites)

        if users:
            conditions.append(self.generateInCondition("m.comment", users))
            params.extend(users)

        if machines:
            conditions.append(self.generateInCondition("m.machine", machines))
            params.extend(machines)

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


        query = "SELECT m.machine, m.site, m.cluster, m.pool, m.status, m.resources, m.flags, m.comment, m.leaseto, m.leasereason, m.leasefrom, m.leasepolicy, s.flags, m.jobid FROM tblmachines m INNER JOIN tblsites s ON m.site=s.site"
        if conditions:
            query += " WHERE %s" % " AND ".join(conditions)

        cur.execute(query, params)

        ret = {}

        while True:
            rc = cur.fetchone()
            if not rc:
                break
            machine = {
                "name": rc[0].strip(),
                "site": rc[1].strip(),
                "cluster": rc[2].strip(),
                "pool": rc[3].strip(),
                "rawstatus": rc[4].strip(),
                "status": self.getStatus(rc[4].strip(), rc[7].strip() if rc[7] else None, rc[3].strip()),
                "resources": rc[5].strip().split("/"),
                "flags": rc[6].strip().split(",") if rc[6].strip() else [],
                "leaseuser": rc[7].strip() if rc[7] else None,
                "leaseto": calendar.timegm(rc[8].timetuple()) if rc[8] else None,
                "leasereason": rc[9].strip() if rc[9] else None,
                "leasefrom": calendar.timegm(rc[10].timetuple()) if rc[10] else None,
                "leasepolicy": rc[11],
                "jobid": rc[13],
                "broken": rc[3].strip().endswith("x"),
                "params": {}
            }

            siteflags = rc[12].strip().split(",") if rc[12].split(",") else []
            machine['flags'].extend(siteflags)

            ret[rc[0].strip()] = machine
        if len(ret.keys()) == 0:
            return ret
        query = "SELECT machine, key, value FROM tblmachinedata WHERE %s" % self.generateInCondition("machine", ret.keys())
        cur.execute(query, ret.keys())

        while True:
            rc = cur.fetchone()
            if not rc:
                break
            if rc[2] and rc[2].strip():
                ret[rc[0].strip()]["params"][rc[1].strip()] = rc[2].strip()
            if rc[1].strip() == "PROPS" and rc[2] and rc[2].strip():
                ret[rc[0].strip()]['flags'].extend(rc[2].strip().split(","))

        for m in ret.keys():
            if flags:
                if not app.utils.check_attributes(",".join(ret[m]['flags']), ",".join(flags)):
                    del ret[m]
                    continue
            if resources:
                if not app.utils.check_resources("/".join(ret[m]['resources']), "/".join(resources)):
                    del ret[m]
                    continue

        if limit:
            machinesToReturn = sorted(ret.keys())[offset:offset+limit]

            for m in ret.keys():
                if not m in machinesToReturn:
                    del ret[m]

        return ret

class ListMachines(_MachineBase):
    PATH = "/machines"
    REQTYPE = "GET"
    DESCRIPTION = "Get machines matching parameters"
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
          'type': 'integer'}
          ]
    RESPONSES = { "200": {"description": "Successful response"}}
    TAGS = ["machines"]
   
    def render(self):
        return self.getMachines(pools = self.getMultiParam("pool"),
                                clusters = self.getMultiParam("cluster"),
                                resources = self.getMultiParam("resource"),
                                sites = self.getMultiParam("site"),
                                status = self.getMultiParam("status"),
                                users = self.getMultiParam("user"),
                                machines = self.getMultiParam("machine"),
                                flags = self.getMultiParam("flags"),
                                pseudoHosts = self.request.params.get("pseudohosts") == "true",
                                limit=int(self.request.params.get("limit", 0)),
                                offset=int(self.request.params.get("offset", 0)))

class GetMachine(_MachineBase):
    PATH = "/machine/{name}"
    REQTYPE = "GET"
    DESCRIPTION = "Gets a specific machine object"
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
        machines = self.getMachines(limit=1, machines=[machine])
        if not machine in machines:
            raise XenRTAPIError(HTTPNotFound, "Machine not found")
        return machines[machine]

class LeaseMachine(_MachineBase):
    WRITE = True
    PATH = "/machine/{name}/lease"
    REQTYPE = "POST"
    DESCRIPTION = "Lease a machine"
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
                    "default": False}
                }
            }
        }
    RESPONSES = { "200": {"description": "Successful response"}}
    OPERATION_ID = "lease_machine"
    PARAM_ORDER = ['name', 'duration', 'reason', 'force']

    def lease(self, machine, user, duration, reason, force):
        leaseFrom = time.strftime("%Y-%m-%d %H:%M:%S",
                                time.gmtime(time.time()))
        if duration:
            leaseToTime = time.gmtime(time.time() + (duration * 3600))
            leaseTo = time.strftime("%Y-%m-%d %H:%M:%S", leaseToTime)
        else: 
            leaseTo = "2030-01-01 00:00:00"
            leaseToTime = time.strptime(leaseTo, "%Y-%m-%d %H:%M:%S")
            duration = (calendar.timegm(leaseToTime) - time.time()) / 3600
        

        machines = self.getMachines(limit=1, machines=[machine])
        if not machine in machines:
            raise XenRTAPIError(HTTPNotFound, "Machine not found")

        leasePolicy = machines[machine]['leasepolicy']
        if leasePolicy and duration > leasePolicy:
            raise XenRTAPIError(HTTPUnauthorized, "The policy for this machine only allows leasing for %d hours, please contact QA if you need a longer lease" % leasePolicy, canForce=False)
        
        leasedTo = machines[machine]['leaseuser']
        if leasedTo and leasedTo != user and not force:
            raise XenRTAPIError(HTTPUnauthorized, "Machine is already leased to %s" % leasedTo, canForce=True)
        currentLeaseTime = machines[machine]['leaseto']
        if currentLeaseTime and time.gmtime(currentLeaseTime) > leaseToTime and not force:
            raise XenRTAPIError(HTTPNotAcceptable, "Machines is already leased for longer", canForce=True)

        db = self.getDB()
        cur = db.cursor()
        cur.execute("UPDATE tblMachines SET leaseTo = %s, leasefrom = %s, comment = %s, leasereason = %s "
                    "WHERE machine = %s",
                    [leaseTo, leaseFrom, user, reason, machine])
        db.commit()
        cur.close()        

    def render(self):
        try: 
            params = json.loads(self.request.body)
            jsonschema.validate(params, self.DEFINITIONS['lease'])
        except Exception, e:
            raise XenRTAPIError(HTTPBadRequest, str(e).split("\n")[0])
        self.lease(self.request.matchdict['name'], self.getUser(), params['duration'], params['reason'], params.get('force', False))
        return {}
        
class ReturnMachine(_MachineBase):
    WRITE = True
    PATH = "/machine/{name}/lease"
    REQTYPE = "DELETE"
    DESCRIPTION = "Return a leased machine"
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

    def return_machine(self, machine, user, force):
        machines = self.getMachines(limit=1, machines=[machine])
        if not machine in machines:
            raise XenRTAPIError(HTTPNotFound, "Machine not found")

        leasedTo = machines[machine]['leaseuser']
        if not leasedTo:
            raise XenRTAPIError(HTTPPreconditionFailed, "Machine is not leased")
        elif leasedTo and leasedTo != user and not force:
            raise XenRTAPIError(HTTPUnauthorized, "Machine is leased to %s" % leasedTo, canForce=True)
        
        db = self.getDB()
        cur = db.cursor()
        cur.execute("UPDATE tblMachines SET leaseTo = NULL, comment = NULL, leasefrom = NULL, leasereason = NULL "
                    "WHERE machine = %s",
                    [machine])
        db.commit()
        cur.close()        

    def render(self):
        try:
            if self.request.body:
                params = json.loads(self.request.body)
            else:
                params = {}
            jsonschema.validate(params, self.DEFINITIONS['leasereturn'])
        except Exception, e:
            raise XenRTAPIError(HTTPBadRequest, str(e).split("\n")[0])
        self.return_machine(self.request.matchdict['name'], self.getUser(), params.get('force', False))
        return {}

RegisterAPI(ListMachines)
RegisterAPI(GetMachine)
RegisterAPI(LeaseMachine)
RegisterAPI(ReturnMachine)
