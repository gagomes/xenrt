from app.apiv2 import *
import app.db
import app.ad
from pyramid.httpexceptions import *
import json
import jsonschema
import os
import subprocess
import datetime
import re
import xml.dom.minidom

class _SuiteStartBase(XenRTAPIv2Page):
    pass

class StartSuite(_SuiteStartBase):
    PATH = "/suiterun/start"
    REQTYPE = "POST"
    MASTER_ONLY = True
    SUMMARY = "Start suite run"
    PARAMS = [
        {'name': 'body',
'in': 'body',
         'required': True,
         'description': 'Details of the suite run to start',
         'schema': { "$ref": "#/definitions/startsuite" }
        }]
    DEFINITIONS = { "startsuite": {
                "title": "Suite run details",
                "type": "object",
                "required": ["suite", "branch", "version"],
                "properties": {
                    "suite": {
                        "type": "string",
                        "description": "Suite to run (e.g. 'TC-12720')"
                    },
                    "branch": {
                        "type": "string",
                        "description": "Branch to run suite against"
                    },
                    "version": {
                        "type": "string",
                        "description": "Version to test"
                    },
                    "sku": {
                        "type": "string",
                        "description": "Suite run SKU"
                    },
                    "devrun": {
                        "type": "boolean",
                        "description": "Whether to run this suite as a dev run"
                    },
                    "rerun": {
                        "type": "boolean",
                        "description": "Whether to rerun tests"
                    },
                    "rerunall": {
                        "type": "boolean",
                        "description": "Whether to rerun all tests in the suite"
                    },
                    "rerunifneeded": {
                        "type": "boolean",
                        "description": "Whether to rerun all tests in the suite if it already exists"
                    },
                    "seqs": {
                        "type": "array",
                        "description": "Sequences to run",
                        "items": {"type": "string"}
                    },
                    "delay": {
                        "type": "integer",
                        "description": "Delay (in seconds) before starting suite"
                    },
                    "params": {
                        "type": "object",
                        "description": "Key-value pair of parameters"
                    },
                    "xenrtbranch": {
                        "type": "string",
                        "description": "XenRT branch to use to submit suite (note that XRTBRANCH also needs to be set in the suite"
                    }
                }
            }
        }
    RESPONSES = { "200": {"description": "Successful response"}}
    OPERATION_ID = "start_suite_run"
    PARAM_ORDER = ['suite', 'branch', 'version', 'sku', 'params', 'seqs', 'rerun', 'rerunall', 'rerunifneeded', 'xenrtbranch', 'devrun', 'delay']
    TAGS = ['suiterun']

    def render(self):
        if not app.db.isDBMaster():
            raise XenRTAPIError(self, HTTPBadRequest, "This request must be made on the master node")
        try: 
            params = json.loads(self.request.body)
            jsonschema.validate(params, self.DEFINITIONS['startsuite'])
        except Exception, e:
            raise XenRTAPIError(self, HTTPBadRequest, str(e).split("\n")[0])
        
        restrict = None

        if os.path.exists("/etc/xenrt/suites/%s" % params['suite']):
            x = xml.dom.minidom.parse("/etc/xenrt/suites/%s" % params['suite'])

            for i in x.childNodes:
                if i.nodeType == i.ELEMENT_NODE and i.localName == "suite":
                    for j in i.childNodes:
                        if j.nodeType == j.ELEMENT_NODE and j.localName == "restrict":
                            for a in j.childNodes:
                                if a.nodeType == a.TEXT_NODE and str(a.data).strip():
                                    restrict = str(a.data).strip().split(",")
        if restrict:
            allow = False
            mygroups = app.ad.ActiveDirectory().get_groups_for_user(self.getUser().userid)
            mygroups.append(self.getUser().userid)

            for r in restrict:
                if r in mygroups:
                    allow=True
                    break
            if not allow:
                raise XenRTAPIError(self, HTTPForbidden, "You do not have permission to run this suite - only members of %s can run this suite" % ",".join(restrict))

        token = self.startSuite(params)

        return {"token": token}

    def startSuite(self, params):
        token = re.sub(r'\W+', '', datetime.datetime.now().isoformat())
        xbranch = params.get("xenrtbranch", "stable")
        command = "/usr/local/bin/runsuite2 %s %s %s -b %s -r %s" % (token, xbranch, params['suite'], params['branch'], params['version'])

        if params.get("sku"):
            command += " --sku /etc/xenrt/suites/%s.sku" % params['sku']

        if params.get("devrun"):
            command += " --devrun"

        if params.get("rerun"):
            command += " --rerun"

        if params.get("rerunall"):
            command += " --rerun-all"

        if params.get("rerunifneeded"):
            command += " --rerun-if-needed"

        if params.get("seqs"):
            command += " --suite-seqs %s" % ",".join(params['seqs'])

        if params.get("delay"):
            command += " --delay-for %d" % params['delay']

        for p in params.get("params", {}).keys():
            command += " -D %s=%s" % (p, params['params'][p])

        wdir = "/local/scratch/www/suiteruns/%s" % token
        os.makedirs(wdir)

        with open("%s/command" % wdir, "w") as f:
            f.write("%s\n" % command)
        with open("%s/user" % wdir, "w") as f:
            f.write("%s\n" % self.getUser().userid)
        command += " > %s/run.out 2>&1" % wdir
        command += "; echo $? > %s/exitcode" % wdir
        with open("%s/command2" % wdir, "w") as f:
            f.write("%s\n" % command)
        pid = subprocess.Popen(command, shell=True).pid
        with open("%s/pid" % wdir, "w") as f:
            f.write("%d\n" % pid)
        return token

class StartSuiteStatus(XenRTAPIv2Page):
    PATH = "/suiterun/start/{token}"
    REQTYPE = "GET"
    MASTER_ONLY = True
    SUMMARY = "Get status on suite run starting"
    PARAMS = [
        {"name": "token",
         "type": "string",
         "in": "path",
         "description": "Token to get the status for"
        }]
    RESPONSES = { "200": {"description": "Successful response"}}
    OPERATION_ID = "get_start_suite_run_status"
    TAGS = ['suiterun']

    def render(self):
        token = self.request.matchdict['token']
        wdir = "/local/scratch/www/suiteruns/%s" % token
        with open("%s/user" % wdir) as f:
            user = f.read().strip()
        with open("%s/command" % wdir) as f:
            command = f.read().strip()
        if os.path.exists("%s/exitcode" % wdir):
            with open("%s/exitcode" % wdir) as f:
                if f.read().strip() == "0":
                    status = "success"
                else:
                    status = "error"
        else:
            with open("%s/pid" % wdir) as f:
                pid = f.read().strip()
            if os.path.exists("/proc/%s" % pid):
                status = "running"
            else:
                status = "error"
        suiterun = None
        includedsuiteruns = []
        jobs = {}
        if os.path.exists("%s/run.out" % wdir):
            with open("%s/run.out" % wdir) as f:
                for l in f:
                    m = re.search("^Starting (.+?)\.\.\. (\d+)", l)
                    if m:
                        jobs[m.group(1)] = int(m.group(2))
                    m = re.search("^INCLUDED SUITE (\d+)", l)
                    if m:
                        includedsuiteruns.append(int(m.group(1)))
                    else:
                        m = re.search("^SUITE (\d+)", l)
                        if m:
                            suiterun = int(m.group(1))
        ret = {
            "user": user,
            "command": command,
            "status": status,
            "suiterun": suiterun,
            "includedsuiteruns": includedsuiteruns,
            "jobs": jobs,
            "console": "http://%s/export/suiteruns/%s/run.out" % (self.request.host, token)
        }

        return ret


RegisterAPI(StartSuite)
RegisterAPI(StartSuiteStatus)
