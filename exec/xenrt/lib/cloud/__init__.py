import xenrt
import os.path
import sys
import urllib, json

try:
    import jenkinsapi
    from jenkinsapi.jenkins import Jenkins
except ImportError:
    pass

def getArtifactsFromTar(place, artifacts):
    tar = xenrt.TEC().lookup("CLOUDRPMTAR", None)
    if not tar:
        raise xenrt.XRTError("CLOUDRPMTAR not specified")
    placeArtifactDir = '/tmp/csartifacts'
    place.execcmd('mkdir %s' % (placeArtifactDir))
    place.execcmd('wget %s -P %s' % (tar, placeArtifactDir))
    place.execcmd('cd %s; tar -xzf %s' % (placeArtifactDir, os.path.basename(tar)))
    # Remove any artifacts that weren't asked for
    allArtifacts = place.execcmd('cd %s; ls *' % (placeArtifactDir))
    for a in allArtifacts.split():
        if not any(map(lambda r: a.startswith(r), artifacts)):
            place.execcmd('rm -f %s' % (os.path.join(placeArtifactDir, a)))
    return placeArtifactDir

def getACSArtifacts(place, artifactsStart, artifactsEnd=[]):
    if xenrt.TEC().lookup("CLOUDRPMTAR", None) is not None:
        return getArtifactsFromTar(place, artifactsStart)

    buildUrl = xenrt.TEC().lookup("ACS_BUILD", None)
    if not buildUrl:
        buildUrl = findACSBuild(place)

    # Load the JSON data for this build
    data = json.loads(urllib.urlopen("%s/api/json" % (buildUrl)).read())
    artifactsDict = {}
    for a in data['artifacts']:
        artifactsDict[a['fileName']] = a['relativePath']

    artifactKeys = filter(lambda x: any(map(lambda a: x.startswith(a), artifactsStart)), artifactsDict.keys())
    artifactKeys.extend(filter(lambda x: any(map(lambda a: x.endswith(a), artifactsEnd)), artifactsDict.keys()))
    

    # Copy artifacts into the temp directory
    localFiles = [xenrt.TEC().getFile(os.path.join(buildUrl, "artifact", artifactsDict[x])) for x in artifactKeys]

    if not place:
        return localFiles

    placeArtifactDir = '/tmp/csartifacts'
    place.execcmd('mkdir %s' % (placeArtifactDir))

    webdir = xenrt.WebDirectory()
    for f in localFiles:
        webdir.copyIn(f)
        place.execcmd('wget %s -P %s' % (webdir.getURL(os.path.basename(f)), placeArtifactDir))

    webdir.remove()

    return placeArtifactDir

def findACSBuild(place):
    jenkinsUrl = 'http://jenkins.buildacloud.org'

    j = Jenkins(jenkinsUrl)
    branch = xenrt.TEC().lookup('ACS_BRANCH', 'master')
    if not branch in j.views.keys():
        raise xenrt.XRTError('Could not find ACS_BRANCH %s' % (branch))

    view = j.views[branch]
    xenrt.TEC().logverbose('View %s has jobs: %s' % (branch, view.keys()))

    jobKey = None
    if 'package-%s-%s' % (place.distro, branch) in view.keys():
        jobKey = 'package-%s-%s' % (place.distro, branch)
    else:
        packageType = 'deb'
        if place.distro.startswith('rhel') or place.distro.startswith('centos'):
            packageType = 'rpm'

        if 'package-%s-%s' % (packageType, branch) in view.keys():
            jobKey = 'package-%s-%s' % (packageType, branch)

        if 'cloudstack-%s-package-%s' % (branch, packageType) in view.keys():
            jobKey = 'cloudstack-%s-package-%s' % (branch, packageType)

    if not jobKey:
        raise xenrt.XRTError('Failed to find a jenkins job for creating MS package')

    xenrt.TEC().logverbose('Using jobKey: %s' % (jobKey))

    lastGoodBuild = view[jobKey].get_last_good_build()
    buildUrl = lastGoodBuild.baseurl
    xenrt.GEC().config.setVariable("ACS_BUILD", buildUrl)
    xenrt.GEC().dbconnect.jobUpdate("ACS_BUILD", buildUrl)
    return buildUrl

from xenrt.lib.cloud.deploy import *
from xenrt.lib.cloud.mansvr import *
from xenrt.lib.cloud.toolstack import *
from xenrt.lib.cloud.marvinwrapper import *
