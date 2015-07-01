import re, string, socket, time, os.path, copy
import xenrt
from sets import Set as unique


class PacketCatcher(object):

    def __init__(self, host, delay=2, nolog=True):
        self.host = host
        self.packets = []
        self.pid = None
        self.delay = delay
        self.nolog = nolog
        self.datafile = self.host.execdom0("mktemp").strip()

    def startCapture(self, params):

        #if isinstance(self.host, xenrt.lib.xenserver.ClearwaterHost):
            #params = params + " -B 64000"
        if isinstance(self.host, xenrt.lib.xenserver.DundeeHost):
            params = params + " -U"

        self.packets = []
        xenrt.TEC().logverbose("PacketCatcher: Starting capture on %s..." % (self.host.getName()))
        self.pid = self.host.execdom0("tcpdump %s &> %s & echo $!" % 
                                      (params, self.datafile)).strip()

    def stopCapture(self):
        xenrt.TEC().logverbose("Sleeping for %ss." % (self.delay))
        time.sleep(self.delay)
        xenrt.TEC().logverbose("PacketCatcher: Stopping capture on %s... (PID %s)" % 
                               (self.host.getName(), self.pid))
        self.host.execdom0("kill %s" % (self.pid))

        # obtain file and save it into log dir for easier analysis.
        d = "%s/captured-%s" % (xenrt.TEC().getLogdir(), time.strftime("%Y%m%d-%H%M%S"))
        try:
            sftp = self.host.sftpClient()
            sftp.copyFrom(self.datafile, d)
        except Exception, e:
            raise xenrt.XRTError("Failed to obtain capture data: %s", str(e))
        self.host.execdom0("rm -f %s" % (self.datafile))

        # Read captured data and process it.
        data = ""
        with open(d, "r") as fp:
            data = fp.read()
        self.processData(data)
        if not xenrt.TEC().lookup("KEEP_TCPDUMP_LOG", False, boolean=True):
            try:
                os.remove(d)
            except:
                pass

    def processData(self, data):
        timestamps = re.findall("\d+\.\d+ IP", data)
        for t in timestamps:
            r = re.search("(%s.*?)\n[^\s]" % (t), data, flags=re.DOTALL)
            if not r:
                raise xenrt.XRTError("Could not find content in data '%s'" % (data))
            contents = r.group(1)
            r = re.search("(%s.*?)\s+0x0000" % (t), contents, re.DOTALL)
            if not r:
                raise xenrt.XRTError("Could not find header in contents '%s'" % (contents))
            header = r.group(1).replace("\n", "").replace("\r", "")
            body = re.sub("\s+", "", "".join(re.findall("0x\w{4}:\s+(.*)", contents)))
            self.packets.append((header, body))

    def searchData(self, pattern):
        return filter(lambda (h,b):re.search(pattern, b), self.packets)

    def searchHeader(self, pattern):
        return filter(lambda (h,b):re.search(pattern, h), self.packets)

    def getTimestamp(self, packet):
        header, body = packet
        return float(re.search("(?P<timestamp>\d+\.\d+)", header).group("timestamp"))

class NFSPacketCatcher(PacketCatcher):

    def getNFSReply(self, packet):
        header, body = packet
        xenrt.TEC().logverbose("Looking for reply to NFS packet with header: %s" % (header))
        sequence = self.getNFSSequence(packet)
        matches = self.searchHeader(".*%s.*reply" % (sequence)) 
        if len(matches) > 1: 
            raise xenrt.XRTError("Found more than one possible NFS reply.")
        return matches[0]

    def getNFSSequence(self, packet):
        header, body = self.getNFSHeader(packet)
        src, dst = re.search("(?P<src>[\w\.]+)\s+>\s+(?P<dst>[\w\.]+)", header).groups()
        srcseq = re.search("\.(?P<sequence>\d+$)", src) 
        dstseq = re.search("\.(?P<sequence>\d+$)", dst)
        xid = re.search("xid\s+(?P<xid>\d+)\s", header)
        if xid:
            return xid.group("xid")
        if srcseq:
            return srcseq.group("sequence")
        elif dstseq:
            return dstseq.group("sequence")
        else:
            raise xenrt.XRTError("Cannot find NFS sequence or xid from packet.")

    def getNFSHeader(self, packet):
        header, body = packet
        # This is broken - assume for now the packet we already have is the one we need
        return (header, body)

        try: 
            id = int(re.search("id (?P<id>\d+)", header).group("id"))
        except:
            xenrt.TEC().warning("Failed to find ID for: %s %s" % (header, body))
            return (header, body)
        while True:
            xenrt.TEC().logverbose("Checking for NFS header in packet with id: %s" % (id))
            matching = self.searchHeader("id %s," % (id))
            if len(matching) == 0:
                raise xenrt.XRTError("Found no packets with ID %s" % (id))
            if len(matching) > 1:
                raise xenrt.XRTError("Found multiple packets with the same ID. (%s)" % (id))
            header, body = matching[0]
            if re.search("read|write", header):
                xenrt.TEC().logverbose("Found NFS header: %s" % (header))
                return (header, body)
            else:
                xenrt.TEC().logverbose("Packet id %s appears to be a fragment." % (id))
                id = id - 1

class IOPPacketCatcher(PacketCatcher):

    def __init__(self, host, delay=2, nolog=True):
        PacketCatcher.__init__(self, host, delay, nolog)
        self.iterations = 0
        self.reads = [] 
        self.writes = []

    def startCapture(self, pattern):
        self.iterations += 1
        return PacketCatcher.startCapture(self, pattern)

    def processData(self, data):
        if isinstance(self.host, xenrt.lib.xenserver.DundeeHost):
            exclude = "null|proc"
        else:
            exclude = "null|win:proc"
        self.reads.append(len(filter(lambda x:re.search("read", x), 
                              filter(lambda x:not re.search(exclude, x), data.splitlines()))))
        self.writes.append(len(filter(lambda x:re.search("write", x), 
                               filter(lambda x:not re.search(exclude, x), data.splitlines()))))

class _Cache(xenrt.TestCase):

    REMOVE_IMAGES = False 
    IN_GUEST = False
    RESET = False
    ASYNC_CACHE_DELAY = 0.1

    def _accessVDI(self, vdi, operations):
        result = {}
        guest = self.getGuest(vdi) 
        xenrt.TEC().logverbose("Guest: %s IN_GUEST: %s" % (guest, self.IN_GUEST))
        if guest and self.IN_GUEST:
            for op in operations:
                if guest.windows:
                    if op == "write":
                        data = guest.xmlrpcExec("%s c:\\test.bin" % 
                                                (xenrt.TEC().lookup("WINDOWS_WRITE")), 
                                                 returndata=True)
                    else:
                        data = guest.xmlrpcExec("%s c:\\test.bin" % 
                                                (xenrt.TEC().lookup("WINDOWS_READ")), 
                                                 returndata=True)
                else: 
                    device = self.host.parseListForOtherParam("vbd-list", "vdi-uuid", vdi, "device")
                    data = guest.execguest("DEVICE=%s %s/progs/lin%s" % (device, 
                                                                         xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), 
                                                                         op))
                time.sleep(self.ASYNC_CACHE_DELAY)
        else:
            self.host.execdom0("echo \#\!/bin/sh > /tmp/vdi.sh")
            for op in operations:
                self.host.execdom0("echo %s/progs/lin%s >> /tmp/vdi.sh" %
                                   (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), op))
                self.host.execdom0("echo sleep %s >> /tmp/vdi.sh" % (self.ASYNC_CACHE_DELAY)) 
            self.host.execdom0("chmod +x /tmp/vdi.sh")
            data = self.host.execdom0("/opt/xensource/debug/with-vdi %s /tmp/vdi.sh" % (vdi))
        results = []
        datapoint = {}
        for l in data.splitlines():
            operation = re.search("read:|write:", l)
            if operation:
                datapoint["operation"] = operation.group().strip(":") 
                datapoint["data"] = re.sub("\s+", "", 
                                    re.search("%s:\s+(.*)" % (datapoint["operation"]), l).group(1))
            start = re.search("start:\s+([\d\.]+)", l)
            if start:
                datapoint["start"] = float(start.group(1))
            end = re.search("end:\s+([\d\.]+)", l)
            if end:
                datapoint["end"] = float(end.group(1))
            duration = re.search("duration:\s+([\d\.]+)", l)
            if duration:
                datapoint["duration"] = float(duration.group(1))
                results.append(datapoint)
                datapoint = {}
        return results

    def readVDI(self, vdi):
        results = self._accessVDI(vdi, ["read"])
        if len(results) > 0:
            return results[0]
        else:
            raise xenrt.XRTError("Error while trying to read the VDI.")

    def writeVDI(self, vdi):
        results = self._accessVDI(vdi, ["write"])
        if len(results) > 0:
            return results[0]
        else:
            raise xenrt.XRTError("Error while trying to write the VDI.")

    def flushCache(self):
        for g in self.guests:
            try:
                g.shutdown(force=True)
            except Exception, e:
                xenrt.TEC().warning("Exception %s shutting down" % str(e))
            g.uninstall()
        self.guests = []
        try:
            cachefiles = self.host.execdom0("ls /var/run/sr-mount/%s/*.vhdcache" % \
                                           (self.host.getLocalSR())).strip().splitlines() 
        except:
            cachefiles = []
        for cache in cachefiles:
            data = self.host.execdom0("tap-ctl list -f %s" % (cache)).strip()
            xenrt.TEC().logverbose("tap-ctl list -f %s's data:\n %s" % (cache, data))
            pid = re.search("pid=(\d+)", data)
            minor = re.search("minor=(\d+)", data)
            if pid and minor:
                self.host.execdom0("tap-ctl destroy -m %s -p %s" % (minor.group(1), pid.group(1)))
            try: self.host.execdom0("rm -f %s" % (cache))
            except: pass
        xenrt.TEC().logverbose("Local SR: %s" % (self.host.execdom0("ls /var/run/sr-mount/%s/" % (self.host.getLocalSR()))))
        xenrt.TEC().logverbose("Remote SR: %s" % (self.host.execdom0("ls /var/run/sr-mount/%s/" % (self.host.lookupDefaultSR()))))

        taplist = self.host.execdom0("tap-ctl list")

        sr_list = []

        for tapfile in taplist:
            tap_parts = tapfile.split()
            if len(tap_parts) != 5:
                xenrt.TEC().logverbose(
                        "Warning Strange tap file in output %s skipping." % (tapfile))
                continue

            vhd = tap_parts[4].strip()
            if not vhd.endswith(".vhd"):
                xenrt.TEC().logverbose("VHD in unexpected format %s" % (vhd))
                continue

            sr_list.append(os.path.dirname(vhd).split('/')[-1])

        for sr in unique(sr_list):
            self.host.execdom0("ls -l /var/run/sr-mount/%s/" % sr)

        # Flushing read cache, too.
        if isinstance(self.host, xenrt.lib.xenserver.CreedenceHost):
            self.host.execdom0("sync && echo 3 > /proc/sys/vm/drop_caches")
            xenrt.sleep(5)


    def configureNetwork(self):
        if "latency" in self.networkCharacteristics:
            for bridge in self.host.getExternalBridges():
                xenrt.TEC().logverbose("Adding network latency of %sms to %s." % 
                                       (self.networkCharacteristics["latency"], bridge))
                self.host.execdom0("tc qdisc add dev %s root netem delay %sms" % 
                                   (bridge, self.networkCharacteristics["latency"]))

    def resetNetwork(self):
        if "latency" in self.networkCharacteristics:
            for bridge in self.host.getExternalBridges():
                xenrt.TEC().logverbose("Removing traffic shaping on %s." % (bridge))
                self.host.execdom0("tc qdisc del dev %s root" % (bridge))

    def beginMeasurement(self): 
        self.configureNetwork()
        xenrt.TEC().logverbose("Capturing all NFS traffic on %s." % (self.host.getName()))
        param = "tcp port nfs and host %s -i %s -tt -x -s 65535 -vv" % (self.host.getIP(),self.host.getPrimaryBridge())
        self.packetCatcher.startCapture(param)
    
    def endMeasurement(self):
        self.packetCatcher.stopCapture()
        self.resetNetwork()

    def getGuest(self, vdi):
        vbduuid = self.host.genParamGet("vdi", vdi, "vbd-uuids")
        for vbd in vbduuid.split(";"):
            vbd = vbd.strip()
            vmuuid = self.host.genParamGet("vbd", vbd, "vm-uuid")
            isdom0 = self.host.genParamGet("vm", vmuuid, "is-control-domain") == "true"
            if isdom0: continue
            xenrt.TEC().logverbose("The VDI %s is attached to the VM with UUID %s." % (vdi, vmuuid))
            for guest in [ xenrt.TEC().registry.guestGet(x) for x in xenrt.TEC().registry.guestList() ]:
                if guest.getUUID() == vmuuid:
                    return guest

    def _previousOperation(self, operation, type, operations):
        possible = filter(lambda x:x["start"] < operation["start"] and x["operation"] == type, 
                          operations)
        if not possible:
            return None
        else:
            return sorted(possible, key=lambda x:x["start"], reverse=True)[0]

    def _nextOperation(self, operation, type, operations):
        possible = filter(lambda x:x["start"] > operation["start"] and x["operation"] == type, 
                          operations)
        if not possible:
            return None
        else:
            return sorted(possible, key=lambda x:x["start"])[0]

    def _nextWrite(self, operation, operations):
        return self._nextOperation(operation, "write", operations)

    def _nextRead(self, operation, operations):
        return self._nextOperation(operation, "read", operations)

    def _previousWrite(self, operation, operations):
        return self._previousOperation(operation, "write", operations)

    def _previousRead(self, operation, operations):
        return self._previousOperation(operation, "read", operations)

    def _matchingRead(self, write, operations):
        nextWrite = self._nextWrite(write, operations)
        nextRead = self._nextRead(write, operations)
        if not nextRead:
            xenrt.TEC().logverbose("Cannot find a matching read for the write at %f." % 
                                   (write["start"]))
            return None
        elif not nextWrite or nextRead["start"] < nextWrite["start"]:
            if not nextRead["data"] == write["data"]:
                raise xenrt.XRTError("Data read at %f does not match that written at %f. (%s, %s)" %
                                     (nextRead["start"], write["start"], 
                                      nextRead["data"], write["data"]))
            return nextRead
        else:
            xenrt.TEC().logverbose("Cannot determine if the write at %f was cached "
                                   "because there was a conflicting write at %f. "   
                                   "This was before the next read at %f." %
                                   (write["start"], nextWrite["start"], nextRead["start"]))
            return None

    def _matchingWrite(self, read, operations):
        previousWrite = self._previousWrite(read, operations)
        if not previousWrite:
            xenrt.TEC().logverbose("Cannot find a matching write for the read at %f." %
                                   (read["start"]))
            return None
        else:
            if not previousWrite["data"] == read["data"]:
                raise xenrt.XRTError("Data read at %f does not match that written at %f. (%s, %s)" %
                                     (read["start"], previousWrite["start"], 
                                      read["data"], previousWrite["data"]))
            return previousWrite
        
    def _checkWriteCommit(self, write):
        writePackets = filter(lambda (h,b):re.search("write", h), 
                                [ self.packetCatcher.getNFSHeader(p) for p in \
                                    self.packetCatcher.searchData(write["data"]) ])
        if not writePackets:
            xenrt.TEC().logverbose("No NFS packet found for the write at %f. "
                                   "It does not appear to be committed." % (write["start"]))
            return None, None 
        elif len(writePackets) > 1:
            xenrt.TEC().warning("Saw %f NFS write packets for the write at %f. "
                                "It's unclear whether it was committed." % (writePackets, write["start"]))
            return None, None
        else:
            writeTime = self.packetCatcher.getTimestamp(writePackets[0])
            xenrt.TEC().logverbose("Saw a NFS packet for the write at %f at %f." % 
                                   (write["start"], writeTime))
            reply = self.packetCatcher.getNFSReply(writePackets[0])
            replyTime = self.packetCatcher.getTimestamp(reply)
            xenrt.TEC().logverbose("Saw a NFS reply packet for the write at %f at %f." % 
                                   (write["start"], replyTime))
            if "latency" in self.networkCharacteristics:
                xenrt.TEC().logverbose("Adjusting observed NFS packet time for "
                                       "simulated network latency of %sms." % 
                                       (self.networkCharacteristics["latency"]))
                writeTime -= self.networkCharacteristics["latency"]/1000.0
            difference = (write["end"]-write["start"]) - (replyTime-writeTime)

            xenrt.TEC().logverbose("GUEST WRITE (%f) : NFS WRITE (%f) : "
                                   "NFS REPLY (%f) : GUEST COMPLETE (%f)" %
                                   (write["start"], writeTime, replyTime, write["end"]))
            xenrt.TEC().logverbose("NFS DURATION (%f) : GUEST DURATION (%f)" % 
                                   (replyTime-writeTime, write["end"]-write["start"]))
            xenrt.TEC().logverbose("NFS WRITE-GUEST WRITE DELTA (%f)" % (writeTime-write["start"]))
            xenrt.TEC().logverbose("NFS DURATION-GUEST DURATION DELTA (%f)" % (difference))
        
            return writeTime, replyTime

    def isDataCorrupt(self, read, operations):
        self._matchingWrite(read, operations) 

    def isWriteCommitted(self, write):
        nfsWrite, nfsReply = self._checkWriteCommit(write)
        if not nfsWrite or not nfsReply:
            xenrt.TEC().logverbose("The write at %f appears uncommitted." % (write["start"]))  
            return False
        else:
            xenrt.TEC().logverbose("The write at %f appears committed." % (write["start"]))  
            return True
 
    def isWriteSynchronised(self, write):       
        nfsWrite, nfsReply = self._checkWriteCommit(write)
        if write["start"] < nfsWrite < nfsReply < write["end"]:
            xenrt.TEC().logverbose("All events ordered: %f < %f < %f < %f" % 
                                   (write["start"], nfsWrite, nfsReply, write["end"]))
            return True
        else:
            xenrt.TEC().logverbose("Events not in correct order.")
            return False
 
    def isWriteLazy(self, write):
        if self.isWriteCommitted(write):
            if not self.isWriteSynchronised(write):
                xenrt.TEC().logverbose("The write at %f appears commmitted but not "
                                       "synchronised. It is lazy." % (write["start"]))
                return True
            else:
                xenrt.TEC().logverbose("The write at %f is synchronous, not lazy." % (write["start"]))
                return False
        else:
            xenrt.TEC().logverbose("No packet seen for write at %f so it's "
                                   "unclear if writes are lazy." % (write["start"])) 
            return False

    def isWriteCached(self, write, operations):
        read = self._matchingRead(write, operations)
        if not read:
            xenrt.TEC().logverbose("Not enough information to determine "
                                   "if the write at %f was cached." % (write["start"]))
            return False
        elif self.isReadCached(read):
            xenrt.TEC().logverbose("The write at %f was cached." % (write["start"])) 
            return True
        else:
            xenrt.TEC().logverbose("The write at %f was not cached." % (write["start"]))
            return False

    def isReadCached(self, read):
        readPackets = filter(lambda (h,b):re.search("read", h), 
                                [ self.packetCatcher.getNFSHeader(p) for p in \
                                    self.packetCatcher.searchData(read["data"]) ]) 
        xenrt.TEC().logverbose("Total number of read packets found: %s" % (len(readPackets)))
        readPackets = filter(lambda (h,b):float(re.search("[0-9\.]+", h).group()) > read["start"], readPackets)
        xenrt.TEC().logverbose("Total number of read packets after trimming early: %s" % (len(readPackets)))
        readPackets = filter(lambda (h,b):float(re.search("[0-9\.]+", h).group()) < read["end"], readPackets)
        xenrt.TEC().logverbose("Total number of read packets found after trimmming late: %s" % (len(readPackets)))
        if not readPackets:
            xenrt.TEC().logverbose("No NFS packet found for the read at %f. "
                                   "It appears to be cached." % (read["start"]))
            return True
        elif len(readPackets) == 1:
            xenrt.TEC().logverbose("Found one NFS read packet for the read at %f. "
                                   "It appears to not be cached." % (read["start"]))
            return False
        else:
            xenrt.TEC().warning("Read %s NFS packets for the read at %f "
                                "instead of one. It appears to not be cached." % 
                                (len(readPackets), read["start"]))
            return False

    def checkWriteDiscard(self, vdi):
        guest = self.getGuest(vdi)
        if not guest:
            xenrt.TEC().logverbose("The VDI %s is not attached to a guest." % (vdi))
            return False
        seed = self.writeVDI(vdi)
        before = self.readVDI(vdi)
        if not before["data"] == seed["data"]:
            xenrt.TEC().logverbose("Data mismatch before VM reboot.")
            return False
        else:
            xenrt.TEC().logverbose("Data matches before VM reboot.")
        guest.reboot()
        read = self.readVDI(vdi)
        if read["data"] == seed["data"]:
            xenrt.TEC().logverbose("Data has not been discarded after VM reboot.")
            return False
        else:
            xenrt.TEC().logverbose("Data has been discarded after VM reboot.")
            return True
    
    def checkReadCaching(self, vdi):
        self.beginMeasurement()
        readA, readB = self._accessVDI(vdi, ["read", "read"])
        self.endMeasurement()
        if not self.seed["data"] == readA["data"] == readB["data"]:
            raise xenrt.XRTFailure("Data mismatch.")
        if self.isReadCached(readA):
            raise xenrt.XRTFailure("Reads from VDI %s are cached." % (vdi))
        else:
            xenrt.TEC().logverbose("Reads from VDI %s are not cached." % (vdi))
        if self.isReadCached(readB):
            xenrt.TEC().logverbose("Reads from VDI %s are cached." % (vdi))
        else:
            raise xenrt.XRTFailure("Reads from VDI %s are not cached." % (vdi))

    def checkWriteCaching(self, vdi):
        self.beginMeasurement()
        write, read = self._accessVDI(vdi, ["write", "read"])
        self.endMeasurement()
        if self.isWriteCached(write, [write, read]):
            xenrt.TEC().logverbose("Writes to VDI %s appear to be cached." % (vdi))
        else:
            raise xenrt.XRTFailure("Writes to VDI %s do not appear to be cached." % (vdi))

    def checkWriteSynchronisation(self, vdi):
        self.beginMeasurement()
        write, read = self._accessVDI(vdi, ["write", "read"])
        self.endMeasurement()
        if self.RESET:
            if self.isWriteSynchronised(write):
                raise xenrt.XRTFailure("Writes to VDI %s appear to be synchronised." % (vdi))
            else:
                xenrt.TEC().logverbose("Writes to VDI %s do not appear to be synchronised." % (vdi))
        else:
            if self.isWriteSynchronised(write):
                xenrt.TEC().logverbose("Writes to VDI %s appear to be synchronised." % (vdi))
            else:
                raise xenrt.XRTFailure("Writes to VDI %s do not appear to be synchronised." % (vdi))

    def checkWriteLaziness(self, vdi):
        self.beginMeasurement()
        write, read = self._accessVDI(vdi, ["write", "read"])
        self.endMeasurement()
        if self.isWriteLazy(write):
            xenrt.TEC().logverbose("Writes to VDI %s appear to be lazy." % (vdi))
        else:
            raise xenrt.XRTFailure("Writes to VDI %s do not appear to be lazy." % (vdi))

    def checkWriteCommit(self, vdi):
        self.beginMeasurement()
        write, read = self._accessVDI(vdi, ["write", "read"])
        self.endMeasurement()
        if self.isWriteCommitted(write):
            xenrt.TEC().logverbose("Writes to VDI %s appear to be committed." % (vdi))
        else:
            raise xenrt.XRTFailure("Writes to VDI %s do not appear to be committed." % (vdi))

    def enableCaching(self):
        self.host.disable()
        self.host.enableCaching()
        self.host.enable()

    def disableCaching(self):
        self.host.disable()
        self.host.disableCaching()
        self.host.enable()

    def createTargetDisk(self, windows=False, cached=False, reset=False, attached=True, seed=False):
        if attached:
            target = self.createTargetVM(windows=windows, cached=cached, reset=reset, seed=seed)
            device = sorted(self.host.minimalList("vbd-list", "userdevice", 
                                                  "vm-uuid=%s type=Disk" % (target.getUUID())))[0]
            return self.host.parseListForOtherParam("vbd-list", "userdevice", device, "vdi-uuid", 
                                                    "vm-uuid=%s" % (target.getUUID()))
        else:
            sruuid = self.host.lookupDefaultSR()
            cli = self.host.getCLIInstance()
            args = []
            args.append("name-label=cache_test")
            args.append("virtual-size=1MiB")
            args.append("sr-uuid=%s" % (sruuid))
            args.append("type=user")
            master = cli.execute("vdi-create", string.join(args)).strip()
            args = []
            args.append("uuid=%s" % (master))
            args.append("sr-uuid=%s" % (sruuid))
            gold = cli.execute("vdi-copy", string.join(args)).strip()
            args = []
            args.append("uuid=%s" % (gold))
            return cli.execute("vdi-clone", string.join(args)).strip()

    def createTargetVM(self, windows=False, cached=False, reset=False, sr=None, seed=False):
        goldkey = (windows and "WINDOWS" or "LINUX") + "_" + \
                  (cached and "CACHED" or "SYNC") + "_" + \
                  (reset and "RESET" or "PERSIST") + "_" + \
                  (seed and "SEED" or "NOSEED") + "_GOLD"
        masterkey = (windows and "WINDOWS" or "LINUX") + "_MASTER"
        if not xenrt.TEC().registry.guestGet(goldkey):
            if not xenrt.TEC().registry.guestGet(masterkey):
                if not sr:
                    sr = self.host.lookupDefaultSR()
                if windows:
                    master = self.host.createGenericWindowsGuest(sr=sr)
                    xenrt.TEC().registry.guestPut(masterkey, master)
                    path = xenrt.TEC().lookup("LOCAL_SCRIPTDIR") + "/progs/winwrite/"
                    xenrt.TEC().config.setVariable("WINDOWS_WRITE", 
                                                    master.compileWindowsProgram(path) + "\\winwrite.exe") 
                    path = xenrt.TEC().lookup("LOCAL_SCRIPTDIR") + "/progs/winread/"
                    xenrt.TEC().config.setVariable("WINDOWS_READ", 
                                                    master.compileWindowsProgram(path) + "\\winread.exe")   
                    master.shutdown()
                else:
                    master = self.host.createGenericLinuxGuest(start=True, sr=sr)
                    master.preCloneTailor()
                    master.shutdown()
                    xenrt.TEC().registry.guestPut(masterkey, master)
            gold = xenrt.TEC().registry.guestGet(masterkey).copyVM()
            xenrt.TEC().registry.guestPut(goldkey, gold)
            if seed:
                if windows:
                    gold.start()
                device = sorted(self.host.minimalList("vbd-list", "userdevice", 
                                                      "vm-uuid=%s type=Disk" % (gold.getUUID())))[0]
                vdi = self.host.parseListForOtherParam("vbd-list", "userdevice", device, "vdi-uuid", 
                                                       "vm-uuid=%s" % (gold.getUUID()))
                gold.seed = self.writeVDI(vdi) 
                if windows:
                    gold.shutdown()
            for vdi in self.host.minimalList("vbd-list", "vdi-uuid", "vm-uuid=%s type=Disk" % (gold.getUUID())):
                self.host.genParamSet("vdi", vdi, "on-boot", reset and "reset" or "persist") 
                self.host.genParamSet("vdi", vdi, "allow-caching", cached and "true" or "false") 
        target = xenrt.TEC().registry.guestGet(goldkey).cloneVM()
        self.guests.append(target)
        xenrt.TEC().registry.guestPut(target.getName(), target)
        if seed:
            self.seed = xenrt.TEC().registry.guestGet(goldkey).seed
        return target

    def prepare(self, arglist=[]):
        self.networkCharacteristics = {}
        self.guests = []
        self.host = self.getDefaultHost()
        if not self.host.genParamGet("sr", self.host.lookupDefaultSR(), "type") == "nfs":
            raise xenrt.XRTError("The default SR must be an nfs one.")
        self.packetCatcher = NFSPacketCatcher(self.host, delay=2)
        if isinstance(self.host, xenrt.lib.xenserver.CreedenceHost):
            self.host.disableReadCaching()
        self.enableCaching()

    def upgrade(self):
        xenrt.TEC().setInputDir(None)
        newhost = self.host.upgrade()
        self.host = newhost
        return
       
    def postRun(self):
        try:
            for guest in self.guests:
                for vdi in self.host.minimalList("vbd-list", "vdi-uuid", "vm-uuid=%s type=Disk" % (guest.getUUID())):
                    self.host.genParamGet("vdi", vdi, "on-boot") 
                    self.host.genParamGet("vdi", vdi, "allow-caching") 
        except:
            pass
        try: self.disableCaching()
        except: pass
        try: self.packetCatcher.stopCapture()
        except: pass
        try: self.host.enable()
        except: pass
        try: self.flushCache()
        except: pass
        if self.REMOVE_IMAGES: 
            for image in ["WINDOWS_MASTER",
                          "LINUX_MASTER",
                          "WINDOWS_CACHED_RESET_GOLD",
                          "WINDOWS_CACHED_PERSIST_GOLD",
                          "WINDOWS_SYNC_RESET_GOLD",
                          "WINDOWS_SYNC_PERSIS_GOLD",
                          "LINUX_CACHED_RESET_GOLD",
                          "LINUX_CACHED_PERSIST_GOLD",
                          "LINUX_SYNC_RESET_GOLD",
                          "LINUX_SYNC_PERSIS_GOLD"]:
                try: self.getGuest(image).shutdown(force=True)
                except: pass
                try: self.getGuest(image).uninstall()
                except: pass

class _CheckCache(_Cache):

    REMOVE_IMAGES = True

    def prepare(self, arglist=[]):
        _Cache.prepare(self, arglist)
        self.vdiuuid = self.createTargetDisk(windows=False, cached=True, reset=self.RESET, seed=True) 

    def run(self, arglist=[]):
        self.runSubcase("checkReadCaching", self.vdiuuid, "Private", "ReadCaching")
        self.runSubcase("checkWriteCaching", self.vdiuuid, "Private", "WriteCaching")
        self.runSubcase("checkWriteSynchronisation", self.vdiuuid, "Private", "WriteSync")

class TC11869(_CheckCache):
    """For disks with the "behaviour on boot" flag set to "persist" but with the "local caching"
       flag set, cache writes on local storage as well as synchronously writing through 
       to the shared storage."""
    
    RESET = False

class TC12068(_CheckCache):

    RESET = True

class TC11870(_Cache):
    """For disks with the "behaviour on boot" flag set to "persist" and with the 
       "local caching" flag not set, synchronously write straight to the shared 
       storage (as in the traditional way)."""

    REMOVE_IMAGES = True

    def prepare(self, arglist=[]):
        _Cache.prepare(self, arglist)
        self.vdiuuid = self.createTargetDisk(windows=False, cached=False, reset=False, seed=True)

    def checkReadCaching(self, vdiuuid):
        try:
            _Cache.checkReadCaching(self, vdiuuid)
        except Exception, e: 
            xenrt.TEC().logverbose("Expected exception: %s" % (str(e)))
        else: raise xenrt.XRTFailure("Reads appear to be cached.")

    def checkWriteCaching(self, vdiuuid):
        try: 
            _Cache.checkWriteCaching(self, vdiuuid)
        except Exception, e: 
            xenrt.TEC().logverbose("Expected exception: %s" % (str(e)))
        else: raise xenrt.XRTFailure("Writes appear to be cached.")

    def run(self, arglist=[]):
        self.runSubcase("checkReadCaching", self.vdiuuid, "Private", "ReadCaching")
        self.runSubcase("checkWriteCaching", self.vdiuuid, "Private", "WriteCaching")
        self.runSubcase("checkWriteSynchronisation", self.vdiuuid, "Private", "WriteSync")
        
        if not xenrt.TEC().lookup("FEATURE_UPGRADE_TEST", False, boolean=True):
            return

        self.upgrade()
        
        self.runSubcase("checkReadCaching", self.vdiuuid, "Private", "ReadCaching")
        self.runSubcase("checkWriteCaching", self.vdiuuid, "Private", "WriteCaching")
        self.runSubcase("checkWriteSynchronisation", self.vdiuuid, "Private", "WriteSync")
        return
        
        
class _Discard(_Cache):

    IN_GUEST = True
    CACHED = True
    RESET = True

    def prepare(self, arglist=[]):
        _Cache.prepare(self)
        self.vdiuuid = self.createTargetDisk(windows=True, cached=self.CACHED, reset=self.RESET)
        self.guest = self.getGuest(self.vdiuuid)
        self.guest.start()

    def run(self, arglist=[]):
        if not self.checkWriteDiscard(self.vdiuuid) == self.RESET:
            raise xenrt.XRTFailure("Writes to VDI %s were not appropriately discarded or persisted." % 
                                   (self.vdiuuid))

class TC11942(_Discard):
    """Write discard test."""

    IN_GUEST = True
    CACHED = True
    RESET = True

class TC12060(_Discard):
    """Write discard test for uncached disks."""

    IN_GUEST = True
    CACHED = False 
    RESET = True

class TC12066(_Discard):
    """Write persist test."""

    IN_GUEST = True
    RESET = False
    CACHED = True

class TC19835(_Discard):
    """Write persist test (with host upgrade)"""
    
    IN_GUEST = True
    RESET = False
    CACHED = True
    
    def run(self, arglist=[]):
        if not self.checkWriteDiscard(self.vdiuuid) == self.RESET:
            raise xenrt.XRTFailure("Writes to VDI %s were not appropriately persisted." % 
                                   (self.vdiuuid))
        self.guest.shutdown()
        self.guest.changeCD(None)
        self.upgrade()
        self.guest.start()

        if not self.checkWriteDiscard(self.vdiuuid) == self.RESET:
            raise xenrt.XRTFailure("Writes to VDI %s were not appropriately persisted after host upgrade." % 
                                   (self.vdiuuid))
        return
        
class TC12067(_Discard):
    """Write persist test for uncached disks."""

    IN_GUEST = True
    RESET = False
    CACHED = False 

class TC11864(_Cache):
    """Check that the host-level caching switch can only be toggled when there are no 
       running VMs and the host is disabled.""" 

    def testHostSwitch(self, caching=False, disabled=False, vms=False):
        try:
            if caching:
                xenrt.TEC().logverbose("Testing disabling of cache.")
            else:
                xenrt.TEC().logverbose("Testing enabling of cache.")
                self.disableCaching()
            if vms:
                xenrt.TEC().logverbose("Testing host switch with a running VM.")
                self.guest.start()
                self.guest.poll("UP")
            else:
                xenrt.TEC().logverbose("Testing host switch with no running VMs.")
            if disabled:
                xenrt.TEC().logverbose("Testing host switch with a disabled host.")
                self.host.disable()
            else:
                xenrt.TEC().logverbose("Testing host switch with an enabled host.")
            expected = disabled and not vms
            xenrt.TEC().logverbose("Expecting cache operation to %s." % (expected and "succeed" or "fail")) 
            if caching:
                togglecache = self.host.disableCaching
            else:
                togglecache = self.host.enableCaching
            try:
                togglecache()
            except Exception, e:
                if expected:
                    raise xenrt.XRTFailure("Toggling cache host flag failed unexpectedly. (%s)" % (str(e))) 
            else:
                if not expected:
                    raise xenrt.XRTFailure("Toggling cache host flag succeeded unexpectedly.") 
        finally:
            if not self.guest.getState() == "DOWN":
                self.guest.shutdown(force=True)
                self.guest.poll("DOWN")
            try: self.enableCaching()
            except: pass

    def prepare(self, arglist=[]):
        _Cache.prepare(self, arglist)
        self.guest = self.createTargetVM(windows=False, cached=False, reset=False)

    def run(self, arglist=[]):
        self.runSubcase("testHostSwitch", (True, True, True), "Cache", "DisabledVM")
        self.runSubcase("testHostSwitch", (True, True, False), "Cache", "DisabledNoVM")
        self.runSubcase("testHostSwitch", (True, False, True), "Cache", "EnabledVM")
        self.runSubcase("testHostSwitch", (True, False, False), "Cache", "EnabledNoVM")
        self.runSubcase("testHostSwitch", (False, True, True), "NoCache", "DisabledVM")
        self.runSubcase("testHostSwitch", (False, True, False), "NoCache", "DisabledNoVM")
        self.runSubcase("testHostSwitch", (False, False, True), "NoCache", "EnabledVM")
        self.runSubcase("testHostSwitch", (False, False, False), "NoCache", "EnabledNoVM")

class TC11865(_Cache):
    """Test that the disk-level caching switches can only be toggled if a VDI is 
       unattached or attached to a stopped VM."""

    ONBOOT = "reset"
    CACHE = "false"

    def testDiskSwitch(self, toggle="allow-caching", attached=False, cached=False, reset=False, running=False):
        vdiuuid = self.createTargetDisk(windows=False, cached=cached, reset=reset, attached=attached)
        if attached:
            guest = self.getGuest(vdiuuid)
        else:
            guest = self.createTargetVM(windows=False, cached=cached, reset=reset) 
        try:
            if running:
                xenrt.TEC().logverbose("Attempting to change flag with a running VM.")
                guest.start()
                guest.poll("UP") 
            expected = not attached or not running
            xenrt.TEC().logverbose("Expecting flag operation to %s." % (expected and "succeed" or "fail"))
            try:
                if toggle == "allow-caching":
                    self.host.genParamSet("vdi", vdiuuid, toggle, cached and "false" or "true")
                else:
                    self.host.genParamSet("vdi", vdiuuid, toggle, reset and "persist" or "reset")
            except:
                if expected:
                    raise xenrt.XRTFailure("Failed to toggle flag as expected.")
            else:
                if not expected:
                    raise xenrt.XRTFailure("Toggling flag succeeded unexpectedly.")
        finally:
            if not guest.getState() == "DOWN":
                guest.shutdown(force=True)
                guest.poll("DOWN")
            self.host.genParamSet("vdi", vdiuuid, "allow-caching", cached and "true" or "false")
            self.host.genParamSet("vdi", vdiuuid, "on-boot", reset and "reset" or "persist")

    def run(self, arglist=[]):
        self.runSubcase("testDiskSwitch", ("allow-caching", True, True, False, True), 
                        "CacheAttached", "CachePersistVM")
        self.runSubcase("testDiskSwitch", ("allow-caching", True, True, True, False), 
                        "CacheAttached", "CachePersistNoVM")
        self.runSubcase("testDiskSwitch", ("allow-caching", True, True, True, True), 
                        "CacheAttached", "CacheNoPersistVM")
        self.runSubcase("testDiskSwitch", ("allow-caching", True, True, True, False), 
                        "CacheAttached", "CacheNoPersistNoVM")
        self.runSubcase("testDiskSwitch", ("allow-caching", True, False, False, True), 
                        "CacheAttached", "NoCachePersistVM")
        self.runSubcase("testDiskSwitch", ("allow-caching", True, False, False, False), 
                        "CacheAttached", "NoCachePersistNoVM")
        self.runSubcase("testDiskSwitch", ("allow-caching", True, False, True, True), 
                        "CacheAttached", "NoCacheNoPersistVM")
        self.runSubcase("testDiskSwitch", ("allow-caching", True, False, True, False), 
                        "CacheAttached", "NoCacheNoPersistNoVM")
        self.runSubcase("testDiskSwitch", ("allow-caching", False, True, False, True), 
                        "CacheOrphan", "CachePersistVM")
        self.runSubcase("testDiskSwitch", ("allow-caching", False, True, False, False), 
                        "CacheOrphan", "CachePersistNoVM")
        self.runSubcase("testDiskSwitch", ("allow-caching", False, True, True, True), 
                        "CacheOrphan", "CacheNoPersistVM")
        self.runSubcase("testDiskSwitch", ("allow-caching", False, True, True, False), 
                        "CacheOrphan", "CacheNoPersistNoVM")
        self.runSubcase("testDiskSwitch", ("allow-caching", False, False, False, True), 
                        "CacheOrphan", "NoCachePersistVM")
        self.runSubcase("testDiskSwitch", ("allow-caching", False, False, False, False), 
                        "CacheOrphan", "NoCachePersistNoVM")
        self.runSubcase("testDiskSwitch", ("allow-caching", False, False, True, True), 
                        "CacheOrphan", "NoCacheNoPersistVM")
        self.runSubcase("testDiskSwitch", ("allow-caching", False, False, True, False), 
                        "CacheOrphan", "NoCacheNoPersistNoVM")
        self.runSubcase("testDiskSwitch", ("on-boot", True, True, False, True), 
                        "PersistAttached", "CachePersistVM")
        self.runSubcase("testDiskSwitch", ("on-boot", True, True, False, False), 
                        "PersistAttached", "CachePersistNoVM")
        self.runSubcase("testDiskSwitch", ("on-boot", True, True, True, True), 
                        "PersistAttached", "CacheNoPersistVM")
        self.runSubcase("testDiskSwitch", ("on-boot", True, True, True, False), 
                        "PersistAttached", "CacheNoPersistNoVM")
        self.runSubcase("testDiskSwitch", ("on-boot", True, False, False, True), 
                        "PersistAttached", "NoCachePersistVM")
        self.runSubcase("testDiskSwitch", ("on-boot", True, False, False, False), 
                        "PersistAttached", "NoCachePersistNoVM")
        self.runSubcase("testDiskSwitch", ("on-boot", True, False, True, True), 
                        "PersistAttached", "NoCacheNoPersistVM")
        self.runSubcase("testDiskSwitch", ("on-boot", True, False, True, False), 
                        "PersistAttached", "NoCacheNoPersistNoVM")
        self.runSubcase("testDiskSwitch", ("on-boot", False, True, False, True), 
                        "PersistOrphan", "CachePersistVM")
        self.runSubcase("testDiskSwitch", ("on-boot", False, True, False, False), 
                        "PersistOrphan", "CachePersistNoVM")
        self.runSubcase("testDiskSwitch", ("on-boot", False, True, True, True), 
                        "PersistOrphan", "CacheNoPersistVM")
        self.runSubcase("testDiskSwitch", ("on-boot", False, True, True, False), 
                        "PersistOrphan", "CacheNoPersistNoVM")
        self.runSubcase("testDiskSwitch", ("on-boot", False, False, False, True), 
                        "PersistOrphan", "NoCachePersistVM")
        self.runSubcase("testDiskSwitch", ("on-boot", False, False, False, False), 
                        "PersistOrphan", "NoCachePersistNoVM")
        self.runSubcase("testDiskSwitch", ("on-boot", False, False, True, True), 
                        "PersistOrphan", "NoCacheNoPersistVM")
        self.runSubcase("testDiskSwitch", ("on-boot", False, False, True, False), 
                        "PersistOrphan", "NoCacheNoPersistNoVM")

class TC11866(_Cache):
    """The caching flags must be preserved across a copy or clone of a VM's disk."""

    def testFlagPreservation(self, cached=False, reset=False, clone=False):
        vdiuuid = self.createTargetDisk(cached=cached, reset=reset)
        cli = self.host.getCLIInstance()
        if clone:
            xenrt.TEC().logverbose("Cloning VDI...")
            args = []
            args.append("uuid=%s" % (vdiuuid))
            duplicate = cli.execute("vdi-clone", string.join(args)).strip() 
        else:
            xenrt.TEC().logverbose("Copying VDI...")
            args = []   
            args.append("uuid=%s" % (vdiuuid))
            args.append("sr-uuid=%s" % (self.host.lookupDefaultSR()))
            duplicate = cli.execute("vdi-copy", string.join(args)).strip() 
        cloneCached = self.host.genParamGet("vdi", duplicate, "allow-caching") == "true" 
        cloneReset = self.host.genParamGet("vdi", duplicate, "on-boot") == "reset" 
        if not cloneCached == cached:
            raise xenrt.XRTFailure("Cache flag not preserved.")
        if not cloneReset == reset:
            raise xenrt.XRTFailure("Reset flag not preserved.")

    def run(self, arglist=[]):
        self.runSubcase("testFlagPreservation", (True, False, True), "CachePersist", "Clone")
        self.runSubcase("testFlagPreservation", (True, True, True), "CacheNoPersist", "Clone")
        self.runSubcase("testFlagPreservation", (False, False, True), "NoCachePersist", "Clone")
        self.runSubcase("testFlagPreservation", (False, True, True), "NoCacheNoPersist", "Clone")
        self.runSubcase("testFlagPreservation", (True, False, False), "CachePersist", "Copy")
        self.runSubcase("testFlagPreservation", (True, True, False), "CacheNoPersist", "Copy")
        self.runSubcase("testFlagPreservation", (False, False, False), "NoCachePersist", "Copy")
        self.runSubcase("testFlagPreservation", (False, True, False), "NoCacheNoPersist", "Copy")

class _DiskOperations(_Cache):
    """Base class for disk operations test case."""

    RESET = False 

    def testSnapshot(self):
        try:
            uuid = self.guest.snapshot()
            self.guest.removeSnapshot(uuid)
        except:
            if self.host.genParamGet("vdi", self.vdiuuid, "on-boot") == "persist": 
                raise xenrt.XRTFailure("Snapshot failed on disk marked as 'persist'.")
            else:
                xenrt.TEC().logverbose("Snapshot failed as expected.")
        else:
            if self.host.genParamGet("vdi", self.vdiuuid, "on-boot") == "reset": 
                raise xenrt.XRTFailure("Snapshot succeeded on disk marked as 'reset'.")
            else:
                xenrt.TEC().logverbose("Snapshot succeeded as expected.")
    
    def testCheckpoint(self):
        try:
            uuid = self.guest.checkpoint()
            self.guest.removeSnapshot(uuid)
        except:
            if self.host.genParamGet("vdi", self.vdiuuid, "on-boot") == "persist": 
                raise xenrt.XRTFailure("Checkpoint failed on disk marked as 'persist'.")
            else:
                xenrt.TEC().logverbose("Checkpoint failed as expected.")
        else:
            if self.host.genParamGet("vdi", self.vdiuuid, "on-boot") == "reset": 
                raise xenrt.XRTFailure("Checkpoint succeeded on disk marked as 'reset'.")
            else:
                xenrt.TEC().logverbose("Checkpoint succeeded as expected.")

    def testSuspend(self):
        try:
            self.guest.suspend()
            self.guest.resume()
        except:
            if self.host.genParamGet("vdi", self.vdiuuid, "on-boot") == "persist": 
                raise xenrt.XRTFailure("Suspend failed on disk marked as 'persist'.")
            else:
                xenrt.TEC().logverbose("Suspend failed as expected.")
        else:
            if self.host.genParamGet("vdi", self.vdiuuid, "on-boot") == "reset": 
                raise xenrt.XRTFailure("Suspend succeeded on disk marked as 'reset'.")
            else:
                xenrt.TEC().logverbose("Suspend succeeded as expected.")

    def testClone(self):
        try:
            self.guest.shutdown()
            clone = self.guest.cloneVM()
            clone.uninstall()
            self.guest.start()
        except:
            raise xenrt.XRTFailure("Clone of VM failed.")
        else:
            xenrt.TEC().logverbose("VM clone succeeded.")

    def testCopy(self):
        self.guest.shutdown()
        clone = self.guest.copyVM()
        clone.uninstall()
        self.guest.start()
        xenrt.TEC().logverbose("VM copy succeeded.")

    def prepare(self, arglist=[]):
        _Cache.prepare(self, arglist)
        self.vdiuuid = self.createTargetDisk(windows=True, cached=True, reset=self.RESET)
        self.guest = self.getGuest(self.vdiuuid)
        self.guest.start()

    def run(self, arglist=[]):
        self.runSubcase("testCopy", (), "Copy", "Copy")    
        self.runSubcase("testClone", (), "Clone", "Clone")    
        self.runSubcase("testSuspend", (), "Suspend", "Suspend")    
        self.runSubcase("testSnapshot", (), "Snapshot", "Snapshot")    
        self.runSubcase("testCheckpoint", (), "Checkpoint", "Checkpoint")   

class TC11867(_DiskOperations):
    """Test disk operations with 'persist' disks."""

    RESET = False

class TC11868(_DiskOperations):
    """Test disk operations with 'reset' disks."""

    RESET = True

class TC11871(xenrt.TestCase):
    """There must be a means of initialising a cache on local storage. It must 
       not impinge on or destroy any VDIs in any local SR(s)."""

    VDIS    = 4
    VDISIZE = "32MiB"

    def vdiHash(self, vdi):
        return self.host.execdom0("sha1sum /var/run/sr-mount/%s/%s.vhd" % 
                                  (self.cache, vdi)).strip()

    def checkVDIs(self, vdis):
        for v in vdis:
            if not vdis[v] == self.vdiHash(v):
                raise xenrt.XRTFailure("VDI hash changed: %s -> %s" % (vdis[v], self.vdiHash(v)))

    def prepare(self, arglist=[]):
        self.host = self.getDefaultHost()
        self.cache = self.host.getLocalSR()    
        self.guest = self.host.createGenericEmptyGuest()
        self.vdis = {}
        for i in range(self.VDIS):
            self.vdis[self.guest.getDiskVDIUUID(self.guest.createDisk(self.VDISIZE, sruuid=self.cache))] = None
        self.guest.start()
        for uuid in self.vdis:
            self.vdis[uuid] = self.vdiHash(uuid) 
        self.guest.shutdown(force=True)

    def run(self, arglist=[]):
        self.host.disable()
        self.host.enableCaching()
        self.host.enable()
        self.guest.start()
        self.checkVDIs(self.vdis)
        self.guest.shutdown(force=True)
        self.host.disable()
        self.host.disableCaching()
        self.host.enable()
        self.guest.start()
        self.checkVDIs(self.vdis)

    def postRun(self):
        try: self.guest.shutdown(force=True)
        except: pass
        try: self.guest.uninstall()
        except: pass
        try:
            self.host.disable()
            self.host.disableCaching()
            self.host.enable()
        except: 
            pass

class _PoolSwitch(xenrt.TestCase):
    """There must be a pool-level switch that may be used to toggle the member hosts' switches 
       used to indicate whether their local storage may be used.
       This switch should operate on a best-effort basis. If at least one host cannot enable 
       caching on local storage, this should not prevent the other hosts in the pool from 
       having caching enabled. """

    INVALID = 0
    CACHING = 0
    ENABLE = True

    def prepare(self, arglist=[]):
        self.pool = self.getDefaultPool()
        self.hosts = self.pool.getHosts()
        if self.INVALID > len(self.hosts):
            raise xenrt.XRTError("Can't have %s invalid hosts with %s hosts." % 
                                 (self.INVALID, len(self.hosts)))
        if self.CACHING > len(self.hosts):
            raise xenrt.XRTError("Can't have %s caching hosts with %s hosts." % 
                                 (self.CACHING, len(self.hosts)))
        for host in self.hosts:
            if not host.getLocalSR():
                raise xenrt.XRTError("Host %s doesn't appear to have a suitable cache SR." % 
                                     (host.getName()))

            # The testcase should only fail if there is at least 2 guests
            # one of which has to be the control domain
            xenrt.TEC().logverbose("Checking %s" % (host.getName()))
            running_domains = host.listGuests(running=True)
            if len(running_domains) > 1:
                raise xenrt.XRTError("Host %s has running guests: %s" % (host.getName(), running_domains))

            host.disable()
        for i in range(self.CACHING):
            self.hosts[i].enableCaching()
        for i in range(self.INVALID):
            self.hosts[i].enable()

    def run(self, arglist=[]):
        try:
            if self.ENABLE:
                self.pool.enableCaching()
            else:
                self.pool.disableCaching()
        except:
            if self.INVALID:
                xenrt.TEC().logverbose("Cache toggle with some invalid hosts returned an "
                                       "error as expected.")
        else:
            if self.INVALID:
                raise xenrt.XRTFailure("Cache toggle with some invalid hosts did not return "
                                       "an error.")
        for i in range(len(self.hosts)):
            enabled = self.hosts[i].getSRParam(self.hosts[i].getLocalSR(), "local-cache-enabled")
            if i < self.INVALID:
                if enabled == "true":
                    if self.ENABLE:
                        raise xenrt.XRTFailure("Cache enabled on invalid host, %s." % 
                                               (self.hosts[i].getName()))
                    else:
                        xenrt.TEC().logverbose("Cache still enabled on host, %s." % 
                                               (self.hosts[i].getName()))
                else: 
                    if self.ENABLE:
                        xenrt.TEC().logverbose("Cache not enabled on host, %s." % 
                                               (self.hosts[i].getName()))
                    else:
                        raise xenrt.XRTFailure("Cache disabled on invalid host, %s." % 
                                               (self.hosts[i].getName()))
            else:
                if enabled == "true":
                    if self.ENABLE:
                        xenrt.TEC().logverbose("Cache enabled on host, %s." % 
                                               (self.hosts[i].getName()))
                    else:
                        raise xenrt.XRTFailure("Cache still enabled on host, %s." % 
                                               (self.hosts[i].getName()))
                else: 
                    if self.ENABLE:
                        raise xenrt.XRTFailure("Cache not enabled on host, %s." % 
                                               (self.hosts[i].getName()))
                    else:
                        xenrt.TEC().logverbose("Cache disabled on host, %s." % 
                                               (self.hosts[i].getName()))

    def postRun(self):  
        for host in self.pool.getHosts():
            host.disable()
        for host in self.pool.getHosts():
            host.disableCaching()
        for host in self.pool.getHosts():
            host.enable()

class TC11898(_PoolSwitch):
    """Enable caching on a pool."""

    INVALID = 0
    CACHING = 0
    ENABLE = True

class TC11899(_PoolSwitch):
    """Disable caching on a pool."""

    INVALID = 0
    CACHING = 2
    ENABLE = False

class TC11900(_PoolSwitch):
    """Partially enable caching on a pool."""

    INVALID = 1
    CACHING = 0
    ENABLE = True

class TC11901(_PoolSwitch):
    """Enable caching on a partially enabled pool."""

    INVALID = 0
    CACHING = 1
    ENABLE = True

class TC11872(_Cache):
    """VMs containing no disks with the "behaviour on boot" flag set to "reset" 
       must be able to be live-migrated to other hosts."""

    def enableCaching(self):
        for host in self.pool.getHosts():
            host.disable()
        self.pool.enableCaching()
        for host in self.pool.getHosts():
            host.enable()

    def disableCaching(self):
        for host in self.pool.getHosts():
            host.disable()
        self.pool.disableCaching()
        for host in self.pool.getHosts():
            host.enable()

    def prepare(self, arglist=[]):
        self.pool = self.getDefaultPool()
        _Cache.prepare(self, arglist)
        self.guest = self.createTargetVM(windows=True, cached=True, reset=False)
        self.guest.start()

    def run(self, arglist=[]):
        other = self.pool.getSlaves()[0] 
        self.guest.migrateVM(other, live="true")

    def postRun(self):
        try: self.guest.shutdown()
        except:
            xenrt.TEC().warning("Guest did not shutdown cleanly, forcing shutdown...")
            self.guest.shutdown(force=True)


class TC11902(_Cache):
    """For disks having the "behaviour on boot" flag set to "reset", it is required that the VM 
       is prevented from crashing when the local cache becomes full."""

    def prepare(self, arglist=[]):
        self.host = self.getDefaultHost()
        self.srsize = self.host.genParamGet("sr", self.host.getLocalSR(), "physical-size")
        _Cache.prepare(self, arglist)
        self.flushCache()
        self.guest = self.createTargetVM(windows=True, cached=True, reset=True)
        self.guest.start()

    def run(self, arglist=[]):
        self.guest.checkHealth()
        try:
            self.host.execdom0("dd if=/dev/zero of=/var/run/sr-mount/%s/zero.bin bs=256M count=%s" %
                               (self.host.getLocalSR(), self.srsize/xenrt.MEGA/256), timeout=900)
        except Exception, e:
            xenrt.TEC().logverbose("DD returned an error as expected. (%s)" % (str(e)))
        self.guest.checkHealth()

class _CacheStress(_Cache):
    """Cache stress test base class."""

    TIMEOUT = 3600
    PERSISTVMS = 0 
    NORMALVMS = 0
    RESETVMS = 0
    SHAREDVMS = 0

    WORKLOADS = ["SQLIOSim", "IOMeter"] 

    def prepare(self, arglist=[]):
        _Cache.prepare(self, arglist)
        self.stressvms = []
        for i in range(self.PERSISTVMS):
            self.stressvms.append(self.createTargetVM(windows=True, cached=True, reset=False))
        for i in range(self.NORMALVMS):
            self.stressvms.append(self.createTargetVM(windows=True, cached=False, reset=False))
        for i in range(self.RESETVMS):
            self.stressvms.append(self.createTargetVM(windows=True, cached=True, reset=True))
        for i in range(self.SHAREDVMS):
            self.stressvms.append(self.createTargetVM(windows=True, cached=False, reset=False, sr=self.host.getLocalSR()))
        for guest in self.stressvms:
            guest.start()
            guest.installWorkloads(self.WORKLOADS)
            guest.shutdown()

    def check(self, guest):
        for w in guest.workloads:
            w.check()

    def run(self, arglist=[]):
        xenrt.sleep(30)
        for guest in self.stressvms:
            if not guest.getState() == "UP":
                guest.start()
            guest.workloads = guest.startWorkloads(self.WORKLOADS)
        for g in self.stressvms:
            self.check(g)
        time.sleep(self.TIMEOUT)
        for g in self.stressvms:    
            self.check(g)
        for guest in self.stressvms:
            guest.checkHealth()

class TC11931(_CacheStress):
    """Mixed-mode stress test."""

    PERSISTVMS = 2
    NORMALVMS = 2
    RESETVMS = 2
    SHAREDVMS = 0 

class TC12007(_CacheStress):
    """Cache co-existence stress test."""

    PERSISTVMS = 2
    NORMALVMS = 2
    RESETVMS = 2
    SHAREDVMS = 2

class TC11932(xenrt.TestCase):
    """On upgrade from a previous release of XenServer, the "behaviour on boot" 
       flag must be set to "persist", and the "local caching" flag should not be set."""

    def prepare(self, arglist):
        self.host = self.getDefaultHost() 
        self.guest = self.host.createGenericLinuxGuest()
        self.uninstallOnCleanup(self.guest)
        self.guest.shutdown()
        self.host.upgrade()

    def run(self, arglist):
        for vdi in map(self.guest.getDiskVDIUUID, self.guest.listDiskDevices()):
            if not self.host.genParamGet("vdi", vdi, "on-boot") == "persist": 
                raise xenrt.XRTFailure("VDI %s has on-boot set to 'reset'." % (vdi))
            if not self.host.genParamGet("vdi", vdi, "allow-caching")  == "false": 
                raise xenrt.XRTFailure("VDI %s has allow-caching set to 'true'." % (vdi))
        if not self.host.genParamGet("sr", self.host.getLocalSR(), "local-cache-enabled") == "true":
            raise xenrt.XRTFailure("Cache not enabled after upgrade.")

class TC12422(xenrt.TestCase):
    """On upgrade from a previous release of XenServer with multiple local ext SRs do not enable caching."""

    def prepare(self, arglist=[]):
        self.host = self.getDefaultHost()
        sr = xenrt.lib.xenserver.EXTStorageRepository(self.host, "Second\ Local\ Storage")
        defaultlist = string.join(map(lambda x:"sd"+chr(97+x), range(2)))
        guestdisks = string.split(self.host.lookup("OPTION_CARBON_DISKS", defaultlist))
        if len(guestdisks) < 2:
            raise xenrt.XRTError("Wanted disk 1 but we only have: %s" % (len(guestdisks)))
        sr.create("/dev/%s" % (guestdisks[1]))
        self.host.upgrade()
      
    def run(self, arglist):
        for sr in self.host.getSRs(type="ext"):
            if self.host.genParamGet("sr", sr, "local-cache-enabled") == "true":
                raise xenrt.XRTFailure("Cache enabled after upgrade.")

class _CachePerformance(_Cache):
    """Measure total number of I/O operations reaching shared storage for a large number 
       of VMs on a single host, where the VMs should all boot and log-in, then remain idle."""

    GUESTS = 4  
    ITERATIONS = 3 
    READMAXGAIN = 2 
    WRITEMAXGAIN = 2
    READMINGAIN = 0
    WRITEMINGAIN = 0
    CACHED = False
    RESET = False

    class IOCounter:

        def reading(self):
            data = self.host.execdom0("nfsstat -o nfs -c").strip("Client nfs v3:")
            key = filter(re.compile("[a-z]+").match, re.split("\s+", data))
            value = filter(re.compile("[0-9]+$").match, re.split("\s+", data))
            result = dict(((x,int(y)) for x,y in zip(key,value)))
            xenrt.TEC().logverbose("IO counts: %s" % (result))
            return result

        def __init__(self, host):
            self.host = host
            self.iterations = 0
            self.reads = [] 
            self.writes = []
            self.initial = {}

        def start(self):
            self.iterations += 1
            self.initial = self.reading()
            xenrt.TEC().logverbose("Initial: %s" % (self.initial))

        def stop(self):
            final = self.reading()
            self.reads.append(final["read"] - self.initial["read"])
            self.writes.append(final["write"] - self.initial["write"])
            # Note: these are numbers (counts) of IO operations, not ops per second.
            xenrt.TEC().logverbose("Current read IOPS: %s" % (self.reads))
            xenrt.TEC().logverbose("Current write IOPS: %s" % (self.writes))

    def prepare(self, arglist=[]):
        _Cache.prepare(self, arglist)
        self.iocounter = self.IOCounter(self.host)
        self.packetCatcher = IOPPacketCatcher(self.host, nolog=True)

    def measure(self):
        start = xenrt.timenow()
        for i in range(self.ITERATIONS):
            self.flushCache()
            for i in range(self.GUESTS):
                self.createTargetVM(windows=True, cached=self.CACHED, reset=self.RESET)
            self.iocounter.start()
            self.packetCatcher.startCapture("dst port nfs -i %s -x -s 65535 -vv" % (self.host.getPrimaryBridge()))
            guestsToStart = copy.copy(self.guests)
            # Booting one guest first to pull everything into the read-cache
            # so that subsequent guests can read from the cache instead of nfs.
            xenrt.lib.xenserver.guest.startMulti(guestsToStart[0:1])
            if self.GUESTS > 1:
                xenrt.lib.xenserver.guest.startMulti(guestsToStart[1:])
            self.packetCatcher.stopCapture()
            self.iocounter.stop()
        # Note: these are numbers (counts) of IO operations, not ops per second.
        xenrt.TEC().logverbose("Read IOPS: %s" % (self.iocounter.reads))
        xenrt.TEC().logverbose("Write IOPS: %s" % (self.iocounter.writes))
        xenrt.TEC().logverbose("Read packets: %s" % (self.packetCatcher.reads))
        xenrt.TEC().logverbose("Write packets: %s" % (self.packetCatcher.writes))
        xenrt.TEC().logverbose("Time: %s" % (xenrt.timenow() - start))
        if xenrt.TEC().lookup("DEBUG_CA49185", False, boolean=True):
            self.pause("Debug after measurement")
        self.flushCache()
        return self.iocounter.reads, self.iocounter.writes, \
                self.packetCatcher.reads, self.packetCatcher.writes  

    def check(self, base, value, maxgain, mingain):
        xenrt.TEC().logverbose("BASE: %s VALUE: %s" % (base, value))
        
        numerator = xenrt.mean(map(float, value))
        denominator = xenrt.mean(map(float, base))
        if denominator == 0:
            raise xenrt.XRTError("Mean of base is 0. Did measurement run properly?")

        observed = numerator / denominator
        if observed > maxgain:
            raise xenrt.XRTFailure("Performance metric not reached: %s > %s" % (observed, maxgain))
        elif observed < mingain:
            raise xenrt.XRTFailure("Performance metric too low: %s < %s" % (observed, mingain))
        else:
            xenrt.TEC().logverbose("Performance metric adequate: %s in range %s to %s" % (observed, mingain, maxgain))

    def run(self, arglist=[]):
        self.disableCaching()
        basereadiops, basewriteiops, basereadpackets, basewritepackets = self.measure()
        # Note: these are numbers (counts) of IO operations, not ops per second.
        xenrt.TEC().logverbose("Baseline read IOPS: %s" % (basereadiops))
        xenrt.TEC().logverbose("Baseline write IOPS: %s" % (basewriteiops))
        xenrt.TEC().logverbose("Baseline read Packets: %s" % (basereadpackets))
        xenrt.TEC().logverbose("Baseline write Packets: %s" % (basewritepackets))
        self.enableCaching()
        self.iocounter = self.IOCounter(self.host)
        self.packetCatcher = IOPPacketCatcher(self.host, nolog=True)
        readiops, writeiops, readpackets, writepackets = self.measure()
        xenrt.TEC().logverbose("Test read IOPS: %s" % (readiops))
        xenrt.TEC().logverbose("Test write IOPS: %s" % (writeiops))
        xenrt.TEC().logverbose("Test read Packets: %s" % (readpackets))
        xenrt.TEC().logverbose("Test write Packets: %s" % (writepackets))
        self.runSubcase("check", (basereadiops, readiops, self.READMAXGAIN, self.READMINGAIN), "IOPS", "Read")
        self.runSubcase("check", (basewriteiops, writeiops, self.WRITEMAXGAIN, self.WRITEMINGAIN), "IOPS", "Write")
        self.runSubcase("check", (basereadpackets, readpackets, self.READMAXGAIN, self.READMINGAIN), "Packets", "Read")
        self.runSubcase("check", (basewritepackets, writepackets, self.WRITEMAXGAIN, self.WRITEMINGAIN), "Packets", "Write")

class TC12005(_CachePerformance):
    """Compare scenarios where the VMs' disks have a "reset-on-boot" policy and 
       where the VMs' disks have a "reset-on-boot without caching" policy."""

    RESET = True
    CACHED = True
    READMAXGAIN = 0.7
    READMINGAIN = 0.01
    WRITEMAXGAIN = 0.5
    WRITEMINGAIN = 0.0

class TC12006(_CachePerformance):
    """Compare scenarios where the VMs' disks have a "persistent with caching" 
       policy and where the VMs' disks have a "persistent without caching" policy."""
    
    RESET = False
    CACHED = True
    READMAXGAIN = 0.7
    READMINGAIN = 0.01
    #WRITEMAXGAIN = 1.15 # Due to increase in cache writeback, this increase is expected.
    WRITEMAXGAIN = 1.5 # Refer CA-124004
    WRITEMINGAIN = 0.5 # Ensure writes are still being sent back to nfs.

class _ReadCachePerformance(_CachePerformance):
    """ Same test with _CachePerformance except it tests read cache. """
    
    INTELLICACHE = False

    def run(self, arglist=[]):
        if not isinstance(self.host, xenrt.lib.xenserver.CreedenceHost):
            raise xenrt.XRTError("Read cache requires Creedence or later.")

        # it is on by default in _Cache class.
        if not self.INTELLICACHE:
            self.disableCaching()

        self.host.disableReadCaching()
        basereadiops, basewriteiops, basereadpackets, basewritepackets = self.measure()
        # Note: these are numbers (counts) of IO operations, not ops per second.
        xenrt.TEC().logverbose("Baseline read IOPS: %s" % (basereadiops))
        #xenrt.TEC().logverbose("Baseline write IOPS: %s" % (basewriteiops))
        xenrt.TEC().logverbose("Baseline read Packets: %s" % (basereadpackets))
        #xenrt.TEC().logverbose("Baseline write Packets: %s" % (basewritepackets))
        self.host.enableReadCaching()
        self.iocounter = self.IOCounter(self.host)
        self.packetCatcher = IOPPacketCatcher(self.host, nolog=True)
        readiops, writeiops, readpackets, writepackets = self.measure()
        xenrt.TEC().logverbose("Test read IOPS: %s" % (readiops))
        #xenrt.TEC().logverbose("Test write IOPS: %s" % (writeiops))
        xenrt.TEC().logverbose("Test read Packets: %s" % (readpackets))
        #xenrt.TEC().logverbose("Test write Packets: %s" % (writepackets))
        self.runSubcase("check", (basereadiops, readiops, self.READMAXGAIN, self.READMINGAIN), "IOPS", "Read")
        #self.runSubcase("check", (basewriteiops, writeiops, self.WRITEMAXGAIN, self.WRITEMINGAIN), "IOPS", "Write")
        self.runSubcase("check", (basereadpackets, readpackets, self.READMAXGAIN, self.READMINGAIN), "Packets", "Read")
        #self.runSubcase("check", (basewritepackets, writepackets, self.WRITEMAXGAIN, self.WRITEMINGAIN), "Packets", "Write")

class TC21544(_ReadCachePerformance):
    """ Compare scenarios where read cache is on and where read cache is off
    when intelliCache is off."""

    CACHED = True
    READMAXGAIN = 0.5
    READMINGAIN = 0.01
    WRITEMAXGAIN = 1.20
    WRITEMINGAIN = 0.50

class TC21545(_ReadCachePerformance):
    """ Compare scenarios where read cache is on and where read cache is off
    when intelliCache is on."""
    
    INTELLICACHE = True
    CACHED = True
    READMAXGAIN = 1.20
    READMINGAIN = 0.50
    WRITEMAXGAIN = 1.20
    WRITEMINGAIN = 0.50

class TC12008(_Cache):
    """Check that vm-start succeeds if a VM's VDIs are set for caching but no
       SR has caching enabled."""

    def prepare(self, arglist=[]):
        _Cache.prepare(self, arglist)
        self.guest = self.createTargetVM(cached=True, reset=True)

    def run(self, arglist=[]):
        self.disableCaching()
        if self.host.minimalList("sr-list", "uuid", "local-cache-enabled=true"):
            raise xenrt.XRTError("A SR on the host has caching enabled.")
        self.guest.start()

    def postRun(self):
        try: self.guest.shutdown(force=True)
        except: pass
        _Cache.postRun(self)

class TC12009(xenrt.TestCase):
    """Check that host-enable-local-storage-caching fails with non-ext SRs."""

    def prepare(self, arglist=[]):
        self.host = self.getDefaultHost()
        if self.host.getSRs(type="ext"):
            raise xenrt.XRTError("Host has ext SR(s).")

    def run(self, arglist=[]):
        self.host.disable() 
        try:
            self.host.enableCaching(sr=self.host.getLocalSR())
        except Exception:
            xenrt.TEC().logverbose("Enabling caching failed as expected.")
        else:
            raise xenrt.XRTFailure("Enabling caching succeeded.")
        self.host.enable()
        if self.host.genParamGet("sr", self.host.getLocalSR(), "local-cache-enabled") == "true":
            raise xenrt.XRTFailure("Cache enabled on non-ext SR.")

class TC12010(xenrt.TestCase):
    """Check that vm-start succeeds if a VM's VDIs has a chain length other than two."""

    def prepare(self, arglist=[]):
        self.host = self.getDefaultHost()
        if self.host.minimalList("sr-list", "uuid", "local-cache-enabled=true"):
            raise xenrt.XRTError("A SR on the host has caching enabled.")
        self.master = self.host.createGenericLinuxGuest(start=False)
        self.guest = self.master.cloneVM()
        self.uninstallOnCleanup(self.master)
        self.uninstallOnCleanup(self.guest)

    def run(self, arglist=[]):
        for vdi in map(self.guest.getDiskVDIUUID, self.guest.listDiskDevices()):
            self.host.genParamSet("vdi", vdi, "allow-caching", "true")
        self.guest.start()

class TC12174(_Cache):
    """Check that VMs are resilient to caching flag changes."""

    def run(self, arglist=[]):
        vdiuuid = self.createTargetDisk(windows=True, cached=True, reset=False)
        guest = self.getGuest(vdiuuid)
        guest.start()
        guest.checkHealth()
        guest.shutdown()
        self.host.genParamSet("vdi", vdiuuid, "on-boot", "reset")
        guest.start()
        guest.checkHealth()
        guest.shutdown()
        self.host.genParamSet("vdi", vdiuuid, "on-boot", "persist")
        guest.start()
        guest.checkHealth()

class TC12175(_Cache):
    """Cache RRD smoke test."""

    def run(self, arglist=[]):
        guest = self.createTargetVM(windows=False, cached=True, reset=False)
        guest.start()
        misses = self.host.dataSourceQuery("sr_%s_cache_misses" % (self.host.getLocalSR()))
        hits = self.host.dataSourceQuery("sr_%s_cache_hits" % (self.host.getLocalSR()))
        size = self.host.dataSourceQuery("sr_%s_cache_size" % (self.host.getLocalSR()))
        xenrt.TEC().logverbose("Hits: %s Misses: %s Size: %s")
        guesttwo = self.createTargetVM(windows=False, cached=True, reset=False)
        guesttwo.start()
        misses = self.host.dataSourceQuery("sr_%s_cache_misses" % (self.host.getLocalSR()))
        hits = self.host.dataSourceQuery("sr_%s_cache_hits" % (self.host.getLocalSR()))
        size = self.host.dataSourceQuery("sr_%s_cache_size" % (self.host.getLocalSR()))
        xenrt.TEC().logverbose("Hits: %s Misses: %s Size: %s")

class TC12421(xenrt.TestCase):
    """Check that caching is enabled by default."""

    def prepare(self, arglist=[]):
        self.host = self.getDefaultHost()   

    def run(self, arglist):
        xenrt.sleep(180) #CA-113559
        if not self.host.genParamGet("sr", self.host.getLocalSR(), "local-cache-enabled") == "true":
            raise xenrt.XRTFailure("Cache not enabled by default.")


class _ResetOnBootBase(_Cache):
    """Base class of all vdi on-boot flag test of PR-1080."""

    VDI_LIST = []

    def initializeDisk(self, device, guest):
        """Partition and Format the new disk"""

        if guest.windows:
            drive_letter = chr(68 + device) # Starting from E drive.
            guest.xmlrpcWriteFile("C:\\partition.txt","rescan\n"
                                                   "list disk\n"
                                                   "select disk %d\n"
                                                   "clean\n"
                                                   "create partition primary\n"
                                                   "assign letter=%s\n" % 
                                                   (device, drive_letter))
            guest.xmlrpcExec("diskpart /s c:\\partition.txt", timeout=600)
            guest.xmlrpcFormat(drive_letter)
        else:
            dev = self.host.parseListForOtherParam("vbd-list",
                                                   "vm-uuid",
                                                    guest.getUUID(),
                                                   "device",
                                                   "userdevice=%d" % (device))
            xenrt.TEC().logverbose("Formatting %d (%s)." % (device, dev)) 
            # On Linux we mkfs and mount/unmount each disk.
            guest.execguest("mkfs.ext2 /dev/%s" % (dev))
            guest.execguest("mkdir /mnt/%s" % (dev))
            guest.execguest("mount /dev/%s /mnt/%s" % (dev, dev))

    def uninstallAllVMs(self):
        """ Uninstall all target VMs."""

        if hasattr(self, "guests"):
            vmlist = self.guests

            for guest in vmlist:
                guest.setState("DOWN")
                guest.uninstall(True)
                xenrt.sleep(10)

            self.guests = None

        elif hasattr(self, "guest") and self.guest:
            self.guest.setState("DOWN")
            self.guest.uninstall(True)
            self.guest = None
            xenrt.sleep(10)
    
    def settingUpTestEnvironment(self):
        self.pool = self.getDefaultPool()
        self.host = self.getDefaultHost()
        
        xenrt.TEC().logverbose("Found pool: " + self.pool.getName())
        xenrt.TEC().logverbose("Found default host: " + self.host.getName())
        
        self.sr = self.host.lookupDefaultSR()
        self.srtype = self.host.genParamGet("sr", self.sr, "type")
        xenrt.TEC().logverbose("Found default SR: %s of type: %s" % (self.sr, self.srtype))
        
        self.goldVM = xenrt.TestCase.getGuest(self, "GoldVM")
        if not self.goldVM:
            raise xenrt.XRTError("Cannot find pre-created Gold VM.")
        xenrt.TEC().logverbose("Found Gold VM %s (%s)"  % (self.goldVM.getName(), self.goldVM.getUUID()))
        
        # Setting up license. This is not required for Clearwater but for trunk.
        #for h in self.pool.getHosts():
            #h.license(edition='platinum')

    def prepare(self, arglist=None):
        self.settingUpTestEnvironment()
        self.guest, self.vdis = self.createTargetVM()

    def createTargetDisk(self, vditype, target):
        """Create a test target vdi and attach it to target VM."""

        cli = target.getCLIInstance()
        vdi = string.strip(cli.execute("vdi-create", "name-label=%s type=user sr-uuid=%s virtual-size=%d" % (vditype+"vdi", self.sr, xenrt.GIGA), compat=False))
        vbd = string.strip(cli.execute("vbd-create", "vdi-uuid=%s vm-uuid=%s device=autodetect" % (vdi, target.uuid), compat=False))

        return vdi

    def createTargetVM(self, onbootlist = None):
        """Clone a VM to test and create disks.""" 
        
        if not onbootlist: onbootlist = self.VDI_LIST
        
        guest =  self.goldVM.cloneVM()
        vdis = []
        for vdi in onbootlist:
            vdis.append(self.createTargetDisk(vdi, target=guest))
        
        guest.start()
        device = 1
        for vdi in vdis:
            self.initializeDisk(device, guest)
            device += 1

        guest.shutdown()
        for vdi, vflag in zip(vdis, onbootlist):
            self.host.genParamSet("vdi", vdi, "on-boot", vflag) 
        
        return guest, vdis

    def guestStart(self):
        # guest can be in any state. Calling setState() is safer rather than start()
        self.guest.setState("UP")

    def guestShutdown(self):
        # guest can be in any state. Calling setState() is safer rather than shutdown()
        self.guest.setState("DOWN")

    def postRun(self):
        # to override _Cache.postRun
        self.uninstallAllVMs()

    def checkSMCapability(self):
        """Checking SM has valid capability and feature."""
        xenrt.TEC().logverbose("Finding Storage Manager that is being used for %s type" % (self.srtype))
        uuids = self.host.minimalList("sm-list", args = "type=" + self.srtype)
        xenrt.TEC().logverbose("Found SM %s" % (uuids))
        for uuid in uuids:
            capabilities = self.host.genParamGet("sm", uuid, "capabilities").strip(";")
            if not "VDI_RESET_ON_BOOT" in capabilities:
                raise xenrt.XRTFailure("SM %s of type %s does not have \"VDI_RESET_ON_BOOT\" capability." % (uuids, self.srtype))
            xenrt.TEC().logverbose("SM %s of type %s has \"VDI_RESET_ON_BOOT\" capability." % (uuids, self.srtype))
            # feature is added in Clearwater.
            if isinstance(self.host, xenrt.lib.xenserver.ClearwaterHost):
                features = self.host.genParamGet("sm", uuid, "features").strip(";")
                if not "VDI_RESET_ON_BOOT: 2" in features:
                    raise xenrt.XRTFailure("SM %s of type %s does not have \"VDI_RESET_ON_BOOT/2\" feature." % (uuids, self.srtype))
                xenrt.TEC().logverbose("SM %s of type %s has \"VDI_RESET_ON_BOOT/2\" feature." % (uuids, self.srtype))
        

class _VDISanityBase(_ResetOnBootBase):
    """Base class for VDI Sanity test."""

    def checkVDISanity(self, handle, actionstr):
        """Write some data in taget disk(s) and check after rebooting."""

        seeds = {}

        self.guestStart()

        for vdi, vflag in zip(self.vdis, self.VDI_LIST):
            seed = self.writeVDI(vdi)
            before = self.readVDI(vdi)
            if not before["data"] == seed["data"]:
                raise xenrt.XRTFailure("Data mismatch before %s." % (actionstr))
            else:
                xenrt.TEC().logverbose("Data matches before %s." % (actionstr))
            seeds[vdi] = seed
        
        handle()
        # Give some time to be shutdowned/rebooted.
        xenrt.sleep(180)

        # Guest can be turned off after shutdown action.
        self.guestStart()

        for vdi, vflag in zip(self.vdis, self.VDI_LIST):
            seed = seeds[vdi]
            read = self.readVDI(vdi)
            if read["data"] == seed["data"]:
                if vflag == "reset":
                    raise xenrt.XRTFailure("Data on reset vdi has not been discarded after %s." % (actionstr))
                else:
                    xenrt.TEC().logverbose("Data on persist vdi has not been discarded after %s." % (actionstr))
            else:
                if vflag == "reset":
                    xenrt.TEC().logverbose("Data on reset vdi has been discarded after VM %s." % (actionstr))
                else:
                    raise xenrt.XRTFailure("Data on persist vdi has been discarded after VM %s." % (actionstr))

    def run(self, arglist = []):
        self.runSubcase("checkVDISanity", (self.guest.reboot, "reboot"), "reboot", "reboot")
        self.runSubcase("checkVDISanity", (self.guest.unenlightenedReboot, "reboot in guest"), "reboot in guest", "reboot in guest")
        self.runSubcase("checkVDISanity", (self.guest.shutdown, "shutdown"), "shutdown", "shutdown")
        self.runSubcase("checkVDISanity", (self.guest.unenlightenedShutdown, "shutdown in guest"), "shutdown in guest", "shutdown in guest")


class TCVDISanityResetVDI(_VDISanityBase):
    """TC-19031"""

    VDI_LIST = ["reset"]
    

class TCVDISanityPersistVDI(_VDISanityBase):
    """TC-19032"""

    VDI_LIST = ["persist"]
    

class TCVDISanityMixedVDI(_VDISanityBase):
    """TC-19033"""

    VDI_LIST = ["reset", "persist"]

    
class _DiskOperationBase(_ResetOnBootBase):
    """ Base class for disk operation tests of Clone on boot"""

    def testSnapshot(self):
        vflag = "persist"
        for v in self.VDI_LIST:
            if v == "reset":
                vflag = "reset"
                break
        try:
            self.guestStart()
            uuid = self.guest.snapshot()
            self.guest.removeSnapshot(uuid)
        except:
            if vflag == "persist": 
                raise xenrt.XRTFailure("Snapshot failed on VM without 'reset' vdi.")
            else:
                xenrt.TEC().logverbose("Snapshot failed as expected.")
        else:
            if vflag == "reset": 
                raise xenrt.XRTFailure("Snapshot succeeded on VM with 'reset' vdi.")
            else:
                xenrt.TEC().logverbose("Snapshot succeeded as expected.")
    
    def testCheckpoint(self):
        vflag = "persist"
        for v in self.VDI_LIST:
            if v == "reset":
                vflag = "reset"
                break
        try:
            self.guestStart()
            uuid = self.guest.checkpoint()
            self.guest.removeSnapshot(uuid)
        except:
            if vflag == "persist": 
                raise xenrt.XRTFailure("Checkpoint failed on VM without 'reset' vdi.")
            else:
                xenrt.TEC().logverbose("Checkpoint failed as expected.")
        else:
            if vflag == "reset": 
                raise xenrt.XRTFailure("Checkpoint succeeded on VM with 'reset' vdi.")
            else:
                xenrt.TEC().logverbose("Checkpoint succeeded as expected.")

    def testSuspend(self):
        try:
            self.guestStart()
            self.guest.suspend()
            self.guest.resume()
        except:
            raise xenrt.XRTFailure("Suspend VM failed.")
        else:
            xenrt.TEC().logverbose("Suspend VM succeeded as expected.")

    def checkVDIOnBoot(self, target):
        """Check vdi has valid on-boot flags as indecated."""
        checkList = {}
        result = xenrt.RESULT_PASS


        for vbd in self.host.minimalList("vbd-list", args="vm-uuid=%s type=Disk" % self.guest.getUUID()):
            if self.host.genParamGet("vbd", vbd, "currently-attached") == "true":
                dev = self.host.genParamGet("vbd", vbd, "device")
                vdi = self.host.genParamGet("vbd", vbd, "vdi-uuid")
                onboot = self.host.genParamGet("vdi", vdi, "on-boot")
                checkList[dev] = onboot
                

        for vbd in self.host.minimalList("vbd-list", args="vm-uuid=%s type=Disk" % target.getUUID()):
            if self.host.genParamGet("vbd", vbd, "currently-attached") == "true":
                dev = self.host.genParamGet("vbd", vbd, "device")
                vdi = self.host.genParamGet("vbd", vbd, "vdi-uuid")
                onboot = self.host.genParamGet("vdi", vdi, "on-boot")
                if dev not in checkList:
                    xenrt.TEC().logverbose("Cannot find corresponsing device %s from test VM." %(dev)) 
                    result = xenrt.RESULT_FAIL
                if onboot != checkList[dev]:
                    xenrt.TEC().logverbose("Mismatched on-boot flag on device %s. Expected: %s, Found: %s" % (dev, checkList[dev], onboot))
                    result = xenrt.RESULT_FAIL
                
        return result

    def testClone(self):
        try:
            self.guestShutdown()
            clone = self.guest.cloneVM()
            if self.checkVDIOnBoot(clone) != xenrt.RESULT_PASS:
                raise xenrt.XRTFailure("Cloned VM has different on-boot layouts.")
            clone.uninstall()
            xenrt.sleep(10)
        except xenrt.XRTFailure as e:
            raise e
        except:
            raise xenrt.XRTFailure("Clone of VM failed.")
        else:
            xenrt.TEC().logverbose("VM clone succeeded.")

    def testCopy(self):
        try:
            self.guestShutdown()
            clone = self.guest.copyVM()
            if self.checkVDIOnBoot(clone) != xenrt.RESULT_PASS:
                raise xenrt.XRTFailure("Copied VM has different on-boot layouts.")
            clone.uninstall()
            xenrt.sleep(10)
        except xenrt.XRTFailure as e:
            raise e
        except:
            raise xenrt.XRTFailure("Copy of VM failed.")
        else:
            xenrt.TEC().logverbose("VM copy succeeded.")

    def testMigrate(self):
        try:
            self.guestStart()
            other = self.pool.getSlaves()[0] 
            self.guest.migrateVM(other)
            for vdi, flag in zip(self.vdis, self.VDI_LIST):
                onboot = self.host.genParamGet("vdi", vdi, "on-boot")
                if flag != onboot:
                    raise xenrt.XRTFailure("Migrated VDI has different on-boot flag. Expected: %s Found: %s." % (flag, onboot))
        except xenrt.XRTFailure as e:
            raise e
        except:
            raise xenrt.XRTFailure("Migration of VM failed.")
        else:
            xenrt.TEC().logverbose("VM migration succeeded.")

    def run(self, arglist=[]):
        self.runSubcase("testCopy", (), "Copy", "Copy")    
        self.runSubcase("testClone", (), "Clone", "Clone")    
        self.runSubcase("testSuspend", (), "Suspend", "Suspend")    
        self.runSubcase("testSnapshot", (), "Snapshot", "Snapshot")    
        self.runSubcase("testCheckpoint", (), "Checkpoint", "Checkpoint")   
        self.runSubcase("testMigrate", (), "Migration", "Migration")


class TCDiskOperationResetVDI(_DiskOperationBase):
    """TC-19034"""
    
    VDI_LIST = ["reset"]


class TCDiskOperationPersistVDI(_DiskOperationBase):
    """TC-19035"""

    VDI_LIST = ["persist"]
    

class TCDiskOperationMixedVDI(_DiskOperationBase):
    """TC-19036"""

    VDI_LIST = ["reset", "persist"]


class TCUpgrade(_ResetOnBootBase):
    """Rolling pool upgrade from Tampa test to ensure upgrade does not affect
    Any issue with on-boot flags and capability/feature in SM updated properly.
    TC-19037"""

    def prepare(self, arglist = []):
        self.settingUpTestEnvironment()
        
        self.guests = []
        self.vdis = {}
        
        # Creating reset on boot vdi and vm
        onbootlist = ["reset"]
        vm, vdis = self.createTargetVM(onbootlist)
        self.guests.append(vm)
        for vdi, vflag in zip(vdis, onbootlist):
            self.vdis[vdi] = vflag
        
        # Creating persist on boot vdi and vm
        onbootlist = ["persist"]
        vm, vdis = self.createTargetVM(onbootlist)
        self.guests.append(vm)
        for vdi, vflag in zip(vdis, onbootlist):
            self.vdis[vdi] = vflag
        
        # Creating both vdis and vm
        onbootlist = ["reset", "persist"]
        vm, vdis = self.createTargetVM(onbootlist)
        self.guests.append(vm)
        for vdi, vflag in zip(vdis, onbootlist):
            self.vdis[vdi] = vflag
        
    def run(self, arglist = []):
        
        # for guest upgrading.
        def installPV(*args):
            guest = args[0]
            xenrt.TEC().logverbose("Updating PV drivers: %s" % (guest.getName()))
            guest.setState("UP")
            if guest.windows:
                guest.installDrivers()  
            else:
                guest.installTools()
            guest.shutdown()
            xenrt.TEC().logverbose("Updating PV drivers done")
            
        # Check capability of relavant SM before upgrade.
        self.checkSMCapability()
        
        # Run rolloing pool upgrade.
        xenrt.TEC().logverbose("Running Rolling Pool upgrade.")
        self.pool = self.pool.upgrade(rolling = True)
        self.host = self.pool.master
        
        xenrt.sleep(180)
        self.pool.check()
        xenrt.TEC().logverbose("Running Rolling Pool upgrade done.")
        
        # Check capability/feature version of relavant SM after upgrade.
        self.checkSMCapability()
        
        # Upgrade geusts.
        # Work-around for crash with Windows driver update.
        #xenrt.TEC().logverbose("Upgrading guests starts.")
        ####################################################
        # This is to save time on upgrading PV driver.
        # Not required for small number of target VMs.
        #tasks = []
        #for guest in self.guests:
            #tasks.append(xenrt.PTask(installPV, guest))
        #xenrt.pfarm(tasks)
        ####################################################
        #for guest in self.guests:
        #    installPV(guest)
        #xenrt.TEC().logverbose("Upgrading guests is done.")

        # Check all VDIs have proper on-boot flags as they are set.
        xenrt.TEC().logverbose("Checking on-boot flag after upgrade.")
        for vdi, flag in self.vdis.items():
            onboot = self.host.genParamGet("vdi", vdi, "on-boot")
            if flag != onboot:
                raise xenrt.XRTFailure("Upgraded VDI %s has different on-boot flag. Expected: %s Found: %s." % (vdi, flag, onboot))
