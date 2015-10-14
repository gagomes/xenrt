#!/usr/bin/python

from app.apiv2 import XenRTAPIv2Swagger
from server import PageFactory
import re

class Path(object):
    def __init__(self, parent, path, method, data, definitions):
        self.parent = parent
        self.path = path
        self.method = method
        self.data = data
        self.definitions = definitions
        self.args = []
        self.argdesc = []
        self.jsonParams = []
        self.formParams = []
        self.pathParams = []
        self.queryParams = []
        self.boolQueryParams = []
        self.returnKey = None
        self.skip = False
        self.parseParams()

    def powerShellParamName(self, param):
        if param == "file":
            return "filepath"
        else:
            return param

    def powerShellType(self, typename, items):
        if typename == "file":
            return "string"
        elif typename == "object":
            return "hashtable"
        elif typename == "integer":
            return "int"
        elif typename == "boolean":
            return "bool"
        else:
            return typename

    @property
    def methodContent(self):
        if self.masterOnly:
            ret = """    $path = $("https://" + $XenRTCreds.MasterServer + "/xenrt/api/v2%s")\n""" % self.path.replace("{", "${")
        else:
            ret = """    $path = $("https://" + $XenRTCreds.Server + "/xenrt/api/v2%s")\n""" % self.path.replace("{", "${")
        ret += """    $paramdict = @{}\n"""
        for p in self.queryParams:
            q = self.powerShellParamName(p)
            if p in self.boolQueryParams:
                ret += """    if ($%s) {\n        $paramdict.%s = ([string]$%s).ToLower()\n    }\n""" % (q, p, q)
            else:
                ret += """    if ($%s) {\n        $ofs=","\n        $paramdict.%s = [string]$%s\n    }\n""" % (q, p, q)
        ret += """    $payload = @{}\n"""
        if self.jsonParams:
            ret += """    $jd = @{}\n"""
            for p in self.jsonParams:
                q = self.powerShellParamName(p)
                ret += """    if ($%s) {\n        $jd.%s = $%s\n    }\n""" % (q, p, q)
            ret += """    $payload = $jd | ConvertTo-JSON\n"""
        #elif self.formParams:
        #    for p in self.formParams:
        #        q = self.powerShellParamName(p)
        if self.method == "get":
            ret += """    $ret = Invoke-RestMethod -Uri $path -Method GET -Headers @{"X-API-Key"=$XenRTCreds.ApiKey} -Body $paramdict\n"""
        else:
            ret += """    $ret = Invoke-RestMethod -Uri $path -Method %s -Headers @{"X-API-Key"=$XenRTCreds.ApiKey} -Body $payload\n""" % self.method
            #if self.formParams:
            #    ret += """        myHeaders = {}\n"""
            #else:
            #    ret += """        myHeaders = {'content-type': 'application/json'}\n"""
            #ret += """        myHeaders.update(self.customHeaders)\n"""
            #ret += """        r = requests.%s(path, params=paramdict, data=payload, files=files, headers=myHeaders)\n""" % self.method
            #ret += """        if r.status_code in (502, 503):\n"""
            #ret += """            time.sleep(30)\n"""
            #ret += """            r = requests.%s(path, params=paramdict, data=payload, files=files, headers=myHeaders)\n""" % self.method
        #ret += """        self.__raiseForStatus(r)\n"""
        if 'application/json' in self.data['produces']:
            if self.returnKey:
                ret += """    return $ret.%s""" % self.returnKey
            else:
                ret += """    return $ret"""
        else:
            ret += """    return $ret"""
        return ret

    def parseParams(self):
        args = []
        argdesc = {}
        for p in self.data.get('parameters', []):
            if p['in'] == "body":
                objType = self.definitions[p['schema']['$ref'].split("/")[-1]]
                for q in [x for x in objType['properties'].keys() if x in objType.get('required', [])]:
                    self.jsonParams.append(q)
                    args.append((q,self.powerShellType(objType['properties'][q]['type'], objType['properties'][q].get("items")),True))
                    argdesc[q] = "%s - %s" % (self.powerShellType(objType['properties'][q]['type'], objType['properties'][q].get("items")), objType['properties'][q].get('description', ""))
                for q in [x for x in objType['properties'].keys() if x not in objType.get('required', [])]:
                    self.jsonParams.append(q)
                    args.append((q,self.powerShellType(objType['properties'][q]['type'], objType['properties'][q].get("items")),False))
                    argdesc[q] = "%s - %s" % (self.powerShellType(objType['properties'][q]['type'], objType['properties'][q].get("items")), objType['properties'][q].get('description', ""))
            else:
                if p['in'] == "path":
                    self.pathParams.append(p['name'])
                elif p['in'] == "query":
                    self.queryParams.append(p['name'])
                    if p['type'] == "boolean":
                        self.boolQueryParams.append(p['name'])
                elif p['in'] == "formData":
                    self.formParams.append(p['name'])

                if p.get('type') == "file":
                    self.skip = True
                    return
                argdesc[p['name']] = "%s - %s" % (self.powerShellType(p.get('type'), p.get("items")), p.get('description',""))
                if p.get('required'):
                    args.append((p['name'],self.powerShellType(p.get('type'), p.get("items")),True))
                else:
                    args.append((p['name'],self.powerShellType(p.get('type'), p.get("items")),False))
        for p in self.data.get('paramOrder', []):
            pp = [x for x in args if x[0] == p]
            if not pp:
                pp = [(p,"string",False)]
            pname = self.powerShellParamName(pp[0][0])
            self.args.append("[parameter(mandatory=$%s)][%s]$%s" % (str(pp[0][2]).lower(),pp[0][1],pname))

            self.argdesc.append((pname, argdesc.get(pp[0][0], "")))
        for p in args:
            if not p[0] in self.data.get('paramOrder', []):
                pname = self.powerShellParamName(p[0])
                self.args.append("[parameter(mandatory=$%s)][%s]$%s" % (str(p[2]).lower(),p[1],pname))
                self.argdesc.append((pname, argdesc.get(p[0], "")))

        if self.data.get('returnKey'):
            self.returnKey = self.data.get('returnKey')

    @property
    def methodSignature(self):
        ret = "function %s {" % (self.methodName)
        return ret

    @property
    def psParams(self):
        if not self.args:
            return ""
        ret = "param("
        ret += ",".join("\n    %s" % x for x in self.args)
        ret += "\n    )"
        return ret

    @property
    def description(self):
        ret = "<#\n.SYNOPSIS\n    %s\n" % (self.data['summary'])
        if "description" in self.data:
            ret += ".DESCRIPTION\n    %s\n" % self.data['description'].rstrip()
        if self.argdesc:
            for p in self.argdesc:
                ret += ".PARAMETER %s\n    %s\n" % (p[0], p[1])
        ret += "#>"
        return ret

    @property
    def masterOnly(self):
        return bool(self.data.get("masterOnly"))

    @property
    def methodName(self):
        if self.data.get('operationId'):
            ret = self.data['operationId']
        else: 
            ret = ""
            if self.method == "get":
                ret += "get_"
            name = self.path.split("{")[0]
            name = name.replace("/", "_")
            name = name.strip("_")
            ret += name
        ret = ret.replace("_", "-XenRT_", 1)
        ret = re.sub('(\_[a-z])', lambda x: x.group(1).upper(), ret) 
        ret = re.sub('(^[a-z])', lambda x: x.group(1).upper(), ret) 
        ret = ret.replace("_", "")
        # Use PowerShell approved verbs
        ret = re.sub('^Replace', 'Set', ret)
        ret = re.sub('^Release', 'Unlock', ret)
        ret = re.sub('^Return', 'Unlock', ret)
        ret = re.sub('^Lease', 'Lock', ret)
        # Special case for power
        ret = ret.replace("Power-XenRTMachine", "Set-XenRTMachinePower")
        return ret

    @property
    def methodParams(self):
        args = []
        return ", ".join(self.args)

class PowerShellBindings(XenRTAPIv2Swagger):
    def render(self):
        self.getPaths()
        return self.generateFile()

    def getPaths(self):
        self.funcs = []
        swagger = XenRTAPIv2Swagger.render(self)

        for p in swagger['paths'].keys():
            for m in swagger['paths'][p].keys():
                if swagger['paths'][p][m].get('operationId') == "no_binding":
                    continue
                self.funcs.append(Path(self, p, m, swagger['paths'][p][m], swagger['definitions']))
        
        self.scheme = swagger['schemes'][0]
        self.base = swagger['basePath']
        self.host = swagger['host']
        self.masterhost = swagger['masterhost']

    def generateFile(self):
        ret = """<#
.SYNOPSIS
    XenRT Powershell Module
.DESCRIPTION
    XenRT powershell
#>

Set-StrictMode -Version Latest

$XenRTCreds = New-Object object |
    Add-Member -MemberType NoteProperty -Name "ApiKey" -Value "" -Passthru |
    Add-Member -MemberType NoteProperty -Name "Server" -Value "%s" -Passthru
    Add-Member -MemberType NoteProperty -Name "MasterServer" -Value "%s" -Passthru

function Connect-XenRT {
<#
.SYNOPSIS
    Makes a connection to XenRT with an API key or Kerberos
.DESCRIPTION
    Makes a connection to XenRT with an API key or Kerberos
.PARAMETER UseDefaultCredentials
    Use built-in Windows Authentication (Kerberos) to connect
.PARAMETER ApiKey
    The API key, if not using kerberos
.PARAMETER Server
    The server to connect to (defaults to %s)
.PARAMETER MasterServer
    The master server to connect to (defaults to %s)
#>
param(
    [parameter(mandatory=$false)][switch]$UseDefaultCredentials,
    [parameter(mandatory=$false)][string]$ApiKey,
    [parameter(mandatory=$false)][string]$Server,
    [parameter(mandatory=$false)][string]$MasterServer
    )
    if ($Server) {
        $XenRTCreds.Server=$Server
    }
    if ($MasterServer) {
        $XenRTCreds.MasterServer=$MasterServer
    }
    if ($UseDefaultCredentials) {
        $path = $("https://" + $XenRTCreds.Server + "/xenrt/api/v2/apikey")
        $XenRTCreds.ApiKey=(Invoke-RestMethod -Uri $path -Method GET -UseDefaultCredentials).key
    }
    else {
        $XenRTCreds.ApiKey=$ApiKey
    }
    Write-Output $("Logged in as " + (Get-XenRTLoggedinUser).user)
}
""" % (self.host, self.masterhost, self.host, self.masterhost)
        for func in self.funcs:
            if func.skip:
                continue
            ret += "%s\n" % func.methodSignature
            ret += "%s\n" % func.description
            ret += "%s\n" % func.psParams
            ret += "%s\n" % func.methodContent
            ret += "}\n\n"
    
        return ret

PageFactory(PowerShellBindings, "bindings/xenrt.psm1", reqType="GET", contentType="text/plain")
