# Marvin Deployment wrapper
# This wrapper is intended to be used to deploy clouds with Marvin using the deployDataCenter logic,
# it should only have dependencies on standard Python libraries, and Marvin.

import pprint
import json
import copy
import random
import string
import os
import inspect
import re

class MarvinDeployException(Exception):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return repr(self.value)

class MarvinDeployer(object):
    CONFIG_SCHEMA = {
        'config': {
          'abstractName': 'MarvinConfig',
          'required': { 'zones': None },
          'notify':   { 'globalConfig': 'notifyGlobalConfigChanged' } },
        'globalConfig': {
          'abstractName': 'MgmtSvrGlobalConfig',
          'required': { 'name': None, 'value': None } },
        'zones': {
          'abstractName': 'Zone',
          'required': { 'name': 'getName', 'networktype': None, 'dns1': 'getDNS', 'internaldns1': 'getInternalDNS', 'secondaryStorages': 'getSecondaryStorages', 'physical_networks': None, },
          'defaults': { 'physical_networks': [ { } ]},
          'optional': { 'domain': 'getDomain', 'primaryStorages': None, 'setPrimaryStoragesConfigZone': None },
          'notify'  : { 'name': 'notifyNewElement' } },
        'secondaryStorages': {
          'abstractName': 'SecondaryStorage',
          'required': { 'url': 'getSecondaryStorageUrl', 'provider': 'getSecondaryStorageProvider' }, 
          'optional': { 'details': 'getSecondaryStorageDetails' } },
        'physical_networks': {
          'abstractName': 'PhysicalNetwork',
          'required': { 'name': None, 'traffictypes': None, 'providers': None, 'broadcastdomainrange': None, 'vlan': 'getPhysicalNetworkVLAN' },
          'defaults': { 'traffictypes': [ { 'typ': 'Guest' }, { 'typ': 'Management' } ],
                        'providers': [ { 'name': 'VirtualRouter', 'broadcastdomainrange': 'ZONE' }, { 'name': 'SecurityGroupProvider', 'broadcastdomainrange': 'Pod' } ],
                        'broadcastdomainrange': 'Zone',
                        'vlan': None },
          'notify'  : { 'traffictypes': 'notifyNetworkTrafficTypes' } },
        'traffictypes': {
          'abstractName': 'TrafficType',
          'required': { 'typ': None } },
        'providers': {
          'abstractName': 'NetworkProviders',
          'required': { 'name': None, 'broadcastdomainrange': None },
          'optional': { 'devices': 'getNetworkDevices' } },
        'vmwaredc': {
          'abstractName': 'VMWareDC',
          'required': { 'name': None, 'vcenter': None, 'username': None, 'password': None } },
        'ipranges': {
          'abstractName': 'IPRange',
          'required': { 'startip': 'getGuestIPRangeStartAddr', 'endip': 'getGuestIPRangeEndAddr', 'gateway': 'getGateway', 'netmask': 'getNetmask' },
          'optional': { 'vlan': 'getZonePublicVlan' } },
        'guestIpRanges': {
          'abstractName': 'GuestIPRange',
          'required': { 'startip': 'getGuestIPRangeStartAddr', 'endip': 'getGuestIPRangeEndAddr', 'gateway': 'getGateway', 'netmask': 'getNetmask' } },
        'pods': {
          'abstractName': 'Pod',
          'required': { 'name': 'getName', 'startip': 'getPodIPStartAddr', 'endip': 'getPodIPEndAddr', 'gateway': 'getGateway', 'netmask': 'getNetmask' },
          'notify'  : { 'name': 'notifyNewElement' },
          'optional': { 'vmwaredc': 'getVmWareDc' } },
        'clusters': {
          'abstractName': 'Cluster',
          'required': { 'clustername': 'getName', 'hypervisor': 'getHypervisorType', 'clustertype': 'getClusterType', 'primaryStorages': 'getPrimaryStorages', 'hosts': 'getHostsForCluster' },
          'defaults': { 'primaryStorages': [ { } ] },
          'notify'  : { 'clustername': 'notifyNewElement' },
          'optional' : { 'url': 'getClusterUrl' } },
        'primaryStorages': {
          'abstractName': 'PrimaryStorage',
          'required': { 'name': 'getPrimaryStorageName', 'url': 'getPrimaryStorageUrl'},
          'optional': { 'details': 'getPrimaryStorageDetails', 'scope': None, 'hypervisor': None} },
        'hosts': {
          'abstractName': 'Host',
          'required': { 'url': 'getHostUrl', 'username': 'getHostUsername', 'password': 'getHostPassword' },
          'notify'  : { 'url': 'notifyNewElement' } },
        'details': {
          'abstractName': 'StorageDetails' },
        'devices': {
          'abstractName': 'NetworkDevices' }
      }

    def __init__(self, mgmtServerIp, logger, username, passwd, marvinTestClient):
        self.marvinCfg = {}
        self.marvinCfg['dbSvr'] = {}
        self.marvinCfg['dbSvr']['dbSvr'] = mgmtServerIp
        self.marvinCfg['dbSvr']['passwd'] = 'cloud'
        self.marvinCfg['dbSvr']['db'] = 'cloud'
        self.marvinCfg['dbSvr']['port'] = 3306
        self.marvinCfg['dbSvr']['user'] = 'cloud'

        self.marvinCfg['mgtSvr'] = []
        self.marvinCfg['mgtSvr'].append({ 'mgtSvrIp': mgmtServerIp,
                                          'port'    : 8096 ,
                                          'user' : username,
                                          'passwd' : passwd})

        self.marvinCfg['zones'] = []
        self.logger = logger
        self.__marvinTestClient = marvinTestClient

    def outputAsJSONFile(self, filename):
        fh = open(filename, 'w')
        json.dump(self.marvinCfg, fh, indent=2)
        fh.close()
        self.logger.debug('Created JSON Marvin config file: %s' % (filename))

    def _checkRequiredFieldsForConfigDictElement(self, elementRef, elementKey, deployer):
        self.logger.debug('Processing config for key: %s' % (elementKey))
        for requiredField in self.CONFIG_SCHEMA[elementKey]['required'].keys():
            if not elementRef.has_key(requiredField):
                value = None
                # Check if there is a getter function available
                if self.CONFIG_SCHEMA[elementKey]['required'][requiredField] != None:
                    if hasattr(deployer, self.CONFIG_SCHEMA[elementKey]['required'][requiredField]):
                        value = getattr(deployer, self.CONFIG_SCHEMA[elementKey]['required'][requiredField])(self.CONFIG_SCHEMA[elementKey]['abstractName'], elementRef)

                if value == None:
                    if self.CONFIG_SCHEMA[elementKey].has_key('defaults') and self.CONFIG_SCHEMA[elementKey]['defaults'].has_key(requiredField):
                        value = copy.deepcopy(self.CONFIG_SCHEMA[elementKey]['defaults'][requiredField])
                    else:
                        raise MarvinDeployException('No value avaialble for required field [%s - %s]' % (elementKey, requiredField))

                elementRef[requiredField] = value

    def _checkOptionalFieldsForConfigDictElement(self, elementRef, elementKey, deployer):
        self.logger.debug('Processing config for key: %s' % (elementKey))
        for optionalField in self.CONFIG_SCHEMA[elementKey]['optional'].keys():
            if not elementRef.has_key(optionalField):
                value = None
                # Check if there is a getter function available
                if self.CONFIG_SCHEMA[elementKey]['optional'][optionalField] != None:
                    if hasattr(deployer, self.CONFIG_SCHEMA[elementKey]['optional'][optionalField]):
                        value = getattr(deployer, self.CONFIG_SCHEMA[elementKey]['optional'][optionalField])(self.CONFIG_SCHEMA[elementKey]['abstractName'], elementRef)

                if value == None:
                    if self.CONFIG_SCHEMA[elementKey].has_key('defaults') and self.CONFIG_SCHEMA[elementKey]['defaults'].has_key(optionalField):
                        value = copy.deepcopy(self.CONFIG_SCHEMA[elementKey]['defaults'][optionalField])
               
                if value != None:
                    elementRef[optionalField] = value
    
    def _notifyFieldsForConfigDictElement(self, elementRef, elementKey, deployer):
        for notifyField in self.CONFIG_SCHEMA[elementKey]['notify']:
            if hasattr(deployer, self.CONFIG_SCHEMA[elementKey]['notify'][notifyField]) and elementRef.has_key(notifyField):
                getattr(deployer, self.CONFIG_SCHEMA[elementKey]['notify'][notifyField])(self.CONFIG_SCHEMA[elementKey]['abstractName'], elementRef[notifyField])

    def _processConfigElement(self, element, parentName, deployer):
        if isinstance(element, list):
            map(lambda x:self._processConfigElement(x, parentName, deployer), element)
        elif isinstance(element, dict):
            if self.CONFIG_SCHEMA[parentName].has_key('required'):
                self._checkRequiredFieldsForConfigDictElement(element, parentName, deployer)
            if self.CONFIG_SCHEMA[parentName].has_key('optional'):
                self._checkOptionalFieldsForConfigDictElement(element, parentName, deployer)
            if self.CONFIG_SCHEMA[parentName].has_key('notify'):
                self._notifyFieldsForConfigDictElement(element, parentName, deployer)
            for key, value in element.items():
                self._processConfigElement(value, key, deployer)

    def generateMarvinConfig(self, config, deployer):
        self.logger.debug("Original Config:\n" + pprint.pformat(config))
        self._processConfigElement(config, 'config', deployer)
        self.logger.debug("New Config:\n" + pprint.pformat(config))
        self.marvinCfg.update(config)
        self.fixUpConfig(self.marvinCfg)
        self.logger.debug("Full Marvin Config:\n" + pprint.pformat(self.marvinCfg))

    def fixUpConfig(self, cfg):
        pass

    def deployMarvinConfig(self):
        from marvin import deployDataCenter
        from marvin import jsonHelper

        cfg = jsonHelper.jsonLoader(self.marvinCfg)

        if hasattr(deployDataCenter, 'deployDataCenters'):
            ddcCls = deployDataCenter.deployDataCenters
        elif hasattr(deployDataCenter, 'DeployDataCenters'):
            ddcCls = deployDataCenter.DeployDataCenters
        else:
            raise MarvinDeployException('Unknown Marvin Deploy Data Center class')
        self.logger.debug('Using Marvin Deploy Data Center class: %s' % (ddcCls))

        ddcArgs = inspect.getargspec(ddcCls.__init__).args
        self.logger.debug('Marvin Deploy Data Center class has constructor args: %s' % (ddcArgs))

        if len(ddcArgs) == 2:
            # This early version of Marvin only take a config file argument (self is the second argument)
            # Create temp directory
            tempDir = os.path.join('/tmp', 'marvin' + ''.join([random.choice(string.ascii_letters + string.digits) for n in xrange(12)]))
            if not os.path.exists(tempDir):
                os.makedirs(tempDir)
            else:
                raise MarvinDeployException('tempDir: %s - already exists' % (tempDir))

            self.marvinCfg['logger'] = [ {'name': 'TestClient', 'file': os.path.join(tempDir, 'testclient.log') },
                                         {'name': 'TestCase',   'file': os.path.join(tempDir, 'testcase.log')   } ]
            fn = os.path.join(tempDir, 'marvin.cfg')
            self.logger.debug('Writing config to file: %s' % (fn))
            self.outputAsJSONFile(fn)
            marvinDeployer = ddcCls(fn)
            # TODO - consider writing log file output to self.logger
        elif not 'test_client' in ddcArgs:
            # This version (circa 4.2 / 4.3) takes config and logger arguments
            marvinDeployer = ddcCls(cfg, logger=self.logger)
        else:
            marvinDeployer = ddcCls(test_client=self.__marvinTestClient, cfg=cfg, logger=self.logger)

        # Disable the automatic cleanup on failure that was introduced with Marvin 4.4
        try:
            from marvin.config.test_data import test_data
            if test_data.has_key('deleteDC'):
                test_data['deleteDC'] = False
        except ImportError:
            pass

        try:
            marvinDeployer.deploy()
        except SystemExit, e:
            # Some versions of Marvin report a failure by calling sys.exit(1) rather than raising an exception, fix this...
            raise MarvinDeployException("Marvin Deploy Data Center failed with exit code %s" % (e.code))

