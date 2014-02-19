###
# Guest INSTALLER
# Perform base installations from various repo types
#
# Written by Andrew Peace, December 2005
# Copyright (C) XenSource UK Ltd.

import os
import popen2
import xgi.rpmtools
import xgi.repo
from xgi.util import _log

def graph(installdef, repos):
    packagelist = getPackageList(installdef, repos)
    installation_set = xgi.rpmtools.RPMSet()
    for p in packagelist:
        rpm = selectRPM(p, repos)
        if not rpm:
            _log(3, "Warning: No RPM provides %s; package ignored." % p)
        else:
            installation_set.addRPM(rpm)

    # pull in dependencies:
    installation_set.solveDeps([rpmset for (_, rpmset) in repos], rpmChooser)

    # produce dependency graph:
    graph = installation_set.depGraph(rpmChooser, [])
    print "digraph {"
    for node in graph:
        print '   "' + node.name.packagename  + '"'
        for adj in node.adj:
            print '   "%s" -> "%s"' % (node.name.packagename, adj.name.packagename)
    print "}"


###
# The main feature; given an installation action list, a
# destination and a set of repositories, performs an installation
#
# An install definition is a list of pairs (type, data) where
#  (type, data) ::= ("group", "<group-name>") |
#                   ("package", "<package>")
def doInstall(installdef, root, repos,
              test = False,
              clean = False,
              rpmtoolpath = "rpm",
              sudotoolpath = "sudo",
              manifest_file = None,
              bootstrapping = False):
    
    _log(1, "Preparing installation directory...")
    if bootstrapping:
        _log(1, "********* BOOTSTRAPPING STAGE ********")
    else:
        _log(1, "********* MAIN INSTALL STAGE ********")

    # set up 'action' to run commands - maybe we actually need
    # to implement a function for this at some point?
    if test:
        action = lambda x: _log(1, "run: %s" % x)
    else:
        action = lambda x: os.system(x)

    # make sure destination exists:
    updating = os.path.isdir(root) and not clean
    if not updating:
        _log(1, "(Initialising a chroot.)")
        if not os.path.isdir(root):
            os.mkdir(root)
    else:
        _log(1, "(Updating a chroot.)")

    def makedirs_p(d):
        if not os.path.exists(d):
            os.makedirs(d)

    if not test and not updating:
        makedirs_p(os.path.join(root, "dev"))
        os.system("%s mknod --mode=0666 %s/dev/null c 1 3" % \
                  (sudotoolpath, root))
        makedirs_p(os.path.join(root, "proc"))
        makedirs_p(os.path.join(root, "etc"))
        makedirs_p(os.path.join(root, "sys"))
        makedirs_p(os.path.join(root, "var", "tmp"))
        makedirs_p(os.path.join(root, "var", "lock", "rpm"))
	makedirs_p(os.path.join(root, "var", "lib", "rpm"))
        for d in ['dev', os.path.join("dev", "null"), 'proc', 'etc', 'sys']:
            os.system("%s chown root:root '%s/%s'" % \
                      (sudotoolpath, root, d))
    else:
        _log(1, "Make /dev /proc /etc /sys /var/lib/rpm")

    # helper function to find an rpm binary inside a chroot:
    def rpm_in_chroot(root):
        paths = [ 'usr/bin/rpm', 'bin/rpm' ]
        return True in [ os.path.exists("%s/%s" % (root, path)) for path in paths ]

    def rpm(root, cmdline):
        if rpm_in_chroot(root):
            return action("%s chroot %s rpm %s" % (sudotoolpath, root, cmdline))
        else:
            return action("%s %s root='%s' %s" % (sudotoolpath, rpmtoolpath, root, cmdline))

    # create an empty fstab and mtab, and initial device nodes:
    if not updating:
        action("%s touch %s" % (sudotoolpath, os.path.join(root, "etc/fstab")))
        action("%s touch %s" % (sudotoolpath, os.path.join(root, "etc/mtab")))
        if not bootstrapping:
            rpm(root, "--initdb")

    alreadyInstalled = []
    if updating:
        _log(2, "Checking which packages are already installed...")
        if rpm_in_chroot(root):
            pipe = popen2.Popen3("%s chroot %s rpm -qa --qf '%%{NAME}\n'" % (sudotoolpath, root))
        else:
            pipe = popen2.Popen3("%s --root %s -qa --qf '%%{NAME}\n'" % (rpmtoolpath, root))
        alreadyInstalled = [x.rstrip() for x in pipe.fromchild.readlines()]
        if pipe.wait() != 0:
            alreadyInstalled = []
            _log(2, "Check for currently installed packages failed")
    _log(1, "Determining packages to install...")
    packagelist = getPackageList(installdef, repos)
    packagelist = filter(lambda x: x not in alreadyInstalled, packagelist)

    # create an installation RPM set:
    installation_set = xgi.rpmtools.RPMSet()
    for p in packagelist:
        rpmfile = selectRPM(p, repos)
        if not rpmfile:
            _log(2, "Warning: No RPM provides %s: package ignored." % p)
        else:
            _log(2, "Installing %s to provide %s which was on the command-line" % (rpmfile.rpmname, p))
            installation_set.addRPM(rpmfile)

    _log(1, "Solving dependencies...")
    installation_set.solveDeps([rpmset for (_, rpmset) in repos], rpmChooser, alreadyInstalled = alreadyInstalled)

    _log(1, "Computing installation order...")
    installation_order = installation_set.getInstallOrder(rpmChooser, alreadyInstalled = alreadyInstalled)

    _log(1, "Performing installation...")
    _log(2, "Installing RPM Packages...")
    
    # create the RPM database if we're initialising:
    if not updating and not bootstrapping:
        rpm(root, '--initdb')

    for x in installation_order:
        if bootstrapping:
            for p in [y.rpmname for y in x]:
                _log(2, "Processing %s: " % os.path.basename(p))
                rc = action("cd %s && (rpm2cpio %s | %s cpio -idu)" % (root, p, sudotoolpath))
                if rc != 0:
                    raise RuntimeError, "Error extracting %s during bootstrapping." % p
                _log(2, "Removing configuration files for %s" % os.path.basename(p))
                pipe = os.popen("rpm -qcp %s" % p)
                for line in pipe:
                    line = line.lstrip('/').strip()
                    if line != "" and line != "(contains no files)":
                        path = os.path.join(root, line)
                        action("%s rm -f %s" % (sudotoolpath, path))
                pipe.close()
        else:
            if rpm_in_chroot(root):
                # copy in the files, then install them from within:
                rpmfiles = [y.rpmname for y in x]
                for rpmfile in rpmfiles:
                    if action("%s cp %s %s" % (sudotoolpath, rpmfile, os.path.join(root, 'tmp'))) != 0:
                        raise RuntimeError, "Error copying %s to the chroot for extraction using inner RPM." % rpmfile
                    
                packages = ['/tmp/%s' % os.path.basename(rpmfile) for rpmfile in rpmfiles]
                pkg_string = " ".join(packages)
                _log(2, "Installing %s using rpm inside chroot." % pkg_string)

                rc = rpm(root, '--force -ivh %s' % pkg_string)
                for rpmfile in rpmfiles:
                    pkgpath = os.path.join(root, 'tmp', os.path.basename(rpmfile))
                    action("%s rm %s" % (sudotoolpath, pkgpath))
            else:
                # install from outside:
                packages = " ".join(map(lambda x: x.rpmname, x))
                _log(2, "Installing %s from outside the chroot." % packages)
                rc = rpm(root, '--force -ivh %s' % packages)

        if manifest_file:
            for p in [y.rpmname for y in x]:
                manifest_file.write("%s %d\n" % (p, rc))

    _log(2, "Package installation complete.")

    _log(1, "Cleaning up")
    action("%s umount -l %s" % (sudotoolpath, os.path.join(root, "proc")))

    _log(1, "Guest installation complete!")


###
# Helper functions

def selectGroup(groupname, repos):
    for (groups,_) in repos:
        if groupname in groups:
            return groups[groupname]

def rpmChooser(package, rpms):
    if len(rpms) > 1:
        _log(2, "Choices for %s: %s - choosing %s" % (package, [x.packagename for x in rpms], rpms[0].packagename))
    return rpms[0]

def selectRPM(package, repos):
    choices = []
    for (_, rpmset) in repos:
        choices.extend(rpmset.whoProvides((package, None)))

    if len(choices) == 0:
        return None
    else:
        return rpmChooser(package, choices)


class UnknownGroupException(Exception):
    pass

def getPackageList(installdef, repos):
    packagelist = []

    for (deftype, data) in installdef:
        if deftype == "group":
            g = selectGroup(data, repos)
            if not g:
	        raise UnknownGroupException, data
            gio = g.getInstallOrder()
            for group in gio:
                packagelist.extend(group.packages)
        elif deftype == "package":
            packagelist.append(data)

    return packagelist
