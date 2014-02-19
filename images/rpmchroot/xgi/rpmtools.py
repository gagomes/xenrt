###
# GUEST INSTALLER
# Tools for managing repositories of RPMs
#
# Written by Andrew Peace, December 2005
# Copyright (C) XenSource UK Ltd.

import os
from xgi.graphutils import Graph, GraphNode
from xgi.util import _log, getNodeData

rpmtoolpath = "rpm 2>/dev/null"

# Represents the .rpm file
class RPM:
    def __init__(self, provides, files, requires, packagename, rpmname, packageid = None):
        self.provides = []
        self.depends = []

        for x in provides:
            self.addProvides(x)

        for x in requires:
            self.addDependency(x)

        self.files = files
        self.packagename = packagename
        self.rpmname = rpmname
        self.packageid = packageid

    def fromFile(fname):
        rv = RPM([], [], [], None, fname)

        # find RPM data:
        pipe = os.popen(rpmtoolpath + ' -q --qf "%{NAME}\\n-provides-\\n[%{PROVIDES}\\n]\\n-files-\\n[%{FILENAMES}\\n]-requires-\\n[%{REQUIRENAME}\\n]-end-\\n" -p ' + fname)
        rv.packagename = pipe.readline().strip("\n")

        # what capabilities does it provide?
        next = pipe.readline().strip("\n")
        assert next == "-provides-"
        next = pipe.readline().strip("\n")
        while next != "-files-":
            if next != "" and next != "(none)":
                packagedata = next.split(" = ")
                if len(packagedata) == 2:
                    [ package,version ] = packagedata
                else:
                    package = next.strip(" ")
                    version = None
                rv.addProvides((package, version))
            next = pipe.readline().strip("\n");

        # what files does it provide?
        next = pipe.readline().strip("\n");
        while next != "-requires-":
            rv.files.append(next)
            next = pipe.readline().strip("\n")            
        
        # work out what packages it depends on:
        next = pipe.readline().strip("\n");
        while next != "-end-":
            if next[:len("rpmlib")] != "rpmlib":
                rv.addDependency((next, None))
            next = pipe.readline().strip("\n")
        pipe.close()

        return rv

    fromFile = staticmethod(fromFile)

    def depFromString(string):
        # XXX we should do something better than this...!
        first_space = string.find(" ")
        if first_space == -1:
            first_space = len(string)
        return (string[:first_space], None)

    depFromString = staticmethod(depFromString)

    def provideFromString(string):
        # XXX we should do something better than this...!
        first_space = string.find(" ")
        if first_space == -1:
            first_space = len(string)

        return (string[:first_space], None)

    provideFromString = staticmethod(provideFromString)

    def addDependency(self, (p, v)):
        if (p,v) not in self.depends and (p,v) not in self.provides:
            self.depends.append((p,v))

    def addProvides(self, (p,v)):
        if (p,v) not in self.provides:
            self.provides.append((p,v))

    def providesPackage(self, (p2,v2)):
        if p2[0] == "/":
            # it's a file, check capabilities then files:
            # (some 'files' are listed in the packages section
            #  because they are symlinks created by pre/post
            #  install script).
            return (p2, None) in self.provides or p2 in self.files
        else:
            # it's a package, check packages:
            return (p2, v2) in self.provides

    # is (p1,v1) compatible with (p2,v2)?
    def package_compatible((p1,v1), (p2,v2)):
        # this is grim - we should check the version really:
        try:
            rv = (p1 == p2)
        except UnicodeDecodeError, u:
            _log(1, "Unicode error: %s" % u)
            _log(1, "p1: %s" % p1)
            _log(1, "p2: %s" % p2)
	    return False
        
        return rv

    package_compatible = staticmethod(package_compatible)

# Represents a set of RPMs, e.g. a repository or an installation
# set.
class RPMSet:
    def __init__(self):
        self.rpms = [] # RPMs in db
        self.rpmmap = {} # pkg-id => rpm

    def addRPM(self, rpm):
        if rpm not in self.rpms:
            self.rpms.append(rpm)

            if rpm.packageid:
                self.rpmmap[rpm.packageid] = rpm

    def __getitem__(self, pkgid):
        if pkgid not in self.rpmmap:
            print "%s not in map!" % pkgid
        return self.rpmmap[pkgid]

    def whoProvides(self, (p,v)):
        rv = []
        for r in self.rpms:
            if r.providesPackage((p,v)):
                rv.append(r)
        return rv

    def solveDeps(self, repoList, rpmChooser, alreadyInstalled = []):
        # first make sure we have all the RPMs in this RPMSet that
        # we need in order to install each RPM in the set
        changed = False
        loop = True
        while loop:
            for rpm in self.rpms:
                # check each package's deps are satisfied:
                for p in rpm.depends:
                    if p[0][:7] != "rpmlib(" and p[0] not in alreadyInstalled:
                        if len(self.whoProvides(p)) == 0:
                            # we need to get another package from
                            # the repo set:
                            possibles = []
                            for repo in repoList:
                                possibles += repo.whoProvides(p)
                            if len(possibles) == 0:
                                _log(2, "dep %s in %s not resolved." % (p, rpm.rpmname))
                            else:
                                # do we already have any of the providers:
                                install = True
                                for x in possibles:
                                    if x.packagename in alreadyInstalled:
                                        install = False
                                if install:
                                    actual = rpmChooser(p, possibles)
                                    if actual not in self.rpms:
                                        _log(2, "Including %s to provide %s for %s" % (actual.rpmname, p, rpm.rpmname))
                                        self.addRPM(actual)
                                        changed = True
                        
            if not changed:
                loop = False
            else:
                changed = False

        self._deps_solved = True

    # really should have a Graph class rather than use lists here...
    def depGraph(self, rpmChooser, alreadyInstalled):
        rv = Graph()
        
        # create a graph node for each RPM
        for rpm in self.rpms:
            gn = GraphNode(rpm, [])
            rv.addNodes(gn)

        # populate adjacency lists:
        def findGraphNode(graph, rpm):
            for x in graph:
                if x.name == rpm:
                    return x

        for node in rv:
            for p in node.name.depends:
                if p in alreadyInstalled:
                    continue
                
                # not interested in rpmlib(...) style deps.
                if p[0][:7] != "rpmlib(":
                    rpmd = self.whoProvides(p)
                    if len(rpmd) > 0:
                        rpmProvider = rpmChooser(p, rpmd)
                        if len(filter(lambda x: x.name.rpmname == rpmProvider.rpmname, node.adj)) == 0:
                            node.adj.append(findGraphNode(rv, rpmProvider))
                    else:
                        _log(3, "Warning: dependency not satisfied: %s requires %s" % (node.name.rpmname, [p]))

        return rv

    def getInstallOrder(self, rpmChooser, alreadyInstalled = []):
        assert self._deps_solved
        
        # get the components graph of the strongly connected
        # components in the dependency graph
        Gscc = self.depGraph(rpmChooser, alreadyInstalled).gscc()

        # Do a depth first search and sort nodes by finish time:
        Gscc.dfs_search()
        Gscc.nodes.sort(lambda x1, x2: cmp(x1.finishtime, x2.finishtime))

        return map(lambda x: x.name, Gscc.nodes)


# Represents a group of packages, e.g. from comps.xml.
class Group:
    def __init__(self, name, deps, packagelist):
        self.name = name
        self.requiredGroups = deps
        self.packages = packagelist

    def getInstallOrder(self):
        rv = []
        for dep in self.requiredGroups:
            if dep not in rv:
                depdeps = dep.getInstallOrder()
                
                # remove anything we already install:
                for d in depdeps:
                    if d in rv:
                        depdeps.remove(d)

                rv = rv + depdeps
        return rv + [self]
