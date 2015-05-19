from app.apiv2 import *
from pyramid.httpexceptions import *
import json
import jsonschema
import os
import subprocess
import datetime
import re

class _SuiteStartBase(XenRTAPIv2Page):
    pass

class StartSuite(_SuiteStartBase):
    PATH = "/suiterun/start"
    REQTYPE = "POST"
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
                    "rerun": {
                        "type": "boolean",
                        "description": "Whether to rerun tests"
                    },
                    "rerunall": {
                        "type": "boolean",
                        "description": "Whether to rerun all tests in the suite"
                    },
                    "seqs": {
                        "type": "array",
                        "description": "Sequences to run",
                        "items": {"type": "string"}
                    },
                    "params": {
                        "type": "object",
                        "description": "Key-value pair of parameters"
                    }
                }
            }
        }
    RESPONSES = { "200": {"description": "Successful response"}}
    OPERATION_ID = "start_suiterun"
    PARAM_ORDER = ['suite', 'branch', 'version']
    TAGS = ['suiterun']

    def render(self):
        try: 
            params = json.loads(self.request.body)
            jsonschema.validate(params, self.DEFINITIONS['startsuite'])
        except Exception, e:
            raise XenRTAPIError(HTTPBadRequest, str(e).split("\n")[0])
        
        token = self.startSuite(params)

        return {"token": token}

    def startSuite(self, params):
        command = "/usr/local/bin/runsuite /etc/xenrt/suites/%s -b %s -r %s" % (params['suite'], params['branch'], params['version'])

        if params.get("sku"):
            command += " --sku /etc/xenrt/suites/%s.sku" % params['sku']

        if params.get("rerun"):
            command += " --rerun"

        if params.get("rerunall"):
            command += " --rerun-all"

        if params.get("seqs"):
            command += " --suite-seqs %s" % ",".join(params['seqs'])

        for p in params.get("params", {}).keys():
            command += " -D %s=%s" % (p, params['params'][p])

        token = re.sub(r'\W+', '', datetime.datetime.now().isoformat())
        wdir = "/local/scratch/suiteruns/%s" % token
        os.makedirs(wdir)

        with open("%s/command" % wdir, "w") as f:
            f.write("%s\n" % command)
        with open("%s/user" % wdir, "w") as f:
            f.write("%s\n" % self.getUser().userid)
        command += " > %s/run.out 2>&1" % wdir
        command += "; echo $? > %s/exitcode" % wdir
        pid = subprocess.Popen(command, shell=True).pid
        with open("%s/pid" % wdir, "w") as f:
            f.write("%d\n" % pid)
        return token

RegisterAPI(StartSuite)
