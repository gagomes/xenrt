from xml.dom.minidom import parseString
import random, string, base64, re, os, os.path, sys, hashlib, traceback
import xenrt, xenrt.lib.xenserver
from M2Crypto import BIO, RSA, EVP
from struct import pack
from math import ceil
from hashlib import sha1
from Crypto.Util.strxor import strxor
from Crypto.Util.number import long_to_bytes
from  xenrt.lazylog import log, step


__all__ = ["TXTCommand", "AttestationIdParser", "TpmQuoteParser", "TXTSuppPackInstaller", "TXTErrorParser"]


class TXTSuppPackInstaller(object):

    __PASSWORD = "xenroot"
    __CONFIG_FILE = "/opt/xensource/tpm/config"

    def install(self, hosts):
        """
        Install Intel txt supp pack onto a hosts

        @type hosts: list
        @param hosts: list of hosts onto which the spupp pack should be installed
        """
        suppPackIso = xenrt.TEC().getFile(xenrt.TEC().lookup("TXT_SUPP_PACK"))

        try:
            for h in hosts:
                self.__installSuppPack(h, suppPackIso)
        except Exception, e:
            xenrt.TEC().logverbose(str(e))
            xenrt.TEC().logverbose("Failure installing TXT supp pack")
            raise

    def __modifyPassword(self, host):
        pw = self.__hashPassword()
        host.execdom0("echo password=%s > %s" % (pw, self.__CONFIG_FILE))

    def __hashPassword(self):
        """Create a sha1 hash of the default password"""
        hasher = hashlib.sha1()
        hasher.update(self.__PASSWORD)
        return hasher.hexdigest()

    def __installSuppPack(self, host, suppPackIso):
        packName = os.path.basename(suppPackIso)
        sftp = host.sftpClient()
        sftp.copyTo(suppPackIso, os.path.join('/tmp', packName))
        sftp.close()
        host.execdom0("xe-install-supplemental-pack /tmp/%s" % packName)
        host.execdom0("sync")
        self.__modifyPassword(host)
        host.reboot()


class TXTCommand(object):
    __PLUGIN_NAME = "tpm"
    __ATT_ID_KEY = "tpm_get_attestation_identity"
    __QUOTE_KEY = "tpm_get_quote"
    __CHALLENGE_KEY = "tpm_challenge"
    __NONCE_KEY = "nonce"
    __CHALLENGE_ARG_KEY = "challenge"
    __ASSET_TAG_SET_KEY = "tpm_set_asset_tag"
    __ASSET_TAG_SET_ARG_KEY = "tag"
    __ASSET_TAG_CLEAR_KEY = "tpm_clear_asset_tag"
    __DEBUG = False

    def getAttestationId(self, hostRef, session):
        """
        Get the attestation id of a host from the TPM

        @type hostRef: string
        @param hostRef: the opaque ref of the host
        @type session: session
        @param session: the session containing the host
        @rtype: string
        @return: xml containing the 4 parts of the attetsation id
        """
        return self.__runCommand(hostRef, session, self.__ATT_ID_KEY, {})

    def getQuote(self, hostRef, session, nonceValue):
        """
        Get the quotes of a host from the TPM

        @type hostRef : string
        @param hostRef: the opaque ref of the host
        @type session: session
        @param session: the session containing the host
        @type nonceValue: string
        @param nonceValue: a random string value to seed the quote - should really be unique per-call
        @rtype: string
        @return: base64 encoded value containing a (uint16)mask size, (byte*)a bit mask, (uint32)a quote size, (byte*) a collection of 20 byte PCR values and 256 byte signature
        """
        return self.__runCommand(hostRef, session, self.__QUOTE_KEY, {self.__NONCE_KEY : nonceValue})

    def getChallenge(self, hostRef, session, challengeValue):
        """
        Provide the TPM with an encrypted challenge

        @type hostRef: string
        @param hostRef: the opaque ref of the host
        @type session: session
        @param session: the session containing the host
        @type challengeValue: string
        @param challengeValue: a challenge for the TPM to decrypt
        @rtype: string
        @return: the decrypted challenge
        """
        bChallenge = base64.b64encode(challengeValue)
        commandOutout = self.__runCommand(hostRef, session, self.__CHALLENGE_KEY, {self.__CHALLENGE_ARG_KEY : bChallenge})
        return base64.b64decode(commandOutout)

    def setAssetTag(self, hostRef, session, assetTag):
        """
        Set the Asset Tag

        @type hostRef: string
        @param hostRef: the opaque ref of the host
        @type session: session
        @param session: the session containing the host
        @type assetTag: sha1 hash
        @param assetTag: base64 encoded asset tag
        @rtype: null
        @return: null
        """
        bAssetTag = base64.b64encode(assetTag)
        self.__runCommand(hostRef, session, self.__ASSET_TAG_SET_KEY, {self.__ASSET_TAG_SET_ARG_KEY : bAssetTag})

    def clearAssetTag(self, hostRef, session):
        """
        Clear the Asset Tag

        @type hostRef: string
        @param hostRef: the opaque ref of the host
        @type session: session
        @param session: the session containing the host
        @rtype: null
        @return: null
        """
        self.__runCommand(hostRef, session, self.__ASSET_TAG_CLEAR_KEY, {})

    def __runCommand(self, hostRef, session, command, args):
        try:
            self.__logDebug("HostRef: " + hostRef, "Plugin: " + self.__PLUGIN_NAME, "Command: " + command, "Args: " + str(args))
            output = session.xenapi.host.call_plugin(hostRef, self.__PLUGIN_NAME, command, args)
            return output
        except:
            traceback.print_exc(file=sys.stderr)
            exc_type, exc_value, exc_traceback = sys.exc_info()

            xenrt.TEC().logverbose("HostRef: %s, Plugin: %s, Command: %s Args: %s" % (hostRef, self.__PLUGIN_NAME, command, str(args)))
            hostName = session.xenapi.host.get_record(hostRef)['hostname']
            log("Host name %s" % hostName)
            hosts = xenrt.TEC().registry.hostFind(hostName)

            if len(hosts) < 1:
                xenrt.TEC().logverbose("Hostname not found")
                raise

            host = hosts[0]
            if host:
                xenrt.TEC().logverbose(host.execdom0("find /etc/xapi.d/plugins -name tpm"))
                xenrt.TEC().logverbose("Host is %s" % hostName)
                m = re.search('xentpm\[[0-9]*\]', str(exc_value))
                if m:
                    xenrt.TEC().logverbose(host.execdom0("grep -F '%s' /var/log/messages" % m.group(0)))

            errorMessage = self.__attemptLogParse(host)
            if errorMessage:
                raise xenrt.XRTFailure(errorMessage)
            raise

    def __attemptLogParse(self, host):
        parser = TXTErrorParser.fromHostFile(host, "/var/log/messages", "/var/log/kern.log", "/var/log/user.log")
        step("Parsing logs from host: %s" % host)
        self.__writeToNewLog("extractedTPMErrors.log", '\n'.join(parser.locateAllTpmData()))
        keyErrs = parser.locateKeyErrors()
        self.__writeToNewLog("keyTPMErrors.log", '\n'.join(keyErrs))
        if len(keyErrs) > 0:
            return TxtLogObfuscator(keyErrs).fuzz()[0]

    def __writeToNewLog(self, fileName, data):
        log("Writing relevant data into %s....." % fileName)
        file("%s/%s" % (xenrt.TEC().getLogdir(), fileName), "w").write(data)

    def __logDebug(self, *message):
        if self.__DEBUG:
            for m in message:
                xenrt.TEC().logverbose(m)


class TpmParser(object):
    def _getSHA1(self, data):
        sha1 = hashlib.sha1()
        sha1.update(data)
        return sha1.digest()

    @staticmethod
    def generateRandomNonce(size=20):
        """
        Static method to generate a random nonce used to generate a quote from the TPM
        @type size: int
        @param size: the size of the key to generate, default = 20
        @rtype string
        @return: base64 encoded random string
        """
        lst = [random.choice(string.ascii_letters + string.digits) for n in xrange(size)]
        nonce = "".join(lst)
        return base64.b64encode(nonce)


class AttestationIdParser(object):

    __TPM_CERT_KEY = "xentxt:TPM_Endorsement_Certficate"
    __EKPUB_KEY = "xentxt:TPM_Endorsement_KEY_PEM"
    __TCPA_KEY = "xentxt:TPM_Attestation_KEY_TCPA"
    __AIK_KEY = "xentxt:TPM_Attestation_KEY_PEM"
    __attestationData = None

    def __init__(self, data):
        """
        @type data: string
        @param data: the xml data from the attestation id TPM call
        """
        self.__attestationData = data

    def __parseDataForKey(self, key):
        try:
            dom = parseString(self.__attestationData)
            node = dom.getElementsByTagName(key)[0]
            return node.firstChild.nodeValue
        except:
            print "Error parsing the Result XML from XenServer"
            return ""

    def getAikPem(self):
        """
        @rtype: string
        @return: the Attestation Identity Key
        """
        return self.__parseDataForKey(self.__AIK_KEY)

    def getTpmCertificate(self):
        """
        @rtype: string
        @return: The Trusted Platform Modules certificate
        """
        return self.__parseDataForKey(self.__TPM_CERT_KEY)

    def getEndorsementKey(self):
        """
        @rtype: string
        @return: The endorsement public key, a 2048-bit RSA public key, private key is in the TPM chip
        """
        return self.__parseDataForKey(self.__EKPUB_KEY)

    def getTcpaKey(self):
        """
        @rtype: blob
        @return: The TCPA key
        """
        return base64.b64decode(self.__parseDataForKey(self.__TCPA_KEY))


class TpmQuoteParser(TpmParser):
    __PCR_QUOTE_SIZE   = 20
    __SHA1_DIGEST_SIZE = (hashlib.sha1()).digest_size
    __SHORT_SIZE       = 2
    __INT_SIZE         = 4
    __quoteStr         = None
    __xenPcrId         = 17
    __domZeroPcrId     = 18
    __initrdPcrId      = 19
    __assetTagPcrId    = 22

    def __init__(self, quoteStr):
        """
        @type quoteStr: string
        @param quoteStr: is the base64 encoded binary blob returned from the TPM as a quote
        """
        self.__quoteStr = base64.b64decode(quoteStr)

    def __readbufint(self, data, pos, size):
        val = 0
        for x in range (0, size):
            val = ( val << 8) | data[pos+x]
        return val

    def __calculatePcrs(self):
        data = bytearray((self.__quoteStr))
        pos = 0
        mask_size = self.__readbufint(data, pos, self.__SHORT_SIZE)
        pos = pos + self.__SHORT_SIZE
        pos = pos + mask_size
        pcrblocksize = self.__readbufint(data, pos, self.__INT_SIZE)
        numPcrs = pcrblocksize / self.__PCR_QUOTE_SIZE
        pos = pos + self.__INT_SIZE
        return numPcrs, data, pos

    def getCurrentQuoteValue(self):
        """
        @rtype: string
        @return: The base64 encoded quote value used to construct the class
        """
        return self.__quoteStr

    def getInitrdPcr(self):
        """
        @rtype: string
        @return: hex value of the PCR representing the hosts boot image
        """
        return self.getPcr(self.__initrdPcrId)

    def getXenPcr(self):
        """
        @rtype: string
        @return: hex value of the PCR representing the Xen hypervisor
        """
        return self.getPcr(self.__xenPcrId)

    def getDomZeroPcr(self):
        """
        @rtype: string
        @return: hex value of the PCR representing Dom0
        """
        return self.getPcr(self.__domZeroPcrId)

    def getAssetTagPcr(self):
        """
        @rtype: string
        @return: hex value of the PCR representing the Asset Tag
        """
        return self.getPcr(self.__assetTagPcrId)

    def getPcr(self, pcr):
        """
        Get a PCR value from the provided quote

        @type pcr: int
        @param pcr: the index of the pcr required
        @rtype: string
        @return: hex value of the n^th PCR
        """
        numPcrs, data, pos = self.__calculatePcrs()
        # BUGBUG check that pcr is not greater than numPCrs
        pos = pos + (self.__PCR_QUOTE_SIZE*pcr)
        return str(data[pos: pos + self.__PCR_QUOTE_SIZE]).encode('hex')

    def allPcrs(self):
        """
        @rtype: list
        @return: collection hex strings containing all PCR values
        """
        pcrs = []
        numPcrs, data, pos = self.__calculatePcrs()
        for x in range (0, numPcrs):
            pcrs.append(str(data[pos: pos + self.__PCR_QUOTE_SIZE]).encode('hex'))
            pos = pos + self.__PCR_QUOTE_SIZE

    def verifyQuote(self, aikPub, nonce):
        """
        The format of the quote file is as follows:
        - 2 bytes of PCR bitmask length (big-endian)
        - PCR bitmask (LSB of 1st byte is PCR0, MSB is PCR7; LSB of 2nd byte is PCR8, etc)
        - 4 bytes of PCR value length (20 times number of PCRs) (big-endian)
        - PCR values
        - 256 bytes of Quote signature

        @type aikPub: string
        @param aikPub: the AIK key of the TPM's attestation identity
        @type nonce: string
        @param nonce: the nonce value used for the quote
        @rtype: boolean
        @returns: verification was successful
        """
        xenrt.TEC().logverbose("Verifying TPM Quote")
        data = bytearray((self.__quoteStr))
        pos = 0
        # skip over the bitmask length and the bitmask itself
        mask_size = self.__readbufint(data, pos, self.__SHORT_SIZE)
        pos = pos + self.__SHORT_SIZE
        pos = pos + mask_size
        # skip over the PCRs
        pcrblocksize = self.__readbufint(data, pos, self.__INT_SIZE)
        pos = pos + self.__INT_SIZE
        numPcrs = pcrblocksize/self.__PCR_QUOTE_SIZE
        pos = pos + (self.__PCR_QUOTE_SIZE*numPcrs)

        # Get the TPM Quote signature
        tpmQuote_signature = data[pos:len(data)]

        # Fill in the TPM_QUOTE_INFO structure.  It contains:
        # TPM_STRUCT_VER version = 1.1.0.0
        # BYTE[4] signature = "QUOT"
        # TPM_COMPOSITE_HASH digestValue = SHA1 hash of the TPM_QUOTE structure
        # TPM_NONCE externalData = SHA1 hash of the nonce
        tpmQuoteInfo_version = bytearray([1,1,0,0])
        tpmQuoteInfo_signature = bytearray(['Q','U','O','T'])
        # pos points to the signature, so get the SHA1 hash of the TPM_QUOTE structure only (do not include the signature)
        tpmQuote_digest = self._getSHA1(str(data[0:pos]))

        nonce_digest = self._getSHA1(nonce)

        tpmQuoteInfo_size =  len(tpmQuoteInfo_version) + len(tpmQuoteInfo_signature) + len(tpmQuote_digest) + len(nonce_digest)
        tpmQuoteInfo = bytearray(([0]*tpmQuoteInfo_size))

        tpmQuoteInfo[0 : len(tpmQuoteInfo_version)] = tpmQuoteInfo_version
        tpmQuoteInfo[len(tpmQuoteInfo_version): len(tpmQuoteInfo_version) + len(tpmQuoteInfo_signature)] = tpmQuoteInfo_signature
        tpmQuoteInfo[len(tpmQuoteInfo_version) + len(tpmQuoteInfo_signature): len(tpmQuoteInfo_version) + len(tpmQuoteInfo_signature) + self.__SHA1_DIGEST_SIZE] = tpmQuote_digest
        tpmQuoteInfo[len(tpmQuoteInfo_version) + len(tpmQuoteInfo_signature) + self.__SHA1_DIGEST_SIZE : len(tpmQuoteInfo)] = nonce_digest

        # Use RSA verify to verify the TPM Quote
        bio = BIO.MemoryBuffer(aikPub.encode('ascii'))
        rsa = RSA.load_pub_key_bio(bio)
        pubkey = EVP.PKey()
        pubkey.assign_rsa(rsa)
        pubkey.reset_context(md='sha1')
        pubkey.verify_init()
        pubkey.verify_update(tpmQuoteInfo)
        return pubkey.verify_final(tpmQuote_signature) != 1


class TpmChallengeParser(TpmParser):
    """
    Class to deal with parsing a secret into an encrypted challenge for the TPM
    do decrypt
    """
    __TPM_ALG_AES             = 0x00000006
    __TPM_ES_SYM_CBC_PKCS5PAD    = 0x00ff
    __TPM_SS_NONE                = 0x0001
    __aikTcpa = None
    __ekPub = None

    def __init__(self, tcpaKey, endorsementKey):
        """
        @type tcpaKey: binary blob
        @param tcpaKey: the TCPA key from the attestation identity
        @type endorsementKey: string
        @param endorsementKey: the endorsement key from the attestation identity
        """
        self.__aikTcpa = tcpaKey
        self.__ekPub = endorsementKey

    def createChallenge(self, session, secret):
        """
        Create a challenge for the TPM to decrypt by encrypting the secret
        using the keys in this class

        @type session: session
        @param session: the session for the host
        @type secret: string
        @secret: a secret to encrypt using stoed keys
        @rtype: string containing the encrypted challenge
        @return: string
        """

        SHA1_DIGEST_SIZE = (hashlib.sha1()).digest_size
        key_size = 16
        key = str(os.urandom(key_size))
        iv  = str(os.urandom(key_size))
        # /* SYM_CA_Structure Encrypt with EK */
        # /*
        #  * Creating the AYSM_CA_CONTENT for encrypting the session key
        #  * typedef struct  TPM_ASYM_CA_CONTENTS
        #     {
        #         TPM_SYMMETRIC_KEY sessionKey; //
        #         TPM_DIGEST idDigest; //sha1 of aik
        #     } TPM_ASYM_CA_CONTENTS;
        #
        #   typedef struct tdTPM_SYMMETRIC_KEY
        #   {
        #         TPM_ALGORITHM_ID algId;
        #         TPM_ENC_SCHEME encScheme;
        #         UINT16 size;
        #        [size_is(size)] BYTE* data;
        #} TPM_SYMMETRIC_KEY;

        asymPlain = bytearray([0]*(8 + key_size + SHA1_DIGEST_SIZE))
        asymPlain[0:8] = pack("!ihh", self.__TPM_ALG_AES, self.__TPM_ES_SYM_CBC_PKCS5PAD, key_size)

        asymPlain[8:8+key_size] = key
        asymPlain[(8+key_size):(8+key_size+SHA1_DIGEST_SIZE)] = self._getSHA1(self.__aikTcpa)

        #Now encrypt the the above Asym_ca_content with tpm public ek
        bio = BIO.MemoryBuffer(self.__ekPub.encode('ascii'))
        pkrsa = RSA.load_pub_key_bio(bio)
        pkey = EVP.PKey()
        pkey.assign_rsa(pkrsa)
        asymPadSize = pkey.size();
        pscheme = OAEP(os.urandom)
        padAsym = pscheme.encode(asymPadSize, str(asymPlain), "TCPA")
        asymEnc = pkrsa.public_encrypt(padAsym, RSA.no_padding)
        challenge = secret

        cipher = EVP.Cipher('aes_128_cbc', key, iv, 1)
        symEnc = cipher.update(challenge)
        symEnc = symEnc + cipher.final()
        symEncLength = len(symEnc)
        symAttest = bytearray(28+ key_size + symEncLength)
        symAttest[0:28] = pack("!iihhiiii",symEncLength+ key_size,self.__TPM_ALG_AES,self.__TPM_ES_SYM_CBC_PKCS5PAD,self.__TPM_SS_NONE,(12),key_size*8,key_size,0)
        symAttest[28:28+key_size] = iv
        symAttest[28+key_size:28+key_size+symEncLength] = symEnc

        challenge = bytearray(4+len(asymEnc)+4+len(symEnc))
        challenge[0:4]= pack("!i",(len(asymEnc)));
        challenge[4:len(asymEnc)] = asymEnc
        challenge[4+len(asymEnc):8+len(asymEnc)] = (pack("!i",len(symAttest)))
        challenge[8+len(asymEnc):len(challenge)] = (symAttest)
        return "".join(map(chr, challenge))


class OAEP(object):
    """
    Class implementing OAEP encoding/decoding.

    This class can be used to encode/decode byte strings using the
    Optimal Asymmetic Encryption Padding Scheme.  It requires a source
    of random bytes, a hash function and a mask generation function.
    By default SHA-1 is used as the hash function, and MGF1-SHA1 is used
    as the mask generation function.

    The method 'encode' will encode a byte string using this padding
    scheme, and the complimentary method 'decode' will decode it.

    The algorithms are from PKCS#1 version 2.1, section 7.1
    """

    def __init__(self, randbytes, hashValue=sha1):
        self.__randbytes = randbytes
        self.__hash = hashValue

    def __generateMgf1(self, mgfSeed, maskLen, hashFn=sha1):
        """
        Mask Generation Function based on a hash function.
        The algorithm is from PKCS#1 version 2.1, appendix B.2.1.

        @type mgfSeed: byte string
        @param mgfSeed: input seed
        @type maskLen: int
        @param maskLen: length of the mask
        @type hashFn: function
        @param hashFn: A hashing function; default = SHA1
        @rtype byte string
        @return: a value approximating a Random Oracle
        """
        hLen = hashFn().digest_size
        if maskLen > 2**32 * hLen:
            raise ValueError("mask too long")
        T = ""
        for counter in range(int(ceil(maskLen / (hLen*1.0)))):
            C = long_to_bytes(counter)
            C = ('\x00'*(4 - len(C))) + C
            assert len(C) == 4, "counter was too big"
            T += hashFn(mgfSeed + C).digest()
        assert len(T) >= maskLen, "generated mask was too short"
        return T[:maskLen]

    def encode(self,k,M,L=""):
        """
        Encode a message using OAEP.

        @type M: byte string
        @param M: to encode using Optimal Asymmetric Encryption Padding
        @type k: int
        @param k: Size of the private key modulus in bytes
        @type L: string
        @param L: label for the encoding
        """
        # Calculate label hash, unless it is too long
        if L:
            limit = getattr(self.__hash,"input_limit",None)
            if limit and len(L) > limit:
                raise ValueError("label too long")
        lHash = self.__hash(L).digest()
        # Check length of message against size of key modulus
        mLen = len(M)
        hLen = len(lHash)
        if mLen > k - 2*hLen - 2:
            raise ValueError("message too long")
        # Perform the encoding
        PS = "\x00" * (k - mLen - 2*hLen - 2)
        DB = lHash + PS + "\x01" + M
        assert len(DB) == k - hLen - 1, "DB length is incorrect"
        seed = self.__randbytes(hLen)
        dbMask = self.__generateMgf1(seed,k - hLen - 1)
        maskedDB = strxor(DB,dbMask)
        seedMask = self.__generateMgf1(maskedDB,hLen)
        maskedSeed = strxor(seed,seedMask)
        return "\x00" + maskedSeed + maskedDB

    def decode(self, k, EM, L=""):
        """
        Decode a message using OAEP.

        @type EM: byte string
        @param EM: to decode using Optimal Asymmetric Encryption Padding
        @type k: int
        @param k: Size of the private key modulus in bytes
        @type L: string
        @param L: label for the decoding
        """
        # Generate label hash, for sanity checking
        lHash = self.__hash(L).digest()
        hLen = len(lHash)
        # Split the encoded message
        Y = EM[0]
        maskedSeed = EM[1:hLen+1]
        maskedDB = EM[hLen+1:]
        # Perform the decoding
        seedMask = self.__generateMgf1(maskedDB,hLen)
        seed = strxor(maskedSeed,seedMask)
        dbMask = self.__generateMgf1(seed,k - hLen - 1)
        DB = strxor(maskedDB,dbMask)
        # Split the DB string
        lHash1 = DB[:hLen]
        x01pos = hLen
        while x01pos < len(DB) and DB[x01pos] != "\x01":
            x01pos += 1
        #PS = DB[hLen:x01pos]
        M = DB[x01pos+1:]
        # All sanity-checking done at end, to avoid timing attacks
        valid = True
        if x01pos == len(DB):  # No \x01 byte
            valid = False
        if lHash1 != lHash:    # Mismatched label hash
            valid = False
        if Y != "\x00":        # Invalid leading byte
            valid = False
        if not valid:
            raise ValueError("Decryption error")
        return M


class TXTErrorParser(object):
    MARKERS = ["xentpm", "TCSD TDDL"]
    __WARNINGS = ["failed", "error", "expired"]

    def __init__(self, logFileAsList):
        """
        Needs the log file read in as an array
        use readlines or equivalent to achieve this
        """
        self.__log = logFileAsList

    @classmethod
    def fromHostFile(cls, host, *filename):
        """
        Alt. constructor. Read marker matches from the log
        on the host and then construct this class
        host: a host object
        filename: the file name on the host to parse
        """
        data = []
        for fname in filename:
            for m in cls.MARKERS:
                grep = "grep '%s' %s" % (m, fname)
                if host.execcmd(grep, retval="code") < 1:
                    data += host.execcmd(grep).split('\n')
                else:
                    log("grep failed for %s in file %s - no data found" % (m, fname))
        return cls(data)

    def __locateKeyLines(self, marker):
        return [l for l in self.__log if marker in l]

    def locateAllTpmData(self):
        """
        Scan the log file array for data matching key identifiers
        and filter them out
        """
        lines = []
        for marker in self.MARKERS:
            lines += self.__locateKeyLines(marker)
        return lines

    def __calculateWeight(self, line):
        return sum([line.lower().count(w) for w in self.__WARNINGS])

    def locateKeyErrors(self):
        """
        Weight lines found by filtering code and weight them with occurences of
        error words to find the most likely issue

        @return list of strings
        """
        weightedList = []
        for l in self.locateAllTpmData():
            weightedList.append((self.__calculateWeight(l),l))
        weightedList.sort()

        if len(weightedList) < 1:
            return weightedList

        maxweight = weightedList[-1][0]
        return [i[1] for i in weightedList if i[0] == maxweight]


class TxtLogObfuscator(object):

    def __init__(self, listOfLines):
        self.__log = listOfLines

    def fuzzTimes(self, data=None):
        # Match 11:43:34 i.e. a timestamp
        regex = re.compile("[0-9]{2}\:[0-9]{2}\:[0-9]{2}")
        sub = "XX:XX:XX"
        return self.__fuzzStrings(data, regex, sub)

    def fuzzDates(self, data=None):
        # Match line starting with "Jul 23", "Aug 2", etc
        regex = re.compile("^[A-Z]{1}[a-z]{2}[ ][0-9]{1,2}")
        sub = "XXX XX"
        return self.__fuzzStrings(data, regex, sub)

    def fuzzThreadMarker(self, data=None):
        regex = re.compile("[\[]{1}[0-9]+[\]]{1}")
        sub = "[XXXX]"
        return self.__fuzzStrings(data, regex, sub)

    def __fuzzStrings(self, data, regex, substitution):
        if not data:
            data = self.__log
        return [regex.sub(substitution, l) for l in data]

    def fuzz(self):
        return self.fuzzThreadMarker(self.fuzzDates(self.fuzzTimes(self.__log)))


