import xenrt
import logging
import os, urllib
from datetime import datetime

import xenrt.lib.cloud

__all__ = ["deploy"]

try:
    from marvin import cloudstackTestClient
    from marvin.integration.lib.base import *
    from marvin import configGenerator
except ImportError:
    pass


def deploy(cloudSpec, manSvr=None):
    xenrt.TEC().logverbose('Cloud Spec: %s' % (cloudSpec))

    # TODO - Get the ManSvr object from the registry
    if not manSvr:
        manSvrVM = xenrt.TEC().registry.guestGet('CS-MS')
        if not manSvrVM:
            raise xenrt.XRTError('No management server specified')
        manSvr = xenrt.lib.cloud.ManagementServer(manSvrVM)

    xenrt.TEC().comment('Using Management Server: %s' % (manSvr.place.getIP()))
    marvinApi = xenrt.lib.cloud.MarvinApi(manSvr)

    marvinApi.setCloudGlobalConfig("secstorage.allowed.internal.sites", "10.0.0.0/8,192.168.0.0/16,172.16.0.0/12")
    marvinApi.setCloudGlobalConfig("check.pod.cidrs", "false", restartManagementServer=True)

    zoneNameIx = 0
    for zoneSpec in cloudSpec['zones']:
        if not zoneSpec.has_key('name'):
            zoneSpec['name'] = 'XenRT-Zone-%d' % (zoneNameIx)
            zoneNameIx += 1

        podSpecs = zoneSpec.pop('pods')
        zone = marvinApi.addZone(**zoneSpec)
        # TODO:  Add more options for Sec Store
        secondaryStroage = marvinApi.addSecondaryStorage(zone)

        if zone.networktype == 'Basic':
            phyNetwork = marvinApi.addPhysicalNetwork(name='BasicPhyNetwork', zone=zone, trafficTypeList=['Management', 'Guest'], 
                                                                                         networkServiceProviderList=['VirtualRouter', 'SecurityGroupProvider'])
            sharedNetwork = marvinApi.addNetwork(name='BasicSharedNetwork', zone=zone)
        else:
            # TODO: Implement advanced zone
            pass


        podNameIx = 0
        for podSpec in podSpecs:
            if not podSpec.has_key('name'):
                podSpec['name'] = '%s-Pod-%d' % (zone.name, podNameIx)
                podNameIx += 1

            clusterSpecs = podSpec.pop('clusters')
            podSpec['zone'] = zone
            pod = marvinApi.addPod(**podSpec)
 
            #TODO - this is nor correct for advanced zone
            ipRange = marvinApi.addNetworkIpRange(pod, phyNetwork, ipRangeSize=20)

            clusterNameIx = 0
            for clusterSpec in clusterSpecs:
                if not clusterSpec.has_key('name'):
                    clusterSpec['name'] = '%s-Cluster-%d' % (pod.name, clusterNameIx)
                    clusterNameIx += 1
                
                cluster = marvinApi.addCluster(clusterSpec['name'], pod)

                hostObject = xenrt.TEC().registry.hostGet('RESOURCE_HOST_%d' % (clusterSpec['masterHostId']))
                try:
                    hostObject.tailorForCloudStack()
                except:
                    xenrt.TEC().logverbose("Warning - could not run tailorForCloudStack()")
                host = marvinApi.addHost(cluster, hostObject.getIP())

                try:
                    xenrt.GEC().dbconnect.jobctrl("mupdate", [hostObject.getName(), "CSIP", manSvr.getIP()])
                    xenrt.GEC().dbconnect.jobctrl("mupdate", [hostObject.getName(), "CSGUEST", "%s/%s" % (manSvr.getHost().getName(), manSvr.getName())])
                except Exception, e:
                    xenrt.TEC().logverbose("Warning - could not update machine info - %s" % str(e))

                # TODO - Add support for using other storage
                priStoreName = '%s-PriStore' % (cluster.name)
                priStore = marvinApi.addPrimaryStorage(priStoreName, cluster)

        zone.update(marvinApi.apiClient, allocationstate='Enabled')

    xenrt.TEC().registry.toolstackPut("cloud", xenrt.lib.cloud.CloudStack(place=manSvr.place))
