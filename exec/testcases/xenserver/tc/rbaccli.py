#
# XenRT: Test harness for Xen and the XenServer product family
#
# RBAC CLI test cases
#
# Copyright (c) 2009 XenSource, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by XenSource, Inc. All other rights reserved.
#

import re, tempfile, copy, string
import xenrt, testcases.xenserver.tc.security

class _CLITest(testcases.xenserver.tc.security._RBAC):

    LICENSE             = "%s/keys/xenserver/%s/FG_Free" % \
                          (xenrt.TEC().lookup("XENRT_CONF"),
                           xenrt.TEC().lookup("PRODUCT_VERSION", None))

    PATCH               = "%s/patchapply/hotfix-mnr-test2.xsupdate" % \
                          (xenrt.TEC().getWorkdir())

    VLAN                = 1024

    FATAL               = {"host-reboot"        :   None,
                           "pif-introduce"      :   None,
                           "pool-eject"         :   None,
                           "pif-reconfigure-ip" :   "Lost connection to the server"                           
                           }

    LOCAL               = ["log-reopen",
                           "host-signal-networking-change",
                           "host-notify",
                           "host-send-debug-keys",
                           "host-management-disable",
                           "host-get-system-status-capabilities",
                           "host-is-in-emergency-mode",
                           "host-fence",
                           "host-ha-xapi-healthcheck",
                           "host-ha-query",
                           "pool-emergency-transition-to-master",
                           "pool-emergency-reset-master",
                           "pool-emergency-ha-disable",
                           "host-emergency-management-reconfigure",
                           "host-shutdown-agent"]

    ALLOWED             = {"vdi-unlock"                      :   "This message has been deprecated",
                           "user-password-change"            :   "Only the local superuser can execute this operation",
                           "host-set-hostname-live"          :   "authentication for this host is already enabled",
                           "pif-unplug"                      :   "the specified PIF is the management interface",
                           "snapshot-create-template"        :   "Unknown command",
                           #adding two more entries because if the SR doesn't support host-enable-local-storage-caching
                           #it will not pass and there is no way the allowed-operations field value can be changed
                           "host-enable-local-storage-caching" : "SR backend does not support the operation",
                           "pool-enable-local-storage-caching" : "HOSTS_FAILED_TO_ENABLE_CACHING",
                           #adding message for host-evacuate because if the host has a VM running and is in a standalone pool
                           #it will throw an error with message "no hosts available to complete the specified operation"
                           "host-evacuate"                   :   "There were no hosts available to complete the specified operation"}


    CONFIG =    {'bond-create'                     : (["PIF", "SecondaryPIFNPRI", "Pool", "Network"],
                                                      ["network-uuid=Network.getUUID()", 
                                                       "pif-uuids=PIF.getUUID(),SecondaryPIFNPRI.getUUID()"]),
                 'bond-destroy'                    : (["Bond"], ["uuid=Bond.getUUID()"]),
                 # 'bond-list'                       : ([],[]),
                 'cd-list'                         : ([],[]),
                 # 'console-list'                    : ([],[]),
                 # 'diagnostic-compact'              : ([],[]),
                 # 'diagnostic-db-log'               : ([],
                 #                                      [],
                 #                                      []),
                 # 'diagnostic-db-stats'             : ([],[]),
                 # 'diagnostic-gc-stats'             : ([],[]),
                 'diagnostic-license-status'       : ([],[]),
                 'diagnostic-timing-stats'         : ([],[]),
                 'diagnostic-vdi-status'           : (["VDI"],
                                                      ["uuid=VDI.getUUID()"]),
                 'diagnostic-vm-status'            : (["VM"],
                                                      ["uuid=VM.getUUID()"]),
                 'event-wait'                      : ([],
                                                      ["class=vm"]),
                 'host-backup'                     : (["TempFile"],
                                                      ["file-name=TempFile.ref"]),
#                 'host-bugreport-upload'           : ([],[]),
                 'host-call-plugin'                : ([],
                                                      ["host-uuid=Host.getUUID()",
                                                       "plugin=echo",
                                                       "fn=main"]),
                 'host-compute-free-memory'        : ([],[]),
                 'host-compute-memory-overhead'    : ([],[]),
                 # 'host-cpu-list'                   : ([],[]),
                 'host-enable-local-storage-caching' : (["DisabledHost", "SR"], 
                                                        ["sr-uuid=SR.getUUID()"]),
                 'host-disable-local-storage-caching' : (["DisabledHost"], 
                                                        []),
# TODO Can't generate crashdumps.
#
#                 'host-crashdump-destroy'          : (["Crashdump"],
#                                                      ["Crashdump.getUUID()"],
#                                                      ["Crashdump"]),
#                 'host-crashdump-list'             : ([],[]),
#                 'host-crashdump-upload'           : ([],[]),
#
                 'host-data-source-forget'         : ([],
                                                      ["data-source=cpu0"]),
                 'host-data-source-list'           : ([],[]),
                 'host-data-source-query'          : ([],
                                                      ["data-source=cpu0"]),
                 'host-data-source-record'         : ([],
                                                      ["data-source=cpu0"]),
                 'host-disable'                    : (["Pool"],
                                                      []),
                 'host-dmesg'                      : ([],[]),
#                 'host-emergency-ha-disable'       : (["HAPool"],
#                                                      ["--force"]),
#                 'host-emergency-management-reconfigure' : (["EmergencyPool"],
#                                                      ["interface=eth0"]),
                 'host-enable'                     : ([],[]),
                 'host-evacuate'                   : ([],
                                                      ["uuid=Host.getUUID()"]),
 #                'host-forget'                     : (["DisabledHost"],
 #                                                     ["uuid=Host.getUUID()",
 #                                                      "--force"]),
                 'host-get-server-certificate'     : ([],[]),
                 'host-get-system-status'          : (["TempFile"],
                                                      ["filename=TempFile.ref"]),
                 'host-get-system-status-capabilities' : ([],[]),
                 'host-get-vms-which-prevent-evacuation' : ([],
                                                      ["uuid=Host.getUUID()"]),
                 'host-is-in-emergency-mode'       : ([],[]),
                 'host-license-add'                : (["FreeHost"],
                                                      ["host-uuid=FreeHost.getUUID()",
                                                       "license-file=%s" % (LICENSE)]),
                 'host-license-view'               : ([],[]),
                 # 'host-list'                       : ([],[]),
                 'host-logs-download'              : ([],[]),
                 'host-management-disable'         : ([],[]),
                 'host-management-reconfigure'     : (["PIF"],
                                                      ["pif-uuid=PIF.getUUID()"]),
#                 'host-power-on'                   : ([],[]),
                 'host-reboot'                     : (["DisabledHost"],[]),
                 'host-restore'                    : (["Pool", "HostBackup"],
                                                      ["file-name=HostBackup.filename"]),
                 'host-retrieve-wlb-evacuate-recommendations' : (["KirkwoodPool"],
                                                      ["uuid=Host.getUUID()"]),
                 'host-send-debug-keys'            : ([],
                                                      ["host-uuid=Host.getUUID()",
                                                       "keys=X"]),
                 'host-set-hostname-live'          : ([],
                                                      ["host-uuid=Host.getUUID()",
                                                       "host-name=Host.ref.machine.name"], 
                                                      []),
#                 'host-shutdown'                   : ([],
#                                                      [],
#                                                      ["Host"]),
                 'host-shutdown-agent'             : (["Pool"],   
                                                      []),
                 'host-sync-data'                  : ([],[]),
                 'host-syslog-reconfigure'         : ([],
                                                      ["host-uuid=Host.getUUID()"]),
                 # 'log-get'                         : ([],[]),
                 # 'log-get-keys'                    : ([],[]),
                 # 'log-reopen'                      : ([],[]),
                 # 'log-set-output'                  : ([],
                 #                                      ["output="]),
                 'message-create'                  : ([],
                                                      ["body=X",
                                                       "name=X",
                                                       "priority=1",
                                                       "host-uuid=Host.getUUID()"]),
                 # 'message-list'                    : ([],[]),
                 'network-create'                  : ([],
                                                      ["name-label=X"]),
                 'network-destroy'                 : (["Network"],
                                                      ["uuid=Network.getUUID()"]),
                 # 'network-list'                    : ([],[]),
#                 'patch-apply'                     : (["Patch"],
#                                                      ["host-uuid=Host.getUUID()",
#                                                       "uuid=Patch.getUUID()"]),
                 'patch-clean'                     : (["Patch"],
                                                      ["uuid=Patch.getUUID()"]),
                 'patch-destroy'                   : (["Patch"],
                                                      ["uuid=Patch.getUUID()"]),
                 # 'patch-list'                      : ([],[]),
 #                'patch-pool-apply'                : (["Patch"],
 #                                                     ["uuid=Patch.getUUID()"]),
 #                'patch-precheck'                  : (["Patch"],
 #                                                     ["host-uuid=Host.getUUID()",
 #                                                      "uuid=Patch.getUUID()"]),
 #                'patch-upload'                    : (["Patch"],
 #                                                     ["file-name=%s" % (PATCH)]),
                 'pbd-create'                      : (["BareSR"],
                                                      ["host-uuid=Host.getUUID()",
                                                       "sr-uuid=BareSR.getUUID()",
                                                       "device-config:location=BareSR.location"]),
                 'pbd-destroy'                     : (["UnpluggedPBD"],
                                                      ["uuid=UnpluggedPBD.getUUID()"]),
                 # 'pbd-list'                        : ([],[]),
                 'pbd-plug'                        : (["UnpluggedPBD"],
                                                      ["uuid=UnpluggedPBD.getUUID()"]),
                 'pbd-unplug'                      : (["PBD"],
                                                      ["uuid=PBD.getUUID()"]),
                 'pif-forget'                      : (["PIF"],
                                                      ["uuid=PIF.getUUID()"]),
#                 'pif-introduce'                   : (["PIF"],
#                                                      ["host-uuid=Host.getUUID()",
#                                                       "mac=00:1B:21:06:C9:4C"]), #TODO
                 # 'pif-list'                        : ([],[]),
#                 'pif-plug'                        : ([],[]),
                 'pif-reconfigure-ip'              : (["SecondaryPIFNPRI"],
                                                      ["uuid=SecondaryPIFNPRI.getUUID()",
                                                       "mode=dhcp"]),
                 'pif-scan'                        : ([],
                                                      ["host-uuid=Host.getUUID()"]),
                 'pif-unplug'                      : (["PIF"],
                                                      ["uuid=PIF.getUUID()"]),
# TODO Bug in certficate filenames (no absolute paths allowed).
#
#                 'pool-certificate-install'        : ([],
#                                                      ["filename=%s" % (CERT)]),
                 'pool-certificate-list'           : ([],[]),
                 'pool-certificate-sync'           : ([],[]),
#                 'pool-certificate-uninstall'      : ([],
#                                                     ["name=%s" % (os.path.basename(CERT))]),
#                 'pool-crl-install'                : ([],
#                                                      ["filename=%s" % (CERT)]),
                 'pool-crl-list'                   : ([],[]),
#                 'pool-crl-uninstall'              : ([],
#                                                     ["name=%s" % (os.path.basename(CERT))]),
                 'pool-deconfigure-wlb'            : (["KirkwoodPool"],
                                                      []),
                 'pool-designate-new-master'       : ([],
                                                      ["host-uuid=Host.getUUID()"]),
#                 'pool-disable-external-auth'      : ([],[]),
                 'pool-disable-redo-log'           : ([],[]),
                 'pool-dump-database'              : (["TempFile"],
                                                      ["file-name=TempFile.ref"]),
#                 'pool-eject'                      : (["Pool"],
#                                                      ["host-uuid=Slave.getUUID()",
#                                                       "--force"]),
                 'pool-emergency-reset-master'     : (["Pool"],
                                                      ["master-address=Host.ref.machine.ipaddr"]),
                 'pool-emergency-transition-to-master' : (["Pool"],[]),
                 'pool-enable-binary-storage'      : ([], []),
                 'pool-disable-binary-storage'     : ([], []),
                 'pool-enable-local-storage-caching'     : (['DisabledHost'], 
                                                            ['uuid=Pool.getUUID()']),
                 'pool-disable-local-storage-caching'     : (['DisabledHost'], 
                                                            ['uuid=Pool.getUUID()']),
#                 'pool-enable-external-auth'       : ([],
#                                                      []),
#                 'pool-enable-redo-log'            : (["SR"],
#                                                      ["sr-uuid=SR.getUUID()"]),
                 'pool-ha-compute-hypothetical-max-host-failures-to-tolerate' : ([],[]),
                 'pool-ha-compute-max-host-failures-to-tolerate' : ([],[]),
                 'pool-ha-compute-vm-failover-plan' : (['Pool'],
                                                       ['host-uuids=Host.getUUID()'], 
                                                       ['Pool']),
#                 'pool-ha-disable'                 : (["HAPool"],
#                                                      []),
#                 'pool-ha-enable'                  : (["DisabledHAPool"],
#                                                      []),
                 'pool-initialize-wlb'             : (["Kirkwood"],
                                                      ["wlb_url=Kirkwood.ref.ip:Kirkwood.ref.port",
                                                       "wlb_username=root",
                                                       "wlb_password=%s" % xenrt.TEC().lookup("ROOT_PASSWORD"),
                                                       "xenserver_username=root",
                                                       "xenserver_password=%s" % xenrt.TEC().lookup("ROOT_PASSWORD")]),
#                 'pool-join'                       : ([],[]),
                 # 'pool-list'                       : ([],[]),
                 'pool-recover-slaves'             : ([],[]),
#                 'pool-restore-database'           : ([],[]),
                 'pool-retrieve-wlb-configuration' : (["KirkwoodPool"],
                                                      []),
#                 'pool-retrieve-wlb-diagnostics'   : (["KirkwoodPool"],
#                                                      []),
                 'pool-retrieve-wlb-recommendations' : (["KirkwoodPool"],
                                                        []),
                 'pool-retrieve-wlb-report'        : (["KirkwoodPool"],
                                                      ["report=X"]),
#                 'pool-send-test-post'             : (["KirkwoodPool"],
#                                                      ["dest-host=Kirkwood.ip",
#                                                       "dest-port=Kirkwood.port",
#                                                       "body=X"]),
                 'pool-send-wlb-configuration'     : (["KirkwoodPool"],[]),
                 'pool-sync-database'              : ([],[]),
                 'pool-vlan-create'                : (["PIF", "Network", "Pool"],
                                                      ["network-uuid=Network.getUUID()",
                                                       "pif-uuid=PIF.getUUID()",
                                                       "vlan=%s" % (VLAN)]),
                 # 'regenerate-built-in-templates'   : ([], []),
                 # 'role-list'                       : ([], []),
                 # 'secret-list'                     : ([], []),
                 'secret-create'                   : ([], ["value=xenrtvalue"]),
                 'secret-destroy'                  : (["Secret"], 
                                                      ["uuid=Secret.getUUID()"]),
                 'session-subject-identifier-list' : ([],[]),
                 'session-subject-identifier-logout' : ([],
                                                        ["subject-identifier=X"]),
                 'session-subject-identifier-logout-all' : ([],[]),
                 # 'sm-list'                         : ([],[]),
                 'snapshot-destroy'                : (["Snapshot"],
                                                      ["snapshot-uuid=Snapshot.getUUID()",
                                                       "--force"]),
                 'snapshot-disk-list'              : (["Snapshot"],
                                                      ["snapshot-uuid=Snapshot.getUUID()"]),
                 'snapshot-export-to-template'     : (["Snapshot", "TempFile"],
                                                      ["snapshot-uuid=Snapshot.getUUID()",
                                                       "filename=TempFile.ref"]),
#                 'snapshot-list'                   : ([],[]),
                 'snapshot-reset-powerstate'       : (["Snapshot"],
                                                      ["snapshot-uuid=Snapshot.getUUID()",
                                                       "--force"]),
                 'snapshot-revert'                 : (["Snapshot"],
                                                      ["snapshot-uuid=Snapshot.getUUID()"]),
                 'snapshot-uninstall'              : (["Snapshot"],
                                                      ["snapshot-uuid=Snapshot.getUUID()",
                                                       "--force"]),
                 'sr-create'                       : (["RemoteTempDir"],
                                                      ["name-label=X",
                                                       "host-uuid=Host.getUUID()",
                                                       "physical-size=1",
                                                       "shared=false",
                                                       "type=file",
                                                       "content-type=user",
                                                       "device-config:location=RemoteTempDir.ref"]),
                 'sr-destroy'                      : (["UnpluggedPBD"],
                                                      ["uuid=NFSSR.getUUID()"]),
                 'sr-forget'                       : (["UnpluggedPBD"],
                                                      ["uuid=NFSSR.getUUID()"]),
                 'sr-introduce'                    : ([],
                                                      ["content-type=user",
                                                       "name-label=X",
                                                       "shared=false",
                                                       "type=file",
                                                       "uuid=`uuidgen`"]),
#                 'sr-list'                         : ([],[]),
                 'sr-probe'                        : (["NFSSR"],
                                                      ["uuid=NFSSR.getUUID()",
                                                       "device-config:server=NFSSR.ref.server",
                                                       "device-config:serverpath=NFSSR.ref.path",
                                                       "type=nfs"]),
                 'sr-scan'                         : (["NFSSR"],
                                                      ["uuid=NFSSR.getUUID()"]),
                 'sr-update'                       : (["SR"],
                                                      ["uuid=SR.getUUID()"]),
                 'subject-add'                     : ([],["subject-name=Administrator"]),
#                 'subject-list'                    : ([],[]),
                 'subject-remove'                  : (["Subject"], ["subject-uuid=Subject.getUUID()"]),
                 'subject-role-add'                : (["Subject", "Role"], 
                                                      ["uuid=Subject.getUUID()", "role-uuid=Role.getUUID()"]),
                 'subject-role-remove'             : (["RoleSubject"], ["uuid=RoleSubject.getUUID()", "role-uuid=Role.getUUID()"]),
                 'task-cancel'                     : (["Task"],
                                                      ["uuid=Task.getUUID()"]),
#                 'task-list'                       : ([],[]),
                 'template-export'                 : (["Template", "TempFile"],
                                                      ["template-uuid=Template.getUUID()",
                                                       "filename=TempFile.ref"]),
#                 'template-list'                   : ([],[]),
                 'template-uninstall'              : (["Template"],
                                                      ["template-uuid=Template.getUUID()",
                                                       "--force"]),
#                 'update-upload'                   : ([],[]),
                 'user-password-change'            : ([],
                                                      ["old=%s" % \
                                                       (xenrt.TEC().lookup("ROOT_PASSWORD")),
                                                       "new=%s" % \
                                                       (xenrt.TEC().lookup("ROOT_PASSWORD"))]),
                 'vbd-create'                      : (["VM"],
                                                      ["bootable=false",
                                                       "device=1", #changing userdevice to 1, to handle device already in use issue
                                                       "mode=RO",
                                                       "type=CD",
                                                       "unpluggable=true",
                                                       "vm-uuid=VM.getUUID()"]),
                 'vbd-destroy'                     : (["UnpluggedVBD"],
                                                      ["uuid=UnpluggedVBD.getUUID()"]),
                 'vbd-eject'                       : (["RemoveableVBD"],
                                                      ["uuid=RemoveableVBD.getUUID()"]),
                 'vbd-insert'                      : (["EmptyVBD", "ISOVDI"],
                                                      ["uuid=EmptyVBD.getUUID()",
                                                       "vdi-uuid=ISOVDI.getUUID()"]),
#                 'vbd-list'                        : ([],[]),
                 'vbd-plug'                        : (["UnpluggedVBD"],
                                                      ["uuid=UnpluggedVBD.getUUID()"]),
                 'vbd-unplug'                      : (["VBD"],
                                                      ["uuid=VBD.getUUID()",
                                                       "--force"]),
                 'vdi-clone'                       : (["VDI"],
                                                      ["uuid=VDI.getUUID()"]),
                 'vdi-copy'                        : (["VDI"],
                                                      ["uuid=VDI.getUUID()",
                                                       "sr-uuid=NFSSR.getUUID()"]),
#                 'vdi-create'                      : (["SR"],
#                                                      ["sr-uuid=SR.getUUID()",
#                                                       "name-label=XenRTVDI",
#                                                       "type=user",
#                                                       "virtual-size=1"]),
                 'vdi-destroy'                     : (["VDI"],
                                                      ["uuid=VDI.getUUID()"]),
                 'vdi-forget'                      : (["VDI"],
                                                      ["uuid=VDI.getUUID()"]),
#                 'vdi-import'                      : (["VDI"],
#                                                      ["uuid=VDI.getUUID()",
#                                                       "filename=%s" % (EXPORTEDVDI)]),
#                 'vdi-introduce'                   : (["SR"],
#                                                      ["uuid=`uuidgen`",
#                                                       "type=user",
#                                                       "shareable=false",
#                                                       "read-only=false",
#                                                       "name-label=XenRTVDI",
#                                                       "sr-uuid=SR.getUUID()",
#                                                       "location="]),
#                 'vdi-list'                        : ([],[]),
                 'vdi-resize'                      : (["VDI"],
                                                      ["uuid=VDI.getUUID()",
                                                       "disk-size=2147483648"]),
                 'vdi-snapshot'                    : (["VDI"],
                                                      ["uuid=VDI.getUUID()"]),
                 'vdi-unlock'                      : (["VDI"],
                                                      ["uuid=VDI.getUUID()",
                                                       "--force"]),
                 'vdi-update'                      : (["VDI"],
                                                      ["uuid=VDI.getUUID()"]),
                 'vif-create'                      : (["Network", "VM"],
                                                      ["device=0",
                                                       "mac=66:db:47:0f:87:95",
                                                       "mtu=1500",
                                                       "network-uuid=Network.getUUID()",
                                                       "vm-uuid=VM.getUUID()"]),
                 'vif-destroy'                     : (["UnpluggedVIF"],
                                                      ["uuid=UnpluggedVIF.getUUID()"]),
#                 'vif-list'                        : (["VIF"],
#                                                      []),
                 'vif-plug'                        : (["UnpluggedVIF"],
                                                      ["uuid=UnpluggedVIF.getUUID()"]),
#                 'vif-unplug'                      : (["RemoveableVIF"],
#                                                      ["uuid=RemoveableVIF.getUUID()"]),
                 'vlan-create'                     : (["PIF", "Network", "Pool"],
                                                      ["pif-uuid=PIF.getUUID()",
                                                       "network-uuid=Network.getUUID()",
                                                       "vlan=%s" % (VLAN)]),
                 'vlan-destroy'                    : (["VLAN"],
                                                      ["uuid=VLAN.getUUID()"]),
                 # 'vlan-list'                       : ([],[]),
                 'vm-cd-add'                       : (["ISOVDI", "VM"],
                                                      ["cd-name=ISOVDI.ISO",
                                                       "device=0",
                                                       "uuid=VM.getUUID()"]),
                 'vm-cd-eject'                     : (["RemoveableVBD"],
                                                      ["uuid=VM.getUUID()"]),
                 'vm-cd-insert'                    : (["EmptyVBD", "ISOVDI"],
                                                      ["cd-name=ISOVDI.ISO",
                                                       "uuid=VM.getUUID()"]),
                 # 'vm-cd-list'                      : (["VM"],
                 #                                      ["uuid=VM.getUUID()"]),
                 'vm-cd-remove'                    : (["RemoveableVBD"],    
                                                      ["cd-name=ISOVDI.ISO",
                                                       "uuid=VM.getUUID()"]),
                 'vm-checkpoint'                   : (["VM"],
                                                      ["new-name-label=X",
                                                       "uuid=VM.getUUID()"]),
                 'vm-clone'                        : (["HaltedVM"],
                                                      ["new-name-label=X",
                                                       "uuid=HaltedVM.getUUID()"]),
                 'vm-compute-maximum-memory'       : (["VM"],
                                                      ["vm=VM.getUUID()",
                                                       "total=1024"]),
                 'vm-compute-memory-overhead'      : (["VM"], ["uuid=VM.getUUID()"]),
                 'vm-copy'                         : (["HaltedVM", "SR"],
                                                      ["vm=HaltedVM.getUUID()",
                                                       "new-name-label=X",
                                                       "sr-uuid=SR.getUUID()"]),
                 'vm-crashdump-list'               : (["VM"],
                                                      ["vm=VM.getUUID()"]),
                 'vm-create'                       : ([], ["name-label=XenRTVM"]),
                 'vm-data-source-forget'           : (["VM"],
                                                      ["data-source=cpu0",
                                                       "vm=VM.getUUID()"]),
                 'vm-data-source-list'             : (["VM"],
                                                      ["vm=VM.getUUID()"]),
                 'vm-data-source-query'            : (["VM"],
                                                      ["data-source=cpu0",
                                                       "vm=VM.getUUID()"]),
                 'vm-data-source-record'           : (["VM"],
                                                      ["data-source=cpu0",
                                                       "vm=VM.getUUID()"]),
                 'vm-destroy'                      : (["HaltedVM"],
                                                      ["uuid=HaltedVM.getUUID()"]),
                 'vm-disk-add'                     : (["SR", "VM"],
                                                      ["device=0",
                                                       "vm=VM.getUUID()",
                                                       "sr-uuid=SR.getUUID()",
                                                       "disk-size=1073741824"]),
                 # 'vm-disk-list'                    : (["VM"],
                 #                                      ["vm=VM.getUUID()"]),
                 'vm-disk-remove'                  : (["UnpluggedVBD"],
                                                      ["vm=VM.getUUID()",
                                                       "device=0"]),
                 'vm-export'                       : (["HaltedVM", "TempFile"],
                                                      ["vm=HaltedVM.getUUID()",
                                                       "filename=TempFile.ref"]),
                 'vm-import'                       : (["ExportedVM"],
                                                      ["filename=ExportedVM.image"]),
                 'vm-install'                      : ([],
                                                      ["new-name-label=XenRTVM",
                                                       "sr-name-label='Local storage'",
                                                       "template='Other install media'"]),
                 # 'vm-list'                         : ([],[]),
                 'vm-memory-shadow-multiplier-set' : (["VM"],
                                                      ["vm=VM.getUUID()",
                                                       "multiplier=1.00"]),
                 'vm-migrate'                      : (["VM"],
                                                      ["host-uuid=Host.getUUID()",
                                                       "vm=VM.getUUID()"]),
                 'vm-pause'                        : (["VM"],
                                                      ["uuid=VM.getUUID()"]),
                 'vm-reboot'                       : (["VM"],
                                                      ["vm=VM.getUUID()"]),
                 'vm-reset-powerstate'             : (["HaltedVM"],
                                                      ["vm=HaltedVM.getUUID()",
                                                       "--force"]),
                 'vm-resume'                       : (["SuspendedVM"],
                                                      ["vm=SuspendedVM.getUUID()"]),
#                 'vm-retrieve-wlb-recommendations' : (["VM", "KirkwoodPool"],
#                                                      ["vm=VM.getUUID()"]),
                 'vm-shutdown'                     : (["VM"],
                                                      ["vm=VM.getUUID()"]),
                 'vm-snapshot'                     : (["VM"],
                                                      ["vm=VM.getUUID()",
                                                       "new-name-label=X"]),
#                 'vm-snapshot-with-quiesce'        : (["VM"],
#                                                      ["vm=VM.getUUID()",
#                                                       "new-name-label=X"]),
                 'vm-start'                        : (["HaltedVM"],
                                                      ["vm=HaltedVM.getUUID()"]),
                 'vm-suspend'                      : (["VM"],
                                                      ["vm=VM.getUUID()"],
                                                      []),
                 'vm-uninstall'                    : (["HaltedVM"],
                                                      ["vm=HaltedVM.getUUID()",
                                                       "--force"]),
                 'vm-unpause'                      : (["PausedVM"],
                                                      ["uuid=PausedVM.getUUID()"]),
#                 'vm-vcpu-hotplug'                 : (["VM"],
#                                                      ["vm=VM.getUUID()",
#                                                       "new-vcpus=1"]),
                 # 'vm-vif-list'                     : (["VM"],
                 #                                      ["vm=VM.getUUID()"])
                } 

    def prepare(self, arglist):
        testcases.xenserver.tc.security._RBAC.prepare(self, arglist)
        
        #for xenserver versions 6.0 onwards pif-reconfigure-ip needs to be removed from FATAL
        if isinstance(self.pool.master, xenrt.lib.xenserver.BostonHost):
           if self.FATAL.has_key("pif-reconfigure-ip"):
              del self.FATAL["pif-reconfigure-ip"]
           
        else: #For older versions like Oxford, changes need to be made
           if self.CONFIG.has_key('pif-forget'):
              del self.CONFIG['pif-forget']
           self.ALLOWED["host-evacuate"]="Not enough host memory is available"
           
        #remove host-license-add and wlb-commands also from CONFIG ,Clearwater onwards
        if isinstance(self.pool.master, xenrt.lib.xenserver.ClearwaterHost):
           listdel=[key for key in self.CONFIG if re.search("wlb",key) or key=="host-license-add"]
           for key in listdel:
                del self.CONFIG[key]
        
        #handle pif-forget differently for pre-Dundee versions and Dundee
        if isinstance(self.pool.master, xenrt.lib.xenserver.CreedenceHost) or isinstance(self.pool.master, xenrt.lib.xenserver.DundeeHost):
           self.ALLOWED["pif-forget"]="The operation you requested cannot be performed because the specified PIF is the management interface"
        else:
           self.FATAL["pif-forget"]="pif-forget timed out"
        
        self.OPERATIONS["cli"] = []
        keys = ("operation", "environment", "parameters", "keep")
        for call in self.CONFIG:         
            values = [call]+ map(copy.deepcopy, self.CONFIG[call])
            if len(values) < len(keys):
                values.append([])
            self.OPERATIONS["cli"].append(self.cliFactory(dict(zip(keys, values))))

class _CLIField(testcases.xenserver.tc.security._RBAC):

    ALLOWED = {"snapshot-param-set"     :   "VM_IS_SNAPSHOT",
               "template-param-set"     :   "The operation attempted is not valid for a template VM"}

    ENTITIES = ["Secret",
                "Host",
                "Pool",
                "Network",
                "PBD",
                "PIF",
                "SM",
                "SR",
                "VDI",
                "VIF", 
                "VLAN",
                "Snapshot", 
                "Console", 
                "VBD",
                "VM",
                "Subject",
                "Bond",
                "Role",
                "Template"]

    # For each entity, list any fields we cannot set due to validation constraints
    NOSET = {"HaltedVM":["suspend-VDI-uuid", "suspend-SR-uuid"], 
             "Snapshot":["suspend-VDI-uuid", "suspend-SR-uuid", "appliance"],
             "Template":["suspend-VDI-uuid", "suspend-SR-uuid", "appliance"]}

    def registerCall(self, cliargs):
        xenrt.TEC().logverbose("Creating: (%s, %s)" % (cliargs["operation"], cliargs["parameters"]))
        self.OPERATIONS["cli"].append(self.cliFactory(cliargs))

    def prepare(self, arglist):
        testcases.xenserver.tc.security._RBAC.prepare(self, arglist)
        
        self.OPERATIONS["cli"] = []
        for entity in self.ENTITIES:
            fields = {}
            values = {}
            cliargs = {}
            cli = self.pool.getCLIInstance()
            callname = entity.lower()

            if entity == "VM": 
                entity = "HaltedVM"
            if entity == "VBD": # using OffVBD instead of VBD because vbd-mode-set requires vm to be in halted state
                entity = "OffVBD" # also OffVBD can be used for all vbd commands, as the state of the vm doesn't affect other commands
            cliargs["environment"] = [entity]
            cliargs["keep"] = [entity]

            self.context.prepare([entity])
            args = ["%s-param-list" % (callname)]
            args.append("params=all")
            args.append("uuid=%s" % (self.context.evaluate("%s.getUUID()" % (entity))))
            data = cli.execute(string.join(args)).strip()
            for line in data.splitlines():
                xenrt.TEC().logverbose("Processing %s." % (line))
                key, field, value = re.match("\s*(\S+)\s+\(\s*(\S+)\).*:\s*(.*)", line).groups()
                fields[key] = field                
                if value == "<not in database>":
                    values[key] = ""
                else:
                    values[key] = value

            # Add a list call for the class.
            cliargs["operation"] = "%s-param-list" % (callname)
            cliargs["parameters"] = ["uuid=%s.getUUID()" % (entity)]
            self.registerCall(cliargs)
            for key in fields:
                if key == "VCPUs-params":
                    defaultkey = "weight"
                    defaultvalue = "1" 
                else:
                    defaultkey = "start"
                    defaultvalue = "true"

                # Add get calls for all fields.
                cliargs["operation"] = "%s-param-get" % (callname)
                cliargs["parameters"] = ["uuid=%s.getUUID()" % (entity)]
                cliargs["parameters"].append("param-name=%s" % (key))
                self.registerCall(cliargs)

                if fields[key] == "RW":
                    # Add set calls for all RW fields.
                    if self.NOSET.has_key(entity) and key in self.NOSET[entity]:
                        continue # CA-62338
                    cliargs["operation"] = "%s-param-set" % (callname)                
                    cliargs["parameters"] = ["uuid=%s.getUUID()" % (entity)]
                    cliargs["parameters"].append("%s='%s'" % (key, values[key]))
                    self.registerCall(cliargs)

                elif fields[key] == "MRW":
                    # Add add calls for all MRW fields.            
                    cliargs["operation"] = "%s-param-add" % (callname)
                    cliargs["parameters"] = ["uuid=%s.getUUID()" % (entity)]
                    cliargs["parameters"].append("param-name=%s" % (key))
                    cliargs["parameters"].append("%s=%s" % (defaultkey, defaultvalue))
                    self.registerCall(cliargs)

                    # Add remove calls for all MRW fields.
                    cliargs["operation"] = "%s-param-remove" % (callname)
                    cliargs["parameters"] = ["uuid=%s.getUUID()" % (entity)]
                    cliargs["parameters"].append("param-name=%s" % (key))
                    cliargs["parameters"].append("param-key=%s" % (defaultkey))
                    self.registerCall(cliargs)

                    # Add clear calls for non-empty MRW fields.
                    if values[key]:
                        cliargs["operation"] = "%s-param-clear" % (callname)
                        cliargs["parameters"] = ["uuid=%s.getUUID()" % (entity)]
                        cliargs["parameters"].append("param-name=%s" % (key))
                        self.registerCall(cliargs)

                    # Add set calls for all MRW fields.
                    cliargs["operation"] = "%s-param-set" % (callname)
                    cliargs["parameters"] = ["uuid=%s.getUUID()" % (entity)]
                    items = re.findall("([^\s;]+): ([^\s;]+)", values[key])
                    if not items:
                        cliargs["parameters"].append("%s:%s=%s" % (key, defaultkey, defaultvalue))
                    else:
                        cliargs["parameters"].extend(["%s:%s='%s'" % (key, k, v) for k,v in items])
                    self.registerCall(cliargs)

            if entity in ["Host", "Pool"]:
                xenrt.TEC().logverbose("Skipping cleaning of '%s'." % (entity))
            else:
                self.context.cleanup([entity])

class _FieldTest(_CLIField):

    ROLES = {"user" : ["pool-admin"]}
 
class _DebugCLI(_CLITest):

    ROLES = {"user" : ["pool-admin"]}

    RUN = []

    FN = lambda self,x:x.operation in self.RUN

    def prepare(self, arglist):
        _CLITest.prepare(self, arglist)
        self.OPERATIONS["cli"] = filter(self.FN, self.OPERATIONS["cli"])
        

class _HATest(_CLITest):
    
    CONFIG = {'pool-ha-disable' : (["HAPool"], []),
              'pool-ha-enable' : (["DisabledHAPool"], []),}

class TC9802(_CLITest):

    ROLES = {"user" : ["pool-admin"]}

class PoolAdminHATest(_HATest):

    ROLES = {"user" : ["pool-admin"]}


class TC9803(_CLITest):

    ROLES = {"user" : ["pool-operator"]}

class PoolOperatorHATest(_HATest):

    ROLES = {"user" : ["pool-operator"]}


class TC9804(_CLITest):

    ROLES = {"user" : ["vm-power-admin"]}

class VmPowerAdminHATest(_HATest):

    ROLES = {"user" : ["vm-power-admin"]}


class TC9805(_CLITest):

    ROLES = {"user" : ["vm-admin"]}

class VmAdminHATest(_HATest):

    ROLES = {"user" : ["vm-admin"]}


class TC9806(_CLITest):

    ROLES = {"user" : ["vm-operator"]}

class VmOperatorHATest(_HATest):

    ROLES = {"user" : ["vm-operator"]}


class TC9807(_CLITest):

    ROLES = {"user" : ["read-only"]}

class ReadOnlyHATest(_HATest):

    ROLES = {"user" : ["read-only"]}


class TC10183(_FieldTest):

    ROLES = {"user" : ["pool-admin"]}

class TC10184(_FieldTest):

    ROLES = {"user" : ["pool-operator"]}

class TC10185(_FieldTest):

    ROLES = {"user" : ["vm-power-admin"]}

class TC10186(_FieldTest):

    ROLES = {"user" : ["vm-admin"]}

class TC10187(_FieldTest):

    ROLES = {"user" : ["vm-operator"]}

class TC10188(_FieldTest):

    ROLES = {"user" : ["read-only"]}

class _DRRBACTest(_CLITest):

    ALLOWED             = {"sr-enable-database-replication"  :   "The SR backend does not support the operation",
                           "drtask-create"                   :   "You attempted an operation that was not allowed",
                           "appliance-start"                 :   "You attempted an operation that was not allowed",
                           "appliance-shutdown"              :   "You attempted an operation that was not allowed"
                           }
    
    
    CONFIG = {'sr-enable-database-replication'  : (["SR"],
                                                   ["uuid=SR.getUUID()"]),
              'sr-disable-database-replication' : (["SR"],
                                                   ["uuid=SR.getUUID()"]),
              'drtask-create'                   : ([],
                                                   ["type=file", 
                                                    "device-config:location=/tmp/f"]),
              'appliance-create'                : ([],
                                                   ["name-label=xenrtapp01"]),
              'appliance-destroy'               : (["Appliance"],
                                                   ["uuid=Appliance.getUUID()"]),
              'appliance-start'                 : (["Appliance"],
                                                   ["uuid=Appliance.getUUID()"]),
              'appliance-shutdown'              : (["Appliance"],
                                                   ["uuid=Appliance.getUUID()"])}

    
class TC14634(_DRRBACTest):

    ROLES = {"user" : ["pool-admin"]}

class TC14635(_DRRBACTest):

    ROLES = {"user" : ["pool-operator"]}

class TC14636(_DRRBACTest):

    ROLES = {"user" : ["vm-power-admin"]}

class TC14637(_DRRBACTest):

    ROLES = {"user" : ["vm-admin"]}

class TC14638(_DRRBACTest):

    ROLES = {"user" : ["vm-operator"]}

class TC14639(_DRRBACTest):

    ROLES = {"user" : ["read-only"]}

class TC14902(xenrt.TestCase):
    
    def prepare(self, arglist=None):
        
        pool = self.getDefaultPool()
        if pool is None:
            self.host = self.getDefaultHost()
        else:
            self.host = pool.master

        #xenrt.getTestTarball("rbac", extract=True)
        xenrt.util.command("cp %s/tests/rbac/%s/rbac_static.csv %s/" % (xenrt.TEC().lookup("BINARY_INPUTS_BASE"),
                           xenrt.TEC().lookup("PRODUCT_VERSION"), xenrt.TEC().getWorkdir()))
        
        if self.host.execdom0("ls /opt/xensource/debug/rbac_static.csv", retval="code") != 0:
            raise xenrt.XRTFailure('rbac_static is missing')
        
        self.rbac_from_host = self.host.execdom0("cat /opt/xensource/debug/rbac_static.csv").strip()
               
        #p = "%s/rbac/%s/rbac_static.csv" % (xenrt.TEC().getWorkdir(), 
        #                                    xenrt.TEC().lookup("PRODUCT_VERSION"))
        p = "%s/rbac_static.csv" % xenrt.TEC().getWorkdir()
        
        self.rbac_reference_copy = file(p).read().strip()
        
    def parsePermissions(self, rbac):
        
        permissions = {}
        
        rbac_lines = rbac.splitlines()
        roles = rbac_lines[0].split(',')[2:8]
        
        for line in rbac_lines[1:]:
            ls = line.split(',')
            api = ls[1]
            rights = ls[2:8]
            permissions[ls[1]] = set(map(lambda x: x[0], 
                                         filter(lambda x: x[1] == 'X', 
                                                zip(roles, rights))))
        return permissions
        
    def run(self, arglist=None):
        
        permissions_host = self.parsePermissions(self.rbac_from_host)
        permissions_reference = self.parsePermissions(self.rbac_reference_copy)
        
        permission_mismatch = False
        mismatched_apis = []
        new_apis_added = []
        
        # We'll not worry about deleted APIs
        
        for api, rights_h in permissions_host.items():
            
            if not permissions_reference.has_key(api):
                new_apis_added.append(api)
                continue

            rights_r = permissions_reference[api]
            
            diff = rights_r.symmetric_difference(rights_h)
            if diff:
                permission_mismatch = True
                mismatched_apis.append(api)
        

        # Analysis
                
        if mismatched_apis:
            curr_perms = lambda x: 'CUR[' + ' '.join(permissions_host[x]) + ']'
            exp_perms = lambda x: 'EXP[' + ' '.join(permissions_reference[x]) + ']'
            
            api_msg = '\n'.join(map(lambda x: x + ' ' + curr_perms(x) + ' ' + exp_perms(x),
                                    mismatched_apis))
            
            err_msg = "Following are the mismatched APIs" + "\n\n" + api_msg
            
            xenrt.TEC().logverbose(err_msg)
        
        if new_apis_added:
            xenrt.TEC().logverbose("Following new APIs were added %s" % new_apis_added)
            
        if permission_mismatch:
            raise xenrt.XRTFailure('APIs with incorrect permissions found')
        
        if new_apis_added:
            raise xenrt.XRTError('Reference permissions (copy of rbac_static.csv) is out of date')
        
    def postRun(self):
        pass
