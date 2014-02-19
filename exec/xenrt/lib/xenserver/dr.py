import xenrt
from xenrt.lazylog import step, comment, log, warning

class DRTask(object):    
    """A base class that represents a single DRTask - contains its uuid"""
    def __init__(self):
        self.uuid = None      

class DRTaskManager(object):
    """Class that handles all Disaster Recovery tasks - drtask on the CLI"""
        
    __DRTASK_CREATE_COMMAND = "drtask-create"     
    __DRTASK_DESTROY_COMMAND = "drtask-destroy"    
    
    def createDRTask(self,
                     host,
                     type,
                     deviceConfigList=None,  #decouple - each SR type has different kinds of params here
                     srWhitelist=None):
            
        """A method that creates a drtask
        @param: host - a handle for the host machine
                type - the type of the SR as a string
                deviceConfigList - an optional list of device config parameters - usage: deviceConfigList=["targetIQN=<targetIQN>", ...]
                srWhitelist - an optional list containing DR SR UUIDs as strings
        @return: on success, returns a DRTask object
        """
            
        # parse the parameters
        typeParam = "type=%s" % type   
            
        deviceConfigParam = ' device-config:'
        if(deviceConfigList):
            deviceConfigParam += " device-config:".join(deviceConfigList)
            
        srWhitelistParam = ' sr-whitelist='
        if(srWhitelist):
            srWhitelistParam += ",".join(srWhitelist)
            
        drCreateParams = typeParam + deviceConfigParam + srWhitelistParam
               
        return DRTask(host.getCLIInstance().execute(self.__DRTASK_CREATE_COMMAND, drCreateParams))
            
    def deleteDRTask(self,
                     host,
                     drtask):
            
        """A method that deletes a drtask
        @param: host - a handle for the host machine
                drtask - a drtask object to be destroyed
        @return: None
        """
        
        host.getCLIInstance().execute(self.__DRTASK_DESTROY_COMMAND, drtask.uuid)
