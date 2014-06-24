import logging
import IPy
import psycopg2
import netifaces
import threading
import time
import json
from SimpleXMLRPCServer import SimpleXMLRPCServer

from libpydhcpserver.dhcp_types.conversion import *
from dhcpdlib.databases.generic import Definition

_logger = logging.getLogger('dhcp')

class XenRTDHCPAllocator(object):
    
    def __init__(self):
        self.conn = None
        self.cur = None
        self.lock = threading.Lock()
        self.interfaceInfo = {}
        with open("xenrtdhcpd.cfg") as f:
            self.config = json.load(f)
        for i in self.config['interfaces'].keys():
            self._parseCfg(i)
            self._setupDB(i)

        self.xmlrpc = SimpleXMLRPCServer(("localhost", 1500))
        self.xmlrpc.register_introspection_functions()
        self.xmlrpc.register_instance(XMLRPCAllocator(self))
        thread = threading.Thread(target=self.startXMLRPC, name="XMLRPC")
        thread.daemon=True
        thread.start()

    def startXMLRPC(self):
        _logger.info("Starting XML/RPC server")
        self.xmlrpc.serve_forever()

    def _parseCfg(self, intf):
        globalcfg = self.config['global']
        intfcfg = self.config['interfaces'][intf]
        for k in globalcfg.keys():
            if not intfcfg.has_key(k):
                intfcfg[k] = globalcfg[k]

        for k in intfcfg.keys():
            if isinstance(intfcfg[k], list):
                for i in xrange(len(intfcfg[k])):
                    if intfcfg[k][i] == "self":
                        intfcfg[k][i] = self.getInterfaceInfo(intf)['addr']
            else:
                if intfcfg[k] == "self":
                    intfcfg[k] = self.getInterfaceInfo(intf)['addr']
        
        if not intfcfg.has_key("reservations"):
            intfcfg['reservations'] = {}

        for r in intfcfg['reservations'].keys():
            addr = intfcfg['reservations'][r]
            del intfcfg['reservations'][r]
            intfcfg['reservations'][r.lower()] = addr

    def _sql(self, sql):
        _logger.info("Executing %s" % sql)
        try:
            self.cur.execute(sql)
        except:
            _logger.info("Attempting reconnection to DB")
            self.conn = psycopg2.connect("host='127.0.0.1' dbname='dhcp' user='dhcp' password='dhcp'")
            self.cur = self.conn.cursor()
            self.conn.autocommit=True
            self.cur.execute(sql)
    
    def _setupDB(self, intf):
        start = self.config['interfaces'][intf]['start']
        end = self.config['interfaces'][intf]['end']
        # 1. Delete addresses in this range that don't belong to this interface

        self._sql("DELETE FROM leases WHERE interface!='%s' AND addr>='%s' AND addr<='%s'" % (intf, start, end))

        # 2. Delete addresses outside of this range that belong to this interface
        
        self._sql("DELETE FROM leases WHERE interface='%s' AND (addr<'%s' OR addr>'%s')" % (intf, start, end))

        # 3. See what addresses we have in this range

        self._sql("SELECT addr FROM leases WHERE interface='%s'" % intf)
        existing = [x[0] for x in self.cur.fetchall()]
        # 4. Add any missing addresses

        alladdrs = [IPy.IP(x).strNormal() for x in range(IPy.IP(start).int(), IPy.IP(end).int()+1)]

        for a in alladdrs:
            if a not in existing:
                self._sql("INSERT INTO leases (addr, interface) VALUES ('%s', '%s')" % (a, intf))

    def _findStaticReservation(self, intf, mac):
        res = self.config['interfaces'][intf]['reservations']
        if mac.lower() in res.keys():
            return (res[mac.lower()]['ip'], res[mac.lower()]['name'])
        else:
            return (None, None)

    def _findActiveLease(self, intf, mac):
        self._sql("SELECT addr FROM leases WHERE mac='%s' AND interface='%s' ORDER BY expiry DESC" % (mac.lower(), intf))
        r = self.cur.fetchone()
        if r:
            return r[0]
        else:
            return None

    def _renewLease(self, intf, mac, ip):
        intfcfg = self.config['interfaces'][intf]
        self._sql("SELECT addr FROM leases WHERE addr='%s' AND mac='%s' AND interface='%s'" % (ip, mac.lower(), intf))
        r = self.cur.fetchone()
        self._sql("UPDATE leases SET expiry=%d WHERE addr='%s'" % (int(time.time() + intfcfg['leasetime']), r[0]))

    def _getNewLease(self, intf, mac):
        # Exclude Cloudstack MACs
        if mac.startswith("02:") or mac.startswith("06:"):
            return None
        intfcfg = self.config['interfaces'][intf]
        self._sql("SELECT addr FROM leases WHERE interface='%s' AND reserved IS NULL AND (mac IS NULL OR expiry<%d) ORDER BY addr LIMIT 1" % (intf, int(time.time())))
        r = self.cur.fetchone()
        if not r:
            return None
        else:
            self._sql("UPDATE leases SET expiry=%d,mac='%s' WHERE addr='%s'" % (int(time.time() + intfcfg['leasetime']), mac.lower(), r[0]))
            return r[0]
        
    def getResponse(self, intf, mac, packet):
        ip = None
        cfg = self.config['interfaces'][intf]
        _logger.info("Request for MAC %s on interface %s" % (intf, mac))
        hostname = None
        (ip, hostname) = self._findStaticReservation(intf, str(mac))
        if ip:
            lease = cfg['staticleasetime']
        else:
            with self.lock:
                currentIp = self._findActiveLease(intf, str(mac))
                if currentIp:
                    try:
                        _logger.info("Renewing lease for %s" % currentIp)
                        self._renewLease(intf, str(mac), currentIp)
                        ip = currentIp
                    except:
                        _logger.warn("Warning: could not renew lease for %s" % currentIp)
                if not ip:
                    ip = self._getNewLease(intf, str(mac))
                if not ip:
                    _logger.warn("Could not allocate lease for %s on %s" % (str(mac), intf))
                    return None
                lease = cfg['leasetime']
        self._populatePXEInfo(packet, intf)

        intfdetails = self.getInterfaceInfo(intf)
        intfaddr = IPy.IP(intfdetails['addr'])
        subnet = intfaddr.make_net(intfdetails['netmask'])[0].strNormal()

        if not hostname:
            hostname = "xenrt-%s" % ip.replace(".","-")

        ret = Definition(ip=ip,
                         lease_time=lease,
                         subnet=subnet,
                         serial=0,
                         gateway=cfg['gateway'],
                         subnet_mask = intfdetails['netmask'],
                         broadcast_address = intfdetails['broadcast'],
                         domain_name=cfg['domain'],
                         domain_name_servers = cfg['dns'],
                         ntp_servers = cfg['ntp'],
                         hostname=hostname)

        return ret

    def _populatePXEInfo(self, packet, intf):
        server = self.getInterfaceInfo(intf)['addr']
        if self.config['interfaces'][intf]['ipxe']:
            userClass = packet.getOption("user_class")
            if userClass and listToStr(userClass) == "iPXE":
                packet.setOption("file", strToPaddedList("http://%s/tftp/default-ipxe.cgi" % server, 128))
            else:
                packet.setOption("file", strToPaddedList("/undionly.kpxe", 128))
        else:
            packet.setOption("file", strToPaddedList("/pxelinux.0", 128))
        packet.setOption("siaddr", ipToList(server))
   
    def getInterfaceInfo(self, intf):
        if not self.interfaceInfo.has_key(intf):
            self.interfaceInfo[intf] = netifaces.ifaddresses(intf)[netifaces.AF_INET][0]
        return self.interfaceInfo[intf]

    def reserveSingleAddress(self, intf, data, mac=None):
        with self.lock:
            self._sql("SELECT addr FROM leases WHERE interface='%s' AND reserved IS NULL AND (mac IS NULL or expiry < %d) ORDER BY addr LIMIT 1;" % (intf, int(time.time()))) 
            r = self.cur.fetchone()
            if not r:
                raise Exception("No address available")
            if mac:
                self._sql("UPDATE leases SET data='%s',mac='%s' WHERE addr='%s'" % (data, mac.lower(), r[0]))
            else:
                self._sql("UPDATE leases SET data='%s',mac=NULL WHERE addr='%s'" % (data, r[0]))

            return r[0]
        

    def reserveAddressRange(self, intf, size, data):
        with self.lock:
            res = []
            self._sql("SELECT addr FROM leases WHERE interface='%s' AND reserved IS NULL AND (mac IS NULL or expiry < %d) ORDER BY addr LIMIT 1;" % (intf, int(time.time()))) 
            rs = self.cur.fetchall()
            ips = [IPy.IP(x[0]).int() for x in rs]

            start = None
            for i in xrange(len(ips)):
                if (i + size) > len(ips):
                    break
                ok = True
                for j in xrange(size):
                    if ips[i+j] != ips[i] + j:
                        ok = False
                        break
                if ok:
                    start = ips[i]
                    break

            if not start:
                raise Exception("No address range available")

            for i in xrange(size):
                ip = IPy.IP(start + i).strNormal()
                self._sql("UPDATE leases SET reserved='%s' WHERE addr='%s'" % (data, ip))
                res.append(ip)

            return res

    def releaseAddress(self, addr):
        with self.lock:
            self._sql("UPDATE leases SET reserved=NULL WHERE addr='%s'" % (addr))

    def listReservedAddresses(self):
        self._sql("SELECT addr,reserved FROM LEASES WHERE interface='%s' AND reserved IS NOT NULL")
        res = {}
        rs = self.cur.fetchall()
        for r in rs:
            res[r[0]] = r[1]

        return res

class XMLRPCAllocator(object):
    def __init__(self, parent):
        self.parent = parent

    def reserveSingleAddress(self, intf, data, mac=None):
        _logger.info("Request for single address on %s with data %s" % (intf, data))
        return self.parent.reserveSingleAddress(intf, data, mac)

    def reserveAddressRange(self, intf, size, data):
        return self.parent.reserveAddressRange(intf, size, data)

    def releaseAddress(self, addr):
        self.parent.releaseAddress(addr)

    def listReservedAddresses(self):
        return self.parent.listReservedAddresses()
