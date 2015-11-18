# XenRT: Test harness for Xen and the XenServer product family
#
# Abstract classes representing storage objects that we can manipulate
#
# Copyright (c) 20012 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.

import sys, string, time, socket, re, os.path, os, shutil, random, sets, math
import xenrt, xenrt.ssh, xenrt.util, xenrt.rootops, xenrt.resources
from abc import ABCMeta, abstractmethod
try:
    import NaServer # NetApp filer administration SDK library.
except:
    sys.stderr.write("Error importing NetApp SDK, NetApp functionality will be unavailable\n")
    sys.stderr.flush()

__all__ = ["StorageArrayFactory", "StorageArrayType", "StorageArrayVendor",
            "StorageArrayContainer", "StorageArrayInitiatorGroup",
            "StorageArrayLun", "StorageArray",
            "NetAppFCStorageArray", "NetAppFCInitiatorGroup", 
            "NetAppISCSIStorageArray", "NetAppISCSIInitiatorGroup", 
            "NetAppLunContainer", "NetAppLun", "NetAppFCLun", "NetAppISCSILun" ]

"""
Factory class for storage array
"""

class StorageArrayVendor(object):
    NetApp, Clariion, PowerVault = range(3)

class StorageArrayType(object):
    FibreChannel, iSCSI = range(2)

class StorageArrayFactory(object):
    """
    Factory class to provide storage arrays
    """
    def getStorageArray(self, vendor, storageType, specify=None):
        """
        Get the required storage array 
        eg: array = StorageArrayFactory().getStorageArray(StorageArrayVendor.NetApp, StorageArrayType.FibreChannel)
        
        @type vendor: one of the StorageArrayVendor
        @param vendor: the required vendor
        @type storageType: one of the StorageArrayTypes
        @param storageType: the required storage type
        """
        if vendor ==  StorageArrayVendor.NetApp and storageType == StorageArrayType.FibreChannel:
            return NetAppFCStorageArray(specify=specify)
        if vendor ==  StorageArrayVendor.NetApp and storageType == StorageArrayType.iSCSI:
            return NetAppISCSIStorageArray(specify=specify)

        raise xenrt.XRTError("There is no implementation for a storage array of this type and vendor" )

"""
Storage array base classes
"""

class StorageElementStatus(object):
    """
    Class to hold the status of a call to the underlying storage array
    """
    inError = False
    errorNumber = 0
    errorReason = None

class StorageElement(object):
    __JOB_HDR = "XENRT_JOB"
    __DEFAULT_JOB_NAME = "UNKNOWN"

    """Base class for storage array elements"""
    def _generateRandomName(self, seedName):
        """
        @type seedName : string
        @param seedName : something to prepend the random additional characters
        @rtype: string
        @return: a randomised name
        """

        jobId = None

        try:
            jobId = str(xenrt.GEC().jobid())
        except: pass 

        if jobId == None:
            jobId = self.__DEFAULT_JOB_NAME

        prefixedName = "_".join([self.__JOB_HDR, jobId, seedName])

        return "%s_%08x" % (prefixedName, (random.randint(0, 0x7fffffff)))

    def _raiseApiFailure(self, elementStatus, verbose, warning=False, ignoreError = False):
        """
        A common storage error reporting function.
        @type elementStatus: StorageElementStatus
        @param elementStatus: elementStatus the status of a given call
        @type verbose : string
        @param verbose: verbose message
        @type warning: bool 
        @param warning: write verbose message as a warning 
        """
        if (not elementStatus.inError):
            if warning:
                xenrt.TEC().warning(verbose)
            else:
                xenrt.TEC().logverbose(verbose)
        else:
            errorString = "Error: %s - %s" % (elementStatus.errorNumber, elementStatus.errorReason)
            if ignoreError:
                xenrt.TEC().logverbose(errorString)
            else:
                raise xenrt.XRTError(errorString)
    
    def _bestEffort(self, fnPointer, *args):
        try:
            if len(*args) < 1: 
                output = fnPointer()
            else:
                output = fnPointer(*args)
            return (True, output)
        except Exception as err:
            xenrt.TEC().logverbose("Best effort failed, ignoring failure: %s" % str(err))
            return (False, None)

"""
(Abstract) base classes
"""

class StorageArrayContainer(StorageElement):
    __metaclass__ = ABCMeta
    @abstractmethod
    def name(self): pass

    @abstractmethod
    def create(self): pass

    @abstractmethod
    def destroy(self, force): pass

    def __str__(self):
        return self.name()

class StorageArrayInitiatorGroup(StorageElement):
    __metaclass__ = ABCMeta
    @abstractmethod
    def name(self): pass

    @abstractmethod
    def create(self): pass

    @abstractmethod
    def list(self, initiatorGroupName): pass

    @abstractmethod
    def destroy(self, force): pass

    @abstractmethod
    def add(self, initiator, initiatorGroupName, force): pass

    @abstractmethod
    def remove(self, initiator, initiatorGroupName, force): pass

    def __str__(self):
        return self.name()

class StorageArrayLun(StorageElement):
    __metaclass__ = ABCMeta

    class ShareState: All, NotSet, Read, Unknown = range(4)

    @abstractmethod
    def create(self, path, sizeMB, thinlyProvisioned) : pass

    @abstractmethod
    def destroy(self, force): pass

    @abstractmethod
    def getID(self): pass

    @abstractmethod
    def map(self, initiatorGroup, force): pass

    @abstractmethod
    def unmap(self, initiatorGroup): pass

    @abstractmethod
    def list(self): pass

    @abstractmethod
    def resize(self, sizeMB, force): pass

    @abstractmethod
    def isMapped(self): pass

    @abstractmethod
    def isOnline(self): pass

    @abstractmethod
    def sharedState(self): pass

    @abstractmethod
    def size(self): pass

    def __str__(self):
        return self.getID()

class StorageArray(xenrt.resources.CentralResource):
    __metaclass__ = ABCMeta

    def __init__(self):
        super(StorageArray, self).__init__()
        self._container = None
        self._initiatorGroup = None
        self._luns = []
        self.__thinlyProvisioned = True
        self.__released = False

    def __bestEffort(self, fnPointer, *args):
        try:
            fnPointer(*args)
            return True
        except Exception as err:
            xenrt.TEC().logverbose("Best effort failed, ignoring failure: %s" % str(err))
            return False

    def getLuns(self):
        """
        Get the provisioned luns of the storage array

        @rtype: List of StorageArrayLun
        @return: Luns that have been provisioned on this storage array
        """
        return self._luns

    def destroyLun(self, lunId):
        xenrt.TEC().logverbose("Looking for LUN %s in %s" % (lunId, str(self._luns)))
        targetLun = None
        try:
            targetLun = next(lun for lun in self._luns if lun.getID() == lunId)
        except: 
            pass

        if targetLun:
            self.__destroySingleLun(targetLun)
            self._luns.remove(targetLun)
        else:
            xenrt.TEC().logverbose("Could not destroy LUN %s" % lunId)

    @property
    def thinlyProvisioned(self):
        return self.__thinlyProvisioned

    @thinlyProvisioned.setter
    def thinlyProvisioned(self, value):
        self.__thinlyProvisioned = value

    @abstractmethod
    def provisionLuns(self, numberofLuns, lunSizeGb, hostInitiators) : pass

    def createContainer(self):
        if self._container != None:
            self._container.create()

    def destroyContainer(self):
        xenrt.TEC().logverbose("Destroying container %s" % self._container.name())
        if self._container:
            if not self.__bestEffort(self._container.destroy, False):
                self.__bestEffort(self._container.destroy, True)
        self._container = None

    def destroyInitiator(self):
        xenrt.TEC().logverbose("Destroying initiator group %s" % self._initiatorGroup.name())
        if self._initiatorGroup:
            if not self.__bestEffort(self._initiatorGroup.destroy, False):
                self.__bestEffort(self._initiatorGroup.destroy, True)
        self._initiatorGroup = None

    def __destroySingleLun(self, lun):
        xenrt.TEC().logverbose("Unmap LUN %s" % lun.getID())
        self.__bestEffort(lun.unmap, self._initiatorGroup)
        xenrt.TEC().logverbose("Destroying LUN %s" % lun.getID())
        if not self.__bestEffort(lun.destroy, False):
            xenrt.TEC().logverbose("Gentle destroy failed - forcing destroy for LUN %s" % lun.getID())
            self.__bestEffort(lun.destroy, True)    

    def destroyLuns(self):
        xenrt.TEC().logverbose("Attempting to remove %s LUNs..." % len(self._luns))
        for lun in self._luns:
            self.__bestEffort(self.__destroySingleLun, lun)
        self._luns = [] 

    def release(self, atExit=False):
        """
        Required abstract implementation from the super class
        """
        xenrt.TEC().logverbose("Cleaning netApp volume and igroup ...")
        
        if self.__released:
            xenrt.TEC().logverbose("NetApp volume and igroup already released, skipping....")
            return

        self.destroyLuns()  
        self.destroyContainer()
        self.destroyInitiator()
        self.__released = True

"""
NetApp specific concrete implementations for NetApp Fibre Channel Storage Array
"""

class NetAppStatus(StorageElementStatus):
    """
    Strategy class encapsulating for the NetApp API result
    """
    def __init__(self, naResult):
        """
        @type naResult: lib.NaElement.NaElement 
        @param naResult: result from a netapp request
        """
        super(NetAppStatus, self).__init__()
        self.inError = naResult.results_status() != 'passed'
        self.errorNumber = naResult.results_errno()
        self.errorReason = naResult.results_reason()

class NetAppStorageArray(StorageArray):
    """
    Strategy class encapsulating for the NetApp Fibre Channel storage array
    """
    __PATH_NAME = "/vol"

    def __init__(self, specify=None):
        super(NetAppStorageArray, self).__init__()
        self.__targetArray = self.targetClass(specify=specify)
        self.__setupServer(self.__targetArray.getTarget(), self.__targetArray.getUsername(), self.__targetArray.getPassword())
        self.createContainer()
        self._setupInitiatorGroup()

    def __setupServer(self, targetIP, username, password):
        self._server = NaServer.NaServer(targetIP, 1, 0)
        self._server.set_admin_user(username, password)

    def createContainer(self):
        if(self._container != None):
            xenrt.TEC().logverbose("Container already exists so skipping creation, to recreate please destroy the existing one first")
            return

        aggr = self.__targetArray.getAggr()
        size = self.__targetArray.getSize()
        self._container = NetAppLunContainer(self._server, aggr, size)
        super(NetAppStorageArray, self).createContainer()

    def __checkInitiatorConfiguredElseWhere(self, wwpnList):
        """This function checks whether the host WWWPN is added to any other iGroup."""

        # By doing restricting to a single iGroup of the test will prevent luns from listing.
        initiatorDict = self._initiatorGroup.list() # dict with list of { 'igroup': [intitiator list]}.

        for initiatorGroupName in initiatorDict.keys():
            for initiator in initiatorDict[initiatorGroupName]:
                if initiator in wwpnList:
                    self._initiatorGroup.remove(initiator, True)

    def provisionLuns(self, numberofLuns, lunSizeGb, hostInitiators):
        """
        Provision required luns for the storage array
        @type numberofLuns: int
        @param numberofLuns: number of luns required
        @type lunSizeGb: int
        @param lunSizeGb: required lun size
        @type hostInitiators : dictionary
        @param hostInitiators : dictionary of FCWWPNs keyed off IP address, eg. : 
        initiatorList = {}
        initiatorList[self.getDefaultHost().getIP()] = self.getDefaultHost().getFCWWPNInfo()
        @rtype: List
        @return: List of Ids of the luns just provisioned
        """
        # Check, if the host is configured elsewhere.
        newLunIds = []

        for hostip in hostInitiators.keys():
            self.__checkInitiatorConfiguredElseWhere(hostInitiators[hostip].values()) # passing a list of wwpn of the host.

        # Create a new volume.
        randomStr = self.LUN_PATH + "_" + ''.join(random.choice(string.ascii_uppercase + string.digits) for x in range(5))
        partialLunPath = ("%s/%s/%s") % (self.__PATH_NAME, self._container.name(), randomStr)

        for count in range(numberofLuns):
            lunSizeMB = 1024 * lunSizeGb
            lunPath = ("%s%d") % (partialLunPath, count)
            newLun = self.lunClass(self._server, lunPath, lunSizeMB, self.thinlyProvisioned)
            self._luns.append(newLun)
            newLunIds.append(newLun.getID())

        # Add WWPN as initiators to iGroup.
        for hostip in hostInitiators.keys():
            for initiator in hostInitiators[hostip].values():
                self._initiatorGroup.add(initiator, False)

        xenrt.TEC().logverbose("Number of LUNs to map: %d" % len(self._luns))
        for lun in filter(lambda l : not l.isMapped(), self._luns):
            xenrt.TEC().logverbose("Attempting map of %s with init %s" % (lun.getID(), self._initiatorGroup.name()))
            try:
                lun.map(self._initiatorGroup.name(), False)
            except: pass

        return newLunIds

    def release(self, atExit=False):
        self.__targetArray.release(atExit=atExit)
        super(NetAppStorageArray, self).release(atExit=atExit)

class NetAppFCStorageArray(NetAppStorageArray):
    LUN_PATH = "fclun"
    
    def __init__(self, specify=None):
        self.targetClass = xenrt.FCHBATarget
        self.lunClass = NetAppFCLun
        super(NetAppFCStorageArray, self).__init__(specify=specify)
        
    def _setupInitiatorGroup(self):
        self._initiatorGroup = NetAppFCInitiatorGroup(self._server)
        self._initiatorGroup.create()

class NetAppISCSIStorageArray(NetAppStorageArray):
    LUN_PATH = "iscsilun"
    
    def __init__(self, specify=None):
        self.targetClass = xenrt.NetAppTarget
        self.lunClass = NetAppISCSILun
        super(NetAppISCSIStorageArray, self).__init__(specify=specify)
        
    def _setupInitiatorGroup(self):
        self._initiatorGroup = NetAppISCSIInitiatorGroup(self._server)
        self._initiatorGroup.create()

class NetAppInitiatorGroupCommunicator(object):
    
    def parseListMessage(self, toParse):
        """
        Parse a listing of initiator groups from the NetApp listing
        @param toParse: The data from the NetApp
        @return: a collection of initiator names and igroups they belong to
        @rtype: dictionary of string, list
        """
        iGroupInfo = toParse.child_get('initiator-groups')

        initiatorDict = {} # dict of initiators {'initiator-group-name' : [initiators]}
        if iGroupInfo.children_get(): # if there is a iGroup
            for iGroup in iGroupInfo.children_get():
                iGroupType = iGroup.child_get_string('initiator-group-type')
                if (iGroupType == "fcp"):
                    iGroupName, data = self.__extractFcpInitiators(iGroup)
                    initiatorDict[iGroupName] = data
                    
        else:
            xenrt.TEC().logverbose("No iGroups exist in the storage array.")

        return initiatorDict

    def __extractFcpInitiators(self, iGroup):
        iGroupName = iGroup.child_get_string('initiator-group-name')
        data = []
        initiatorList = iGroup.child_get('initiators')
        if initiatorList.children_get(): # if there is a initiator
            for initiator in initiatorList.children_get():
                data.append(initiator.child_get_string('initiator-name'))
        else:
            xenrt.TEC().logverbose("No initiators added in this iGroup %s" % iGroupName)
        return iGroupName, data
            

class NetAppInitiatorGroup(StorageElement):
    """
    Strategy class encapsulating for the NetApp Fibre Channel initiator group aka. iGroup
    """
    __OS_TYPE = "linux"
    __name = "all"

    def __init__(self, server):
        super(NetAppInitiatorGroup, self).__init__()
        self._server = server

    def create(self):
        """Creates a new initiator group."""
        initiatorGroupName = self._generateRandomName(self.SEED_IGROUP_NAME)

        results = self._server.invoke('igroup-create', 'initiator-group-name', initiatorGroupName, 
                                        'initiator-group-type', self.PROTOCOL, 'os-type', self.__OS_TYPE)

        verbose = "An initiator group %s is created." % initiatorGroupName
        self._raiseApiFailure(NetAppStatus(results), verbose)
        self.__name = initiatorGroupName

    def name(self):
        return self.__name

    def list(self):
        """
        Get information for initiator group(s).
        @rtype: Dictionary 
        @return: Initiator groups, keyed on iGroup name. If initiatorGroupName is not specified, information for all inititor groups are returned
        """
        if self.__name:
            results = self._server.invoke('igroup-list-info', 'initiator-group-name', self.__name)
        else:
            self.__name = "all"
            results = self._server.invoke('igroup-list-info')

        verbose = "Listing initiators in %s group." % self.__name
        self._raiseApiFailure(NetAppStatus(results), verbose)

        comm = NetAppInitiatorGroupCommunicator()
        return comm.parseListMessage(results)

    def destroy(self, force):
        """Destroys an existing initiator group."""
        # By default a group cannot be destroyed if there are existing lun maps defined for that group. 
        # This behaviour can be overridden with the use of force option.

        results = self._server.invoke('igroup-destroy', 'initiator-group-name', self.__name, 'force', force)

        verbose = "An initiator group %s is destroyed." % self.__name
        self._raiseApiFailure(NetAppStatus(results), verbose)

    def add(self, initiator, force):
        """Adds initiator to an existing initiator group."""
        # force  (Boolean) [optional] = Forcibly add the initiator, disabling mapping and type conflict checks.
        # initiator (String) = WWPN or Alias of Initiator to add.
        results = self._server.invoke('igroup-add', 'initiator', initiator, 'initiator-group-name', self.__name, 'force', force)

        verbose = "An initiator %s is added to initiator group %s." % (initiator, self.__name)
        self._raiseApiFailure(NetAppStatus(results), verbose)

    def remove(self, initiator, force):
        """Removes node(s) from an initiator group."""
        # force  (Boolean) [optional] = Forcibly remove the initiator even if there are existing LUNs mapped to this initiator group
        # initiator (String) = WWPN or Alias of Initiator to add.
        results = self._server.invoke('igroup-remove', 'initiator', initiator, 'initiator-group-name', self.__name, 'force', force)

        verbose = "An initiator %s is removed from the initiator group %s." % (initiator, self.__name)
        self._raiseApiFailure(NetAppStatus(results), verbose)

class NetAppFCInitiatorGroup(NetAppInitiatorGroup):
    SEED_IGROUP_NAME = "NET_APP_FC_IGROUP"
    PROTOCOL = "fcp"

class NetAppISCSIInitiatorGroup(NetAppInitiatorGroup):
    SEED_IGROUP_NAME = "NET_APP_ISCSI_IGROUP"
    PROTOCOL = "iscsi"

class NetAppLunContainer(StorageArrayContainer):
    """
    Strategy class encapsulating for the NetApp Fibre Channel container group aka. Volume
    """
    __SEED_VOL_NAME="NET_APP_VOLUME"
    __name = None

    def __init__(self, server, aggregate, size):
        self._server = server
        self.__aggregate = aggregate
        self.__size = size   

    def create(self):
        # Invoke ONTAP SDK API to create NetApp volume.
        # Make sure the volume does not reserve space. but how?
        self.__name = self._generateRandomName(self.__SEED_VOL_NAME)
        results = self._server.invoke('volume-create',
                                        'containing-aggr-name', self.__aggregate,
                                        'size', ("%sg" % self.__size),
                                        'volume', self.__name,
                                        'space-reserve', 'file')
        verbose = "A NetApp Volume %s of size %sGB is created." % (self.__name, self.__size)
        self._raiseApiFailure(NetAppStatus(results), verbose)
        results = self._server.invoke('snapshot-set-reserve',
                                        'percentage', 0,
                                        'volume', self.__name)
        verbose = "Volume %s snapshot reserve set to 0." % (self.__name)
        self._raiseApiFailure(NetAppStatus(results), verbose)

        return self.__name

    def name(self):
        return self.__name

    def destroy(self, force):
        # The ONTAP SDK API does not support to delete infinite volumes.
        # In case if it supported, we do not want to implement here. 
        # Make sure this is added to the job cleanup (see callback)
        results = self._server.invoke('volume-offline', 'name', self.__name)

        verbose = "The specified volume %s is being taken offline before destroying it." % self.__name
        self._raiseApiFailure(NetAppStatus(results), verbose)

        results = self._server.invoke('volume-destroy', 'name', self.__name, 'force', force)

        verbose = "The specified volume %s is destroyed." % self.__name
        self._raiseApiFailure(NetAppStatus(results), verbose)
    
class NetAppLun(StorageArrayLun):
    """
    Strategy class encapsulating for the NetApp LUN
    """
    __OS_TYPE = "linux"
    _server = None
    __path = None

    def __init__(self, server, path, sizeMB, thinlyProvisioned):
        self._server = server
        self.create(path, sizeMB, thinlyProvisioned)

    def create(self, path, sizeMB, thinlyProvisioned):
        self.__path = path
        results = self._server.invoke('lun-create-by-size',
                                        'ostype', self.__OS_TYPE, 
                                        'path', self.__path,
                                        'size', sizeMB * xenrt.MEGA,
                                        'space-reservation-enabled', not thinlyProvisioned)

        verbose = "A LUN of size %d Mega Bytes is created in NetApp path %s" % (sizeMB, path)
        self._raiseApiFailure(NetAppStatus(results), verbose)

    def destroy(self, force):
        # This operation will fail if the LUN is currently mapped and is online. 
        # The force option can be used to destroy it regardless of being online or mapped."""
        # The default value for force parameter if not specified is "false". 
        if force:
            xenrt.TEC().logverbose("Allowing a LUN to be destroyed which is online and mapped.")
        else:
            xenrt.TEC().logverbose("Preventing a LUN from being destroyed which is online and mapped.")

        results = self._server.invoke('lun-destroy', 'force', force, 'path', self.__path)

        verbose = "The LUN at %s is destroyed" % self.__path
        self._raiseApiFailure(NetAppStatus(results), verbose)

    def getID(self):
        results = self._server.invoke('lun-get-serial-number', 'path', self.__path)

        verbose = "The serial number of the specified LUN @ %s is obtained" % self.__path
        self._raiseApiFailure(NetAppStatus(results), verbose)

        serialNumber = results.child_get_string('serial-number')
        xenrt.TEC().logverbose("The serial number is %s" % serialNumber)
        return self.__netAppSerialToSCSIId(serialNumber)

    def getNetAppSerialNumber(self):
        return self.__scsiIDToNetAppSerial(self.getID())

    def map(self, initiatorGroup, force):
        """Maps the LUN to all the initiators in the specified initiator group."""
        results = self._server.invoke('lun-map', 'initiator-group', initiatorGroup, 'path', self.__path, 'force', force) # lun-id is defaulted.
        verbose = "The LUN is mapped with the smallest lun id is added to initiator group %s." % initiatorGroup
        self._raiseApiFailure(NetAppStatus(results), verbose)

    def unmap(self, initiatorGroup):
        """Reverses the effect of lun-map on the specified LUN for the specified group."""
        # initiator-group = string Initiator group to unmap from.
        # path = string Path of the LUN.
        xenrt.TEC().logverbose("Unmapping LUN for path %s..." % self.__path)
        results = self._server.invoke('lun-unmap', 'initiator-group', initiatorGroup, 'path', self.__path)
        verbose = "The specified LUN %s is unmapped from initiator group %s." % (self.__path, initiatorGroup)
        self._raiseApiFailure(NetAppStatus(results), verbose)
        
    def isMapped(self):
        mapped, details = self._bestEffort(self.list, [])
        if not mapped:
            return False

        return details[self.__path][0] == 'true'

    def isOnline(self):
        mapped = self.list()[self.__path][1]
        return mapped == 'true'

    def sharedState(self):
        state = self.list()[self.__path][3]
        if(state == "none"): return self.ShareState.NotSet
        if(state == "all"): return self.ShareState.All
        if(state == "unknown"): return self.ShareState.Unknown
        if(state == "read"): return self.ShareState.Read
        return self.ShareState.Unknown

    def size(self):
        return int(self.list()[self.__path][4])

    def sizeUsed(self):
        return int(self.list()[self.__path][5])

    def list(self):
        """Get the status (size, online/offline state, shared state, comment string, serial number, LUN mapping) of the given LUN, or all LUNs."""
        # path  string optional - Path of LUN. If specified, only the information of that LUN is returned.
        # volume-name  string optional - Name of a volume. If specified, only the information of the LUNs in that volume is returned.
        # please note that any one of the parameter can be used at a time.
        results = self._server.invoke('lun-list-info', 'path', self.__path)

        xenrt.TEC().logverbose("Listing the LUN information for path %s..." % self.__path)
        verbose = "Listing the LUN information for path %s..." % self.__path
        self._raiseApiFailure(NetAppStatus(results), verbose)

        luns = results.child_get('luns')

        lunDict = {}
        if not luns.children_get():
            xenrt.TEC().logverbose("No LUNs available")
            return lunDict
        else:
            for lun in luns.children_get():
                lunMappedStatus = lun.child_get_string('mapped')
                lunOnline = lun.child_get_string('online')
                lunPath = lun.child_get_string('path')
                lunSerialNumber = lun.child_get_string('serial-number')
                lunSharedState = lun.child_get_string('share-state')
                lunSize = lun.child_get_int('size')
                lunSizeUsed = lun.child_get_int('size-used')
                lunUUID = lun.child_get_string('uuid')
                lunList = [lunMappedStatus, lunOnline, lunSerialNumber, lunSharedState, lunSize, lunSizeUsed, lunUUID]
                lunDict[lunPath] = lunList
            # return the lun dictionary
            return lunDict

    def resize(self, sizeMB, force):
        """Changes the size of the lun."""

        results = self._server.invoke('lun-resize', 'force', force, 'path', self.__path, 'size', sizeMB * xenrt.MEGA)

        verbose = "Resizing LUN %s to %d Megabytes ..." % (self.__path, sizeMB * xenrt.MEGA)
        self._raiseApiFailure(NetAppStatus(results), verbose)

        # Actual new size may be different from the specified size due to the requested size not fitting on a cylinder boundary.
        actualSize = results.child_get_int('actual-size')
        return actualSize

    def __netAppSerialToSCSIId(self, serialNumber):
        """Converts NetApp LUN serial number to SCISID."""
        serialNumber = serialNumber.encode('hex') # convert ascii to hex
        lunSCSIId = "360a98000" + serialNumber # SCSI vendor, the SCSI product (model) and then the the serial number.
        return lunSCSIId

    def __scsiIDToNetAppSerial(self, SCSIId):
        """Converts SCISID to NetApp LUN serial number."""
        if SCSIId.startswith("360a98000"):
            serialNumberInHexa = SCSIId.split("360a98000").pop()
            serialNumber = serialNumberInHexa.decode("hex") # in ascii
        else:
            raise xenrt.XRTFailure("Unsupported SCSI ID for the test.")
        return serialNumber

class NetAppFCLun(NetAppLun):
    """Encapsulates a netapp FC LUN"""

class NetAppISCSILun(NetAppLun):
    """Encapsulates a netapp ISCSI LUN"""

    def getISCSIIQN(self):
        results = self._server.invoke('iscsi-node-get-name')
        verbose = "Getting ISCSI Target IQN"
        self._raiseApiFailure(NetAppStatus(results), verbose)
        return results.child_get_string("node-name")

    def getISCSILunObj(self):
        obj = xenrt.ISCSIIndividualLun(None,
                                       None,
                                       scsiid = self.getID(),
                                       server = self._server.server,
                                       targetname = self.getISCSIIQN())
        return obj
