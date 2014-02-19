###
# GUEST INSTALLER
# Tools for installations from package repositories
#
# Written by Andrew Peace, December 2005
# Copyright (C) XenSource UK Ltd.

import os.path
import sys
import gzip
import xml.sax
from xml.sax.handler import ContentHandler
import xml.dom.minidom

import xgi.rpmtools
from rpmtools import Group, RPM, RPMSet
from util import _log, getNodeData

# Convert a list of repo source directories into a list of
# (string -> Group, RPMSet) pairs.
def parseRepo(repodir):
    attrs = getRepoAttributes(repodir)

    rpmdb = None
    groups = None

    # first get RPM data:
    def populateRPMSetFromDirectory(dirname, rpmdb):
        files = os.listdir(dirname)
        for fname in files:
            path = os.path.join(dirname, fname)
            if os.path.isdir(path):
                populateRPMSetFromDirectory(path, rpmdb)
            else:
                if fname.lower().endswith(".rpm"):
                    rpmdb.addRPM(RPM.fromFile(path))
            
    if "yum-compatible" in attrs:
        locations = readYUMRepoMD(repodir)
        rpmdb = getYUMRepoRPMSet(repodir, locations['primary'], locations['filelists'])
        if not locations.has_key('group'):
            # some YUM repos don't have a groups file - we'll look for a 
            # RedHat comps file instead:
            locations['group'] = findCompsFile(repodir)
        if locations['group']:
            groups = parseCompsFile(os.path.join(repodir, locations['group']))
        else:
            groups = {}
    elif "suse" in attrs:
        rpmdb = getSuseRPMSet(repodir)

        # now groups - this is stupid in SLES:
        patterns = []
        if "suse-selections-present" in attrs:
            patterns.extend(getSelList(repodir))
        if "suse-patterns-present" in attrs:
            patterns.extend(getPatFileList(repodir))
        groups = parseSelFiles(patterns)
    elif "redhat" in attrs:
        rpmdb = RPMSet()
        populateRPMSetFromDirectory(os.path.join(repodir, "RedHat/RPMS"), rpmdb)
        compsfile = findCompsFile(repodir)
        if compsfile:
            groups = parseCompsFile(compsfile)
    else:
        rpmdb = RPMSet()
        populateRPMSetFromDirectory(repodir, rpmdb)
        groups = {}

    return (groups, rpmdb)

# Given a path to a YUM repository, will read the repomd file that points to
# other files in the repository
def readYUMRepoMD(path):
    class RepoMDHandler(ContentHandler):
        data_stack = [u'data', u'repomd']
        location_stack = [u'location', u'data', u'repomd']

        def __init__(self):
            self._elementstack = []
            self.files = {}

        def startElement(self, name, attrs):
            self._elementstack.insert(0, name)
            if self._elementstack == self.data_stack:
                self._current_type = attrs['type']
            elif self._elementstack == self.location_stack:
                self._location = attrs['href']

        def endElement(self, name):
            if self._elementstack == self.location_stack:
                self.files[self._current_type] = self._location 

            del self._elementstack[0]

    repomd = os.path.join(path, "repodata", "repomd.xml")
    if not os.path.exists(repomd):
        raise RuntimeError, "Couldn't find required file %s" % repomd 

    repomd_fobj = open(repomd, 'r')
    repomd_handler = RepoMDHandler()
    xml.sax.parse(repomd_fobj, repomd_handler)
    repomd_fobj.close()

    return repomd_handler.files

# Given a path to a RedHat-derrived repository, tries to find
# an appropriate file to pass to parseCompsFile:
def findCompsFile(repopath):
    possibles = [ os.path.join(repopath, "repodate/yumgroups.xml"),
                  os.path.join(repopath, "RedHat/base/comps.xml"),
                  os.path.join(repopath, "Fedora/base/comps.xml"),
                  os.path.join(repopath, "CentOS/base/comps.xml") ]

    for possible in possibles:
        if os.path.isfile(possible):
            return possible
        
    return None

# Given a path to a repository, determines what type it is and any
# other important attributes.  Returns a list of strings representing
# attributes about the repository; possibles are:
#  'remote-http', 'remote-ftp', 'yum-compatible', 'yum-groups'
#  'redhat', 'suse'
def getRepoAttributes(path):
    attributes = []

    # work out distribution:
    if os.path.isdir(os.path.join(path, "suse")):
        attributes.append("suse")
        if os.path.exists(os.path.join(path, "suse", "setup", "descr", "selections")):
            attributes.append("suse-selections-present")
        if os.path.exists(os.path.join(path, "suse", "setup", "descr", "patterns")):
            attributes.append("suse-patterns-present")
    elif os.path.isdir(os.path.join(path, "RedHat")):
        attributes.append("redhat")
    elif os.path.isdir(os.path.join(path, "Fedora")):
        attributes.append("redhat")
	    
    # is it equipped with YUM repodata?
    repodata_path = os.path.join(path, "repodata")
    if os.path.isdir(repodata_path):
        attributes.append("yum-compatible")
    if os.path.isfile(os.path.join(repodata_path, "yumgroups.xml")):
        attributes.append("yum-groups")

    return attributes

# Given a comps file object or filename, returns a dictionary of
# string => Group (groupname to Group instance).
def parseCompsFile(comps_fname):
    # use minidom to parse this doc:
    compsFile = open(comps_fname, 'r')
    comps = xml.dom.minidom.parse(compsFile)
    compsFile.close()
        
    # first read group data:
    groups = {}
    for group in comps.getElementsByTagName("group"):
        # group name:
        id_tag = group.getElementsByTagName("id")[0]
        groupname = getNodeData(id_tag)
            
        # dependencies:
        deps = []
        grouplist_tags = group.getElementsByTagName("grouplist")
        if len(grouplist_tags) == 1: # any required groups?
            grouplist_tag = grouplist_tags[0]
            for dep in grouplist_tag.getElementsByTagName("groupreq"):
                deps.append(getNodeData(dep))

        # package list:
        packagelist = []
        packagelist_tags = group.getElementsByTagName("packagelist")
        if len(packagelist_tags) == 1:
            packages = packagelist_tags[0]
            for p in packages.getElementsByTagName("packagereq"):
                packagelist.append(getNodeData(p))
                    
        # construct group object:
        groups[groupname] = Group(groupname, deps, packagelist)

    # now create dependency graph:
    for group in groups.values():
        deplist = []
        for dep in group.requiredGroups:
            deplist.append(groups[dep])

        group.requiredGroups = deplist

    return groups

# Given a list of .sel file paths, will return a dict of
# string => Group (groupname to Group instance).  The list must
# contain a set of files whose inter-group dependencies are
# close.
def parseSelFiles(selfiles):
    ( SEL_FILE, PAT_FILE, ) = range(2)

    groups = {}
    
    for selfile in selfiles:
        if selfile.endswith('.sel'):
            ftype = SEL_FILE
        elif selfile.endswith('.pat'):
            ftype = PAT_FILE

        # these files aren't very big so this ok:
        sel_fobj = open(selfile, "r")
        lines = sel_fobj.readlines()
        sel_fobj.close()

        # work out where things start and end (I hate this!)
        groupname = ""
        depgroups_ranges = []
        packagelist_ranges = []
        depgroups_start = 0
        packagelist_start = 0
        version = 0
        for i in range(len(lines)):
            if ftype == SEL_FILE:
                # sel file:
                if lines[i][:5] == "=Ver:":
                    version = lines[i][5:].strip("\n").strip()
                elif lines[i][:5] == "=Sel:":
                    if version == "3.0":
                        groupname = lines[i][5:].strip("\n").strip()
                    elif version == "4.0":
                        groupname, _, _, _ = lines[i][5:].strip("\n").strip().split(" ")
                elif lines[i][:5] == "+Req:":
                    depgroups_start = i
                elif lines[i][:5] == "-Req:":
                    depgroups_ranges.append((depgroups_start, i))
                elif lines[i][:5] == "+Ins:":
                    packagelist_start = i
                elif lines[i][:5] == "-Ins:":
                    packagelist_ranges.append((packagelist_start, i))
            elif ftype == PAT_FILE:
                # pat file:
                if lines[i][:5] == "=Ver:":
                    version = lines[i][5:].strip()
                elif lines[i][:5] == "=Pat:":
                    groupname, _, _, _ = lines[i][5:].strip().split(" ")
                elif lines[i][:5] == "+Req:":
                    depgroups_start = i
                elif lines[i][:5] == "-Req:":
                    depgroups_ranges.append((depgroups_start, i))
                elif lines[i][:5] in ['+Prq:', '+Prc:']:
                    packagelist_start = i
                elif lines[i][:5] in ['-Prq:', '-Prc:']:
                    packagelist_ranges.append((packagelist_start, i))

        depgroups = []
        for (start, end) in depgroups_ranges:
            depgroups += [x.strip() for x in lines[start + 1:end - 1] ]

        packagelist = []
        for (start, end) in packagelist_ranges:
            packagelist += [x.strip() for x in lines[start + 1:end - 1] ]

        groups[groupname] = Group(groupname, depgroups, packagelist)

    # now create dependency graph:
    for group in groups.values():
        deplist = []
        for dep in group.requiredGroups:
            if groups.has_key(dep):
                deplist.append(groups[dep])
        group.requiredGroups = deplist

    return groups

def getSelList(repodir):
    """ Return list of .sel files in SUSE repo. """
    descr_dir = os.path.join(repodir, "suse", "setup", "descr")
    return  [ os.path.join(descr_dir, x) for x in _readlist(os.path.join(descr_dir, 'selections')) ]

def getPatFileList(repodir):
    """ Return list of .pat files in SUSE repo. """
    descr_dir = os.path.join(repodir, "suse", "setup", "descr")
    return  [ os.path.join(descr_dir, x) for x in _readlist(os.path.join(descr_dir, 'patterns')) ]

def _readlist(fname):
    """ Return list of lines in file fname, after 'strip()'."""
    lst_fd = open(fname, 'r')
    lst = [ x.strip() for x in lst_fd ]
    lst_fd.close()

    return lst

# Get an RPMSet object from a SuSE repository.
def getSuseRPMSet(repoPath):
    _log(1, "Parsing SUSE repository package data...")

    packages_path = os.path.join(repoPath, "suse/setup/descr/packages")
    extra_prov_path = os.path.join(repoPath, "suse/setup/descr/EXTRA_PROV")

    package_fobj = open(packages_path, "r")

    rpmdb = RPMSet()

    # check the version of the file; we currently know how to read
    # version 2:
    next = package_fobj.readline().strip("\n").strip()
    if next[:5] == "=Ver:":
        version = next[len(next)-3:]
        if version != "2.0":
            raise Exception("Unable to deal with this version of repository: %s" % version)

    # now read the rest of the file:
    currentPackage = None
    inDeps = False
    inProvs = False
    for line in package_fobj:
        line = line.strip("\n")
        if line[:5] == "=Pkg:":
            if currentPackage:
                # we have a package ready to save:
                rpm = RPM(currentProvides, [], currentDepends,
                          currentPackageName, currentLocation)
                rpmdb.addRPM(rpm)

            # we have a new package - re-initialise the variables:
            currentPackage = None
            currentPackageName = ""
            currentArch = ""
            currentLocation = ""
            currentProvides = []
            currentDepends = []
            
            currentPackage = line[5:].strip().split(" ")
            currentPackageName = currentPackage[0]
            currentArch = currentPackage[3]

        if line[:5] == "=Loc:":
            values = line[5:].strip().split(" ")
            # we're not interested in src RPMs:
            if not (len(values) == 3 and values[2] == "src"):
                (disc, location) = values[:2]
                currentLocation = os.path.join(os.path.join(repoPath, "suse/" + currentArch), location)

        if line[:5] == "-Req:" or line[:5] == "-Prq:":
            inDeps = False

        if line[:5] == "-Prv:":
            inProvs = False

        if inDeps: currentDepends.append(RPM.depFromString(line))

        if inProvs: currentProvides.append(RPM.provideFromString(line))

        if line[:5] == "+Req:" or line[:5] == "+Prq:":
            inDeps = True

        if line[:5] == "+Prv:":
            inProvs = True

    package_fobj.close()

    # Now read the EXTRA_PROV file if it exists... (ugh)
    if os.path.exists(extra_prov_path):
        extraprov_fobj = open(extra_prov_path, "r")

        for line in extraprov_fobj:
            line = line.strip("\n")
            (package, extraprov) = line.split(":\t")
            extraprov = extraprov.split(" ")

            rpms = rpmdb.whoProvides(RPM.provideFromString(package))
            for rpm in rpms:
                for prov in extraprov:
                    rpm.addProvides(RPM.provideFromString(prov))

        extraprov_fobj.close()

    # XXX SLES9 has a couple of extra files that aren't listed in its meta-data
    # We should abstract out classes for dealing with repos but for now we'll
    # hack this in here:
    extra_files = ['suse/i586/sles-release-9-82.11.i586.rpm']
    for f in extra_files:
        f = os.path.join(repoPath, f)
        if os.path.isfile(f):
            rpmdb.addRPM(RPM.fromFile(f))

    return rpmdb

# Get an RPMSet object from a YUM repository.  Path should not
# include 'repodata' directory.
def getYUMRepoRPMSet(repoPath, primary_gz_rel, filelist_gz_rel):
    class FileListHandler(ContentHandler):
        package_stack = [u'package', u'filelists']
        file_stack = [u'file', u'package', u'filelists']

        def __init__(self, rpmset):
            self._elementstack = []
            self.rpmset = rpmset
            self._currentrpm = None
            self._currentitem = ""

        def startElement(self, name, attrs):
            self._elementstack.insert(0, name)
            if self._elementstack == FileListHandler.package_stack:
                self._currentrpm = self.rpmset[attrs['pkgid']]

        def endElement(self, name):
            if self._elementstack == FileListHandler.file_stack:
                self._currentrpm.files.append(self._currentitem)
            
            del self._elementstack[0]
            self._currentitem = ""

        def characters(self, content):
            if self._elementstack == FileListHandler.file_stack:
                self._currentitem += content

    class PrimaryHandler(ContentHandler):
        packagename_stack = [u'name', u'package', u'metadata']
        filename_stack = [u'file', u'format', u'package', u'metadata']
        provides_entry_stack = [u'rpm:entry', u'rpm:provides', u'format', u'package', u'metadata']
        requires_entry_stack = [u'rpm:entry', u'rpm:requires', u'format', u'package', u'metadata']
        file_stack = [u'file', u'format', u'package', u'metadata']
        checksum_stack = [u'checksum', u'package', u'metadata']
        arch_stack = [u'arch', u'package', u'metadata']

        interesting_archs = ['i386', 'i486', 'i586', 'i686', 'narch']

        def __init__(self, rpmset, root):
            self.root = root
            self.rpmset = rpmset
	    self._cleartemps()
            self._elementstack = []

        def _cleartemps(self):
            self._package = ""
            self._rpmfile = ""
            self._pkgid = ""
            self._currentitem = ""
            self._provides = []
            self._depends = []
            self._files = []
            self._arch = ""

        def startElement(self, name, attrs):
            self._elementstack.insert(0, name)
            if name == "package":
                self._cleartemps()
            elif name == "location":
                self._rpmfile = attrs['href']
            elif self._elementstack == PrimaryHandler.provides_entry_stack:
                self._provides.append((attrs['name'], None))
            elif self._elementstack == PrimaryHandler.requires_entry_stack:
                self._depends.append((attrs['name'], None))

        def endElement(self, name):
	    if name == "package":
                # add the completed package to the set:
                self._rpmfile = os.path.join(self.root, self._rpmfile)
                self.rpmset.addRPM(RPM(self._provides, self._files, self._depends, self._package, self._rpmfile, self._pkgid))
                self._cleartemps()

            if self._elementstack == PrimaryHandler.file_stack:
                self._files.append(self._currentitem)

            del self._elementstack[0]
            self._currentitem = ""

        def characters(self, content):
            if self._elementstack == PrimaryHandler.packagename_stack:
                self._package += content
            elif self._elementstack == PrimaryHandler.file_stack:
                self._currentitem += content
            elif self._elementstack == PrimaryHandler.checksum_stack:
                self._pkgid += content
            elif self._elementstack == PrimaryHandler.arch_stack:
                self._arch += content

    primary_gz = os.path.join(repoPath, primary_gz_rel)
    filelist_gz = os.path.join(repoPath, filelist_gz_rel)

    # check we can find the primary and filelist package metadata
    # XML files:
    if not os.path.isfile(primary_gz) or not os.path.isfile(filelist_gz):
        raise Exception("Not a YUM Repository!")

    rv = RPMSet()

    _log(1, "Reading YUM repodata...")

    _log(2, "Reading primary repository data...")
    primary_fobj = gzip.GzipFile(primary_gz, "r")
    primary_handler = PrimaryHandler(rv, repoPath)
    xml.sax.parse(primary_fobj, primary_handler)
    primary_fobj.close()

    _log(2, "Reading file list...")
    filelist_fobj = gzip.GzipFile(filelist_gz, "r")
    filelist_handler = FileListHandler(rv)
    xml.sax.parse(filelist_fobj, filelist_handler)
    filelist_fobj.close()

    return rv
