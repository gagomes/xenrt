import xenrt

import random

class TCInstanceLifecycleStress(xenrt.TestCase):
    def prepare(self, arglist):
        self.args = self.parseArgsKeyValue(arglist)

        self.cloud = self.getDefaultToolstack()
        self.instance = self.cloud.createInstance(distro=self.args['distro'], hypervisorType=self.args.get("hypervisor"), name=self.args.get("instancename"))
        self.instance.createSnapshot("%s-base" % self.instance.name)
        self.getLogsFrom(self.instance)

        self.snapCount = self.args.get("snapcount", 9)
    
    def run(self, arglist):
        ops = {"StopStart": "stopStart",
               "Reboot": "reboot",
               "Migrate": "migrate",
               "SnapRevert": "snapRevert",
               "SnapDelete": "snapDelete",
               "MultiSnapDelete": "multiSnapDelete",
               "MultiSnapRevert": "multiSnapRevert",
               "CloneDelete": "cloneDelete"}

        for i in xrange(int(self.args.get("iterations", 400))):
            op = random.choice(ops.keys())
            if self.runSubcase(ops[op], (), "Iter-%d" % i, op) != xenrt.RESULT_PASS:
                break

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

    def snapRevert(self):
        snapName = xenrt.randomGuestName()
        self.instance.createSnapshot(snapName)
        self.instance.revertToSnapshot(snapName)
        self.instance.setPowerState(xenrt.PowerState.up)
        self.instance.deleteSnapshot(snapName)
        # Revert to base snapshot to prevent snapshot chain getting too long
        self.instance.revertToSnapshot("%s-base" % self.instance.name)
        self.instance.setPowerState(xenrt.PowerState.up)

    def snapDelete(self):
        snapName = xenrt.randomGuestName()
        self.instance.createSnapshot(snapName)
        self.instance.deleteSnapshot(snapName)
        # Revert to base snapshot to prevent snapshot chain getting too long
        self.instance.revertToSnapshot("%s-base" % self.instance.name)
        self.instance.setPowerState(xenrt.PowerState.up)

    def multiSnapRevert(self):
        
        snapNames = [xenrt.randomGuestName() for x in range(self.snapCount)]
        for s in snapNames:
            self.instance.createSnapshot(s)
        for s in snapNames:
            self.instance.revertToSnapshot(s)
            self.instance.setPowerState(xenrt.PowerState.up)
        
        # Revert to base snapshot to prevent snapshot chain getting too long
        self.instance.revertToSnapshot("%s-base" % self.instance.name)
        self.instance.setPowerState(xenrt.PowerState.up)

        for s in snapNames:
            self.instance.deleteSnapshot(s)

    def multiSnapDelete(self):
        snapNames = [xenrt.randomGuestName() for x in range(self.snapCount)]
        for s in snapNames:
            self.instance.createSnapshot(s)
        for s in snapNames:
            self.instance.deleteSnapshot(s)
        
        self.instance.revertToSnapshot("%s-base" % self.instance.name)
        self.instance.setPowerState(xenrt.PowerState.up)

    def cloneDelete(self):
        templateName = xenrt.randomGuestName()
        self.cloud.createTemplateFromInstance(self.instance, templateName)

        instance2 = self.cloud.createInstanceFromTemplate(templateName)
        instance2.destroy()
        templateid = [x.id for x in self.cloud.cloudApi.listTemplates(templatefilter="all", name=templateName) if x.name==templateName][0]

        self.cloud.cloudApi.deleteTemplate(id=templateid)

