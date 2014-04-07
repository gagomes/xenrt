
import pprint
import json
from marvin import deployDataCenter
from marvin import jsonHelper

class MarvinDeployException(Exception):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return repr(self.value)

class MarvinDeployer(object):
    CONFIG_SCHEMA = {
                      'config': {
                        'abstractName': 'Config',
                        'required': { 'zones': None } },
                      'zones': {
                        'abstractName': 'Zone',
                        'required': { 'name': 'getName', 'networktype': None, 'dns1': 'getDNS', 'internaldns1': 'getDNS', 'secondaryStorages': None, 'physical_networks': None },
                        'defaults': { 'physical_networks': [ { } ], 'secondaryStorages': [ { } ] },
                        'notify'  : { 'name': 'notifyNewElement' } },
                      'secondaryStorages': {
                        'abstractName': 'SecondaryStorage',
                        'required': { 'url': 'getSecondaryStorageUrl', 'provider': 'getSecondaryStorageProvider' } },
                      'physical_networks': {
                        'abstractName': 'PhysicalNetwork',
                        'required': { 'name': None, 'traffictypes': None, 'providers': None, 'broadcastdomainrange': None, },
                        'defaults': { 'traffictypes': [ { 'typ': 'Guest' }, { 'typ': 'Management' } ],
                                      'providers': [ { 'name': 'VirtualRouter', 'broadcastdomainrange': 'ZONE' }, { 'name': 'SecurityGroupProvider', 'broadcastdomainrange': 'Pod' } ],
                                      'broadcastdomainrange': 'Zone' },
                        'notify'  : { 'traffictypes': 'notifyNetworkTrafficTypes' } },
                      'traffictypes': {
                        'abstractName': 'TrafficType',
                        'required': { 'typ': None } },
                      'providers': {
                        'abstractName': 'NetworkProviders',
                        'required': { 'name': None, 'broadcastdomainrange': None } },
                      'ipranges': {
                        'abstractName': 'IPRange',
                        'required': { 'startip': 'getIPRangeStartAddr', 'endip': 'getIPRangeEndAddr', 'gateway': 'getGateway', 'netmask': 'getNetmask' } },
                      'guestIpRanges': {
                        'abstractName': 'GuestIPRange',
                        'required': { 'startip': 'getGuestIPRangeStartAddr', 'endip': 'getGuestIPRangeEndAddr', 'gateway': 'getGateway', 'netmask': 'getNetmask' } },
                      'pods': {
                        'abstractName': 'Pod',
                        'required': { 'name': 'getName', 'startip': 'getPodIPStartAddr', 'endip': 'getPodIPEndAddr', 'gateway': 'getGateway', 'netmask': 'getNetmask' },
                        'notify'  : { 'name': 'notifyNewElement' } },
                      'clusters': {
                        'abstractName': 'Cluster',
                        'required': { 'clustername': 'getName', 'hypervisor': 'getHypervisorType', 'clustertype': None, 'primaryStorages': None, 'hosts': 'getHostsForCluster' },
                        'defaults': { 'primaryStorages': [ { } ], 'clustertype': 'CloudManaged' },
                        'notify'  : { 'clustername': 'notifyNewElement' } },
                      'primaryStorages': {
                        'abstractName': 'PrimaryStorage',
                        'required': { 'name': 'getPrimaryStorageName', 'url': 'getPrimaryStorageUrl', } },
                      'hosts': {
                        'abstractName': 'Host',
                        'required': { 'url': 'getHostUrl', 'username': 'getHostUsername', 'password': 'getHostPassword' },
                        'notify'  : { 'url': 'notifyNewElement' } },
                    }

    def __init__(self, mgmtServerIp, logger):
        self.marvinCfg = {}
        self.marvinCfg['dbSvr'] = {}
        self.marvinCfg['dbSvr']['dbSvr'] = mgmtServerIp
        self.marvinCfg['dbSvr']['passwd'] = 'cloud'
        self.marvinCfg['dbSvr']['db'] = 'cloud'
        self.marvinCfg['dbSvr']['port'] = 3306
        self.marvinCfg['dbSvr']['user'] = 'cloud'

        self.marvinCfg['mgtSvr'] = []
        self.marvinCfg['mgtSvr'].append({ 'mgtSvrIp': mgmtServerIp,
                                          'port'    : 8096 })

        self.marvinCfg['zones'] = []
        self.logger = logger

    def outputAsJSONFile(self, filename):
        fh = open(filename, 'w')
        json.dump(self.marvinCfg, fh)
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
                        value = self.CONFIG_SCHEMA[elementKey]['defaults'][requiredField]
                    else:
                        raise MarvinDeployException('No value avaialble for required field [%s - %s]' % (elementKey, requiredField))

                elementRef[requiredField] = value

    def _notifyFieldsForConfigDictElement(self, elementRef, elementKey, deployer):
        for notifyField in self.CONFIG_SCHEMA[elementKey]['notify']:
            if hasattr(deployer, self.CONFIG_SCHEMA[elementKey]['notify'][notifyField]):
                getattr(deployer, self.CONFIG_SCHEMA[elementKey]['notify'][notifyField])(self.CONFIG_SCHEMA[elementKey]['abstractName'], elementRef[notifyField])

    def _processConfigElement(self, element, parentName, deployer):
        if isinstance(element, list):
            map(lambda x:self._processConfigElement(x, parentName, deployer), element)
        elif isinstance(element, dict):
            if self.CONFIG_SCHEMA[parentName].has_key('required'):
                self._checkRequiredFieldsForConfigDictElement(element, parentName, deployer)
            if self.CONFIG_SCHEMA[parentName].has_key('notify'):
                self._notifyFieldsForConfigDictElement(element, parentName, deployer)
            for key, value in element.items():
                self._processConfigElement(value, key, deployer)

    def generateMarvinConfig(self, config, deployer):
        self.logger.debug("Original Config:\n" + pprint.pformat(config))
        self._processConfigElement(config, 'config', deployer)
        self.logger.debug("New Config:\n" + pprint.pformat(config))
        self.marvinCfg.update(config)
        self.logger.debug("Full Marvin Config:\n" + pprint.pformat(self.marvinCfg))

    def deployMarvinConfig(self):
        cfg = jsonHelper.jsonLoader(self.marvinCfg)
        marvinDeployer = deployDataCenter.deployDataCenters(cfg, self.logger)
        marvinDeployer.deploy()
