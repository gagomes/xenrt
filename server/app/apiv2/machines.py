from app.apiv2 import XenRTAPIv2Page, RegisterAPI
from pyramid.httpexceptions import *
import calendar
import app.utils

class XenRTGetMachinesBase(XenRTAPIv2Page):

    def getStatus(self,
                  status,
                  leaseuser,
                  pool):
        broken = pool.endswith("x")
        if leaseuser:
            return "borrowed"
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
                elif s == "borrowed":
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

class XenRTListMachines(XenRTGetMachinesBase):
    PATH = "/machines"
    REQTYPE = "GET"
    DESCRIPTION = "Get machines matching parameters"
    PARAMS = [
         {'collectionFormat': 'multi',
          'default': '',
          'description': 'Filter on machine status. Any of "idle", "running", "borrowed", "offline", "broken" - can specify multiple',
          'in': 'query',
          'items': {'enum': ['idle', 'running', 'borrowed', 'offline', 'broken'], 'type': 'string'},
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

class XenRTGetMachine(XenRTGetMachinesBase):
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
            return HTTPNotFound()
        return machines[machine]

RegisterAPI(XenRTListMachines)
RegisterAPI(XenRTGetMachine)
