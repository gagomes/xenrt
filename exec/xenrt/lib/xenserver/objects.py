import re
import xenrt
from xenrt.lazylog import log

"""
Xapi object model base and factory classes
"""
__all__ = ['XapiObject', 'VM', 'VBD', 'XapiHost', 'SR', 'VDI', 'PBD', 'Snapshot']


class XapiObject(object):
    """
    XapiObject base class containing commandline commands to execute
    This class should remain generic
    """
    _OBJECT_TYPE = "XapiObject"

    def __init__(self, cli, uuid):
        self.uuid = uuid
        self.cli = cli

    def _getStringParam(self, paramName):
        """
        @var paramName: the name of a parameter to fetch from the xapidb
        @type paramName: string
        @return: the requested param value
        @rtype string
        """
        return self.cli.execute("%s-param-get uuid=%s param-name=%s" % (self._OBJECT_TYPE, self.uuid, paramName)).strip()

    def _getIntParam(self, paramName):
        """
        @var paramName: the name of a parameter to fetch from the xapidb
        @type paramName: string
        @return: the requested param value
        @rtype int
        """
        return int(self._getStringParam(paramName))

    def _getListParam(self, paramName, delimiter=';'):
        """
        Get the params from xapi, in the form of a list of strings - useful for composite fields

        @var paramName: the name of a parameter to fetch from the xapidb
        @type paramName: string
        @var delimiter: how the resulting array is delimeted by xapi
        @type delimiter: char
        @return: the requested param value
        @rtype list
        """
        return self.cli.execute("%s-param-get uuid=%s param-name=%s" % (self._OBJECT_TYPE, self.uuid, paramName )).strip().split(delimiter)

    def _getDictParam(self, paramName, listDelimiter=';', keyDelimiter=':'):
        """
        Get the params from xapi, in the form of a dictionary of strings - useful for composite fields

        @var paramName: the name of a parameter to fetch from the xapidb
        @type paramName: string
        @var listDelimiter: how the resulting array is delimited by xapi
        @type listDelimiter: char
        @var keyDelimiter: how the resulting array values are delimited by xapi
        @type keyDelimiter: char
        @return: the requested param values
        @rtype dictionary of strings
        """
        params = {}
        listParams = self._getListParam(paramName, listDelimiter)

        if not listParams or len(listParams) < 1:
            return params

        for p in listParams:
            pair = p.split(keyDelimiter, 1)
            params[pair[0].strip()] = pair[1].strip()
        return params

    def _getObjectParam(self, objType, paramName):
        """
        Get object-model form of a field referenced by the current object. For example if an object contains
        a ref to another object

        eg. for a vdi type: and sr class can be obtained by: sr = vdi._getObjectParam("sr", "sr-uuid")

        @var objType: the objects type to look up in the factory
        @type objType: string
        @var paramName: the parameter that provides the uuid of the target type
        @type paramName: string
        @return: the requested object derived from XapiObject
        @rtype class
        """
        uuid = self.cli.execute("%s-param-get uuid=%s param-name=%s" % (self._OBJECT_TYPE, self.uuid, paramName)).strip()
        return uuid

    def _getObjectsReferencing(self, refObjectType, currentObjectType=None):
        """
        Get objects that reference the current object
        @var refObjectType: the type to look up
        @type refObjectType:  string
        @var currentObjectType: how the resulting array is refered to
        @type delimiter: string
        @return XapiObjects represented the objects that reference the current object
        @rtype list of XapiObjects
        """
        if currentObjectType:
            uuids = self.cli.execute("%s-list %s-uuid=%s --minimal" % (refObjectType, currentObjectType, self.uuid)).strip().split(',')
        else:
            uuids = self.cli.execute("%s-list --minimal" % refObjectType).strip().split(',')
        return [uuid for uuid in uuids if uuid != '']

    def _getObjectsFromListing(self, refObjectType):
        uuids = self.cli.execute("%s-list --minimal" % refObjectType).strip().split(',')
        return [uuid for uuid in uuids if uuid != '']

    def _op(self, operation, params=""):
        return self.cli.execute("%s-%s uuid=%s %s" % (self._OBJECT_TYPE, operation, self.uuid, params)).strip()

    def __repr__(self):
        return ';'.join([self._OBJECT_TYPE, self.uuid])

    def __hash__(self):
        return hash(self.__repr__())

    def __eq__(self, other):
        return self.uuid == other.uuid

    def __ne__(self, other):
        return self.uuid != other.uuid


    #Setter could be implemented like so....
    #def setParam(paramName, value): etc...


class NamedXapiObject(XapiObject):
    __NAME = "name-label"

    @property
    def name(self):
        return self._getStringParam(self.__NAME)

    def _getObjectsReferencingName(self, refObjectType, currentObjectType):
        uuids = self.cli.execute("%s-list %s=%s --minimal" % (refObjectType, currentObjectType, self.name)).strip().split(',')
        return [uuid for uuid in uuids if uuid != '']

"""
Additional class implementations
NB: Don't forget to register any new implementations with the object factory
"""


class VM(NamedXapiObject):
    _OBJECT_TYPE = "vm"
    __NETWORK_ADDRESSES = "networks"
    __CPU_USAGE = "VCPUs-utilisation"
    __RESIDENT = "resident-on"

    @xenrt.irregularName
    @property
    def VBDs(self):
        return [VBD(self.cli, uuid) for uuid in self._getObjectsReferencing(VBD._OBJECT_TYPE, self._OBJECT_TYPE)]

    @xenrt.irregularName
    @property
    def VDIs(self):
        return [vbd.VDI for vbd in self.VBDs]

    @property
    def networkAddresses(self):
        return self._getListParam(self.__NETWORK_ADDRESSES)

    def ipv6NetworkAddress(self, deviceNo=0, ipNo=0):
        addresses = self.networkAddresses
        tag = str(deviceNo) + "/ipv6/" + str(ipNo)
        log("Addresses found: %s" % str(addresses))
        ipv6Address = next((n for n in addresses if tag in n), None)
        log("IPV6 address %s found with ID: %s" % (ipv6Address, tag))
        if ipv6Address:
            ipv6Address = (':'.join(ipv6Address.split(':')[1:])).strip()
            return ipv6Address
        else:
            log("No IPV6 guest found for guest %s" % self.name)
            return None

    @xenrt.irregularName
    @property
    def XapiHost(self):
        return XapiHost(self.cli, self._getObjectParam(XapiHost._OBJECT_TYPE, self.__RESIDENT))

    @xenrt.irregularName
    @property
    def SR(self):
        return list(set([v.SR for v in self.VDIs]))

    @property
    def cpuUsage(self):
        return self._getDictParam(self.__CPU_USAGE)

    def snapshot(self):
        snaps = [Snapshot(self.cli, uuid) for uuid in self._getObjectsFromListing(Snapshot._OBJECT_TYPE)]
        return [s for s in snaps if s.VM.uuid == self.uuid]


class VBD(XapiObject):
    _OBJECT_TYPE = "vbd"
    __VM_UUID = "vm-uuid"
    __VDI_UUID = "vdi-uuid"
    __OPS = "allowed-operations"

    @xenrt.irregularName
    @property
    def VM(self):
        return VM(self.cli, self._getObjectParam(VM._OBJECT_TYPE, self.__VM_UUID))

    @property
    def allowedOperations(self):
        return self._getListParam(self.__OPS)

    @xenrt.irregularName
    @property
    def VDI(self):
        return VDI(self.cli, self._getObjectParam(VDI._OBJECT_TYPE, self.__VDI_UUID))

    @property
    def device(self):
        return self._getStringParam("device")

    def plug(self):
        self._op("plug")

    def unPlug(self):
        self._op("unplug")

    def destroy(self):
        self._op("destroy")


class XapiHost(NamedXapiObject):
    _OBJECT_TYPE = "host"

    @xenrt.irregularName
    @property
    def SRs(self):
        return [SR(self.cli, uuid) for uuid in self._getObjectsReferencing(SR._OBJECT_TYPE)]

    @property
    def localSRs(self):
        return [SR(self.cli, uuid) for uuid in self._getObjectsReferencingName(SR._OBJECT_TYPE, self._OBJECT_TYPE)]


class PBD(XapiObject):
    _OBJECT_TYPE = "pbd"

    @property
    def deviceConfig(self):
        return self._getDictParam("device-config")

    @property
    def host(self):
        return XapiHost(self.cli, self._getObjectParam(XapiHost._OBJECT_TYPE, "host-uuid"))


class SR(NamedXapiObject):
    _OBJECT_TYPE = "sr"
    __LOCAL = "Local storage"
    __TYPE = "type"

    @property
    def isLocalStorage(self):
        return re.search(self.__LOCAL, self.name)

    @property
    def srType(self):
        return self._getStringParam(self.__TYPE)

    @xenrt.irregularName
    @property
    def VDIs(self):
        return [VDI(self.cli, uuid) for uuid in self._getObjectsReferencing(VDI._OBJECT_TYPE, self._OBJECT_TYPE)]

    @xenrt.irregularName
    @property
    def PBDs(self):
        return [PBD(self.cli, uuid) for uuid in self._getObjectsReferencing(PBD._OBJECT_TYPE, self._OBJECT_TYPE)]

    @property
    def otherConfig(self):
        return self._getStringParam("other-config")

    @property
    def contentType(self):
        return self._getStringParam("content-type")

    @property
    def smConfig(self):
        return self._getStringParam("sm-config")

    @property
    def physicalSize(self):
        return self._getIntParam("physical-size")

    @property
    def virtualAllocation(self):
        return self._getIntParam("virtual-allocation")

    @property
    def physicalUtilisation(self):
        return self._getIntParam("physical-utilisation")


class VDI(NamedXapiObject):
    _OBJECT_TYPE = "vdi"
    __SR_UUID = "sr-uuid"
    __RC = "sm-config param-key=read-caching-enabled-on-%s"

    @xenrt.irregularName
    @property
    def SR(self):
        return SR(self.cli, self._getObjectParam(SR._OBJECT_TYPE, self.__SR_UUID))

    def snapshot(self):
        return VDI(self.cli, self._op("snapshot"))

    @property
    def isASnapshot(self):
        return self._getStringParam("is-a-snapshot") == "true"

    def readcachingEnabled(self, xapiHost):
        return self._getStringParam(self.__RC % xapiHost.uuid) == "true"

    @property
    def size(self):
        return self._getIntParam("virtual-size")

    def copy(self, params):
        return VDI(self.cli, self._op("copy", params))


class Snapshot(NamedXapiObject):
    _OBJECT_TYPE = "snapshot"

    def delete(self, metadataOnly=False):
        if metadataOnly:
            self._op("destroy")
        else:
            self._op("uninstall", "force=true")

    @xenrt.irregularName
    @property
    def VM(self):
        return VM(self.cli, self._op("list", "params=snapshot-of --minimal"))
