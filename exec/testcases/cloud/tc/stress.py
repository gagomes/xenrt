import xenrt

import random
from datetime import datetime

class TCInstanceLifecycleStress(xenrt.TestCase):
    STRESS_OPS = { "StopStart": "stopStart",
                   "Reboot": "reboot",
                   "Migrate": "migrate",
                   "SnapRevert(D)": "snapRevertDisk",
                   "SnapDelete(D)": "snapDeleteDisk",
                   "MultiSnapRevert(D)": "multiSnapRevertDisk",
                   "MultiSnapDelete(D)": "multiSnapDeleteDisk",
                   "SnapRevert(DM)": "snapRevertDiskAndMem",
                   "SnapDelete(DM)": "snapDeleteDiskAndMem",
                   "MultiSnapRevert(DM)": "multiSnapRevertDiskAndMem",
                   "MultiSnapDelete(DM)": "multiSnapDeleteDiskAndMem",
                   "CloneDelete": "cloneDelete" }

    def prepare(self, arglist):
        self.args = self.parseArgsKeyValue(arglist)

        self.cloud = self.getDefaultToolstack()
        self.instance = self.cloud.createInstance(distro=self.args['distro'], hypervisorType=self.args.get("hypervisor"), name=self.args.get("instancename"))
        self.instance.createSnapshot("%s-base" % self.instance.name)
        self.getLogsFrom(self.instance)

        self.snapCount = self.args.get("snapcount", 9)
    
    def run(self, arglist):
        for i in xrange(int(self.args.get("iterations", 400))):
            op = random.choice(self.STRESS_OPS.keys())
            startTime = datetime.now()
            if self.runSubcase(self.STRESS_OPS[op], (), "Iter-%d-%s" % (i, self.args.get("distro")), op) != xenrt.RESULT_PASS:
                break
            xenrt.TEC().comment('Iter-%d for %s(%s): Operation: %s took %d minute(s)' % (i, self.instance.name, self.args.get("distro"), op, (datetime.now() - startTime).seconds / 60))

    def _snapshotRevert(self, snapshotName, memorySnapshot):
        """A user is only permitted to revert to a disk only snapshots for
           an instance that is stopped."""
        if not memorySnapshot:
            self.instance.setPowerState(xenrt.PowerState.down)

        self.instance.revertToSnapshot(snapshotName)
        if not memorySnapshot:
            self.instance.setPowerState(xenrt.PowerState.up)

    def _snapRevert(self, memorySnapshot=False):
        snapName = xenrt.randomGuestName()
        self.instance.createSnapshot(snapName, memory=memorySnapshot)
        self._snapshotRevert(snapName, memorySnapshot)
        self.instance.deleteSnapshot(snapName)
        # Revert to base snapshot to prevent snapshot chain getting too long
        self._snapshotRevert("%s-base" % self.instance.name, memorySnapshot=False)

    def _snapDelete(self, memorySnapshot=False):
        snapName = xenrt.randomGuestName()
        self.instance.createSnapshot(snapName, memory=memorySnapshot)
        self.instance.deleteSnapshot(snapName)
        # Revert to base snapshot to prevent snapshot chain getting too long
        self._snapshotRevert("%s-base" % self.instance.name, memorySnapshot=False)

    def _multiSnapRevert(self, memorySnapshot=False):
        snapNames = [xenrt.randomGuestName() for x in range(self.snapCount)]
        for s in snapNames:
            self.instance.createSnapshot(s, memory=memorySnapshot)
        for s in snapNames:
            self._snapshotRevert(s, memorySnapshot)

        # Revert to base snapshot to prevent snapshot chain getting too long
        self._snapshotRevert("%s-base" % self.instance.name, memorySnapshot=False)

        for s in snapNames:
            self.instance.deleteSnapshot(s)

    def _multiSnapDelete(self, memorySnapshot=False):
        snapNames = [xenrt.randomGuestName() for x in range(self.snapCount)]
        for s in snapNames:
            self.instance.createSnapshot(s, memory=memorySnapshot)
        for s in snapNames:
            self.instance.deleteSnapshot(s)

        # Revert to base snapshot to prevent snapshot chain getting too long
        self._snapshotRevert("%s-base" % self.instance.name, memorySnapshot=False)

    def snapRevertDisk(self):
        self._snapRevert()

    def snapDeleteDisk(self):
        self._snapDelete()

    def multiSnapRevertDisk(self):
        self._multiSnapRevert()

    def multiSnapDeleteDisk(self):
        self._multiSnapDelete()

    def snapRevertDiskAndMem(self):
        self._snapRevert(memorySnapshot=True)

    def snapDeleteDiskAndMem(self):
        self._snapDelete(memorySnapshot=True)

    def multiSnapRevertDiskAndMem(self):
        self._multiSnapRevert(memorySnapshot=True)

    def multiSnapDeleteDiskAndMem(self):
        self._multiSnapDelete(memorySnapshot=True)

    def stopStart(self):
        self.instance.stop()
        self.instance.start()

    def reboot(self):
        self.instance.reboot()

    def migrate(self):
        migrateToList = self.instance.canMigrateTo
        if not migrateToList:
            xenrt.TEC().logverbose("No suiteable machines for migration")
            return
        migrateTo = random.choice(migrateToList)
        self.instance.migrate(migrateTo)

    def cloneDelete(self):
        templateName = xenrt.randomGuestName()
        self.cloud.createTemplateFromInstance(self.instance, templateName)

        instance2 = self.cloud.createInstanceFromTemplate(templateName)
        instance2.destroy()
        templateid = [x.id for x in self.cloud.cloudApi.listTemplates(templatefilter="all", name=templateName) if x.name==templateName][0]

        self.cloud.cloudApi.deleteTemplate(id=templateid)

class TCStopStartInstanceStress(TCInstanceLifecycleStress):
    """Simple stress test that just stops and starts instances"""
    STRESS_OPS = { "StopStart": "stopStart" }
