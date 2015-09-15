#
# XenRT: Test harness for Xen and the XenServer product family
#
# TransferVM standalone testcases
#
# Copyright (c) 2010 Citrix Systems, Inc. All use and distribution of this
# copyrighted material is governed by and subject to terms and
# conditions as licensed by Citrix Systems, Inc. All other rights reserved.
#

#import os.path
import socket, re, string, time, traceback, sys, random, copy, os, os.path, urllib2, filecmp
import xenrt, xenrt.lib.xenserver, XenAPI, httplib, threading
import base64, subprocess, zlib, ssl
import xml.dom.minidom 
from xml.dom.minidom import parseString
from xml.dom import minidom
from xenrt.lazylog import step, comment, log, warning

MB = 1024*1024
KB = 1024
BITS_CONTEXT_SERVER = '0x7'
BITS_E_INVALIDARG = '0x80070057'
BITS_PROTOCOL = '{7df0354d-249b-430f-820D-3D2A9BEF4931}'
PATTERN_EMPTY                  = 0
PATTERN_SHORT_STRING_BEGINNING = 1
PATTERN_SHORT_STRING_MIDDLE    = 2
PATTERN_SHORT_STRING_END       = 3
PATTERN_BLOCKS_SEQUENTIAL      = 4
PATTERN_BLOCKS_REVERSE         = 5
PATTERN_BLOCKS_RANDOM          = 6
PATTERN_BLOCKS_RANDOM_FRACTION = 7
VDI_MB = 16 
BLOCK_SIZE = 4096
VHD_BLOCK_SIZE = 2 * 1024 * 1024
LIBVHDIO_PATH = "/usr/lib/libvhdio.so"
VHD_UTIL = "vhd-util"

class ExposeThread(threading.Thread,xenrt.TestCase):

    def __init__(self,vdi,transferMode,useSSL,transferVMInst):
        threading.Thread.__init__(self)
        self.vdi = vdi
        self.transferMode = transferMode
        self.useSSL = useSSL
        self.transferVMInst = transferVMInst

    def run(self):

        self.ref = self.transferVMInst.expose(self.vdi,self.transferMode,self.useSSL)
    
    def getRecord(self,vdi = None):
 
        if vdi <> None:
            self.vdi = vdi
            ref = None
        else:
            ref = self.ref
        return self.transferVMInst.get_record(ref,self.vdi)
 
    def unexpose(self):
 
        return self.transferVMInst.unexpose(self.ref,self.vdi)

def authHeader(username, password):
    return 'Basic ' + base64.encodestring('%s:%s' % (username, password)).strip()

def rangeHeader(rangeStart, rangeAbove):
    return 'bytes=%d-%d' % (rangeStart, rangeAbove - 1)

def contentRangeHeader(rangeStart, rangeAbove, total):
    return 'bytes %d-%d/%d' % (rangeStart, rangeAbove - 1, total)

class _TransferVM(xenrt.TestCase):

    def __init__(self, tcid=None):
        xenrt.TestCase.__init__(self, tcid)
        self.srcTransferVMInst = None
        self.host = None

    def getTransferVMInst(self,host):
      
        return xenrt.lib.xenserver.host.TransferVM(host)

    def prepareForTest(self,srcHost,transferMode,useSSL):

        vdiSize = VDI_MB * MB
        srcVdi = self.createVdi(srcHost,vdiSize)
        self.srcTransferVMInst = self.getTransferVMInst(srcHost)
        srcRef = self.srcTransferVMInst.expose(srcVdi,transferMode,use_ssl=useSSL)
        srcRec = self.srcTransferVMInst.get_record(srcRef,srcVdi)
        return srcRef,srcRec,srcVdi

    def bitsPostTest(self,ref,transferVMInst):
  
        transferVMInst.unexpose(ref)

    def getVDIFile(self,record):

        uri = 'http://%s:%s%s' % (str(record['ip']), str(record['port']), str(record['url_path']))
        auth = urllib2.HTTPPasswordMgrWithDefaultRealm()
        auth.add_password(realm=None, uri=uri, user=str(record['username']), passwd=str(record['password']))
        opener = urllib2.build_opener(urllib2.HTTPBasicAuthHandler(auth))
        return opener.open(uri)
 
    def checkVdiDataisZero(self,record,size):

        vdifile = self.getVDIFile(record)
        try:
            vdidata = vdifile.read()
            vdidata = vdidata.strip()
        finally:
            vdifile.close()
        if size*MB <> len(vdidata):
            raise xenrt.XRTFailure("VDI size %s is not equal to %s" % (len(vdidata),size*MB))

        if '\0' * (size*MB) <> vdidata:
            raise xenrt.XRTFailure("VDI data is not zero")

    def createVdi(self,host,vdiSize,sruuid=None):
                
        cli = self.host.getCLIInstance()
        if not sruuid:
            sruuid = host.minimalList("sr-list",args="name-label=Local\ storage")
        args = []
        args.append("name-label='sample_vdi'")
        args.append("sr-uuid=%s" % (sruuid[0]))
        args.append("virtual-size=%d" % ((vdiSize))) 
        args.append("type=user")
        vdi = cli.execute("vdi-create", string.join(args), strip=True)
        
        return vdi 

    def destroyVdi(self,host,vdi):
        
        cli = self.host.getCLIInstance()
        cli.execute("vdi-destroy","uuid=%s" % (vdi))    

    def httpConnection(self,record):
    
        if not record:
            raise xenrt.XRTFailure("Record not found")
        conn = httplib.HTTPConnection(str(record['ip']), str(record['port']))
   
        return conn
   
    def httpsConnection(self,record):

        try:
            conn = httplib.HTTPSConnection(record['ip'],int(record['port']))
        except:
            raise xenrt.XRTFailure("Exception occured while opening a https connection")

        return conn

    def httpPUT(self,record,conn,headers,data,offset,vdiSize):

        if offset is not None:
            headers['Content-Range'] = contentRangeHeader(offset,offset + len(data),vdiSize)
        conn.request('PUT',record['url_path'],data,headers)
        resp = conn.getresponse()
        return resp

    def getHeaders(self,record,rangeBounds=None,contentRange=None):
  
        headers = {'Authorization':authHeader(record['username'], record['password'])}
        if rangeBounds:
            headers['Range'] = rangeHeader(*rangeBounds) 
        if contentRange:
            headers['Content-Range'] = contentRangeHeader(*contentRange)
 
        return headers 

    def httpGET(self,record,conn,headers):

        conn.request('GET',record['url_path'], None,headers)
        resp = conn.getresponse()
        return resp 

    def bitsConnection(self,host,record,packetType,sessionId=None,vhd=False,headers=None,data=None,connection=None,expectedStatus=200,vdiRaw=False,connClose=False,reqheaders=None,useSSL=False):

        if not record:
            raise xenrt.XRTFailure("Record not found") 
   
        if not connection:
            if not useSSL:
                conn = self.httpConnection(record)
            else:
                conn = self.httpsConnection(record)
        else:
            conn = connection
        
        if not reqheaders:
            reqheaders = {'Authorization': authHeader(record['username'], record['password'])}
        reqheaders['BITS-Packet-Type'] = packetType
        reqheaders['BITS-Supported-Protocols'] = BITS_PROTOCOL

        v = sys.version_info
        if v.major == 2 and ((v.minor == 7 and v.micro >= 9) or v.minor > 7):
            xenrt.TEC().logverbose("Disabling certificate verification on >=Python 2.7.9")
            ssl._create_default_https_context = ssl._create_unverified_context

        if sessionId is not None:
            reqheaders['BITS-Session-Id'] = sessionId

        if headers:
            for ele1, ele2 in headers.iteritems():
                reqheaders[ele1] = ele2

        try:
            if vhd:
                urlPath = record['url_path'] + ".vhd"
            else:
                urlPath = record['url_path']
            conn.request('BITS_POST', urlPath,data,reqheaders)
            resp = conn.getresponse()
            respheaders = dict((ele1.lower(),ele2) for (ele1,ele2) in resp.getheaders())
            resp.read()
        finally:
            if not connClose:
                conn.close()
        if expectedStatus <> resp.status:
            raise xenrt.XRTFailure("Status %d is not same as expected %d" % (int(resp.status),int(expectedStatus)))

        return respheaders,conn,reqheaders

    def checkHeader(self,header,name,value):

        name = name.lower()
        ret = False
        if value is None:
            if name not in header:
                ret = True
            else:
                ret = False
        else:
            if name in header:
                ret = True
            if ret <> False:
                if header[name] == value:
                    ret = True
        if not ret:
            raise xenrt.XRTFailure("%s is not equal to %s" % (name,value))

    def verifyVdiData(self,record,data,ssl=False):

        if ssl:
            http = 'https'
        else:
            http = 'http'
        uri = http + '://%s:%s%s' % (str(record['ip']), str(record['port']), str(record['url_path']))
        auth = urllib2.HTTPPasswordMgrWithDefaultRealm()
        auth.add_password(realm=None, uri=uri, user=str(record['username']), passwd=str(record['password']))
        opener = urllib2.build_opener(urllib2.HTTPBasicAuthHandler(auth))
        vdifile = opener.open(uri)
        try:
            vdidata = vdifile.read()
            vdidata = vdidata.strip()
        finally:
            vdifile.close()
        if len(data) <> len(vdidata):
            raise xenrt.XRTFailure("Length of data initially %s is not equal to length of data in VDI %s" % (len(data),len(vdidata)))
        if data <> vdidata:
            raise xenrt.XRTFailure("Data is not same in the VDI as it was copied earlier")
            
    def fillFile(self,vhdFile,referenceFile,vdiSize,pattern,host):

        patternFile = "pattern.tmp"
        #Fill reference file with Zeroes(a kind of initialization)
        self.fillReferenceFileWithZero(referenceFile,vdiSize,host)
        
        size = vdiSize* MB
        fraction = 100
        if pattern == PATTERN_EMPTY:
            cmd = "dd if=/dev/zero of=%s bs=1M count=%d" % (referenceFile,size)
            try:
                host.execdom0("%s "% cmd)
            except:
                raise xenrt.XRTFailure("Exception occurred while trying to execute command on host")
            return

        patternString = "Random bits start here %s end of random bits" % random.getrandbits(100)
        try:
            host.execdom0("echo %s >%s" % (patternString,patternFile))
        except:
            raise xenrt.XRTFailure("Exception occurred while trying to write in the pattern file")
        patternLen = len(patternString)
 
        if pattern == PATTERN_SHORT_STRING_BEGINNING:
            self.fillRange(vhdFile,referenceFile,patternFile,0,0,host)
        elif pattern == PATTERN_SHORT_STRING_MIDDLE:
            self.fillRange(vhdFile,referenceFile,patternFile,0,size / 2,host)
        elif pattern == PATTERN_SHORT_STRING_END:
            self.fillRange(vhdFile,referenceFile,patternFile,0,size - patternLen,host)
        elif pattern == PATTERN_BLOCKS_SEQUENTIAL:
            for i in range(size / VHD_BLOCK_SIZE):
                self.fillRange(vhdFile, referenceFile,patternFile,i*VHD_BLOCK_SIZE, i * VHD_BLOCK_SIZE + 1000,host)
        elif pattern == PATTERN_BLOCKS_REVERSE:
            for i in range(size / VHD_BLOCK_SIZE - 1, -1, -1):
                self.fillRange(vhdFile, referenceFile,patternFile,i*VHD_BLOCK_SIZE, i * VHD_BLOCK_SIZE + 1000,host)
        elif pattern == PATTERN_BLOCKS_RANDOM:
            blockSeq = range(size / VHD_BLOCK_SIZE)
            random.shuffle(blockSeq)
            for i in blockSeq:
                self.fillBlock(vhdFile,referenceFile,i,patternFile,patternLen,host)
        elif pattern == PATTERN_BLOCKS_RANDOM_FRACTION:
            blockSeq = range(1,(size / VHD_BLOCK_SIZE), fraction)
            random.shuffle(blockSeq)
            for i in blockSeq:
                self.fillBlock(vhdFile,referenceFile,i,patternFile,patternLen,host)
        else:
            raise xenrt.XRTFailure("Invalid pattern number: %d" % pattern)

    def fillBlock(self,vhdFile,referenceFile,block,patternFile,patternLen,host):

        startOffset = block*VHD_BLOCK_SIZE
        remaining = VHD_BLOCK_SIZE
        while remaining:
            amount = random.randint(1,512 * 800)
            if amount > remaining:
                amount = remaining
            remaining -= amount

            startOffset += amount
            rep = random.randint(1,100)
            for j in range(rep):
                if not remaining:
                    break
                amount = patternLen
                if amount > remaining:
                    amount = remaining
                remaining -= amount
                self.fillRange(vhdFile, referenceFile,patternFile,startOffset,startOffset,host)
                startOffset += amount

    def fillRange(self,vhdFile,referenceFile,patternFile,offset,patternOffset,host):
        
        if patternOffset < offset:
            raise xenrt.XRTFailure("Invalid usage of fill range")
 
        if not os.path.isfile(LIBVHDIO_PATH):
            raise xenrt.XRTError("File %s not found" % LIBVHDIO_PATH)
 
        libvhdIOcmd = "LD_PRELOAD=" + LIBVHDIO_PATH + " "

        cmd = "dd conv=notrunc if=%s of=%s bs=1 seek=%d" % (patternFile, referenceFile, patternOffset)
        try:
            host.execdom0("%s" % cmd)
        except:
            raise xenrt.XRTFailure("Exception occurred while trying to execute command on host")

        cmd = libvhdIOcmd + "&& dd if=%s of=%s bs=1 seek=%d" % (patternFile, vhdFile, patternOffset)
#        try:
        host.execdom0("%s" % cmd)
#        except:
#            raise xenrt.XRTFailure("Exception occurred while trying to execute command on host")

    def fillReferenceFileWithZero(self,referenceFile,size,host):
  
        if os.path.isfile(referenceFile):
            cmdrm = "rm %s" % (referenceFile)
            try:
                host.execdom0("%s" % cmdrm)
            except:
                raise xenrt.XRTFailure("Exception occurred while trying to execute command on host")

        cmd = "dd if=/dev/zero of=%s bs=1M count=%d" % (referenceFile,size)
        try:
            host.execdom0("%s" % cmd)
        except:
            raise xenrt.XRTFailure("Exception occurred while trying to execute command on host")

    def createVHD(self,path,size,host):

        try:
            host.execdom0("vhd-util create -n %s -s %d" % (path,size))
        except:
            raise xenrt.XRTFailure("Exception occurred while creating VHD")

    def copyToHost(self,host,src,dest):

        sftp = host.sftpClient()
        sftp.copyTo(src,dest)
        sftp.close()

    def copyFromHost(self,host,src,dest):  

        sftp = host.sftpClient()
        sftp.copyFrom(src,dest)
        sftp.close()

    #unexpose of vdi over ISCSI does not works with SSH
 
    def getXenApiSession(self,host):

        password = self.host.password
        user = "root"
        ip = host.getIP()
        session = XenAPI.Session("http://%s" % ip)
        session.login_with_password(user,password)
 
        return session

    def exposeOverIscsi(self,host,vdi,transferMode,useSSL=False,networkuuid=None,readOnly=False):

        session = self.getXenApiSession(host)
        if not networkuuid:
            networkuuid = "management"
        if useSSL == False:
            ssl = "false"
        else:
            ssl = "true"

        if readOnly == False:
            readOnly = "false"
        else:
            readOnly = "true"
        
        # Assign xenrt random mac to transferVM instance
        mac = xenrt.randomMAC()
        
        hostRef = session.xenapi.host.get_all()[0]
        args = {"vdi_uuid": vdi,
            "transfer_mode": transferMode,
            "use_ssl": ssl,
            "network_uuid": networkuuid,
            "network_mac": mac,
            "read_only": readOnly}
        ref = session.xenapi.host.call_plugin(hostRef, "transfer", "expose", args)
 
        return ref

    def unexposeOverIscsi(self,host,ref=None,vdi=None):
 
        if ref:
            args = {'record_handle':ref}
        elif vdi:
            args = {'vdi_uuid':vdi}
        else:
            raise xenrt.XRTFailure("Nither Record handle was given nor vdi uuid")
        session = self.getXenApiSession(host)
        hostRef = session.xenapi.host.get_all()[0]
        res = session.xenapi.host.call_plugin(hostRef,"transfer", "unexpose", args)
  
        return res

    def getRecordOverIscsi(self,host,ref=None,vdi=None):

        if ref:
            args = {'record_handle':ref}
        elif vdi:
            args = {'vdi_uuid':vdi}
        else:
            raise xenrt.XRTFailure("Nither Record handle was given nor vdi uuid")
        session = self.getXenApiSession(host)
        hostRef = session.xenapi.host.get_all()[0]
        record = session.xenapi.host.call_plugin(hostRef,"transfer", "get_record", args)
        dom = xml.dom.minidom.parseString(record)
        attribs = dom.getElementsByTagName('transfer_record')[0].attributes

        return (dict([(k, attribs[k].value.strip()) for k in attribs.keys()]))

    def getmd5Sum(self,host,vdi):

        host.execdom0("echo 'md5sum /dev/${DEVICE}' > /tmp/md5.sh")
        host.execdom0("chmod u+x /tmp/md5.sh")
        md5sum = host.execdom0("/opt/xensource/debug/with-vdi %s /tmp/md5.sh" % vdi,
                               timeout=1800).splitlines()[-1].split()[0]
        if "The device is not currently attached" in md5sum:
            raise xenrt.XRTError("Device not attached when trying to md5sum")

        return md5sum

    def checkPatternOnVDI(self,host,uuid, patternid=0):
        # Check a deterministic pattern on the VDI
        sftp = host.sftpClient()
        size = long(self.host.genParamGet("vdi", uuid, "virtual-size"))
        cmd = "%s/remote/patterns.py /dev/${DEVICE} %d read 1 %u" % \
              (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), size, patternid)
        filename = "cmd.sh"
        file(filename,"w").write(cmd)
        try:
            sftp.copyTo("cmd.sh","/tmp/cmd.sh")
        finally:
            sftp.close()
        host.execdom0("chmod u+x /tmp/cmd.sh")
        host.execdom0("/opt/xensource/debug/with-vdi %s "
                      "/tmp/cmd.sh" % uuid, timeout=5400)

    def writePatternToVDI(self,host,uuid,patternid=0):

        sftp = host.sftpClient()
        size = long(host.genParamGet("vdi",uuid,"virtual-size"))
        cmd = "%s/remote/patterns.py /dev/${DEVICE} %d write 1 %u" % \
              (xenrt.TEC().lookup("REMOTE_SCRIPTDIR"), size, patternid)

        filename = "cmd.sh"
        file(filename,"w").write(cmd)
        try:
            sftp.copyTo("cmd.sh","/tmp/cmd.sh")
        finally:
            sftp.close()
        host.execdom0("chmod u+x /tmp/cmd.sh")
        host.execdom0("/opt/xensource/debug/with-vdi %s "
                      "/tmp/cmd.sh" % uuid, timeout=5400)

        host.genParamSet("vdi",uuid,"other-config","%u" % (patternid),"xenrt-pattern")
        host.genParamSet("vdi",uuid,"other-config","%u" % (size), "xenrt-pattlem")

class BitsTest(_TransferVM):

    PACKETTYPE = None
    SESSIONID = None
    HEADERS = None
    DATA = None
    CONNECTION = None
    SSL = False
    EXPECTEDSTATUS = None
    VDIRAW = False
    EXPECTEDHEADERS = None
    RETHEADER = None
    EXPECTEDSESSIONID = None
    EXPECTEDERRORCODE = None
    EXPECTEDERRORCONTEXT = None
    VERIFYVDIDATA = False
    RECORD = None
    CONNCLOSE = False
    RESPHEADERS = None
    VHD = False
    EXPECTEDVDI = None
 
    def prepare(self,arglist):
        
        self.host = self.getHost("RESOURCE_HOST_0")
        
    def run(self,arglist): 

        transferMode = 'BITS'
        if not self.RECORD:
            self.ref,self.RECORD,self.vdi = self.prepareForTest(self.host,transferMode,self.SSL)
        self.RESPHEADERS,self.CONNECTION,reqheaders = self.bitsConnection(self.host,self.RECORD,self.PACKETTYPE,self.SESSIONID,self.VHD,self.HEADERS,self.DATA,self.CONNECTION,self.EXPECTEDSTATUS,self.VDIRAW,self.CONNCLOSE,useSSL=self.SSL)     
        self.checkHeader(self.RESPHEADERS,'Content-Length','0')
        self.checkHeader(self.RESPHEADERS,'BITS-Packet-Type', 'Ack')
        if self.EXPECTEDSESSIONID:
            self.checkHeader(self.RESPHEADERS,'BITS-Session-Id',self.EXPECTEDSESSIONID)
        if self.EXPECTEDERRORCODE:
            self.checkHeader(self.RESPHEADERS,'BITS-Error-Code',self.EXPECTEDERRORCODE)
        if self.EXPECTEDERRORCONTEXT:
            self.checkHeader(self.RESPHEADERS,'BITS-Error-Context',self.EXPECTEDERRORCONTEXT)
        if self.EXPECTEDHEADERS:
            for i, j in self.EXPECTEDHEADERS.iteritems():
                self.checkHeader(self.RESPHEADERS,i,j)

        if self.EXPECTEDVDI:
            self.verifyVdiData(self.RECORD,self.EXPECTEDVDI,self.SSL)
  
    def postRun(self):

        if self.CONNCLOSE:
            self.CONNECTION.close()
        self.bitsPostTest(self.ref,self.srcTransferVMInst)
        self.destroyVdi(self.host,self.vdi)

class TC14047(BitsTest):
    """To check the return status when the Content range is missing in the BITS-POST request"""

    PACKETTYPE = 'FRAGMENT'
    SESSIONID = '{00000000-0000-0000-0000-000000000111}'
    VHD = False
    DATA = 'a' * (5*KB)    
    EXPECTEDSTATUS = 400
    EXPECTEDERRORCODE = BITS_E_INVALIDARG 
    EXPECTEDERRORCONTEXT = BITS_CONTEXT_SERVER
    RETHEADER = True

class TC14048(BitsTest):
    """To check the return status when the Content range is invalid in the BITS-POST request"""

    PACKETTYPE = 'FRAGMENT'
    SESSIONID = '{00000000-0000-0000-0000-000000000222}'
    DATA = 'a' * (5*KB)
    EXPECTEDSTATUS = 400
    EXPECTEDERRORCODE = BITS_E_INVALIDARG
    EXPECTEDERRORCONTEXT = BITS_CONTEXT_SERVER
    HEADERS = {'Content-Range':contentRangeHeader(1*MB,1*MB + len(DATA),2* VDI_MB*MB)}

class TC14049(BitsTest):
    """To check the return status when the session id is missing in the BITS-POST request"""

    PACKETTYPE = 'FRAGMENT'
    DATA = 'a' * (5*KB)
    EXPECTEDSTATUS = 400
    EXPECTEDERRORCODE = BITS_E_INVALIDARG
    EXPECTEDERRORCONTEXT = BITS_CONTEXT_SERVER
    HEADERS = {'Content-Range':contentRangeHeader(1*MB,1*MB + len(DATA),VDI_MB*MB)}

class TC14050(BitsTest):
    """To write 5K of data on vdi exposed using transfer VM over BITS and verify it"""

    PACKETTYPE = 'FRAGMENT'
    SESSIONID = '{00000000-0000-0000-0000-000000000333}'
    DATA = 'a' * (5*KB)
    EXPECTEDSTATUS = 200
    EXPECTEDSESSIONID = '{00000000-0000-0000-0000-000000000333}'
    HEADERS = {'Content-Range':contentRangeHeader(1*MB,1*MB + len(DATA),VDI_MB*MB)}
    EXPECTEDHEADERS = {'BITS-Received-Content-Range': str(1*MB + len(DATA)),'BITS-Reply-URL': None}
    EXPECTEDVDI = ('\0'*(1*MB)) + DATA + ('\0'*(VDI_MB*MB - 1*MB - len(DATA)))

class TC14051(BitsTest):
    """To write 4MB of data on vdi exposed using transfer VM over BITS and verify it"""

    PACKETTYPE = 'FRAGMENT'
    SESSIONID = '{00000000-0000-0000-0000-000000000444}'
    DATA = 'a' * (4*MB)
    EXPECTEDSTATUS = 200
    EXPECTEDSESSIONID = '{00000000-0000-0000-0000-000000000444}'
    HEADERS = {'Content-Range':contentRangeHeader(1*MB,1*MB + len(DATA),VDI_MB*MB)}
    EXPECTEDHEADERS = {'BITS-Received-Content-Range': str(1*MB + len(DATA)),'BITS-Reply-URL': None}
    EXPECTEDVDI = ('\0'*(1*MB)) + DATA + ('\0'*(VDI_MB*MB - 1*MB - len(DATA)))

class TC14052(BitsTest):
    """To check the return status when Packet type is missing in the BITS-POST request"""

    DATA = 'a' * (5*KB)
    EXPECTEDSTATUS = 400
    EXPECTEDERRORCODE = BITS_E_INVALIDARG
    EXPECTEDERRORCONTEXT = BITS_CONTEXT_SERVER
    HEADERS = {'Content-Range':contentRangeHeader(1*MB,1*MB + len(DATA),VDI_MB*MB)}

class TC14053(BitsTest):
    """To check the return status when Packet type is invalid in the BITS-POST request"""

    PACKETTYPE = 'FAILURE-MESSAGE'
    DATA = 'a' * (5*KB)
    EXPECTEDSTATUS = 400
    EXPECTEDERRORCODE = BITS_E_INVALIDARG
    EXPECTEDERRORCONTEXT = BITS_CONTEXT_SERVER
    HEADERS = {'Content-Range':contentRangeHeader(1*MB,1*MB + len(DATA),VDI_MB*MB)}

class TC14054(BitsTest):
    """To check the return status when header is missing from BITS-POST request when packet type is create-session"""

    PACKETTYPE = 'CREATE-SESSION'
    EXPECTEDSTATUS = 200

class TC14055(BitsTest):
    """To verify the return status when packet type is create-session in BITS-POST request"""

    PACKETTYPE = 'CREATE-SESSION'
    EXPECTEDSTATUS = 200
    HEADERS = {'BITS-Supported-Protocols': BITS_PROTOCOL}
    EXPECTEDHEADERS={'BITS-Protocol': BITS_PROTOCOL.lower(),
                     'BITS-Host-ID': None,
                     'BITS-Host-Id-Fallback-Timeout': None}

class TC14057(BitsTest):
    """To verify the return status when packet type is Ping in BITS-POST request"""

    PACKETTYPE = 'PING'
    EXPECTEDSTATUS = 200

class TC14058(BitsTest):
    """To verify the return status when non zero content length is present in BITS-POST request when packet type is Close session"""

    PACKETTYPE = 'CLOSE-SESSION'
    EXPECTEDSTATUS = 400
    DATA = 'ABCDEFGH'
    SESSIONID = '{00000000-0000-0000-0000-000000000123}'
    EXPECTEDERRORCODE=BITS_E_INVALIDARG
    EXPECTEDERRORCONTEXT = BITS_CONTEXT_SERVER
    EXPECTEDSESSIONID = '{00000000-0000-0000-0000-000000000123}'

class TC14059(BitsTest):
    """To verify the return status when Session id is missing in BITS-POST request when packet type is Close session"""

    PACKETTYPE = 'CLOSE-SESSION'
    EXPECTEDSTATUS = 400
    EXPECTEDERRORCODE=BITS_E_INVALIDARG
    EXPECTEDERRORCONTEXT = BITS_CONTEXT_SERVER
    
class TC14060(BitsTest):
    """To verify the return status of BITS-POST request when packet type is Close session""" 

    PACKETTYPE = 'CLOSE-SESSION'
    EXPECTEDSTATUS = 200
    SESSIONID = '{00000000-0000-0000-0000-000000000123}'
    EXPECTEDSESSIONID = '{00000000-0000-0000-0000-000000000123}'

class TC14061(BitsTest):
    """To verify the return status when non zero content length is present in BITS-POST request and packet type is Cancel session request"""

    PACKETTYPE = 'CANCEL-SESSION'
    EXPECTEDSTATUS = 400
    DATA = 'ABCDEFGH'
    SESSIONID = '{00000000-0000-0000-0000-000000000789}'
    EXPECTEDERRORCODE=BITS_E_INVALIDARG
    EXPECTEDERRORCONTEXT = BITS_CONTEXT_SERVER
    EXPECTEDSESSIONID = '{00000000-0000-0000-0000-000000000789}'

class TC14062(BitsTest):
    """To verify the return status of BITS-POST request when packet type is Cancel session"""

    PACKETTYPE = 'CANCEL-SESSION'
    EXPECTEDSTATUS = 200
    SESSIONID = '{00000000-0000-0000-0000-000000000789}'
    EXPECTEDSESSIONID = '{00000000-0000-0000-0000-000000000789}'

class TC14063(BitsTest):
    """To verify writing of multiple fragments of data in single connction request when VDI is exposed ovr BITS"""

    PACKETTYPE = 'FRAGMENT' 
    SESSIONID = '{00000000-0000-0000-0000-000000000333}'
    EXPECTEDSTATUS = 200
    EXPECTEDSESSIONID = '{00000000-0000-0000-0000-000000000333}'
    CONNCLOSE = True
    EXPECTEDVDI = '\0' * (VDI_MB*MB)   
 
    def run(self,arglist):
 
        for i in xrange(1,6):
            self.DATA = ("xabcde"[i]) * MB
            offset = i * MB/2
            rangeHeader = contentRangeHeader(offset,offset + len(self.DATA), VDI_MB * MB)
            self.HEADERS = {'Content-Range': rangeHeader}
            self.EXPECTEDHEADERS = {'BITS-Received-Content-Range': str(offset + len(self.DATA)),
                                    'BITS-Reply-URL': None}          
            self.EXPECTEDVDI = self.EXPECTEDVDI[:offset] + self.DATA + self.EXPECTEDVDI[offset + len(self.DATA):]
            BitsTest.run(self,[])

class TC14064(TC14063):
    """To verify writing of multiple fragments of data in single connction request when VDI is exposed ovr BITS over SSL """

    SSL = True
          
class VhdFragment(BitsTest):

    VHDFILE = "tmp.vhd"
    REFERENCEFILE = "reference.tmp"    
    FRAGSIZE = None
    PACKETTYPE = 'CREATE-SESSION'
    HEADERS = {'BITS-Supported-Protocols': BITS_PROTOCOL}
    EXPECTEDSTATUS = 200
    EXPECTEDHEADERS = {'BITS-Protocol': BITS_PROTOCOL.lower(),
                       'BITS-Host-ID': None,
                       'BITS-Host-Id-Fallback-Timeout': None}
    VHD = True      

    def run(self,arglist):

        fragVar = False
        if not self.FRAGSIZE:
            self.FRAGSIZE = random.randint(1,100*KB)
            fragVar = True
 
        self.createVHD(self.VHDFILE,VDI_MB,self.host)
        self.fillFile(self.VHDFILE,self.REFERENCEFILE,VDI_MB,PATTERN_BLOCKS_RANDOM,self.host) 
        try:
            data = self.host.execdom0("cat %s" % self.VHDFILE)
            data = data.strip()
        except:
            raise xenrt.XRTFailure("Unable to get the data from the file")
        BitsTest.run(self,[])
        self.SESSIONID = self.RESPHEADERS['bits-session-id']
        rangeStart = self.FRAGSIZE
        rangeEnd = self.FRAGSIZE + self.FRAGSIZE
        total = len(data)
        while (rangeStart < total):
            if rangeEnd > total:
                rangeEnd = total
            rangeheader = contentRangeHeader(rangeStart, rangeEnd, total)
            self.PACKETTYPE = 'FRAGMENT'
            self.DATA = data[rangeStart:rangeEnd]
            self.HEADERS = {'Content-Range': rangeheader}  
            self.EXPECTEDHEADERS = {'BITS-Received-Content-Range':str(rangeEnd),
                                    'BITS-Reply-URL':None}
            BitsTest.run(self,[])
            rangeStart = rangeEnd
            if fragVar:
                self.FRAGSIZE = random.randint(1,100*KB)   
            rangeEnd += self.FRAGSIZE

        try:
            data = self.host.execdom0("cat %s" % self.REFERENCEFILE)
            data = data.strip()
        except:
            raise xenrt.XRTFailure("Unable to get the data from the reference file")

        self.verifyVdiData(self.RECORD,data)

class TC14067(_TransferVM):
    """To verify the behaviour of transfer VM when both expose and cleanup are triggered on the same vdi parallely"""

    useSSL = False

    def prepare(self,arglist):

        self.host = self.getHost("RESOURCE_HOST_0")

    def run(self,arglist):
 
        self.vdi = self.createVdi(self.host,VDI_MB*MB)
        transferVMInst = self.getTransferVMInst(self.host)
        transferMode = 'http'
        self.asyncExpose = ExposeThread(self.vdi,transferMode,self.useSSL,transferVMInst)  
        self.asyncExpose.start()

        while self.asyncExpose.isAlive():
            transferVMInst.cleanup()
   
        record = self.asyncExpose.getRecord()
 
        self.checkVdiDataisZero(record,VDI_MB)
 
    def postRun(self):
  
        try:
            self.asyncExpose.unexpose()
        except:
            pass
        try:
            self.destroyVdi(self.host,self.vdi)
        except:
            pass

class TC14068(TC14067):
    """To verify the behaviour of transfer VM when both expose(over SSL) and cleanup are triggered on the same vdi parallely"""

    useSSL = True

class TC14069(_TransferVM):
    """To verify the behaviour of transfer VM when multiple exposes are tried on the different VDIs parallely"""

    useSSL = False

    def prepare(self,arglist):

        self.host = self.getHost("RESOURCE_HOST_0")

    def run(self,arglist):

        parallelExpose = 3
        transferMode = 'http'
        transferVMInst = self.getTransferVMInst(self.host)
        self.vdis = []
        self.vdis = [self.createVdi(self.host,VDI_MB*MB) for i in xrange(parallelExpose)] 

        self.threads = [ExposeThread(vdi,transferMode,self.useSSL,transferVMInst) for vdi in self.vdis]

        for t in self.threads:
            t.start()
        #synching the child threads with the main one
        for t in self.threads:
            t.join()

        for t in self.threads:
            record = t.getRecord()
            self.checkVdiDataisZero(record,VDI_MB)

    def postRun(self):

        for t in self.threads:
            try:
                t.unexpose()
            except:
                pass
        for vdi in self.vdis:
            try:
                self.destroyVdi(self.host,vdi)
            except:
                pass

class TC14070(TC14069):
    """To verify the behaviour of transfer VM when multiple exposes(over SSL) are tried on the different VDIs parallely"""

    useSSL = True

class TC14071(_TransferVM):
    """To verify the behaviuor of transfer VM when expose of VDI is ongoing and if get_record is tried """
 
    useSSL = False  

    def prepare(self,arglist):

        self.host = self.getHost("RESOURCE_HOST_0")

    def run(self,arglist):

        transferMode = 'http'
        transferVMInst = self.getTransferVMInst(self.host)
        self.vdi = self.createVdi(self.host,VDI_MB*MB)
        self.asyncExpose = ExposeThread(self.vdi,transferMode,self.useSSL,transferVMInst)
        self.asyncExpose.start()
        record = {'status':'unused'}               
        while record['status'] == 'unused':
            try:
                record = self.asyncExpose.getRecord()
            except:
                pass
 
        self.checkVdiDataisZero(record,VDI_MB)       
 
    def postRun(self):

        try:
            self.asyncExpose.unexpose()
        except:
            pass
        try:
            self.destroyVdi(self.host,self.vdi)
        except:
            pass

class TC14072(TC14071):
    """To verify the behaviuor of transfer VM when expose of VDI is ongoing(over ssl) and if get_record is tried """

    useSSL = True

class TC14076(_TransferVM):
    """To verify that Unexpose waits until partial expose has finished"""

    useSSL = False

    def prepare(self,arglist):

        self.host = self.getHost("RESOURCE_HOST_0")

    def run(self,arglist):

        transferMode = 'http'
        transferVMInst = self.getTransferVMInst(self.host)
        self.vdi = self.createVdi(self.host,VDI_MB*MB)
        self.asyncExpose = ExposeThread(self.vdi,transferMode,self.useSSL,transferVMInst)
        self.asyncExpose.start()
        response = None
        while not response: 
            try:
                response = self.asyncExpose.unexpose()
            except:
                pass
#                exception = str(e.data)
#                if exception.details[2] <> 'VDINotInUse':
#                    raise xenrt.XRTFailure("Exception occurred while trying to unxpose the VDI")
        if response <> 'OK':
            raise xenrt.XRTFailure("Unexpose response is not equal to OK")
        if self.asyncExpose.getRecord(self.vdi)['status'] <> 'unused':
            raise xenrt.XRTFailure("VDI status is not unused, it might be still in use")

    def postRun(self):
   
        try:
            self.asyncExpose.unexpose()
        except:
            pass
        try:
            self.destroyVdi(self.host,self.vdi)
        except:
            pass

class TC14078(TC14076):
    """To verify that Unexpose waits until partial expose(over ssl) has finished"""

    useSSL = True

class TC14080(_TransferVM):
    """To verify 'expose' when important parameters are missing or invalid in the 'expose' call"""

    VDI = None
    TRANSFERMODE = 'http'
    USESSL = False

    def prepare(self,arglist):

        self.host = self.getHost("RESOURCE_HOST_0")

    def run(self,arglist):

        transferVMInst = self.getTransferVMInst(self.host)
        self.VDI = self.createVdi(self.host,VDI_MB*MB)
        transferVMInst = self.getTransferVMInst(self.host)
      
        self.checkForException(transferVMInst,self.VDI,None,self.USESSL)

        self.checkForException(transferVMInst,None,self.TRANSFERMODE,self.USESSL)

        self.checkForException(transferVMInst,self.VDI,'InvalidTransferMode',self.USESSL)

        self.checkForException(transferVMInst,self.VDI,self.TRANSFERMODE,'InvalidSSL')

        self.checkForException(transferVMInst,self.VDI,self.TRANSFERMODE,self.USESSL,networkPort = 'abcd')

        self.checkForException(transferVMInst,self.VDI,self.TRANSFERMODE,self.USESSL,networkPort = '-123')  

        self.checkForException(transferVMInst,self.VDI,'iscsi',self.USESSL,networkPort = '3261')

        self.checkForException(transferVMInst,None,self.TRANSFERMODE,self.USESSL,timeout = 'invalidTimeout')

        self.checkForException(transferVMInst,None,self.TRANSFERMODE,self.USESSL,timeout = '-90')

        self.checkForException(transferVMInst,None,self.TRANSFERMODE,self.USESSL,networkUUID = 'invalidUUID')

        self.checkForException(transferVMInst,None,self.TRANSFERMODE,self.USESSL,networkConf = 'invalidConf')

        self.checkForException(transferVMInst,None,self.TRANSFERMODE,self.USESSL,networkMac = 'invalidMac')

        self.checkForException(transferVMInst,'invalidVDIUUID',self.TRANSFERMODE,self.USESSL)

    def checkForException(self,transferVMInst,vdi,transferMode,usessl,
                         timeout = None,networkUUID = None,networkConf = None,
                         networkPort = None,networkMac = None):
      
        try:
            transferVMInst.expose(vdi,transferMode,use_ssl=usessl,timeout_minutes = timeout,network_uuid = networkUUID,network_conf = networkConf,network_port = networkPort,network_mac = networkMac) 
            raise xenrt.XRTFailure("Exception was not raised while exposing VDI with incorrect/missing parameter(s)")
        except:
            xenrt.TEC().logverbose("Exception raised while exposing a VDI because one of the parameter was incorrect")

    def postRun(self):

        try:
            self.destroyVdi(self.host,self.VDI)
        except:
            pass

class TC14082(_TransferVM): 
    """To verify the behaviour of 'unexpose' in various scenarios whne the vdi is exposed over http"""

    VDI = None
    TRANSFERMODE = 'http'
    USESSL = False

    def prepare(self,arglist):

        self.host = self.getHost("RESOURCE_HOST_0")

    def run(self,arglist):

        transferVMInst = self.getTransferVMInst(self.host)
        self.VDI = self.createVdi(self.host,VDI_MB*MB)
        transferVMInst = self.getTransferVMInst(self.host)
        ref = transferVMInst.expose(self.VDI,self.TRANSFERMODE,self.USESSL)
        transferVMInst.unexpose(ref)
        vbd = None
        try:
            vbd = self.host.minimalList("vbd-list",args="vdi-uuid=%s" % (self.VDI))
        except:
            pass
        if vbd:
            raise xenrt.XRTFailure("VBD still exists after unexpose")
 
        record = transferVMInst.get_record(vdi_uuid=self.VDI) 

        if record['status'] <> 'unused':
            raise xenrt.XRTFailure("VDI status is not unused")

        try:
            transferVMInst.unexpose(vdi_uuid='invalidVDIUUID')
            raise xenrt.XRTFailure("Exception was not raised while unexposing VDI with incorrect vdi uuid")
        except:    
            xenrt.TEC().logverbose("Exception raised while unexposing a VDI because one of the parameter was incorrect")

        try:
            transferVMInst.unexpose(vdi_uuid=self.VDI)
            raise xenrt.XRTFailure("Exception was not raised while unexposing VDI which was not exposed earlier")
        except:
            xenrt.TEC().logverbose("Exception raised while unexposing a VDI which is not exposed")

    def postRun(self):

        try:
            self.destroyVdi(self.host,self.VDI)
        except:
            pass

class TC14083(TC14082):
    """To verify the behaviour of 'unexpose' in various scenarios whne the vdi is exposed over http over ssl"""

    USESSL = True

class TC14084(TC14082):
    """To verify the behaviour of 'unexpose' in various scenarios whne the vdi is exposed over bits"""

    TRANSFERMODE = 'bits'

class TC14085(TC14084):
    """To verify the behaviour of 'unexpose' in various scenarios whne the vdi is exposed over bits over ssl"""

    USESSL = True

class TC14086(_TransferVM):
    """To verify the behaviour of get_record in various scenarios"""

    VDI = None
    TRANSFERMODE = 'http'
    USESSL = False

    def prepare(self,arglist):

        self.host = self.getHost("RESOURCE_HOST_0")

    def run(self,arglist):

        self.VDI = self.createVdi(self.host,VDI_MB*MB)
        self.transferVMInst = self.getTransferVMInst(self.host)
        
        self.checkForException(self.transferVMInst)
 
        self.checkForException(self.transferVMInst,vdi = 'Invalid vdi uuid')
 
        record = self.transferVMInst.get_record(vdi_uuid=self.VDI)
        if record['status'] <> 'unused':
            raise xenrt.XRTFailure("VDI status is not unused")

        self.ref = self.transferVMInst.expose(self.VDI,self.TRANSFERMODE,self.USESSL)
        record = self.transferVMInst.get_record(self.ref)
        self.checkRecordFields(record,['url_path','url_full'])
        self.compareFieldValue(record['status'],'exposed')
        self.compareFieldValue(record['transfer_mode'],'http')
        self.compareFieldValue(record['port'],'80')
        self.transferVMInst.unexpose(self.ref)      
  
        self.ref = self.transferVMInst.expose(self.VDI,self.TRANSFERMODE,use_ssl=True)
        record = self.transferVMInst.get_record(self.ref)
        self.checkRecordFields(record,['url_path','url_full','ssl_cert'])
        self.compareFieldValue(record['status'],'exposed')
        self.compareFieldValue(record['transfer_mode'],'http')
        self.compareFieldValue(record['port'],'443')
        self.transferVMInst.unexpose(self.ref)

        self.TRANSFERMODE = 'bits'
        self.ref = self.transferVMInst.expose(self.VDI,self.TRANSFERMODE,self.USESSL)
        record = self.transferVMInst.get_record(self.ref)
        self.checkRecordFields(record,['url_path','url_full'])
        self.compareFieldValue(record['status'],'exposed')
        self.compareFieldValue(record['transfer_mode'],'bits')
        self.compareFieldValue(record['port'],'80')
        self.transferVMInst.unexpose(self.ref)

        self.TRANSFERMODE = 'iscsi'
        self.ref = self.exposeOverIscsi(self.host,self.VDI,self.TRANSFERMODE,self.USESSL)
        record = self.getRecordOverIscsi(self.host,self.ref)
        self.checkRecordFields(record,['iscsi_iqn','iscsi_lun','iscsi_sn'])
        self.compareFieldValue(record['status'],'exposed')
        self.compareFieldValue(record['transfer_mode'],'iscsi')
        self.compareFieldValue(record['port'],'3260')
        self.unexposeOverIscsi(self.host,self.ref)

        self.TRANSFERMODE = 'http'
        self.ref = self.transferVMInst.expose(self.VDI,self.TRANSFERMODE,self.USESSL)
        self.transferVMInst.unexpose(self.ref)
        self.TRANSFERMODE = 'bits'
        self.ref = self.transferVMInst.expose(self.VDI,self.TRANSFERMODE,self.USESSL)
        self.transferVMInst.unexpose(self.ref)
        self.TRANSFERMODE = 'iscsi'
        self.ref = self.exposeOverIscsi(self.host,self.VDI,self.TRANSFERMODE,self.USESSL)
        self.unexposeOverIscsi(self.host,self.ref)          
        
    def compareFieldValue(self,field,value):
 
        if field <> value:
            raise xenrt.XRTFailure("%s is not equal to %s" % (field,value))

    def checkRecordFields(self,record,fields):
 
        for field in fields:
            if not field in record.keys():
                raise xenrt.XRTFailure("Field %s not found in record" % (field))
            if not len(str(record[field])) > 0:
                raise xenrt.XRTFailure("Lenght of data in record for field %s is zero" % (field))

    def checkForException(self,transferVMInst,vdi = None,recordHandle = None):

        try: 
            transferVMInst.get_record(record_handle=recordHandle, vdi_uuid=vdi) 
            raise xenrt.XRTFailure("Exception was not raised while getting the record with incorrect/missing parameters")
        except:
            xenrt.TEC().logverbose("Exception was raised while getting the record")

    def postRun(self):

        try:
            if self.TRANSFERMODE <> 'iscsi':
                self.transferVMInst.unexpose(self.ref)
            else:
                self.unexposeOverIscsi(self.host,self.ref)
        except:
            pass

        try:
            self.destroyVdi(self.host,self.VDI)
        except:
            pass

class TC14087(_TransferVM):
    """To verify whether timeout works for expose or not"""

    VDI = None
    TRANSFERMODE = 'http'

    def prepare(self,arglist):

        self.host = self.getHost("RESOURCE_HOST_0")

    def run(self,arglist):

        self.VDI = self.createVdi(self.host,VDI_MB*MB)
        self.transferVMInst = self.getTransferVMInst(self.host)
        self.ref = self.transferVMInst.expose(self.VDI,self.TRANSFERMODE,timeout_minutes=1)
        record = self.transferVMInst.get_record(self.ref) 
        xenrt.sleep(30) 
        ret = self.isVDIStillExposed(record)
        if not ret:
            raise xenrt.XRTFailure("VDI is not exposed anymore")

        xenrt.sleep(30)
        ret = self.isVDIStillExposed(record)
        if not ret:
            raise xenrt.XRTFailure("VDI is not exposed anymore")

        xenrt.sleep(240)
        ret = self.isVDIStillExposed(record)
        if ret:
            raise xenrt.XRTFailure("VDI is still exposed even after timeout")
        
    def isVDIStillExposed(self,record):

        try:
            vdiFile = self.getVDIFile(record) 
            try:
                vdidata = vdiFile.read()
            finally:
                vdiFile.close()
            if len(vdidata) > 0:
                return True
            else:
                return False
        except:
            return False

        return False

    def postRun(self):

        try:
            self.destroyVdi(self.host,self.VDI)
        except:
            pass

class TC14088(_TransferVM):
    """To verify the behaviour of TVM when VDI is exposed over http over SSL"""

    VDI = None
    TRANSFERMODE = 'http'
    USESSL = True

    def prepare(self,arglist):

        self.host = self.getHost("RESOURCE_HOST_0")

    def run(self,arglist):

        self.VDI = self.createVdi(self.host,VDI_MB*MB)
        self.transferVMInst = self.getTransferVMInst(self.host)
        self.ref = self.transferVMInst.expose(self.VDI,self.TRANSFERMODE,use_ssl=self.USESSL)
        record = self.transferVMInst.get_record(self.ref)

        self.getData(record, '\0' * (VDI_MB*MB))

        data = 'a' * (1*MB)
        self.putData(record,data,2*MB,VDI_MB*MB)  
        expectedData = ('\0' * (2*MB)) + data + ('\0' * (13*MB)) 
        self.getData(record,expectedData)
        self.transferVMInst.unexpose(self.ref)
        self.destroyVdi(self.host,self.VDI)
      
        self.VDI = self.createVdi(self.host,VDI_MB*MB)
        self.ref = self.transferVMInst.expose(self.VDI,self.TRANSFERMODE,use_ssl=self.USESSL)
        record = self.transferVMInst.get_record(self.ref)
        self.multiplePutRequestInOneHttpConnection(record)
        self.transferVMInst.unexpose(self.ref)
        self.destroyVdi(self.host,self.VDI)

        self.VDI = self.createVdi(self.host,VDI_MB*MB)
        self.ref = self.transferVMInst.expose(self.VDI,self.TRANSFERMODE,use_ssl=self.USESSL)
        record = self.transferVMInst.get_record(self.ref)
        serverCert = self.getServerCert(record['ip'],record['port'])
        translatedCert = serverCert.replace("\n"," ")
        if translatedCert <> record['ssl_cert']:
            raise xenrt.XRTFailure("SSL Certifacte is not same in record")
       
    def getServerCert(self,hostname,port):

        openssl = subprocess.Popen(['openssl', 's_client', '-showcerts', '-connect', '%s:%s' % (hostname, port)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        output = openssl.communicate()
        match = re.search(r'-----BEGIN CERTIFICATE-----.*-----END CERTIFICATE-----', output[0], re.DOTALL)
        if match:
            return match.group(0)
        else:
            return None
        
    def multiplePutRequestInOneHttpConnection(self,record):

        conn = self.httpsConnection(record)
        headers = self.getHeaders(record)
        try:
            for i in xrange(1,5):
                data = 'a' * (i*100*KB)
                resp = self.httpPUT(record,conn,headers,data,i*MB*2 +  234*KB,VDI_MB*MB)
                resp.read()
                if resp.status <> 200:
                    raise xenrt.XRTFailure("Response status is %d which is not 200" % (int(resp.status)))
        finally:
            conn.close()

    def putData(self,record,data,offset,vdiSize):

        conn = self.httpsConnection(record)
        headers = self.getHeaders(record)
        resp = self.httpPUT(record,conn,headers,data,offset,vdiSize)
        resp.read(0)
        if resp.status <> 200:
            raise xenrt.XRTFailure("Response status is %d which is not 200" % (int(resp.status)))

        conn.close()
 
    def getData(self,record,data):
        conn = self.httpsConnection(record)
        headers = self.getHeaders(record)
        resp = self.httpGET(record,conn,headers) 
        respData = resp.read()

        if resp.status <> 200:
            raise xenrt.XRTFailure("Response status is %d which is not 200" % (int(resp.status)))

        if len(data) <> len(respData):
            raise xenrt.XRTFailure("Length of data expected %s is not equal to length of data fetched %s" %  (len(data), len(respData)))

        if data <> respData:
            raise xenrt.XRTFailure("Expected data is not equal to the fetched data") 

        conn.close()

    def postRun(self):

        try:
            self.transferVMInst.unexpose(self.ref)          
        except:
            pass
        try:
            self.destroyVdi(self.host,self.VDI)
        except:
            pass

class VhdFunctions(_TransferVM):

    VDI = None
    TRANSFERMODE = 'bits'
    USESSL = False

    def prepare(self,arglist):

        self.host = self.getHost("RESOURCE_HOST_0")
        
        self.transferVMInst = self.getTransferVMInst(self.host)
        data = self.host.execdom0("vgdisplay -c 2>/dev/null | grep XenStorage")
        self.vgdisplay = data.split(":")[0].strip()
        masterlvm = ""
        if self.host.execdom0("ls /etc/lvm/master", retval="code") == 0:
            masterlvm = "LVM_SYSTEM_DIR=/etc/lvm/master "
        lvcreate = self.host.execdom0("%slvcreate -L 60G %s" % (masterlvm, self.vgdisplay))
        self.lvName = lvcreate.split('"')[1].strip()
        self.host.execdom0("mkfs /dev/%s/%s" % (self.vgdisplay,self.lvName))
        self.host.execdom0("mkdir /tmp/tmp;mount /dev/%s/%s /tmp/tmp" % (self.vgdisplay,self.lvName))

    def getFiles(self,data):

        files = []
        count = 0
        while True:
            try:
                files.append(data.splitlines()[count])
            except:
                break
            count = count + 1
        return files
      
    def getVdiBitmaps(self,bitmapsXML,vdiuuid):

        xmldoc = minidom.parseString(bitmapsXML)
        bitmaps = xmldoc.getElementsByTagName('bitmap') 
        for node in bitmaps:
            if node.attributes['vdi_uuid'].value == vdiuuid:
                return node.firstChild.data
        return bitmaps
 
    def bitsDownloadVHD(self,record,dest,reqSize,host,ssl):

        auth = 'Basic %s' % base64.b64encode('%s:%s' % (record['username'],record['password']))
        range = '"bytes=%s-%s" % (startReq,startReq+reqSize)'
        if ssl:
            http = "https"
        else:
            http = "http"
        script = u"""
import urllib2
VHD_BLOCK_SIZE = 2 * 1024 * 1024
vhdPath = "%s"  + ".vhd"
urlPath = "%s://" + "%s" + ":%s" + vhdPath
req = urllib2.Request(urlPath)
req.headers["Range"] = "bytes=0-1"
req.headers["Authorization"] = "%s"
f = urllib2.urlopen(req)
contentRange = f.headers.get("Content-Range").split("/")
length = int(contentRange[1])
reqSize = %s 
if reqSize == 0:
    reqSize = length
startReq = 0
dest = "%s"
file = open(dest,"w")
while startReq < length:
    if reqSize > length - startReq:
        reqSize = length -startReq
    req.headers["Range"] = %s
    f = urllib2.urlopen(req)
    downloadedLength = 0
    while True:
        buf = f.read(VHD_BLOCK_SIZE)
        if buf:
            file.write(buf)
            downloadedLength += len(buf)
        else:
            break
    startReq += reqSize + 1
        """ % (record['url_path'],http,record['ip'],str(record['port']),auth,reqSize,dest,range)
        try:
            host.execdom0("echo '%s' >/tmp/tmp/script.py" % script)
            python = host.execdom0('which python').strip() 
            host.execdom0("%s /tmp/tmp/script.py" % python,timeout=5600)
        except:
            raise xenrt.XRTFailure("Exception occurred while trying to download VDI")

    def getEncodedBitmapFromFile(self,dest,host):

        vdiMb = self.getPhysicalSize(dest,host)
        blocks = self.getAllocatedBlocks(dest,vdiMb*MB,host)
        bitmapFromFile = self.convertToBitmap(blocks,vdiMb * MB)
        actualBitmap = base64.b64encode(zlib.compress(bitmapFromFile))
        return actualBitmap

    def matchingBitmap(self,dest,bitmap,host):

        actualBitmap = self.getEncodedBitmapFromFile(dest,host) 
        if actualBitmap <> bitmap:
            raise xenrt.XRTFailure("Bitmap from the downloaded file is not same as that of the source file")
      
    def getPhysicalSize(self,filename,host):
  
        try:
            data = host.execdom0("%s query -S -n %s" % (VHD_UTIL, filename)) 
        except:
            raise xenrt.XRTFailure("Unable to read Physical vhd size")

        return int(data)

    def getVirtualSize(self,filename,host):

        try:
            data = host.execdom0("%s query -s -n %s" % (VHD_UTIL, filename))
        except:
            raise xenrt.XRTFailure("Unable to read virtual vhd size")

        return int(data)

    def getAllocatedBlocks(self,filename,vdiMb,host):

        numBlocks = vdiMb / VHD_BLOCK_SIZE
        script = u"""
import subprocess,re
VHD_UTIL = "vhd-util"
allocated = []
numBlocks = int(%s)
for block in range(numBlocks):
    process = subprocess.Popen([VHD_UTIL, "read", "-b",str(block),"-n","%s"],
              stdout=subprocess.PIPE)
    stdout,_ = process.communicate()
    if process.returncode == 0:
        if (not re.search("not allocated",stdout)) and re.search("offset",stdout):
            allocated.append(block)
        else:
            pass
print allocated

        """ % (numBlocks,filename)

        try:
            host.execdom0("echo '%s' >/tmp/tmp/scriptAllocated.py" % script)
            python = host.execdom0('which python').strip()
            data = host.execdom0("%s /tmp/tmp/scriptAllocated.py" % python,timeout=1080)
        except:
            raise xenrt.XRTFailure("Unable to get the allocated blocks")
        data = data.replace("[","")
        data = data.replace("]","")
        data = data.replace(" ","")
        allocated = []
        i = 0 
        while 1:
            try:
                allocated.append(int(data.split(",")[i]))
            except:
                break
            i = i + 1
        return allocated

    def convertToBitmap(self,blocks,size):

        BIT_MASK = 0x80
        numBlocks = size/VHD_BLOCK_SIZE
        bitmapSize = numBlocks >> 3
        if (bitmapSize << 3) < numBlocks:
            bitmapSize += 1
        bitmapArr = []
        for i in range(numBlocks):
            if i % 8 == 0:
                bitmapArr.append(0)
            if i in blocks:
                bitmapArr[i >> 3] |= (BIT_MASK >> (i & 7))
        bitmap = ""
        for byte in bitmapArr:
            bitmap += chr(byte)
        return bitmap

    def checkDownloadedBitmaps(self,fileName,host):
 
        vdiMb = self.getPhysicalSize(fileName,host)
        blocks = self.getAllocatedBlocks(fileName,vdiMb*MB,host)
        nonFilledBitmaps = self.checkBitmaps(fileName,blocks,host)
        nonFilledBitmaps = nonFilledBitmaps.replace("[","")
        nonFilledBitmaps = nonFilledBitmaps.replace("]","")
        nonFilledBitmaps = nonFilledBitmaps.strip()
        if nonFilledBitmaps:
            raise xenrt.XRTFailure("bitmaps are corrupt for the blocks %s" % (nonFilledBitmaps))

    def checkBitmaps(self,fileName,blocks,host):

        script = u"""
import subprocess,re
VHD_UTIL = "vhd-util"

def checkIfBitmapFull(bitmap):

    fullBitmap = "\\xff" * 512
    return bitmap == fullBitmap

def getBitmap(block):
    process = subprocess.Popen([VHD_UTIL, "read", "-m",str(block), "-n","%s"],stdout=subprocess.PIPE)
    stdout, _ = process.communicate()

    if process.returncode == 0:
        x = re.compile("block*")
        if not re.match(x, stdout):
            return stdout
        else:
            return None

nonFilledBitmaps = []
blocks = %s
for block in blocks:
    bitmap = getBitmap(block)
    if not checkIfBitmapFull(bitmap):
        nonFilledBitmaps.append(block)

print nonFilledBitmaps

        """ % (fileName,blocks)
        try:
            host.execdom0("echo '%s' >/tmp/tmp/checkBitmaps.py" % script)
            python = host.execdom0('which python').strip()
            data = host.execdom0("%s /tmp/tmp/checkBitmaps.py" % python,timeout=1800)
        except:
            raise xenrt.XRTFailure("Unable to get the bitmap")
 
        return data

    def checkIfBitmapFull(self,bitmap):

        fullBitmap = "\xff" * 512
        return bitmap == fullBitmap

    def checkVhdFile(self,fileName,host):

        data = host.execdom0("%s check -n %s" % (VHD_UTIL,str(fileName))) 
        if "invalid" in data:
            raise xenrt.XRTFailure("Invalid vhd file %s" % (fileName))

    def fragmentEnd(self,start,total):

        end = start + (2 << 20)
        if end > total:
            end = total
        return end

    def uploadBitsVhd(self,record,fileName,host):
   
        auth = authHeader(record['username'],record['password'])
        content = '"bytes %d-%d/%d" % (rangeStart, rangeAbove - 1, total)'
        if self.USESSL:
            useSSL = "True"
        else:
            useSSL = "False"

        script = u"""
import httplib
import base64,os
BITS_PROTOCOL = "{7df0354d-249b-430f-820D-3D2A9BEF4931}"

def bitsConnection(packetType,sessionId=None,vhd=False,headers=None,data=None,connection=None,expectedStatus=200,vdiRaw=False,connClose=False,reqheaders=None):

    ip = "%s"
    port = "%s"
    username = "%s"
    passwd = "%s"
    url = "%s"
    useSSL = %s 
    if not connection:
        if not useSSL:
            conn = httplib.HTTPConnection(ip,int(port))
        else:
            conn = httplib.HTTPSConnection(ip,int(port))
    else:
        conn = connection

    if not reqheaders:
        reqheaders = {"Authorization": "%s"}
    reqheaders["BITS-Packet-Type"] = packetType
    reqheaders["BITS-Supported-Protocols"] = BITS_PROTOCOL

    if sessionId is not None:
        reqheaders["BITS-Session-Id"] = sessionId

    if headers:
        for ele1, ele2 in headers.iteritems():
            reqheaders[ele1] = ele2

    try:
        if vhd:
            urlPath = url + ".vhd"
        else:
            urlPath = url
        conn.request("BITS_POST", urlPath,data,reqheaders)
        resp = conn.getresponse()
        respheaders = dict((ele1.lower(),ele2) for (ele1,ele2) in resp.getheaders())
        resp.read()
    finally:
        if not connClose:
            conn.close()
    if expectedStatus <> resp.status:
        raise ("Status is not same as expected ")

    return respheaders,conn,reqheaders

def fragmentEnd(start,total):

    end = start + (2 << 20)
    if end > total:
        end = total
    return end

def contentRangeHeader(rangeStart, rangeAbove, total):
    return %s
 
packetType = "Create-Session"
fileName = "%s"
respheaders,conn,reqheaders = bitsConnection(packetType=packetType,vhd=True,expectedStatus=200,connClose=True) 
       
packetType = "Fragment"
sessionId = respheaders["bits-session-id"]
rangeTotal = os.stat(fileName).st_size
rangeStart = 0
file = open(fileName,"r")
while rangeStart < rangeTotal:
    rangeEnd = fragmentEnd(rangeStart,rangeTotal)
    data = file.read(rangeEnd - rangeStart)
    reqheaders = {"Content-Range": contentRangeHeader(rangeStart,rangeEnd,rangeTotal),
                  "Content-Length": rangeEnd - rangeStart}
 
    dummy1, dummy2, dummy3 = bitsConnection(packetType=packetType,sessionId=sessionId,vhd=True,expectedStatus=200,connClose=True,connection=conn,reqheaders=reqheaders,data=data)
    rangeStart = rangeEnd     

conn.close()
file.close()
        """ % (record['ip'],record['port'],record['username'],record['password'],record['url_path'],useSSL,auth,content,fileName)
        try:
            host.execdom0("echo '%s' >/tmp/tmp/upload.py" % script)
            python = host.execdom0('which python').strip()
            data = host.execdom0("%s /tmp/tmp/upload.py" % python,timeout=5400)
        except:
            raise xenrt.XRTFailure("Upload failed")

class DownloadVHDs(VhdFunctions):

    REQSIZE = 0
    VDIUUID = None
    SIZE = None

    def run(self,arglist):

        if not self.VDIUUID:
            
            self.vdiuuid = self.createVdi(self.host,self.SIZE)
            self.writePatternToVDI(self.host,self.vdiuuid)
        else:
            self.vdiuuid = self.VDIUUID

        self.dest = "/tmp/tmp/%s" % (self.vdiuuid) + ".vhd"

        bitmapsXML = self.transferVMInst.getBitmaps(self.vdiuuid)
        self.srcBitmap = self.getVdiBitmaps(bitmapsXML,self.vdiuuid)     
        self.ref = self.transferVMInst.expose(self.vdiuuid,self.TRANSFERMODE,read_only=True,use_ssl=self.USESSL,vhd_blocks=self.srcBitmap,vhd_uuid=self.vdiuuid)

        record = self.transferVMInst.get_record(self.ref)

        self.bitsDownloadVHD(record,self.dest,self.REQSIZE,self.host,self.USESSL)
 
        self.matchingBitmap(self.dest,self.srcBitmap,self.host)

        self.checkDownloadedBitmaps(self.dest,self.host)

        self.checkVhdFile(self.dest,self.host)

        self.transferVMInst.unexpose(self.ref)

        self.srcmd5Sum = self.getmd5Sum(self.host,self.vdiuuid)
      
        if not self.VDIUUID:
            self.destroyVdi(self.host,self.vdiuuid)

    def postRun(self):

        try:
            self.transferVMInst.unexpose(self.ref)
        except:
            pass
 
        try:
            if not self.VDIUUID:
                self.destroyVdi(self.host,self.vdiuuid)
        except:
            pass
        try:
            self.host.execdom0("umount /tmp/tmp")
            masterlvm = ""
            if self.host.execdom0("ls /etc/lvm/master", retval="code") == 0:
                masterlvm = "LVM_SYSTEM_DIR=/etc/lvm/master "
            self.host.execdom0("%slvremove -f /dev/%s/%s" % (masterlvm, self.vgdisplay,self.lvName))
        except:
            xenrt.TEC().logverbose("Exception occurred while trying to remove logical volume") 

class TC14089(DownloadVHDs):
    """To verify the downloaded vhd file from small vdi when it is exposed over bits"""

    SIZE = 1 * 1024 * MB

class TC14090(DownloadVHDs):
    """To verify the downloaded vhd file from medium vdi when it is exposed over bits"""
 
    SIZE = 10 * 1024 * MB
    REQSIZE = "1073741824"

class TC14091(DownloadVHDs):
    """To verify the downloaded vhd file from large vdi when it is exposed over bits"""

    SIZE = 50 * 1024 * MB

class TC14092(TC14089):
    """To verify the downloaded vhd file from small vdi when it is exposed over bits over ssl"""

    USESSL = True    

class TC14093(TC14090):
    """To verify the downloaded vhd file from medium vdi when it is exposed over bits over ssl"""
 
    USESSL = True

class TC14094(TC14091):
    """To verify the downloaded vhd file from large vdi when it is exposed over bits over ssl"""

    USESSL = True

class UploadDownloadVHD(DownloadVHDs):

    def run(self,arglist):
 
        DownloadVHDs.run(self,[])
        vdiSize = self.getPhysicalSize(self.dest,self.host)
        self.destVdi = self.createVdi(self.host,vdiSize*MB)
        bitmap = self.getEncodedBitmapFromFile(self.dest,self.host) 

        self.ref = self.transferVMInst.expose(self.destVdi,self.TRANSFERMODE,read_only=False,use_ssl=self.USESSL,vhd_blocks=bitmap,vhd_uuid=self.destVdi)                

        record = self.transferVMInst.get_record(self.ref)
        self.uploadBitsVhd(record,self.dest,self.host)
        self.transferVMInst.unexpose(self.ref) 
#        bitmapsXML = self.transferVMInst.getBitmaps(self.destVdi)
#        destBitmap = self.getVdiBitmaps(bitmapsXML,self.destVdi)
#        if self.srcBitmap <> destBitmap:
#            raise xenrt.XRTFailure("Bitmap of source VDI is not same as that of destination VDI")       
        self.destmd5Sum = self.getmd5Sum(self.host,self.destVdi) 
        if self.srcmd5Sum <> self.destmd5Sum:
            raise xenrt.XRTFailure("md5 sum of source and destination VDIs are not same")
        self.destroyVdi(self.host,self.destVdi)
    def postRun(self):

        try:
            self.transferVMInst.unexpose(self.ref)
        except:
            pass
        try: 
            self.destroyVdi(self.host,self.destVdi)
        except:
            pass
 
        DownloadVHDs.postRun(self)

class TC14095(UploadDownloadVHD): 
    """To verify the uploaded vdi file from small vhd file when the vdi is exposed over bits """

    SIZE = 10 * 1024 * MB

class TC14096(UploadDownloadVHD):
    """To verify the uploaded vdi file from large vhd file when the vdi is exposed over bits """

    SIZE = 50 * 1024 * MB

class GuestUploadDownloadVHD(UploadDownloadVHD):

    LINUX = False

    def run(self,arglist):

        if self.LINUX:
            guest = self.host.createGenericLinuxGuest(name="test")
        if not self.LINUX:
            guest = self.host.createGenericWindowsGuest(name="test")
        self.uninstallOnCleanup(guest)
        if guest.getState() == "UP":
            guest.shutdown()
        cli = self.host.getCLIInstance()
        guest.snapshot() 
        vdiuuid= guest.getDiskVDIUUID("0")
        localSRuuid = self.host.minimalList("sr-list",args="name-label=Local\ storage")
        self.VDIUUID = cli.execute("vdi-copy uuid=%s sr-uuid=%s" %(vdiuuid,localSRuuid[0])).strip()
        UploadDownloadVHD.run(self,[])

class TC14097(GuestUploadDownloadVHD):
    """To verify the uploaded vdi file from large vhd file where the vhd file is downloaded from a vdi which is attached to a Linux VM """

    LINUX = True

class TC14102(GuestUploadDownloadVHD):
    """To verify the uploaded vdi file from large vhd file where the vhd file is downloaded from a vdi which is attached to a windows VM """

    LINUX = False

class TC14104(TC14095):
    """To verify the uploaded vdi file from small vhd file when the vdi is exposed over bits over ssl"""

    USESSL = True 

class TC14106(TC14096):
    """To verify the uploaded vdi file from large vhd file when the vdi is exposed over bits over ssl"""

    USESSL = True

class TC14108(TC14097):
    """To verify the uploaded vdi file from large vhd file where the vhd file is downloaded from a vdi(over ssl) which is attached to a Linux VM """
 
    USESSL = True

class TC14109(TC14102):
    """To verify the uploaded vdi file from large vhd file where the vhd file is downloaded from a vdi(over ssl) which is attached to a windows VM """

    USESSL = True

class SRGCTest(_TransferVM):

    VDI = None
    TRANSFERMODE = 'http'
    USESSL = False

    def prepare(self,arglist):

        self.host = self.getHost("RESOURCE_HOST_0")

        self.transferVMInst = self.getTransferVMInst(self.host)

    def isVdiKeyOnSR(self,host,vdiuuid): 

        srOtherConfig = host.minimalList("sr-list","other-config",args="name-label=Local\ storage")

        key = "tvm_%s" % vdiuuid
        keyCount = 0
        for pair in srOtherConfig:
            if pair.startswith(key):
                keyCount = keyCount +1

        if keyCount == 0:
            return False
        elif keyCount > 1:
            raise xenrt.XRTFailure("Multiple identical keys found for vdi %s" % vdiuuid)
        else:
            return True
         
    def checkGCStatus(self,host,sruuid):

        sm_script = "/opt/xensource/sm/cleanup.py"
        target_commands = "/opt/xensource/sm/cleanup.py -q -u %s" % sruuid

        data = host.execdom0(target_commands)
        rc = data.find("True")
        if (rc!= -1):
            return True
        else:
            return False

class TC14112(SRGCTest):
    """To verify that when VDI is exposed then GC script should not be running in Dom0 """

    def run(self,arglist):

        self.VDI = self.createVdi(self.host,VDI_MB*MB)
        self.transferVMInst = self.getTransferVMInst(self.host)
        self.ref = self.transferVMInst.expose(self.VDI,self.TRANSFERMODE,use_ssl=self.USESSL)
#        if not self.isVdiKeyOnSR(self.host,self.VDI):
#            raise xenrt.XRTFailure("SR other-config signal is not present for VDI_UUID %s" % self.VDI)
        sr = self.host.minimalList("sr-list",args="name-label=Local\ storage")
        gcStatus = self.checkGCStatus(self.host,sr[0])
        if gcStatus:
            raise xenrt.XRTFailure("The GC script in Dom0 is running when assumed it should not be")
        self.transferVMInst.unexpose(self.ref) 

    def postRun(self):

        try:
            self.transferVMInst.unexpose(self.ref)
        except:
            pass
        try:
            self.destroyVdi(self.host,self.VDI)
        except:
            pass

class HttpGetTest(_TransferVM):

    VDI = None
    TRANSFERMODE = 'http'
    USESSL = False
    SIZE = None
    RANGEBOUNDS = None
    RESPONSELENGTH = None

    def prepare(self,arglist):

        self.host = self.getHost("RESOURCE_HOST_0")

        self.transferVMInst = self.getTransferVMInst(self.host)

    def run(self,arglist):
 
        self.VDI = self.createVdi(self.host,self.SIZE)                  
        self.ref = self.transferVMInst.expose(self.VDI,self.TRANSFERMODE,use_ssl=self.USESSL)
        record =  self.transferVMInst.get_record(self.ref)
        if self.USESSL:
            conn = self.httpsConnection(record) 
        else:
            conn = self.httpConnection(record)
        headers = self.getHeaders(record,self.RANGEBOUNDS)
        resp = self.httpGET(record,conn,headers)
        respHeaders = dict(resp.getheaders())
        data= resp.read()

        if self.RANGEBOUNDS is None:
            if resp.status <> httplib.OK:
                raise xenrt.XRTFailure("Status is %d which is not same as expected %d" % (int(resp.status),int(httplib.OK)))
        else:
            if resp.status <> httplib.PARTIAL_CONTENT:
                raise xenrt.XRTFailure("Status is %d which is not same as expected %d" % (int(resp.status),int(httplib.PARTIAL_CONTENT)))
            if not 'content-range' in map(str.lower, respHeaders.iterkeys()):
                raise xenrt.XRTFailure("content-range not found in respHeaders")
        if self.RESPONSELENGTH <> len(data):
            raise xenrt.XRTFailure("Response Length is not equal to expected length")
        expectedData = '\0' * self.RESPONSELENGTH
        if expectedData <> data:
            raise xenrt.XRTFailure("Data is not equal to expected data")
        self.transferVMInst.unexpose(self.ref)
        self.destroyVdi(self.host,self.VDI) 
        conn.close()

    def postRun(self):

        try:
            self.transferVMInst.unexpose(self.ref)
        except:
            pass
        try:
            self.destroyVdi(self.host,self.VDI)
        except:
            pass

class TC14124(HttpGetTest):
    """To verify the data fetched from vdi exposed over http"""

    SIZE = 10*MB
    RESPONSELENGTH = 10*MB

class TC14125(HttpGetTest):
    """To verify 1 MB of data fetched with in given range from vdi exposed over http"""

    SIZE = 6000*MB
    RESPONSELENGTH = 1*MB
    RANGEBOUNDS = (5678*MB,5679*MB)

class TC14126(TC14124):
    """To verify the data fetched from vdi exposed over http over ssl"""

    USESSL = True

class TC14127(TC14125):
    """To verify 1 MB of data fetched with in given range from vdi exposed over http over ssl"""

    USESSL = True

class HttpPutTest(_TransferVM):

    SIZE = None
    VDI = None
    TRANSFERMODE = 'http'
    USESSL = False
    DATASIZE = None
    OFFSET = None
    BORDERSIZE = None
    REEXPOSE = False
   
    def prepare(self,arglist):

        self.host = self.getHost("RESOURCE_HOST_0")

        self.transferVMInst = self.getTransferVMInst(self.host)

    def run(self,arglist):

        if (self.OFFSET + self.DATASIZE) > self.SIZE:
            raise xenrt.XRTFailure("Invalid offset is given")
        lowerBorderSize = min(self.OFFSET,self.BORDERSIZE)
        upperBorderSize = min(self.SIZE - self.OFFSET - self.DATASIZE,self.BORDERSIZE)

        data = 'abcdefgh'*(self.DATASIZE/8)
        expectedData = ('\0' *lowerBorderSize) + data + ('\0' * upperBorderSize)
   
        self.VDI = self.createVdi(self.host,self.SIZE)
        self.ref = self.transferVMInst.expose(self.VDI,self.TRANSFERMODE,use_ssl=self.USESSL)
        record =  self.transferVMInst.get_record(self.ref)
        if self.USESSL:
            conn = self.httpsConnection(record)
        else:
            conn = self.httpConnection(record)
        headers = self.getHeaders(record)
        resp = self.httpPUT(record,conn,headers,data,self.OFFSET,self.SIZE)
        resp.read()
        status = resp.status 

        if status <> 200:
            raise xenrt.XRTFailure("Status is %d which is not equal to 200" % (int(status)))
  
        conn.close()
 
        if self.REEXPOSE:
            self.transferVMInst.unexpose(self.ref)
            self.ref = self.transferVMInst.expose(self.VDI,self.TRANSFERMODE,use_ssl=self.USESSL)
            record =  self.transferVMInst.get_record(self.ref) 

        if self.USESSL:
            conn = self.httpsConnection(record)
        else:
            conn = self.httpConnection(record) 
        headers = self.getHeaders(record,(self.OFFSET - lowerBorderSize,self.OFFSET + self.DATASIZE + upperBorderSize))
        resp = self.httpGET(record,conn,headers)
        respHeaders = dict(resp.getheaders())
        data= resp.read()        
        if not(resp.status == 200 or resp.status == 206):
            raise xenrt.XRTFailure("GET status code is %d which is not success" % (int(resp.status)))
         
        if len(expectedData) <> len(data):
            raise xenrt.XRTFailure("Response Length is not equal to expected length")
        if expectedData <> data:
            raise xenrt.XRTFailure("Data is not equal to expected data")

        conn.close()

        self.transferVMInst.unexpose(self.ref)
        self.destroyVdi(self.host,self.VDI)

    def postRun(self):

        try:
            self.transferVMInst.unexpose(self.ref)
        except:
            pass
        try:
            self.destroyVdi(self.host,self.VDI)
        except:
            pass

class TC14128(HttpPutTest):
    """To verify the 16k data written on a vdi exposed over http with offset being close to 1 MB """

    SIZE = 10*MB
    DATASIZE = 16*KB
    OFFSET = 1*MB + 123*KB
    BORDERSIZE = 3*KB
    REEXPOSE = False

class TC14130(HttpPutTest): 
    """To verify the 8mb data written on a vdi exposed over http with offset being close to the vdi size"""

    SIZE = 50000*MB
    DATASIZE = 8*MB
    OFFSET = 50000 *MB - 8*MB
    BORDERSIZE = 3*KB
    REEXPOSE = True

class TC14131(TC14128):
    """To verify the 16k data written on a vdi exposed over http over ssl with offset being close to 1 MB """

    USESSL = True 

class TC14132(TC14130):
    """To verify the 8mb data written on a vdi exposed over http over ssl with offset being close to the vdi size"""

    USESSL = True

class HugeVdi(_TransferVM):

    TRANSFERMODE = 'http'
    USESSL = False
    SIZE = None

    def prepare(self,arglist):

        self.host = self.getHost("RESOURCE_HOST_0")

        self.transferVMInst = self.getTransferVMInst(self.host)
   
    def run(self,arglist):

        self.vdi = self.createVdi(self.host,self.SIZE)
        self.ref = self.transferVMInst.expose(self.vdi,self.TRANSFERMODE,use_ssl=self.USESSL)
        record =  self.transferVMInst.get_record(self.ref)
        numBlocks = self.SIZE / (VHD_BLOCK_SIZE * 8)
         
        conn = self.getConn(record,self.USESSL)
        data = 'abcdefgh' *(VHD_BLOCK_SIZE/8) *8
        for i in xrange(1,numBlocks):
            headers = self.getHeaders(record)
            resp = self.httpPUT(record,conn,headers,data,(i-1)*VHD_BLOCK_SIZE *8 ,self.SIZE)
            resp.read()
            status = resp.status
            if self.USESSL:
                conn.close()
                conn = self.getConn(record,self.USESSL)
            if status <> 200:
                raise xenrt.XRTFailure("Return status is %d which is not equal to 200" % (int(status)))
        conn.close()
        self.transferVMInst.unexpose(self.ref)

        self.ref = self.transferVMInst.expose(self.vdi,self.TRANSFERMODE,use_ssl=self.USESSL)
        record =  self.transferVMInst.get_record(self.ref)
        conn = self.getConn(record,self.USESSL)
        for i in xrange(1,numBlocks):
            headers = self.getHeaders(record,((i-1)*VHD_BLOCK_SIZE *8,((i-1)*VHD_BLOCK_SIZE*8) + VHD_BLOCK_SIZE*8))
            resp = self.httpGET(record,conn,headers)
            respHeaders = dict(resp.getheaders())
            returnData= resp.read()
            if self.USESSL:
                conn.close()
                conn = self.getConn(record,self.USESSL)
            if not(resp.status == 200 or resp.status == 206):
                raise xenrt.XRTFailure("GET status code is %d which is not success" % (int(resp.status)))

            if len(returnData) <> len(data):
                raise xenrt.XRTFailure("Response Length is not equal to expected length")
            if returnData <> data:
                raise xenrt.XRTFailure("Data is not equal to expected data")

        conn.close()
        self.transferVMInst.unexpose(self.ref)
        self.destroyVdi(self.host,self.vdi)
        
    def getConn(self,record,ssl):
 
        if ssl:
            conn = self.httpsConnection(record)
        else:
            conn = self.httpConnection(record)
 
        return conn
 
    def postRun(self):

        try:
            self.transferVMInst.unexpose(self.ref)
        except:
            pass
        try:
            self.destroyVdi(self.host,self.vdi)
        except:
            pass

class TC14133(HugeVdi):
    """To verify the Download and upload of 1 GB of VDI exposed over http """

    SIZE = 1 * 1024 * MB

class TC14134(HugeVdi):
    """To verify the Download and upload of 50 GB of VDI exposed over http """ 

    SIZE = 50 * 1024 * MB

class TC14135(HugeVdi):
    """To verify the Download and upload of 100 GB of VDI exposed over http """

    SIZE = 100 * 1024 * MB

class TC14136(TC14133):
    """To verify the Download and upload of 1 GB of VDI exposed over http over ssl"""

    USESSL = True

class TC14137(TC14134):
    """To verify the Download and upload of 50 GB of VDI exposed over http over ssl"""

    USESSL = True

class TC14138(TC14135):
    """To verify the Download and upload of 100 GB of VDI exposed over http over ssl"""

    USESSL = True

class TC14139(_TransferVM): 
    """To verify the http put request onto a vdi with various invalid parameters """

    VDI = None
    TRANSFERMODE = 'http'
    USESSL = False

    def prepare(self,arglist):

        self.host = self.getHost("RESOURCE_HOST_0")
        self.transferVMInst = self.getTransferVMInst(self.host)

    def run(self,arglist):

        self.httpPutReq(10,'bqqqs 0-1/10485760',400)
        self.httpPutReq(10,'bytes 01/10485760',400)
        self.httpPutReq(10,'bytes *-1/10485760',501)
        self.httpPutReq(10,'bytes 0-*/10485760',501)
        self.httpPutReq(10,'bytes 0-1/*',501)
        self.httpPutReq(10,'bytes 0-1/1000000000000000',400)
        self.httpPutReq(10,'bytes 0-10000000000000000/10485760',400)
        self.httpPutReq(10,'bytes 1000-1/10485760',400) 

    def httpPutReq(self,dataSize,rangeStr,responseStatus): 

        size = 100*MB
        self.VDI = self.createVdi(self.host,size)
        self.ref = self.transferVMInst.expose(self.VDI,self.TRANSFERMODE,use_ssl=self.USESSL)
        record = self.transferVMInst.get_record(self.ref)
        headers = self.getHeaders(record)
        if self.USESSL:
            conn = self.httpsConnection(record)
        else:
            conn = self.httpConnection(record)
        data = 'a' * dataSize
        resp = self.httpFailurePUT(record,conn,headers,data,rangeStr)
        if resp.status <> responseStatus:
            raise xenrt.XRTFailure("Response status is %d which is not equal to %d " % (int(resp.status,responseStatus)))
        self.transferVMInst.unexpose(self.ref) 
        self.destroyVdi(self.host,self.VDI)

    def httpFailurePUT(self,record,conn,headers,data,rangeStr):

        headers['Content-Range'] = rangeStr 
        conn.request('PUT',record['url_path'],data,headers)
        resp = conn.getresponse()
        return resp

    def postRun(self):

        try:
            self.transferVMInst.unexpose(self.ref)
        except:
            pass
        try:
            self.destroyVdi(self.host,self.VDI)
        except:
            pass

class TC14140(TC14139):
    """To verify the http put request over ssl onto a vdi with various invalid parameters """
  
    USESSL = True

class IscsiTest(VhdFunctions):

    SIZE = None
 
    def prepare(self,arglist):
 
        self.host = self.getHost("RESOURCE_HOST_0")
        self.transferVMInst = self.getTransferVMInst(self.host)
        self.VDI = self.createVdi(self.host,self.SIZE)
        self.cli = self.host.getCLIInstance() 

    def run(self,arglist):

        step("Expose the VDI on Local SR as iscsi target")
        self.ref = self.exposeOverIscsi(self.host,self.VDI,"iscsi")
        record = self.getRecordOverIscsi(self.host,self.ref)
        scsiId = self.getscsiId(record)
        step("Attaching the created iSCSI SR to the host")
        self.sruuid = self.createISCSISR(self.host,record,scsiId)
        xenrt.sleep(5) 
        physicalSize = self.cli.execute("sr-param-get uuid=%s param-name=physical-size" % (self.sruuid))
        physicalUtil = self.cli.execute("sr-param-get uuid=%s param-name=physical-utilisation" % (self.sruuid)).strip()
        self.pbd = self.cli.execute("sr-param-get uuid=%s param-name=PBDs" % (self.sruuid))
        srSize = int(physicalSize) - int(physicalUtil)
        if srSize <= 0:
            raise xenrt.XRTFailure("Invalid physical size and physical Utilisation")
        step("Create a VDI on the iSCSI SR")
        self.sampleVdi,srSize = self.createVDIonISCSISR(self.sruuid,srSize)
        self.host.execdom0("lvchange -ay /dev/VG_XenStorage-%s/VHD-%s" % (self.sruuid,self.sampleVdi))
        filename = "/dev/VG_XenStorage-%s/VHD-%s" % (self.sruuid,self.sampleVdi)
        data = self.host.execdom0("%s check -n %s" % (VHD_UTIL,filename))
        if "invalid" in data:
            raise xenrt.XRTFailure("Invalid vdi with uuid %s" % (self.sampleVdi)) 
     
        try:
            self.host.execdom0("mkdir /tmp/tmp")
        except:
            pass
        allocated = self.getAllocatedBlocks(filename,srSize,self.host)
        if allocated:
            raise xenrt.XRTFailure("VDI is newly created but some of the blocks are allocated, seems like vdi is corrupted")  

        step("Write a deterministic pattern on the vdi via patterns.py script")
        self.writePatternToVDI(self.host,self.sampleVdi)

        step("Copy the VDI from iSCSI SR to Local SR")
        localSRuuid = self.host.minimalList("sr-list",args="name-label=Local\ storage")
        if self.SIZE == 100 * 1024 * MB:
            self.destVDI = self.cli.execute("vdi-copy uuid=%s sr-uuid=%s" %(self.sampleVdi,localSRuuid[0]),timeout=3800).strip()
        else:
            self.destVDI = self.cli.execute("vdi-copy uuid=%s sr-uuid=%s" %(self.sampleVdi,localSRuuid[0])).strip()

        xenrt.sleep(5)
        step("Check the pattern on the vdi via patterns.py script")
        ret = self.checkPatternOnVDI(self.host,self.destVDI)
        if ret == None:
            log("There are no issues in the copied vdi")
        else:
            raise xenrt.XRTFailure("Their is an inconsistency while checking pattern, script result is %s" % ret)

        step("Copy the VDI from Local SR to iSCSI SR")
        self.destroyVdi(self.host,self.sampleVdi)
        xenrt.sleep(10)
        if self.SIZE == 100 * 1024 * MB:
            self.sampleVdi = self.cli.execute("vdi-copy uuid=%s sr-uuid=%s" %(self.destVDI,self.sruuid),timeout=3800).strip()
        else:
            self.sampleVdi = self.cli.execute("vdi-copy uuid=%s sr-uuid=%s" %(self.destVDI,self.sruuid)).strip()
        ret = self.checkPatternOnVDI(self.host,self.sampleVdi)
        if ret == None:
            log("There are no issues in the copied vdi")
        else:
            raise xenrt.XRTFailure("Their is an inconsistency while checking pattern, script result is %s" % ret)

        self.destroyVdi(self.host,self.destVDI)
        self.destroyVdi(self.host,self.sampleVdi)
        self.cli.execute("pbd-unplug","uuid=%s" % (self.pbd))
        self.cli.execute("sr-forget","uuid=%s" % (self.sruuid))
        self.unexposeOverIscsi(self.host,self.ref)
        self.destroyVdi(self.host,self.VDI)
 
    def startStunnel(self,record,host):

        tmpDir = xenrt.TEC().tempDir()       
        filename = "%s/tvmiscsi.conf" % (tmpDir)
        if isinstance(self.host, xenrt.lib.xenserver.DundeeHost):
            config = u"""
fips = no
sslVersion = TLSv1.2

[localhost-stunnel]
accept = 127.0.0.1:%d
connect = %s:%d
client = yes
""" % (int(record['port']),str(record['ip']),int(record['port']))
        else:
            config = u"""
[localhost-stunnel]
accept = 127.0.0.1:%d
connect = %s:%d
client = yes
""" % (int(record['port']),str(record['ip']),int(record['port']))
        file(filename,"w").write(config)
        sftp = host.sftpClient()
        try:
            sftp.copyTo(filename,"/tmp/tvmiscsi.conf")
        finally:
            sftp.close()
        self.host.execdom0("stunnel /tmp/tvmiscsi.conf")

    def createVDIonISCSISR(self,sruuid,srSize):

        args = []
        args.append("sr-uuid=%s" % (sruuid))
        args.append("type='user'")
        args.append("name-label=iscsi")
        args.append("virtual-size=%d" % (srSize))
        while 1:
            try:
                vdi = self.cli.execute("vdi-create",string.join(args),strip=True)
                break
            except:
                srSize = srSize - VHD_BLOCK_SIZE
                args[3] = "virtual-size=%d" % (srSize)

        return vdi,srSize

    def createISCSISR(self,host,record,scsiId):

        hostuuid = host.getMyHostUUID()
        args = []
        args.append("name-label=iscsiSR")
        args.append("host-uuid=%s" % (hostuuid))        
        args.append("content-type=user")
        args.append("shared=true")
        args.append("type=lvmoiscsi")
        args.append("device-config:target=%s" % (record['ip']))
        args.append("device-config:targetIQN=%s" % (record['iscsi_iqn'])) 
        args.append("device-config:SCSIid=%s" % scsiId)
        args.append("device-config:chapuser=%s" % (record['username']))
        args.append("device-config:chappassword=%s" %(record['password']))
        sr = self.cli.execute("sr-create", string.join(args), strip=True)
        return sr

    def getscsiId(self,record):    

        args = []
        args.append("type='lvmoiscsi'")
        args.append("device-config:target=%s" % (record['ip']))
        args.append("device-config:targetIQN=%s" % (record['iscsi_iqn']))
        args.append("device-config:chapuser=%s" % (record['username']))
        args.append("device-config:chappassword=%s" % (record['password']))
  
        #sr-probe always return with an exception
        try:
            tempStr = self.cli.execute("sr-probe",string.join(args))
        except Exception, e:
            tempStr = str(e.data)
            tempStr = '\n'.join(tempStr.split('\n')[2:])

        temp = parseString(tempStr)
        ids = temp.getElementsByTagName('SCSIid')
        for id in ids:
            for node in id.childNodes:
                scsiId = (node.nodeValue).strip()
        return scsiId

    def postRun(self):

        try:
            self.destroyVdi(self.host,self.sampleVdi)
        except:
            pass
        try:
            self.cli.execute("pbd-unplug","uuid=%s" % (self.pbd))
        except:
            pass
        try:
            self.cli.execute("sr-forget","uuid=%s" % (self.sruuid))
        except:
            pass
        try:
            self.unexposeOverIscsi(self.host,self.ref)
        except:
            pass
        try:
            self.destroyVdi(self.host,self.VDI)
        except:
            pass

class TC14144(IscsiTest):
    """To verify the behaviour of transfer vm when the vdi of size 1 GB it is exposing is used as the iscsi target"""

    SIZE = 1 * 1024 * MB

class TC14146(IscsiTest):
    """To verify the behaviour of transfer vm when the vdi of size 50 GB it is exposing is used as the iscsi target"""

    SIZE = 50 * 1024 * MB

class TC14147(IscsiTest):
    """To verify the behaviour of transfer vm when the vdi of size 100 GB it is exposing is used as the iscsi target"""

    SIZE = 100 * 1024 * MB

class TC14149(IscsiTest):
    """To verify the behaviour of transfer vm when the vdi of size 500 GB it is exposing over ssl using stunnel is used as the iscsi target"""

    SIZE = 500*MB

    def run(self,arglist):

        self.ref = self.exposeOverIscsi(self.host,self.VDI,"iscsi",useSSL=True)
        record = self.getRecordOverIscsi(self.host,self.ref)
        self.startStunnel(record,self.host)
        try:
            self.host.execdom0("xe sr-probe host-uuid=%s type=lvmoiscsi device-config:target=127.0.0.1 device-config:port=%s" % (self.host.getMyHostUUID(),record['port']))
        except:
            pass
        discovery = self.host.execdom0("iscsiadm -m discovery -t st -p 127.0.0.1:%s" % (str(record['port']))).strip()
        portal = discovery.split(",")[0].strip()
        iqn = discovery.split(" ")[1].strip()
        ipAddr = portal.split(":")[0].strip()
        port = portal.split(":")[1].strip()
   
        if iqn <> str(record['iscsi_iqn']):
            raise xenrt.XRTFailure("IQN received from ISCSI target through secure channel is not same as fetched directly from ISCSI target")
        if ipAddr <> str(record['ip']):
            raise xenrt.XRTFailure("ISCSI IP received from ISCSI target through secure channel is not same as fetched directly from ISCSI target")
        if port <> str(record['port']):
            raise xenrt.XRTFailure("ISCSI PORT received from ISCSI target through secure channel is not same as fetched directly from ISCSI target")
 
        self.unexposeOverIscsi(self.host,self.ref)
        self.destroyVdi(self.host,self.VDI)

    def postRun(self):    
 
        try:
            self.unexposeOverIscsi(self.host,self.ref)
        except:
            pass
        try:
            self.destroyVdi(self.host,self.VDI)
        except:
            pass
