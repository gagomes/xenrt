#
# XenRT: Test harness for Xen and the XenServer product family
#
# RBAC API test cases
#
# Copyright (c) 2009 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import re, tempfile, xmlrpclib, copy
import xenrt, testcases.xenserver.tc.security
from xenrt.lib.xenserver.call import *

class _APIGet(testcases.xenserver.tc.security._RBAC):
    """Test all the 'X.get' API calls."""

    ALLOWED = {"xenapi.host.get_log"                            : "NOT_IMPLEMENTED",
               "xenapi.message.get"                             : "BROKEN",
               "xenapi.host.get_memory_total"                   : "METHOD_UNKNOWN"}

    TYPES   = ["Blob",
               "Bond",
#             "VTPM",
#             "auth",
#             "Crashdump",
              "Subject",
              "Session",
               "User",
#             "host_crashdump",
               "Role",
               "Console",
               "CPU",
               "Host",
               "Message",
               "Network",
               "Patch",
               "PBD",
               "PIF",
               "Pool",
               "Secret",
               "SM",
               "SR",
               "VBD",
               "VDI",
               "VIF",
               "VLAN",
               "VM",
               "VMPP",
               "VM_metrics",
               "VM_guest_metrics",
               "Task",
               "host_metrics",
               "PIF_metrics",
               "VBD_metrics",
               "VIF_metrics",
               "event"]

    def prepare(self, arglist):
        testcases.xenserver.tc.security._RBAC.prepare(self, arglist)
        
        #MESSAGE_REMOVED for VM_guest_metrics.get_disks and get_memory in trunk
        if isinstance(self.pool.master, xenrt.lib.xenserver.DundeeHost):
            self.ALLOWED["xenapi.VM_guest_metrics.get_disks"]="MESSAGE_REMOVED"
            self.ALLOWED["xenapi.VM_guest_metrics.get_memory"]="MESSAGE_REMOVED"
            
        self.OPERATIONS["api"] = []
        for t in self.TYPES:
            if self.context.classes.has_key(t):
                apiname = self.context.classes[t].NAME
            else:
                apiname = t
            calls = filter(re.compile("(?<!_)%s\.get" % (apiname)).search, self.PERMISSIONS)
            calls = filter(lambda x:not re.search("/", x), calls)
            calls = self.clearwaterAPICallCheck(calls)
            for call in calls:
                apiargs = {}
                apiargs["operation"] = call
                apiargs["environment"] = [t]
                apiargs["parameters"] = ["%s.getHandle()" % (t)]
                apiargs["keep"] = [t]
                apicall = self.apiFactory(apiargs)
                if call == "xenapi.%s.get_all" % (apiname):
                    apicall.parameters = []
                elif call == "xenapi.%s.get_all_records" % (apiname):
                    apicall.parameters = []
                elif call == "xenapi.%s.get_by_uuid" % (apiname):
                    apicall.parameters = ["%s.getUUID()" % (t)]
                elif call == "xenapi.%s.get_all_records_where" % (apiname):
                    apicall.parameters = ["true"]
                elif call == "xenapi.SR.get_supported_types":
                    apicall.parameters = []
                elif call == "xenapi.message.get_since":
                    apicall.parameters = [xmlrpclib.DateTime()]
                elif call == "xenapi.message.get":
                    continue
                elif call == "xenapi.event.get_current_id":
                    apicall.environment = []
                    apicall.parameters = []
                elif call == "xenapi.session.get_all_subject_identifiers":
                    apicall.parameters = []
                elif call == "xenapi.VMPP.get_alerts":
                    apicall.parameters.append("10")
                elif call == "xenapi.VM.get_SRs_required_for_recovery":
                    apicall.environment.append("Session")
                    apicall.parameters.append("Session.getHandle()")
                    
                self.OPERATIONS["api"].append(apicall)

class _APIAddRemove(testcases.xenserver.tc.security._RBAC):
    """Test all the 'add_to' and 'remove_from' API calls."""    
   
    ALLOWED = {"xenapi.VM.add_to_VCPUs_params_live":"NOT_IMPLEMENTED",
               "xenapi.event.get_all":"NOT_IMPLEMENTED"}

    OKEY = "Y"
    OVAL = "Y"

    TYPES = ["Blob",
             "Bond",
#             "VTPM",
#             "auth",
#             "Crashdump",
#             "Patch",
             "Subject",
             "Session",
             "User",
#             "host_crashdump",
             "Role",
             "Console",
             "CPU",
             "Host",
             "Message",
             "Network",
             "PBD",
             "PIF",
             "Pool",
             "Secret",
             "SM",
             "SR",
             "VBD",
             "VDI",
             "VIF",
             "VLAN",
             "VM",
#             "VMPP",
             "VM_metrics",
             "VM_guest_metrics",
             "Task",
             "host_metrics",
             "PIF_metrics",
             "VBD_metrics",
             "VIF_metrics",
             "event"]

    def prepare(self, arglist):
        testcases.xenserver.tc.security._RBAC.prepare(self, arglist) 
        self.OPERATIONS["api"] = []
        for t in self.TYPES:
            if self.context.classes.has_key(t):
                apiname = self.context.classes[t].NAME
            else:
                apiname = t
            calls = filter(re.compile("%s\.add_to" % (apiname)).search, self.PERMISSIONS)
            calls = filter(lambda x:not re.search("/", x), calls)
            calls = self.clearwaterAPICallCheck(calls)
            for call in calls: 
                apiargs = {}
                apiargs["operation"] = call
                apiargs["environment"] = [t]
                apiargs["parameters"] = ["%s.getHandle()" % (t)]
                apiargs["keep"] = [t]
                apicall = self.apiFactory(apiargs)
                apicall.parameters.append(self.OKEY)
                apicall.parameters.append(self.OVAL)
                if call == "xenapi.VM.add_to_blocked_operations":
                    apicall.parameters = ["VM.getHandle()", "start", "x"]
                elif call == "xenapi.subject.add_to_roles":
                    apicall.environment.append("Role")
                    apicall.parameters = ["Subject.getHandle()", "Role.getHandle()"]
                xenrt.TEC().logverbose("Adding: %s (%s)" % (apicall, apiargs))
                self.OPERATIONS["api"].append(apicall)
            calls = filter(re.compile("%s\.remove_from" % (apiname)).search, self.PERMISSIONS)
            calls = filter(lambda x:not re.search("/", x), calls)
            for call in calls: 
                apiargs = {}
                apiargs["operation"] = call
                apiargs["environment"] = [t]
                apiargs["parameters"] = ["%s.getHandle()" % (t)]
                apiargs["keep"] = [t]
                apicall = self.apiFactory(apiargs)
                apicall.parameters.append(self.OKEY)
                if call == "xenapi.VM.remove_from_blocked_operations":
                    apicall.parameters = ["VM.getHandle()", "start"]
                elif call == "xenapi.subject.remove_from_roles":
                    apicall.environment.append("Role")
                    apicall.parameters = ["Subject.getHandle()", "Role.getHandle()"]
                self.OPERATIONS["api"].append(apicall)

class _APISet(testcases.xenserver.tc.security._RBAC):
    """Test access control of API 'set' calls."""

    ALLOWED = {"xenapi.VM.set_VCPUs_number_live"        :   "OPERATION_NOT_ALLOWED",
               "xenapi.pool.set_vswitch_controller"     :   "OPERATION_NOT_ALLOWED", 
               "xenapi.PBD.set_device_config"           :   "PERMISSION_DENIED", 
               "xenapi.SR.set_physical_utilisation"     :   "PERMISSION_DENIED", 
               "xenapi.SR.set_physical_size"            :   "PERMISSION_DENIED", 
               "xenapi.SR.set_virtual_allocation"       :   "PERMISSION_DENIED", 
               "xenapi.VDI.set_missing"                 :   "PERMISSION_DENIED", 
               "xenapi.VDI.set_physical_utilisation"    :   "PERMISSION_DENIED", 
               "xenapi.VDI.set_sharable"                :   "PERMISSION_DENIED", 
               "xenapi.VDI.set_virtual_size"            :   "PERMISSION_DENIED", 
               "xenapi.VDI.set_read_only"               :   "PERMISSION_DENIED", 
               "xenapi.VDI.set_managed"                 :   "PERMISSION_DENIED",
               "xenapi.VDI.set_snapshot_of"             :   "PERMISSION_DENIED",
               "xenapi.VDI.set_is_a_snapshot"           :   "PERMISSION_DENIED",
               "xenapi.VDI.set_metadata_of_pool"        :   "PERMISSION_DENIED",
               "xenapi.VDI.set_snapshot_time"           :   "PERMISSION_DENIED",
               "xenapi.host.set_cpu_features"           :   "CPU_FEATURE_MASKING_NOT_SUPPORTED|INVALID_FEATURE_STRING",
               "xenapi.host.set_hostname_live"          :   "AUTH_ALREADY_ENABLED"} 

    TYPES = ["Blob",
             "Bond",
#             "VTPM",
#             "auth",
#             "Crashdump",
#             "Patch",
             "Subject",
             "Session",
             "User",
#             "host_crashdump",
             "Role",
             "Console",
             "CPU",
             "Host",
             "Message",
             "Network",
             "PBD",
             "PIF",
             "Pool",
             "Secret",
             "SM",
             "SR",
             "VBD",
             "VDI",
             "VIF",
             "VLAN",
             "VM",
             "VMPP",
             "VM_metrics",
             "VM_guest_metrics",
             "Task",
             "host_metrics",
             "PIF_metrics",
             "VBD_metrics",
             "VIF_metrics",
             "event"]

    def prepare(self, arglist):
        testcases.xenserver.tc.security._RBAC.prepare(self, arglist) 
        self.OPERATIONS["api"] = []
        all = filter(re.compile("\.set_").search, self.PERMISSIONS)
        xenrt.TEC().logverbose("ALL: %s" % (all))
        xenrt.TEC().logverbose("TOTAL: %s" % (len(all)))
        for t in self.TYPES:
            if self.context.classes.has_key(t):
                apiname = self.context.classes[t].NAME
            else:
                apiname = t
            calls = filter(re.compile("%s\.set" % (apiname)).search, self.PERMISSIONS)
            calls = filter(lambda x:not re.search("/", x), calls)
            calls = self.clearwaterAPICallCheck(calls)
            if not calls: continue
            # Try and work out the correct type for each field
            # by looking at its current value.
            apiargs = {}
            apiargs["operation"] = "xenapi.%s.get_record" % (apiname)
            if t == "Host":
                apiargs["environment"] = ["Pool"]  
                apiargs["keep"] = ["Pool"]
            else:
                apiargs["environment"] = [t]
                apiargs["keep"] = [t]
            apiargs["parameters"] = ["%s.getHandle()" % (t)]          
            apicall = self.apiFactory(apiargs)
            try: 
                local = xenrt.ActiveDirectoryServer.Local("root", xenrt.TEC().lookup("ROOT_PASSWORD"))
                values = apicall.call(self.pool.master, local) 
            except Exception, e:
                xenrt.TEC().warning("Failed to get values for %s. (%s)" % (t, str(e)))
                values = {}
            for call in calls:
                field = re.sub(".*set_", "", call)
                apiargs = {}
                apiargs["operation"] = call
                if t == "Host":
                    apiargs["environment"] = ["Pool"]
                elif t == "VM_guest_metrics":
                    apiargs["environment"] = ["VM", "VM_guest_metrics"]
                else:
                    apiargs["environment"] = [t]
                apiargs["parameters"] = ["%s.getHandle()" % (t)]
                apicall = self.apiFactory(apiargs)
                if values.has_key(field):
                    apicall.parameters.append(values[field])
                #The default mode for bond creation is "balance-slb" and for the bond.properties={}
                #so set_property is not supposed to work, change the bond mode to lacp
                if call=="xenapi.Bond.set_property":
                    apicall.environment=["LacpBond"]
                    apicall.parameters=["LacpBond.getHandle()","hashing_algorithm","tcpudp_ports"]
                #PIF.set_property added for Dundee
                if call=="xenapi.PIF.set_property":
                    apicall.parameters=["PIF.getHandle()","gro","off"]
                #for VBD.set_mode the VM needs to be in halted state, a seperate class OffVBD has
                #been created
                if call == "xenapi.VBD.set_mode":
                    apicall.environment=["OffVBD"]
                    apicall.parameters=["OffVBD.getHandle()", values[field]]
                #this API call cannot be made on a management interface therefore changing the environment
                #to SecondaryPIF
                if call == "xenapi.PIF.set_primary_address_type":
                    apicall.environment=["SecondaryPIFNPRI"]
                    apicall.parameters=["SecondaryPIFNPRI.getHandle()", values[field]]
                if call == "xenapi.VM.set_memory_target_live":
                    apicall.parameters.append(values["memory_dynamic_max"])
                if call == "xenapi.host.set_localdb_key":
                    apicall.parameters.append("X")
                    apicall.parameters.append("X")
                if call == "xenapi.VM.set_VCPUs_number_live":
                    apicall.parameters.append(values["VCPUs_at_startup"])
                if call == "xenapi.VM.set_shadow_multiplier_live":
                    apicall.parameters.append(values["HVM_shadow_multiplier"])
                if call == "xenapi.host.set_hostname_live":
                    apicall.parameters.append(values["hostname"])
                if call == "xenapi.VM.set_memory_static_min":
                    apicall.environment = ["HaltedVM"]
                    apicall.parameters = ["HaltedVM.getHandle()", values[field]]    
                if call == "xenapi.VM.set_HVM_shadow_multiplier":
                    apicall.environment = ["HaltedVM"] 
                    apicall.parameters = ["HaltedVM.getHandle()", values[field]]    
                if call == "xenapi.VM.set_VCPUs_at_startup":
                    apicall.environment = ["HaltedVM"]   
                    apicall.parameters = ["HaltedVM.getHandle()", values[field]]    
                if call == "xenapi.VM.set_memory_static_max":
                    apicall.environment = ["HaltedVM"] 
                    apicall.parameters = ["HaltedVM.getHandle()", values[field]]    
                if call == "xenapi.VM.set_VCPUs_max":
                    apicall.environment = ["HaltedVM"]           
                    apicall.parameters = ["HaltedVM.getHandle()", values[field]]   
                if call == "xenapi.VM.set_memory_limits":
                    apicall.environment = ["HaltedVM"]
                    apicall.parameters = ["HaltedVM.getHandle()", 
                                           values["memory_static_min"], 
                                           values["memory_dynamic_min"], 
                                           values["memory_dynamic_max"],
                                           values["memory_static_max"]]
                if call == "xenapi.VM.set_memory_static_range":
                    apicall.environment = ["HaltedVM"]
                    apicall.parameters = ["HaltedVM.getHandle()", 
                                           values["memory_static_min"], 
                                           values["memory_static_max"]]
                if call == "xenapi.VM.set_memory_dynamic_range":
                    apicall.environment = ["HaltedVM"]
                    apicall.parameters = ["HaltedVM.getHandle()",
                                           values["memory_dynamic_min"],
                                           values["memory_dynamic_max"]] 
                #using the SuspendVDI class because I need the opaque ref of the vdi containing the
                #suspend image
                if call=="xenapi.VM.set_suspend_VDI":
                    apicall.environment =["SuspendVDI"]
                    apicall.parameters= ["VM.getHandle()","SuspendVDI.getHandle()"]
                if call == "xenapi.task.set_other_config":
                    apicall.parameters.append({"Y":"Y"})
                if call == "xenapi.host.set_power_on_mode":
                    apicall.parameters.append({})
                if call == "xenapi.host.set_cpu_features":
                    apicall.parameters.append("00000000-00000000-00000000-00000000")
                if call == "xenapi.pool.set_vswitch_controller":
                    continue
                    apicall.parameters = ["Pool.getHandle()"]
                self.OPERATIONS["api"].append(apicall)

class _APITest(testcases.xenserver.tc.security._RBAC):

    # Format of the below dictionary:

    #            'name of API call'                 : ([environment],
    #                                                  [parameters],
    #                                                  [keep])
    
    # environment   -   Required entities for this API call.
    # parameters    -   Parameters to pass to the call.
    # keep          -   Entities to keep after the call.

    ALLOWED = {"xenapi.VM.migrate"                      :   "NOT_IMPLEMENTED",
               "xenapi.VM.send_trigger"                 :   "NOT_IMPLEMENTED",
               "xenapi.host.dmesg_clear"                :   "NOT_IMPLEMENTED",
               "xenapi.host.list_methods"               :   "NOT_IMPLEMENTED",
               "xenapi.VM.update_snapshot_metadata"     :   "NOT_IMPLEMENTED",
               "xenapi.VM.send_sysrq"                   :   "NOT_IMPLEMENTED",
               "xenapi.VDI.generate_config"             :   "SR_OPERATION_NOT_SUPPORTED",
               "xenapi.SR.assert_can_host_ha_statefile" :   "SR_OPERATION_NOT_SUPPORTED",
               "xenapi.VDI.introduce"                   :   "SR_OPERATION_NOT_SUPPORTED",
               "xenapi.host.enable_local_storage_caching" :   "SR_OPERATION_NOT_SUPPORTED",
               "xenapi.SR.make"                         :   "MESSAGE_DEPRECATED",
               "xenapi.VDI.force_unlock"                :   "MESSAGE_DEPRECATED",
               "xenapi.VDI.db_forget"                   :   "PERMISSION_DENIED",
               "xenapi.VDI.db_introduce"                :   "PERMISSION_DENIED",
               "xenapi.pool.enable_local_storage_caching"   : "HOSTS_FAILED_TO_ENABLE_CACHING",
               "xenapi.VM.create_template"              :   "MESSAGE_METHOD_UNKNOWN",
               "xenapi.VBD.unplug_force"                :   "OPERATION_NOT_ALLOWED"}

    FATAL = {"xenapi.host.management_disable":"ProtocolError",
             "xenapi.host.local_management_reconfigure":"NONESUCH",
             "xenapi.host.reboot":None,
             "xenapi.host.shutdown_agent":None,
             "xenapi.host.restart_agent":None,
             "xenapi.host.destroy":"HOST_IS_LIVE",
             "xenapi.host.management_reconfigure":None,
            }

    FILESR = "/tmp/emptyXenRTSR"

    CONFIG =    {'xenapi.blob.create'              : ([],
                                                      ["''"]),
                 'xenapi.blob.destroy'             : (["Blob"],
                                                      ["Blob.getHandle()"]),
                 'xenapi.Bond.create'              : (["PIF", "SecondaryPIFNPRI", "Pool", "Network"], 
                                                      ["Network.getHandle()", ["PIF.getHandle()", "SecondaryPIFNPRI.getHandle()"], ""]),
                 'xenapi.Bond.destroy'             : (["Bond"], ["Bond.getHandle()"]),
                 'xenapi.network.add_tags'         : (['Network'], 
                                                      ['Network.getHandle()', 'X']), 
                 'xenapi.network.remove_tags'      : (['Network'], 
                                                      ['Network.getHandle()', 'X']), 
                 'xenapi.network.attach'           : (['Network'], 
                                                      ['Network.getHandle()', 'Host.getHandle()']),
                 'xenapi.network.create'           : ([],          
                                                      [{'name_description'      : 'X', 
                                                        'name_label'            : 'X', 
                                                        'other_config'          : {}, 
                                                        'tags'                  : []}]), 
                 'xenapi.network.destroy'          : (['Network'], 
                                                      ['Network.getHandle()']), 
                 'xenapi.network.create_new_blob'  : (['Network'],
                                                      ['Network.getHandle()', 'blob', '']),
                 'xenapi.network.pool_introduce'   : (['Network'], 
                                                      ['X', 'X', '1500', {}, 'xenbr0']), 
                 'xenapi.VIF.create'               : (['Network', 'VM'],
                                                      [{'MAC'                   : '66:db:47:0f:87:95',
                                                        'MTU'                   : '1500',
                                                        'VM'                    : 'VM.getHandle()',
                                                        'device'                : '0',
                                                        'network'               : 'Network.getHandle()',
                                                        'other_config'          : {},
                                                        'qos_algorithm_params'  : {},
                                                        'qos_algorithm_type'    : ''}]),
                 'xenapi.VIF.destroy'               : (['UnpluggedVIF'],
                                                       ['UnpluggedVIF.getHandle()']),
                 'xenapi.VIF.plug'                  : (['UnpluggedVIF'],
                                                       ['UnpluggedVIF.getHandle()']),
#                 'xenapi.VIF.unplug'                : (['VIF'],
#                                                       ['VIF.getHandle()']),
                 'xenapi.VLAN.create'               : (['PIF', 'Network'],
                                                       ['PIF.getHandle()', '999', 'Network.getHandle()']),
                 'xenapi.VLAN.destroy'              : (['VLAN'], 
                                                       ['VLAN.getHandle()']), 
                 'xenapi.VBD.assert_attachable'     : (['VBD'], 
                                                       ['VBD.getHandle()']), 
                 'xenapi.VBD.create'                : (['VM'],
                                                       [{'VDI'                  : '',
                                                         'VM'                   : 'VM.getHandle()',
                                                         'bootable'             : False,
                                                         'empty'                : True,
                                                         'mode'                 : 'RO',
                                                         'other_config'         : {},
                                                         'qos_algorithm_params' : {},
                                                         'qos_algorithm_type'   : '',
                                                         'type'                 : 'CD',
                                                         'unpluggable'          : False,
                                                         #while creating a new VBD, using userdevice=0 will throw 'DEVICE_ALREADY_IN_USE' error
                                                         #therefore changing it to 1
                                                         'userdevice'           : '1'}]),
                 'xenapi.VBD.destroy'               : (['UnpluggedVBD'],
                                                       ['UnpluggedVBD.getHandle()']),
                 'xenapi.VBD.eject'                 : (['RemoveableVBD'],
                                                       ['RemoveableVBD.getHandle()']),
                 'xenapi.VBD.insert'                : (['EmptyVBD', 'ISOVDI'],
                                                       ['EmptyVBD.getHandle()', 'ISOVDI.getHandle()']),
#                 'xenapi.VBD.pause'                 : (['VBD'], 
#                                                       ['VBD.getHandle()']),     
#                 'xenapi.VBD.unpause'               : (['PausedVBD'],
#                                                       ['PausedVBD.getHandle()']),
                 'xenapi.VBD.plug'                  : (['UnpluggedVBD'],
                                                       ['UnpluggedVBD.getHandle()']),
#                 'xenapi.VBD.unplug'                : (['VBD'], 
#                                                       ['VBD.getHandle()']), 
                 'xenapi.VBD.unplug_force'          : (['VBD'], 
                                                       ['VBD.getHandle()']), 
                 'xenapi.VBD.unplug_force_no_safety_check': (['VBD'],
                                                       ['VBD.getHandle()']),
                 'xenapi.SR.add_tags'               : (['SR'], 
                                                       ['SR.getHandle()', 'X']), 
                 'xenapi.SR.assert_can_host_ha_statefile': (['SR'], 
                                                       ['SR.getHandle()']), 
                 'xenapi.SR.create'                 : ([],
                                                       ['Host.getHandle()', 
                                                        {'location'             : FILESR}, 
                                                        '1', 
                                                        'XenRT SR', 
                                                        '',
                                                        'file',
                                                        'user',
                                                        False]),
                 'xenapi.SR.create_new_blob'        : (['SR'],
                                                       ['SR.getHandle()', 'blob', '']), 
                 'xenapi.SR.destroy'                : (['UnpluggedPBD'],
                                                       ['NFSSR.getHandle()']),
                 'xenapi.SR.forget'                 : (['UnpluggedPBD'],
                                                       ['NFSSR.getHandle()']),
                 'xenapi.SR.introduce'              : ([],
                                                       ['00000000-0000-000-000-000000000000',
                                                        'XenRT SR',
                                                        '',
                                                        'file',
                                                        'user',
                                                         False]),
                 'xenapi.SR.lvhd_stop_using_these_vdis_and_call_script': (['SR'],
                                                        [[],
                                                        'lvhdrt-helper',
                                                        'get_sr_vfree',
                                                        {'sruuid': 'SR.getUUID()'}]),
#                 'xenapi.SR.make'                   : (['SR'], 
#                                                       ['Host.getHandle()', 
#                                                        {'location'             : FILESR}, 
#                                                        '1', 
#                                                        'XenRT SR', 
#                                                        '',
#                                                        'file',
#                                                        'user',
#                                                         False]),      
                 'xenapi.SR.probe'                  : (['NFSSR'],
                                                       ['Host.getHandle()',
                                                        {'server'               : 'NFSSR.ref.server',
                                                         'serverpath'           : 'NFSSR.ref.path'},
                                                        'nfs',
                                                        {}]),
                 'xenapi.SR.remove_tags'            : (['SR'], 
                                                       ['SR.getHandle()', 'X']), 
                 'xenapi.SR.scan'                   : (['NFSSR'], 
                                                       ['NFSSR.getHandle()']), 
                 'xenapi.SR.update'                 : (['SR'], 
                                                       ['SR.getHandle()']), 
                 'xenapi.VDI.add_tags'              : (['VDI'], 
                                                       ['VDI.getHandle()', 'X']), 
                 'xenapi.VDI.clone'                 : (['VDI'], 
                                                       ['VDI.getHandle()']), 
                 'xenapi.VDI.copy'                  : (['VDI'], 
                                                       ['VDI.getHandle()', 'NFSSR.getHandle()']), 
                 'xenapi.VDI.create':                 (['SR'],
                                                       [{'SR'                   : 'SR.getHandle()',
                                                         'name_description'     : '',
                                                         'name_label'           : 'XenRTVDI',
                                                         'other_config'         : {},
                                                         'read_only'            : False,
                                                         'sharable'             : False,
                                                         'type'                 : 'User',
                                                         'virtual_size'         : '1073741824',
                                                         'xenstore_data'        : {}}]),
                 'xenapi.VDI.db_forget'             : (['VDI'], 
                                                       ['VDI.getHandle()']), 
                 'xenapi.VDI.db_introduce'          : (['NFSSR'],
                                                       ['00000000-0000-000-000-000000000000',
                                                        'XenRTVDI',
                                                        '',
                                                        'NFSSR.getHandle()',
                                                        'User',
                                                        False,
                                                        False,
                                                        {},
                                                        '']),
                 'xenapi.VDI.destroy'               : (['VDI'], 
                                                       ['VDI.getHandle()']), 
                 'xenapi.VDI.force_unlock'          : (['VDI'], 
                                                       ['VDI.getHandle()']), 
                 'xenapi.VDI.forget'                : (['VDI'], 
                                                       ['VDI.getHandle()']), 
                 'xenapi.VDI.generate_config'       : (['VDI'],    
                                                       ['Host.getHandle()', 'VDI.getHandle()']),
                 'xenapi.VDI.introduce'             : (['NFSSR'],
                                                       ['00000000-0000-000-000-000000000000',
                                                        'XenRTVDI',
                                                        '',
                                                        'NFSSR.getHandle()',
                                                        'User',
                                                        False,
                                                        False,
                                                        {},
                                                        '']),
                 'xenapi.VDI.pool_introduce'        : (['NFSSR'],
                                                       ['00000000-0000-000-000-000000000000',
                                                        'XenRTVDI',
                                                        '',
                                                        'NFSSR.getHandle()',
                                                        'User',
                                                        False,
                                                        False,
                                                        {},
                                                        '']),
                 'xenapi.VDI.remove_tags'           : (['VDI'], 
                                                       ['VDI.getHandle()', 'X']), 
                 'xenapi.VDI.resize'                : (['VDI'], 
                                                       ['VDI.getHandle()', '2147483648']), 
                 'xenapi.VDI.snapshot'              : (['VDI'], 
                                                       ['VDI.getHandle()']), 
                 'xenapi.VDI.update'                : (['VDI'], 
                                                       ['VDI.getHandle()']), 
                 'xenapi.VM.send_trigger'           : (['VM'],
                                                       ['VM.getHandle()', 'X']),
                 'xenapi.VM.destroy'                : (['HaltedVM'],
                                                       ['HaltedVM.getHandle()']),
                 'xenapi.VM.resume'                 : (['SuspendedVM'],
                                                       ['SuspendedVM.getHandle()', True, True]),
                 'xenapi.VM.add_tags'               : (['VM'],
                                                       ['VM.getHandle()', 'X']),
                 'xenapi.VM.clean_reboot'           : (['VM'],
                                                       ['VM.getHandle()']),
                 'xenapi.VM.assert_agile'           : (['VM'],
                                                       ['VM.getHandle()']),
                 'xenapi.VM.pool_migrate'           : (['VM'],
                                                       ['VM.getHandle()', 'Host.getHandle()', {}]),
                 'xenapi.VM.assert_operation_valid' : (['VM'],
                                                       ['VM.getHandle()', 'hard_shutdown']),
                 'xenapi.VM.snapshot'               : (['VM'],
                                                       ['VM.getHandle()', 'snapshot']),
                 'xenapi.VM.unpause'                : (['PausedVM'],
                                                       ['PausedVM.getHandle()']),
                 'xenapi.VM.query_data_source'      : (['VM'],
                                                       ['VM.getHandle()', 'cpu0']),
                 'xenapi.VM.provision'              : (['Template'],
                                                       ['Template.getHandle()']),
                 'xenapi.VM.clone'                  : (['HaltedVM'],
                                                       ['HaltedVM.getHandle()', 'clone']),
                 'xenapi.VM.create_new_blob'        : (['VM'],
                                                       ['VM.getHandle()', 'blob', '']),
                 'xenapi.VM.resume_on'              : (['SuspendedVM'],
                                                       ['SuspendedVM.getHandle()', 'Host.getHandle()', True, True]),
                 'xenapi.VM.migrate'                : (['VM'],
                                                       ['VM.getHandle()', 'Host.getHandle()', False, {}]),
                 'xenapi.VM.update_allowed_operations' : (['VM'],
                                                       ['VM.getHandle()']),
                 'xenapi.VM.power_state_reset'      : (['HaltedVM'],
                                                       ['HaltedVM.getHandle()']),
                 'xenapi.VM.retrieve_wlb_recommendations' : (['VM', 'KirkwoodPool'],
                                                       ['VM.getHandle()']),
                 'xenapi.VM.update_snapshot_metadata' : (['VM'],
                                                       ['VM.getHandle()', 
                                                        'VM.getHandle()', 
                                                         xmlrpclib.DateTime(xmlrpclib.DateTime().value + 'Z'),
                                                        '']),
                 'xenapi.VM.create'                  : ([],
                                                       [{'PV_args'                  : '', 
                                                         'ha_restart_priority'      : 'best-effort', 
                                                         'PV_bootloader'            : '', 
                                                         'blocked_operations'       : {}, 
                                                         'name_description'         : '', 
                                                         'PCI_bus'                  : '', 
                                                         'actions_after_crash'      : 'Destroy', 
                                                         'memory_target'            : '1048576', 
                                                         'PV_ramdisk'               : '', 
                                                         'name_label'               : 'RBACVM', 
                                                         'VCPUs_at_startup'         : '1', 
                                                         'HVM_boot_params'          : {}, 
                                                         'platform'                 : {}, 
                                                         'PV_kernel'                : '', 
                                                         'affinity'                 : 'Host.getHandle()', 
                                                         'ha_always_run'            : False, 
                                                         'VCPUs_params'             : {}, 
                                                         'memory_static_min'        : '1048576', 
                                                         'HVM_boot_policy'          : '', 
                                                         'tags'                     : [], 
                                                         'VCPUs_max'                : '1', 
                                                         'memory_static_max'        : '1048576', 
                                                         'actions_after_shutdown'   : 'Destroy', 
                                                         'memory_dynamic_max'       : '1048576', 
                                                         'user_version'             : '0', 
                                                         'xenstore_data'            : {}, 
                                                         'is_a_template'            : False, 
                                                         'memory_dynamic_min'       : '1048576', 
                                                         'PV_bootloader_args'       : '', 
                                                         'other_config'             : {}, 
                                                         'HVM_shadow_multiplier'    : 1.0, 
                                                         'actions_after_reboot'     : 'Destroy', 
                                                         'PV_legacy_args'           : '', 
                                                         'recommendations'          : ''}]),
#                'xenapi.VM.snapshot_with_quiesce'    : (['VM'],
#                                                        ['VM.getHandle()', 'snapshot']),
#                'xenapi.VM.wait_memory_target_live'  : (['VM'],
#                                                        ['VM.getHandle()']),
                'xenapi.VM.checkpoint'               : (['VM'],
                                                        ['VM.getHandle()', 'X']),
                'xenapi.VM.compute_memory_overhead'  : (['VM'],
                                                        ['VM.getHandle()']),
                'xenapi.VM.maximise_memory'          : (['VM'],
                                                        ['VM.getHandle()', '1024', True]),
#                'xenapi.VM.pause'                    : (['VM'],
#                                                        ['VM.getHandle()']),
                'xenapi.VM.clean_shutdown'           : (['VM'],
                                                        ['VM.getHandle()']),
#                'xenapi.VM.csvm'                     : (['VM'],
#                                                        ['VM.getHandle()']),
                'xenapi.VM.start_on'                 : (['HaltedVM'],
                                                        ['HaltedVM.getHandle()', 
                                                         'Host.getHandle()', 
                                                          True, 
                                                          True]),
                'xenapi.VM.forget_data_source_archives' : (['VM'],
                                                        ['VM.getHandle()', 'cpu0']),
                'xenapi.VM.hard_shutdown'            : (['VM'],
                                                        ['VM.getHandle()']),
                'xenapi.VM.assert_can_boot_here'     : (['VM'],
                                                        ['VM.getHandle()', 'Host.getHandle()']),
#                'xenapi.VM.hard_reboot_internal'     : (['VM'],
#                                                        ['VM.getHandle()']),
                'xenapi.VM.suspend'                  : (['VM'],
                                                        ['VM.getHandle()']),
                'xenapi.VM.record_data_source'       : (['VM'],
                                                        ['VM.getHandle()', 'cpu0']),
                'xenapi.VM.send_sysrq'               : (['VM'],
                                                        ['VM.getHandle()', 'X']),
                'xenapi.VM.hard_reboot'              : (['VM'],
                                                        ['VM.getHandle()']),
                'xenapi.VM.copy'                     : (['HaltedVM', 'SR'],
                                                        ['HaltedVM.getHandle()', 'copy', 'SR.getHandle()']),
#                'xenapi.VM.revert'                   : (['Snapshot'],
#                                                        ['Snapshot.getHandle()']),
                'xenapi.VM.atomic_set_resident_on'   : (['VM'],
                                                        ['VM.getHandle()', 'Host.getHandle()']),
                'xenapi.VM.remove_tags'              : (['VM'],
                                                        ['VM.getHandle()', 'X']),
                'xenapi.VM.start'                    : (['HaltedVM'],
                                                        ['HaltedVM.getHandle()',True, True]),
#                'xenapi.host.retrieve_wlb_evacuate_recommendations' : (['Pool'],
#                                                        ['Host.getHandle()']),
#                'xenapi.host.disable_external_auth'  : (['Pool'],
#                                                        ['Host.getHandle()']),
                'xenapi.host.attach_static_vdis'     : (['Pool'],
                                                        ['Host.getHandle()', []],
                                                        ["Pool"]),
                'xenapi.host.attach_static_vdis'     : (['Pool'],
                                                        ['Host.getHandle()', {}],
                                                        ["Pool"]),
                'xenapi.host.compute_free_memory'    : (['Pool'],
                                                        ['Host.getHandle()'],
                                                        ["Pool"]),
                'xenapi.host.is_in_emergency_mode'   : (['Pool'],
                                                        [],
                                                        ["Pool"]),
                'xenapi.host.forget_data_source_archives' : (['Pool'],
                                                             ['Host.getHandle()', 'cpu0']),
#                'xenapi.host.bugreport_upload'       : (['Pool'],
#                                                        ['Host.getHandle()']),
                'xenapi.host.enable_binary_storage'  : (['Pool'],
                                                        ['Host.getHandle()']),
#                'xenapi.host.local_management_reconfigure' : (['EmergencyPool'],
#                                                        ['Host.getHandle()']),
#                'xenapi.host.tickle_heartbeat'       : (['Pool'],
#                                                        ['Host.getHandle()', ""]),
                'xenapi.host.reboot'                 : (['DisabledHost'],
                                                        ['DisabledHost.getHandle()']),
                'xenapi.host.ha_xapi_healthcheck'    : (['Pool'],
                                                        [],
                                                        ["Pool"]),
                'xenapi.host.ha_release_resources'   : (['Pool'],
                                                        ['Host.getHandle()']),
#                'xenapi.host.certificate_install'    : (['Pool'],
#                                                        ['Host.getHandle()']),
                'xenapi.host.abort_new_master'       : (['Pool'],
                                                        ['Host.getHandle()']),
                'xenapi.host.management_disable'     : (['Pool'],
                                                        []),
                'xenapi.host.ha_stop_daemon'         : (['Pool'],
                                                        ['Host.getHandle()']),
                'xenapi.host.evacuate'               : (['Pool'],
                                                        ['Host.getHandle()']),
                'xenapi.host.local_assert_healthy'   : (['Pool'],
                                                        []),
                'xenapi.host.disable'                : (['Pool'],
                                                        ['Host.getHandle()']),
#                'xenapi.host.propose_new_master'     : (['Pool'],
#                                                        ['Host.getHandle()', True]),
                'xenapi.host.dmesg'                  : (['Pool'],
                                                        ['Host.getHandle()'],
                                                        ["Pool"]),
#                'xenapi.host.crl_uninstall'          : (['Pool'],
#                                                        ['Host.getHandle()']),
#                'xenapi.host.call_plugin'            : (['Pool'],
#                                                        ['Host.getHandle()']),
#                'xenapi.host.crl_list'               : (['Pool'],
#                                                        ['Host.getHandle()']),
#                'xenapi.host.preconfigure_ha'        : (['Pool'],
#                                                        ['Host.getHandle()']),
                'xenapi.host.ha_disable_failover_decisions' : (['Pool'],
                                                        ['Host.getHandle()']),
#                'xenapi.host.crl_install'            : (['Pool'],
#                                                        ['Host.getHandle()']),
#                'xenapi.host.request_backup'         : (['Pool'],
#                                                        ['Host.getHandle()', "0", False]),
                'xenapi.host.enable'                 : (['Pool'],
                                                        ['Host.getHandle()']),
#                'xenapi.host.enable_external_auth'   : (['Pool'],
#                                                        ['Host.getHandle()']),
#                'xenapi.host.certificate_uninstall'  : (['Pool'],
#                                                        ['Host.getHandle()']),
                'xenapi.host.send_debug_keys'        : (['Pool'],
                                                        ['Host.getHandle()', "X"]),
                'xenapi.host.compute_memory_overhead': ([],
                                                        ['Host.getHandle()']),
                'xenapi.host.syslog_reconfigure'     : (['Pool'],
                                                        ['Host.getHandle()']),
                'xenapi.host.sync_data'              : (['Pool'],
                                                        ['Host.getHandle()']),
#                'xenapi.host.power_on'               : (['Pool'],
#                                                        ['Host.getHandle()']),
                'xenapi.host.ha_wait_for_shutdown_via_statefile' : (['Pool'],
                                                        ['Host.getHandle()']),
                'xenapi.host.ha_disarm_fencing'      : (['Pool'],
                                                       ['Host.getHandle()']),
#                'xenapi.host.shutdown'               : (['Pool'],
#                                                        ['Host.getHandle()']),
                'xenapi.host.record_data_source'     : (['Pool'],
                                                        ['Host.getHandle()', 'cpu0']),
#                'xenapi.host.ha_join_liveset'        : (['Pool'],
#                                                        ['Host.getHandle()']),
                'xenapi.host.add_tags'               : (['Pool'],
                                                        ['Host.getHandle()', 'X']),
                'xenapi.host.enable_local_storage_caching' : (['DisabledHost', 'Pool', 'SR'],
                                                        ['Host.getHandle()', 'SR.getHandle()']),
                'xenapi.host.disable_local_storage_caching' : (['DisabledHost', 'Pool'],
                                                        ['Host.getHandle()']),
                'xenapi.host.certificate_list'       : (['Host'],
                                                        ['Host.getHandle()'],
                                                        ['Host']),
#                'xenapi.host.commit_new_master'      : (['Pool'],
#                                                        ['Host.getHandle()']),
                'xenapi.host.notify'                 : (['Pool'],
                                                        ['Host.getHandle()', ""]),
                'xenapi.host.list_methods'           : (['Pool'],
                                                        [],
                                                        ["Pool"]),
#                'xenapi.host.update_master'          : (['Pool'],
#                                                        ['Host.getHandle()']),
                'xenapi.host.shutdown_agent'         : (['Pool'],
                                                        []),
                'xenapi.host.remove_tags'            : (['Pool'],
                                                        ['Host.getHandle()', 'X']),
                'xenapi.host.create_new_blob'        : (['Pool'],
                                                        ['Host.getHandle()', 'blob', '']),
                'xenapi.host.assert_can_evacuate'    : (['Pool'],
                                                        ['Host.getHandle()'],
                                                        ['Pool']),
                'xenapi.host.restart_agent'          : (['Pool'],
                                                        ['Host.getHandle()']),
                'xenapi.host.disable_binary_storage' : (['Pool'],
                                                        ['Host.getHandle()']),
                'xenapi.host.query_data_source'      : (['Pool'],
                                                        ['Host.getHandle()', 'cpu0'],
                                                        ["Pool"]),
                'xenapi.host.update_pool_secret'     : (['Pool'],
                                                        ['Host.getHandle()', "xensecret"],
                                                        ['Pool']),
#                'xenapi.host.certificate_list'       : (['Pool'],
#                                                        ['Host.getHandle()']),
                'xenapi.host.destroy'                : (['DisabledHost'],
                                                        ['DisabledHost.getHandle()']),
#                'xenapi.host.backup_rrds'            : (['Pool'],
#                                                        ['Host.getHandle()', '5']),
                'xenapi.host.management_reconfigure' : (['Pool', 'PIF'],
                                                        ['PIF.getHandle()']),
#                'xenapi.host.emergency_ha_disable'   : (['Pool'],
#                                                        []),
                'xenapi.host.request_config_file_sync' : (['Pool'],
                                                          ['Host.getHandle()', 'Host.getHandle()'],
                                                          ['Pool']),
#                'xenapi.host.create'                 : (['Pool'],
#                                                        ['Host.getHandle()']),
                'xenapi.host.dmesg_clear'            : (['Pool'],
                                                        ['Host.getHandle()'],
                                                        ['Pool']),
#                'xenapi.host.certificate_sync'       : (['Pool'],
#                                                        ['Host.getHandle()']),
                'xenapi.host.get_uncooperative_domains' : (['Pool'],
                                                           ['Host.getHandle()'],
                                                           ['Pool']),
#                'xenapi.host.license_apply'          : (['Pool'],
#                                                        ['Host.getHandle()']),
                'xenapi.host.signal_networking_change' : (['Pool'],
                                                          [],
                                                          ['Pool']),
                'xenapi.message.create'              : ([],
                                                        ["X",
                                                         "1",
                                                         "host",
                                                         "Host.getUUID()",
                                                         "X"]),
                'xenapi.message.destroy'             : (["Message"],
                                                        ["Message.getHandle()"]),
                'xenapi.PBD.plug'                    : (['UnpluggedPBD'],
                                                        ['UnpluggedPBD.getHandle()']),
                'xenapi.PBD.destroy'                 : (['UnpluggedPBD'],
                                                        ['UnpluggedPBD.getHandle()']),
#                'xenapi.PBD.create'                  : (['BareSR'],
#                                                        [{'SR'              : 'BareSR.getHandle()', 
#                                                          'host'            : 'Host.getHandle()', 
#                                                          'other_config'    : {}, 
#                                                          'device_config': {}}]),
                'xenapi.PBD.unplug'                  : (['PBD'],
                                                        ['PBD.getHandle()']),
#                'xenapi.pool.send_wlb_configuration' : (['Pool'],
#                                                        [[]]),
                'xenapi.pool.emergency_reset_master' : (['Pool', 'Master'],
                                                        ['Master.ref.machine.ipaddr']),
                'xenapi.pool.recover_slaves'         : (['Pool'],
                                                        []),
                'xenapi.pool.enable_local_storage_caching'         : (['DisabledHost', 'Pool'],
                                                        ["Pool.getHandle()"]),
                'xenapi.pool.disable_local_storage_caching'         : (['DisabledHost', 'Pool'],
                                                        ["Pool.getHandle()"]),
                'xenapi.pool.ha_compute_max_host_failures_to_tolerate' : (['Pool'],
                                                        []),
#                'xenapi.pool.disable_ha'             : (['Pool'],
#                                                        []),
#                'xenapi.pool.enable_external_auth'   : (['Pool'],
#                                                        ['Pool.getHandle()']),
#                'xenapi.pool.retrieve_wlb_recommendations' : (['Pool'],
#                                                        []),
#                'xenapi.pool.ha_prevent_restarts_for' : (['Pool'],
#                                                        ['0']),
                'xenapi.pool.ha_compute_vm_failover_plan' : (['Pool'],
                                                        [[], []]),
                'xenapi.pool.is_slave'               : (['Pool'],
                                                        ['Pool.getHandle()']),
                'xenapi.pool.initial_auth'           : (['Pool'],
                                                        []),
                'xenapi.pool.emergency_transition_to_master' : (['Pool'],
                                                        []),
#                'xenapi.pool.disable_external_auth'  : (['Pool'],
#                                                        ['Pool.getHandle()']),
                'xenapi.pool.add_tags'               : (['Pool'],
                                                        ['Pool.getHandle()', 'X']),
                'xenapi.pool.enable_binary_storage'  : (['Pool'],
                                                        []),
#                'xenapi.pool.hello'                  : (['Pool'],
#                                                        ['Host.getUUID()', 'Host.ref.machine.ipaddr']),
                'xenapi.pool.ha_compute_hypothetical_max_host_failures_to_tolerate' : (['Pool'],
                                                        [{}]),
#                'xenapi.pool.crl_uninstall'          : (['Pool'],
#                                                        ['Pool.getHandle()']),
#                'xenapi.pool.retrieve_wlb_configuration' : (['Pool'],
#                                                        []),
                'xenapi.pool.detect_nonhomogeneous_external_auth' : (['Pool'],
                                                        ['Pool.getHandle()']),
                'xenapi.pool.disable_binary_storage' : (['Pool'],
                                                        []),
                'xenapi.pool.create_new_blob'        : (['Pool'],
                                                        ['Pool.getHandle()', 'blob', '']),
#                'xenapi.pool.create_VLAN_from_PIF'   : (['Pool', 'PIF', 'Network'],
#                                                        ['PIF.getHandle()', 'Network.getHandle()', '1024']),
#                'xenapi.pool.designate_new_master'   : (['Pool'],
#                                                        ['Pool.getHandle()']),
#                'xenapi.pool.initialize_wlb'         : (['Pool'],
#                                                        ['Pool.getHandle()']),
#                'xenapi.pool.slave_network_report'   : (['Pool'],
#                                                        ['Pool.getHandle()']),
#                'xenapi.pool.crl_install'            : (['Pool'],
#                                                        ['Pool.getHandle()']),
#                'xenapi.pool.certificate_install'    : (['Pool'],
#                                                        ['Pool.getHandle()']),
                'xenapi.pool.crl_list'               : (['Pool'],
                                                        []),
#                'xenapi.pool.ha_schedule_plan_recomputation' : (['Pool'],
#                                                        []),
                'xenapi.pool.certificate_list'       : (['Pool'],
                                                        []),
                'xenapi.pool.certificate_sync'       : (['Pool'],
                                                        []),
                'xenapi.pool.sync_database'          : (['Pool'],
                                                        []),
#                'xenapi.pool.enable_ha'              : (['Pool'],
#                                                        ['Pool.getHandle()']),
#                'xenapi.pool.deconfigure_wlb'        : (['Pool'],
#                                                        []),
                'xenapi.pool.remove_tags'            : (['Pool'],
                                                        ['Pool.getHandle()', 'X']),
#                'xenapi.pool.send_test_post'         : (['Pool'],
#                                                        ['localhost', '80', 'X']),
#                'xenapi.pool.certificate_uninstall'  : (['Pool'],
#                                                        ['Pool.getHandle()']),
#                'xenapi.pool.join_force'             : (['Pool', 'Master'],
#                                                        ['Master.ref.machine.ipaddr', 
#                                                         'root', 
#                                                         'xensource']),
                'xenapi.pool.ha_failover_plan_exists' : (['Pool'],
                                                         ['0']),
#                'xenapi.pool.eject'                  : (['Pool'],
#                                                        ['Pool.getHandle()']),
                'xenapi.pool.create_VLAN'            : (['Pool', 'Network'],
                                                        ['eth0', 'Network.getHandle()', '1024']),
#                'xenapi.pool.join'                   : (['Pool', 'Master'],
#                                                        ['Master.ref.machine.ipaddr', 
#                                                         'root', 
#                                                         'xensource']),
#                'xenapi.pool_patch.apply'            : (),
#                'xenapi.pool_patch.clean'            : (),
#                'xenapi.pool_patch.destroy'          : (),
#                'xenapi.pool_patch.pool_apply'       : (),
#                'xenapi.pool_patch.precheck'         : (),
                'xenapi.secret.create'               : ([],
                                                        [{"value":"xenrttest"}]),
                'xenapi.secret.destroy'              : (["Secret"], ["Secret.getHandle()"]),
                'xenapi.secret.introduce'            : ([],
                                                        ["00000000-0000-000-000-000000000000",
                                                         "xenrttest"]),
                'xenapi.VMPP.create'                 : ([],
                                                        [{"name_label":"vmpprbac",
                                                          "name_description":"rbacvmpp",
                                                          "backup_type":"snapshot",
                                                          "backup_frequency":"weekly",
                                                          "backup_schedule":{}}]),
                'xenapi.VMPP.destroy'                : (["VMPP"],
                                                        ["VMPP.getHandle()"]),
                'xenapi.session.change_password'     : ([],
                                                        [xenrt.TEC().lookup("ROOT_PASSWORD"),
                                                         xenrt.TEC().lookup("ROOT_PASSWORD")]),
                'xenapi.session.local_logout'        : (["Session"], []),
#                'xenapi.session.login_with_password' : (),
                'xenapi.session.logout'              : (["Session"], []),
#                'xenapi.session.logout_subject_identifier' : (),
#                'xenapi.session.slave_local_login'   : (),
#                'xenapi.session.slave_local_login_with_password' : (),
#                'xenapi.session.slave_login'         : (["Session"], [POOL_TOKEN]),
                 'xenapi.subject.create'              : ([], [{"subject_identifier":"xenrttest"}]),
                 'xenapi.subject.destroy'             : (["Subject"], ["Subject.getHandle()"]),
#                'xenapi.task.cancel'                 : (["Task"],
#                                                        ["Task.getHandle()"]),
#                'xenapi.task.create'                 : ([],
#                                                        ["X", "X"]),
#                'xenapi.task.destroy'                : (["Task"],
#                                                        ["Task.getHandle()"])
                 'xenapi.user.create'                 : ([], [{"short_name":"xrttest", "fullname":"xenrttest", "other-config":{}}]),
                 'xenapi.user.destroy'                : (["User"], ["User.getHandle()"]),
                 'xenapi.GPU_group.create'            : ([], ['abc']),
                 'xenapi.GPU_group.destroy'           : (["GPU_group"],["GPU_group.getHandle()"]),
                 'xenapi.VGPU.create'                 : (["HaltedVM","GPU_group"], ["HaltedVM.getHandle()","GPU_group.getHandle()"]),
                 'xenapi.VGPU.destroy'                : (["VGPU"],["VGPU.getHandle()"])
               } 

    # TODO xenapi.PIF.create_VLAN
    # TODO xenapi.PIF.db_forget
    # TODO xenapi.PIF.db_introduce
    # TODO xenapi.PIF.destroy
    # TODO xenapi.PIF.forget
    # TODO xenapi.PIF.introduce
    # TODO xenapi.PIF.plug
    # TODO xenapi.PIF.pool_introduce
    # TODO xenapi.PIF.reconfigure_ip
    # TODO xenapi.PIF.scan
    # TODO xenapi.PIF.unplug
    # TODO xenapi.VTPM.create
    # TODO xenapi.VTPM.destroy
    # TODO xenapi.crashdump.destroy
    # TODO xenapi.event.next
    # TODO xenapi.event.register
    # TODO xenapi.event.unregister
    # TODO xenapi.host_crashdump.destroy
    # TODO xenapi.host_crashdump.upload

    # TODO xenapi.system.listMethods

    # XXX xenapi.console.create ['INTERNAL_ERROR', 'Server_helpers.Dispatcher_FieldNotFound("other_config")']
    # XXX xenapi.console.destroy ['NOT_IMPLEMENTED', 'Console.destroy']

    def prepare(self, arglist):
  
        testcases.xenserver.tc.security._RBAC.prepare(self, arglist)
        #for old builds host.management_disable should fail with Protocol Error
        #6.0 onwards it should not throw any error 
        if isinstance(self.pool.master, xenrt.lib.xenserver.BostonHost):
           self.FATAL["xenapi.host.management_disable"]=None
             
        self.OPERATIONS["api"] = []
        calls = filter(lambda x:not re.search("\.get", x), self.PERMISSIONS)
        calls = filter(lambda x:not re.search("\.set", x), calls)
        calls = filter(lambda x:not re.search("\.add_to", x), calls)
        calls = filter(lambda x:not re.search("\.remove_from", x), calls)
        calls = filter(lambda x:not re.search("/", x), calls)
        calls = self.clearwaterAPICallCheck(calls)
        for call in calls: 
            apiargs = {}
            apiargs["operation"] = call
            if call in self.CONFIG:
                # TODO Needs a tidy up.
                if len(self.CONFIG[call]) == 3:
                    environment, parameters, keep = self.CONFIG[call]
                else:
                    environment, parameters = self.CONFIG[call]
                    keep = []
                apiargs["environment"] = environment 
                apiargs["parameters"] = copy.deepcopy(parameters)
                apiargs["keep"] = keep
                self.OPERATIONS["api"].append(self.apiFactory(apiargs))

    def postRun(self):
        testcases.xenserver.tc.security._RBAC.postRun(self)
        self.pool.master.execdom0("rm -rf %s" % (self.FILESR))
            
class _APITestFilter(_APITest):

    FN = lambda x:x

    def prepare(self, arglist):
        _APITest.prepare(self, arglist)
        self.OPERATIONS["api"] = filter(self.FN, self.OPERATIONS["api"])

class _DebugTest(_APITestFilter):

    FN = lambda self,x:re.search("secret", x.operation)

    ROLES = {"user" : ["pool-admin"]}

class _BasicTest(_APITestFilter):

    NOMODIFY = False
    NOREVERT = False
    MROLES = {}

    FN = lambda self,x:re.search("xenapi.VM.start_on", x.operation)

    def setRoles(self, old, new):
        self.context.cache.clear()
        for user in old:
            subject = self.authserver.getSubject(name=user)
            for role in old[user]:
                self.pool.removeRole(subject, role)
            for role in new[user]:
                self.pool.addRole(subject, role)

    def modify(self):
        self.setRoles(self.ROLES, self.MROLES)

    def revert(self):
        self.setRoles(self.MROLES, self.ROLES)

class _NetworkTest(_APITestFilter):

    FN = lambda self,x:re.search("\.network\.", x.operation)

class _VIFTest(_APITestFilter):

    FN = lambda self,x:re.search("\.VIF\.", x.operation)

class _VLANTest(_APITestFilter):

    FN = lambda self,x:re.search("\.VLAN\.", x.operation)

class _VBDTest(_APITestFilter):

    FN = lambda self,x:re.search("\.VBD\.", x.operation)

class _SRTest(_APITestFilter):

    FN = lambda self,x:re.search("\.SR\.", x.operation)

class _VDITest(_APITestFilter):

    FN = lambda self,x:re.search("\.VDI\.", x.operation)

class _VMTest(_APITestFilter):

    FN = lambda self,x:re.search("\.VM\.", x.operation)

class _PBDTest(_APITestFilter):

    FN = lambda self,x:re.search("\.PBD\.", x.operation)

class _HostTest(_APITestFilter):

    FN = lambda self,x:re.search("\.host\.", x.operation)

class _PoolTest(_APITestFilter):

    FN = lambda self,x:re.search("\.pool\.", x.operation)

class _MiscTest(_APITestFilter):

    FN = lambda self,x:not re.search("\.pool\.|\.host\.|\.network\.|\.VIF\.|" \
                                     "\.VLAN\.|\.VBD\.|\.SR\.|\.VDI\.|\.VM\.|\.PBD\.", x.operation)
                                     
class TC9859(_PoolTest):

    ROLES = {"user" : ["pool-admin"]}

class TC9835(_HostTest):

    ROLES = {"user" : ["pool-admin"]}

class TC9847(_NetworkTest):

    ROLES = {"user" : ["pool-admin"]}

class TC9889(_VIFTest):

    ROLES = {"user" : ["pool-admin"]}

class TC9895(_VLANTest):

    ROLES = {"user" : ["pool-admin"]}

class TC9877(_VBDTest):

    ROLES = {"user" : ["pool-admin"]}

class TC9865(_SRTest):

    ROLES = {"user" : ["pool-admin"]}

class TC9883(_VDITest):

    ROLES = {"user" : ["pool-admin"]}

class TC9901(_VMTest):

    ROLES = {"user" : ["pool-admin"]}

class TC9853(_PBDTest):

    ROLES = {"user" : ["pool-admin"]}

class TC9841(_MiscTest):

    ROLES = {"user" : ["pool-admin"]}

class TC9829(_APIGet):

    ROLES = {"user" : ["pool-admin"]}

class TC9871(_APISet):

    ROLES = {"user" : ["pool-admin"]}

class TC9823(_APIAddRemove):

    ROLES = {"user" : ["pool-admin"]}

class TC9860(_PoolTest):

    ROLES = {"user" : ["pool-operator"]}

class TC9836(_HostTest):

    ROLES = {"user" : ["pool-operator"]}

class TC9848(_NetworkTest):

    ROLES = {"user" : ["pool-operator"]}

class TC9890(_VIFTest):

    ROLES = {"user" : ["pool-operator"]}

class TC9896(_VLANTest):

    ROLES = {"user" : ["pool-operator"]}

class TC9878(_VBDTest):

    ROLES = {"user" : ["pool-operator"]}

class TC9866(_SRTest):

    ROLES = {"user" : ["pool-operator"]}

class TC9884(_VDITest):

    ROLES = {"user" : ["pool-operator"]}

class TC9902(_VMTest):

    ROLES = {"user" : ["pool-operator"]}

class TC9854(_PBDTest):

    ROLES = {"user" : ["pool-operator"]}

class TC9842(_MiscTest):

    ROLES = {"user" : ["pool-operator"]}

class TC9830(_APIGet):

    ROLES = {"user" : ["pool-operator"]}

class TC9872(_APISet):

    ROLES = {"user" : ["pool-operator"]}

class TC9824(_APIAddRemove):

    ROLES = {"user" : ["pool-operator"]}

class TC9861(_PoolTest):

    ROLES = {"user" : ["vm-power-admin"]}

class TC9837(_HostTest):

    ROLES = {"user" : ["vm-power-admin"]}

class TC9849(_NetworkTest):

    ROLES = {"user" : ["vm-power-admin"]}

class TC9891(_VIFTest):

    ROLES = {"user" : ["vm-power-admin"]}

class TC9897(_VLANTest):

    ROLES = {"user" : ["vm-power-admin"]}

class TC9879(_VBDTest):

    ROLES = {"user" : ["vm-power-admin"]}

class TC9867(_SRTest):

    ROLES = {"user" : ["vm-power-admin"]}

class TC9885(_VDITest):

    ROLES = {"user" : ["vm-power-admin"]}

class TC9903(_VMTest):

    ROLES = {"user" : ["vm-power-admin"]}

class TC9855(_PBDTest):

    ROLES = {"user" : ["vm-power-admin"]}

class TC9843(_MiscTest):

    ROLES = {"user" : ["vm-power-admin"]}

class TC9831(_APIGet):

    ROLES = {"user" : ["vm-power-admin"]}

class TC9873(_APISet):

    ROLES = {"user" : ["vm-power-admin"]}

class TC9825(_APIAddRemove):

    ROLES = {"user" : ["vm-power-admin"]}

class TC9862(_PoolTest):

    ROLES = {"user" : ["vm-admin"]}

class TC9838(_HostTest):

    ROLES = {"user" : ["vm-admin"]}

class TC9850(_NetworkTest):

    ROLES = {"user" : ["vm-admin"]}

class TC9892(_VIFTest):

    ROLES = {"user" : ["vm-admin"]}

class TC9898(_VLANTest):

    ROLES = {"user" : ["vm-admin"]}

class TC9880(_VBDTest):

    ROLES = {"user" : ["vm-admin"]}

class TC9868(_SRTest):

    ROLES = {"user" : ["vm-admin"]}

class TC9886(_VDITest):

    ROLES = {"user" : ["vm-admin"]}

class TC9904(_VMTest):

    ROLES = {"user" : ["vm-admin"]}

class TC9856(_PBDTest):

    ROLES = {"user" : ["vm-admin"]}

class TC9844(_MiscTest):

    ROLES = {"user" : ["vm-admin"]}

class TC9832(_APIGet):

    ROLES = {"user" : ["vm-admin"]}

class TC9874(_APISet):

    ROLES = {"user" : ["vm-admin"]}

class TC9826(_APIAddRemove):

    ROLES = {"user" : ["vm-admin"]}

class TC9863(_PoolTest):

    ROLES = {"user" : ["vm-operator"]}

class TC9839(_HostTest):

    ROLES = {"user" : ["vm-operator"]}

class TC9851(_NetworkTest):

    ROLES = {"user" : ["vm-operator"]}

class TC9893(_VIFTest):

    ROLES = {"user" : ["vm-operator"]}

class TC9899(_VLANTest):

    ROLES = {"user" : ["vm-operator"]}

class TC9881(_VBDTest):

    ROLES = {"user" : ["vm-operator"]}

class TC9869(_SRTest):

    ROLES = {"user" : ["vm-operator"]}

class TC9887(_VDITest):

    ROLES = {"user" : ["vm-operator"]}

class TC9905(_VMTest):

    ROLES = {"user" : ["vm-operator"]}

class TC9857(_PBDTest):

    ROLES = {"user" : ["vm-operator"]}

class TC9845(_MiscTest):

    ROLES = {"user" : ["vm-operator"]}

class TC9833(_APIGet):

    ROLES = {"user" : ["vm-operator"]}

class TC9875(_APISet):

    ROLES = {"user" : ["vm-operator"]}

class TC9827(_APIAddRemove):

    ROLES = {"user" : ["vm-operator"]}

class TC9864(_PoolTest):

    ROLES = {"user" : ["read-only"]}

class TC9840(_HostTest):

    ROLES = {"user" : ["read-only"]}

class TC9852(_NetworkTest):

    ROLES = {"user" : ["read-only"]}

class TC9894(_VIFTest):

    ROLES = {"user" : ["read-only"]}

class TC9900(_VLANTest):

    ROLES = {"user" : ["read-only"]}

class TC9882(_VBDTest):

    ROLES = {"user" : ["read-only"]}

class TC9870(_SRTest):

    ROLES = {"user" : ["read-only"]}

class TC9888(_VDITest):

    ROLES = {"user" : ["read-only"]}

class TC9906(_VMTest):

    ROLES = {"user" : ["read-only"]}

class TC9858(_PBDTest):

    ROLES = {"user" : ["read-only"]}

class TC9846(_MiscTest):

    ROLES = {"user" : ["read-only"]}

class TC9834(_APIGet):

    ROLES = {"user" : ["read-only"]}

class TC9876(_APISet):

    ROLES = {"user" : ["read-only"]}

class TC9828(_APIAddRemove):

    ROLES = {"user" : ["read-only"]}                                   

class TC10208(TC9847):

    CHECK_AUDIT = True

class TC10209(TC9890):

    CHECK_AUDIT = True

class TC10210(TC9897):

    CHECK_AUDIT = True

class TC10211(TC9880):

    CHECK_AUDIT = True

class TC10212(TC9869):

    CHECK_AUDIT = True

class TC10213(TC9888):

    CHECK_AUDIT = True

class TC10214(_BasicTest):

    ROLES = {"user" : ["pool-admin"]}
    MROLES = {"user" : ["read-only"]}
    
class TC10215(_BasicTest):

    ROLES = {"user" : ["pool-admin"]}
    MROLES = {"user" : ["pool-operator"]}

class TC10216(_BasicTest):

    ROLES = {"user" : ["pool-admin"]}
    MROLES = {"user" : []}        

class TC10217(_BasicTest):

    ROLES = {"user" : ["read-only"]}
    MROLES = {"user" : ["pool-admin"]}
    
class TC10218(_BasicTest):

    ROLES = {"user" : ["pool-operator"]}
    MROLES = {"user" : ["pool-admin"]}

class TC10219(_BasicTest):

    ROLES = {"user" : []}
    MROLES = {"user" : ["pool-admin"]}

class TC10220(_BasicTest):

    ROLES = {"user" : ["read-only", "pool-admin"]}
    MROLES = {"user" : ["read-only"]}   

class TC10725(TC10220):
    """Large pool smoke test."""
    pass

class _GroupRoles(_BasicTest):

    NOMODIFY = True
    NOREVERT = True

    TESTUSERS = ["u1"]

class _MultipleRoles(_BasicTest):

    NOMODIFY = True
    NOREVERT = True

class TC10702(_MultipleRoles):

    ROLES = {"user" : ["pool-admin", "pool-operator", "vm-power-admin", "vm-admin", "vm-operator", "read-only"]}
    
class TC10703(_MultipleRoles):

    ROLES = {"user" : ["pool-admin", "pool-operator", "vm-power-admin", "vm-admin", "vm-operator"]}
    
class TC10704(_MultipleRoles):

    ROLES = {"user" : ["pool-admin", "pool-operator", "vm-power-admin", "vm-admin"]}
    
class TC10705(_MultipleRoles):

    ROLES = {"user" : ["pool-admin", "pool-operator", "vm-power-admin"]}
    
class TC10706(_MultipleRoles):

    ROLES = {"user" : ["vm-power-admin", "vm-admin"]}
    
class TC10707(_MultipleRoles):

    ROLES = {"user" : ["pool-admin", "read-only"]}
    
class TC10708(_GroupRoles):

    SUBJECTGRAPH = """
<subjects>
  <group name="g2">
    <group name="g1">
      <user name="u1"/>
    </group>
  </group>
</subjects>
"""

    ROLES = {"g1":["read-only"],
             "g2":["pool-admin"],
             "u1":["read-only"]} 
    ENABLE = ["u1", "g1", "g2"]

class TC10709(TC10708):

    ROLES = {"g2":["pool-admin"]}
    ENABLE = ["g2"]

class TC10710(_GroupRoles):

    SUBJECTGRAPH = """
<subjects>
  <group name="g1">
    <user name="u1"/>
  </group>
</subjects>
"""

    ROLES = {"g1":["pool-admin"],
             "u1":["read-only"]} 
    ENABLE = ["u1", "g1"]

class TC10711(TC10710):

    ROLES = {"g1":["pool-admin"]}
    ENABLE = ["g1"]

class TC10712(_GroupRoles):

    SUBJECTGRAPH = """
<subjects>
  <group name="g1">
    <user name="u1"/>
  </group>
</subjects>
"""

    ROLES = {"g1":["read-only"],
             "u1":["pool-admin"]} 
    ENABLE = ["u1", "g1"]

class TC10713(TC10712):

    ROLES = {"u1":["pool-admin"]}
    ENABLE = ["u1"]

class TC10714(_GroupRoles):

    SUBJECTGRAPH = """
<subjects>
  <group name="g1">
    <user name="u1"/>
  </group>
  <group name="g2">
    <user name="u1"/>
  </group>
</subjects>
"""

    ROLES = {"g1":["read-only"],
             "g2":["pool-admin"],
             "u1":["read-only"]} 
    ENABLE = ["u1", "g1", "g2"]

class TC10715(TC10714):

    ROLES = {"g2":["pool-admin"]}
    ENABLE = ["g2"]

class TC10716(_GroupRoles):

    SUBJECTGRAPH = """
<subjects>
  <group name="g3">
    <group name="g1">
      <user name="u1"/>
    </group>
    <group name="g2">
      <user name="u1"/>
    </group>
  </group>
</subjects>
"""

    ROLES = {"g1":["read-only"],
             "g2":["read-only"],
             "g3":["pool-admin"],
             "u1":["read-only"]} 
    ENABLE = ["u1", "g1", "g2", "g3"]

class TC10717(TC10716):

    ROLES = {"g3":["pool-admin"]}
    ENABLE = ["g3"]

class TC10719(_APITestFilter):

    ROLES = {"user" : ["pool-admin"]}

    FN = lambda self,x:x.operation in self.SLAVE

    def apiFactory(self, apiargs):
        _APITestFilter.apiFactory(self, apiargs)
        return APICall(**apiargs)
        
    def getValidAPI(self, operation):
        return []
        
