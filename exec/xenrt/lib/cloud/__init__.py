import xenrt
import os.path
import sys

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

def getLatestArtifactsFromJenkins(place, artifacts, updateInputDir=False):
    if xenrt.TEC().lookup("CLOUDRPMTAR", None) is not None:
        return getArtifactsFromTar(place, artifacts)

    jenkinsUrl = 'http://jenkins.buildacloud.org'

    j = Jenkins(jenkinsUrl)
    # TODO - Add support for getting a specific build (not just the last good one)?
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
    if updateInputDir:
        xenrt.GEC().dbconnect.jobUpdate("ACSINPUTDIR", lastGoodBuild.baseurl)
    artifactsDict = lastGoodBuild.get_artifact_dict()

    artifactKeys = filter(lambda x: any(map(lambda a: x.startswith(a), artifacts)), artifactsDict.keys())

    placeArtifactDir = '/tmp/csartifacts'
    place.execcmd('mkdir %s' % (placeArtifactDir))

    xenrt.TEC().logverbose('Using CloudStack Build: %d, Timestamp %s' % (lastGoodBuild.get_number(), lastGoodBuild.get_timestamp().strftime('%d-%b-%y %H:%M:%S')))

    # Copy artifacts into the temp directory
    localFiles = [xenrt.TEC().getFile(artifactsDict[x].url) for x in artifactKeys]

    webdir = xenrt.WebDirectory()
    for f in localFiles:
        webdir.copyIn(f)
        place.execcmd('wget %s -P %s' % (webdir.getURL(os.path.basename(f)), placeArtifactDir))

    webdir.remove()

    return placeArtifactDir

from xenrt.lib.cloud.deploy import *
from xenrt.lib.cloud.mansvr import *
from xenrt.lib.cloud.toolstack import *
from xenrt.lib.cloud.marvinwrapper import *
