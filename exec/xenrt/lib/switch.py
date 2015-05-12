#
# XenRT: Test harness for Xen and the XenServer product family
#
# Classes for manipulating switches
#

# define switch model/type and return appropriate class

from telnetlib import Telnet
import re
import xenrt
import random
import os
from xenrt.lazylog import log, warning

random.seed()

def suitableForLacp(switchName):
    # return True if XenRT is able to set up LACP on the switch
    switchName = re.sub('^XenRT','', switchName)
    try:
        switch = switchChooser(switchName)(switchName, None)
        return switch.isLacpCapable() 
    except:
        return False

def lacpCleanUp(hostname):
    # get the list of clean-up actions from clean-up flags file
    # and perform the actions.
    cleanUpFlagsFile = xenrt.TEC().lookup("CLEANUP_FLAGS_PATH") + '/' + hostname + "/LACP"
    
    if not os.path.exists(cleanUpFlagsFile):
        raise xenrt.XRTError("Expected file not found: '%s'" % cleanUpFlagsFile)
        
    flagFileHandle = open(cleanUpFlagsFile, 'r')
    content = flagFileHandle.read().strip()
    flagFileHandle.close()
    
    lines = content.split('\n')
    
    switches = {}
    
    for line in lines:
        if len(line) == 0 :
            continue
        fields = line.split()
        if len(fields) < 3:
            warning("Ignoring malformatted line '%s' in clean-up file" % line)
            continue
        if len(fields) > 3:
            warning("Malformatted line '%s' in clean-up file, will attempt to process anyway"
                % line)
        switchName, field, value = fields
        if not switches.has_key(switchName):
            switches[switchName] = []
        switches[switchName].append([field, value])
        
    for switchName in switches.keys():
        sw = createSwitch(switchName, hostname)
        for field, value in switches[switchName]:
            if field == 'PORT':
                sw.unsetLagOnPort(port=value)
            elif field == 'LAG':
                sw.portChannelInterfaceClean(lag=value)
            else:
                raise xenrt.XRTError("Unsupported field '%s' in file '%s'" % (field, cleanUpFlagsFile) )
        sw.disconnect()
                
    # check if the cleanUpFlags file is empty now
    flagFileHandle = open(cleanUpFlagsFile, 'r')
    content = flagFileHandle.read().strip()
    flagFileHandle.close()
    
    if len(content) > 0:
        raise xenrt.XRTError(
            "Clean-up of LACP seems to have failed, following content still exist in the cleanup-flags file: %s",
            content )
    os.remove(cleanUpFlagsFile)

class SwitchCleanupFlags(object):
    """ Manage flags for switch clean up.
    Clean-up flags are set in file /local/scratch/cleanup/hostname/LACP
    and are to be used in case a job is killed"""
        
    def __init__(self, switch, hostname):
        self.switch = switch
        self.hostname = hostname
        self.cleanUpRootDir = xenrt.TEC().lookup("CLEANUP_FLAGS_PATH")
        d = self.cleanUpRootDir + '/' + self.hostname
        if not os.path.exists(d):
            os.makedirs(d)
        self.cleanUpFlagsFile = d + '/LACP'
        if not os.path.exists(self.cleanUpFlagsFile):
            open(self.cleanUpFlagsFile, 'w').close()

    def set(self, category, value):
        # set a cleanup category and value
        self._addLine("%s\t%s\t%s" % (self.switch, category, value) )

    def clear(self, category, value):
        # set a cleanup category and value
        self._removeMatching("^%s\t%s\t%s(\s|$)" % (self.switch, category, value) )
        
    def _addLine(self, line):
        f = open(self.cleanUpFlagsFile, 'a')
        f.write(line.strip()+"\n")
        f.close()
        
    def _readAll(self):
        f = open(self.cleanUpFlagsFile, 'rs')
        content = f.read()
        f.close()
        return content
        
    def _writeAll(self, content):
        self._checkContent(content)
        f = open(self.cleanUpFlagsFile, 'w')
        f.write(content)
        f.close()
        
    def _checkContent(self, content):
        # Check that we have three fields in every line
        # This check was implemented, as occasionally we see malformatted lines
        # It can be removed once we get to root cause of this behaviour
        candidateContent = content
        content = content.rstrip()
        if len(content) == 0:
            return
        lines = content.rstrip().split("\n")
        for l in lines:
            fields = l.split()
            if len(fields) != 3:
                warning('Problem in switch.py library - attempt to write a malformatted line')
                current = self._readAll()
                log('current data:\n%s' % current)
                log('candidate data:\n"%s"' % candidateContent)
                raise xenrt.XRTError('Attempted to write a malformatted line "%s" '
                        'in LACP clean-up flags file.' % l)


    def _removeMatching(self, pattern):
        reg = re.compile(pattern , re.MULTILINE)
        newContent = reg.sub('', self._readAll()).strip()
        newContent = newContent + "\n"
        self._writeAll(newContent)
        
    def getLines(self):
        content = self._readAll().strip()
        if content:
            return content.split('\n')
        else:
            return []
    
    def getValues(self):
        lines =  filter(lambda l: len(l.strip())>0,  self.getLines())
        return map(lambda l: l.split()[-1],  lines)
                   
    def _tidyUpHostDir(self):
        
        # if clean-up flags file is empty, remove it
        
        if len( self._readAll().strip() ) == 0:
            os.remove(self.cleanUpFlagsFile)
            
        # then remove the whole host directory, if empty.
        
        hostDir = self.cleanUpRootDir + '/' + self.hostname
        dirs = os.listdir(hostDir)
        if len(dirs) == 0:
            os.rmdir(hostDir)     
                
class _Switch(object): 
    DEBUG = False

class _CiscoStyleSwitch(_Switch):
    CONNECT_TIMEOUT=30
    CONNECT_ATTEMPTS=5
    TIMEOUT = 15
    MAX_ATTEMPTS = 3
    CHANNELPREFIX = None
    PORTREGEX = None
    PORTPREFIX = None
    MAX_PORTS_PER_LAG = 8
    KNOWN_WARNINGS = []
    
    def __init__(self, switchName, hostname='', ports=[]):
        # arguments: e.g.: 'cl11-07', 'PC6248-SVCL07',  ['4/g46', '4/g48']
        
        self.login = ""
        self.password = ""
        self.telnet = None    
        self.prompt = ""
        self.hostname = hostname
        self.switch = switchName
        self.lag = None
        self.knownWarnings = []

        
        # find the IP and the password
        
        log("Accessing NETSWITCHES config for switch %s" %self.switch)
        self.ip = xenrt.TEC().lookup(["NETSWITCHES", self.switch, 'ADDRESS'])
        self.login = xenrt.TEC().lookup(["NETSWITCHES", self.switch, 'USERNAME'], "admin")
        self.password = xenrt.TEC().lookup(["NETSWITCHES", self.switch, 'PASSWORD'])
        log('Switch IP (%s) and password retrieved.' % self.ip)
        
        # define warnings to ignore
        
        for warn in self.KNOWN_WARNINGS:
            warnRobust =  re.sub('\s', '\s+', warn )
            self.knownWarnings.append(re.compile(warnRobust, re.MULTILINE) )
        if hostname:
            self.cleanUpFlags = SwitchCleanupFlags(self.switch, hostname)

            # for existing LAG set-up, retrieve the LAG number
            portsWithLacpCleanupSet = filter(lambda m: m in self.ports, self.cleanUpFlags.getValues())
            # check for LAG only if a clean-up flag was set 
            if portsWithLacpCleanupSet:
                lags, lagsMembers = self.getExistingLAGs()
                for i in range(0,len(lags)):
                    members = lagsMembers[i]
                    if filter(lambda m: m in self.ports, members):
                        self.lag = lags[i]
                        break
        else:
            self.cleanUpFlags = None

    def isLacpCapable(self):
        return True
                    
    def sendEnable(self):
        raise xenrt.XRTError('Function sendEnable not implemented for base class')
        
    def checkPrompt(self, text, pattern=None, subtract=''):
    # check if the prompt is as expected
        cleanedText = text
        if subtract:
            if text.lstrip().startswith(subtract.strip()):
                ind = text.find(subtract)
                cleanedText = text[ind+len(subtract):]
                cleanedText = cleanedText.strip()
            else:
                log("Prompt check failed - unexpected output returned by the switch.\n" 
                            +"Text expected at the beginning: '%s'\nText observed:\n'%s'" % (subtract, text) )
                raise xenrt.XRTError("Unexpected string returned by the switch.")
        RegExType = type(re.compile(' '))
        regex=None
        if not pattern:
            regex = re.compile('\s*'+self.prompt+'[^ #]*#|.*\(config\)#|.*\(config-if\)#')
        elif isinstance(pattern, RegExType): 
            regex = pattern
        else:
            regex = re.compile(pattern)
        if not regex.match(cleanedText):
            cleanedText = self.removeKnownWarnings(cleanedText)
            if not regex.match(cleanedText):
                log("Prompt check failed - unexpected output returned by the switch:\n'%s'" % cleanedText)
                log("Expected %s" % regex.pattern)
                raise xenrt.XRTError("Unexpected string returned by the switch")
            
    def removeKnownWarnings(self, txt):
        # remove known warnings from txt
        for w in self.knownWarnings:
            txt = re.sub(w, '', txt).strip()
        return txt
                
    def checkForPrompt(self):
        # re-connect if telnet connection timed out
        if self.DEBUG:
            log('Poking the switch')
        out= ''
        try: 
            self.telnet.write('\r')
            out = self.telnet.read_until('#', timeout=self.TIMEOUT)
            if out.strip() == '*** IDLE TIMEOUT ***' : 
                log('Idle timeout on switch, will  re-connect.')
                raise Exception("Idle timeout")
        except: 
            self.connectToSwitch()
            self.telnet.write('\r')
            out = self.telnet.read_until('#', timeout=self.TIMEOUT)
        if self.DEBUG:
            log("Output on switch console:\n'%s'" % out)
        self.checkPrompt(out)
        if self.DEBUG:
            log('Poking the switch successful.')
        prompt=out.strip()
        return prompt
            
    def commandWithResponse(self, command, maxpages=10):
        # send a command to the switch and gather the answer
        # long commands are broken into parts, so we need to 'press enter' to get the whole output
        # this currently does not work for commands with very long output (several pages) - see CA-86870
        self.checkForPrompt()
        if command != '' or self.DEBUG:
            log("Executing switch command '%s'" % command)
        self.telnet.write('%s\r' % command)
        output = []
        patterns = [re.compile(p, re.MULTILINE) for p in ['^%s[^# ]*#' % self.prompt, '^--More-- or \(q\)uit', '^ --More--']]

        for i in range(0,maxpages):
            (index, match, portion) = self.telnet.expect(patterns, timeout=self.TIMEOUT)
            if command != '' or self.DEBUG:
                log("switch command output:\n'%s'" % portion)
            if not match:
                log("Error! Unexpected command output!")
                self.deb = portion
                raise xenrt.XRTError("Unexpected output while executing switch command '%s'" % command)
            output += portion.strip().split("\n")
            if index == 0 : 
                # prompt pattern matched, so end loop
                break
            else:
                # remove line '--More-- or quit'
                output.pop()
                # send 'enter'
                self.telnet.write(' ')
        else:
            raise xenrt.XRTError("Too many pages of output after switch command '%s'" % command)
        # read whatever is in the buffer 
        out = self.telnet.read_eager()
        if out.strip():
            log("Remaining output read from switch console '%s'" % out)
            raise xenrt.XRTError("Unexpected output read from switch console!")
        self.checkForPrompt()
        return output
        
    def command(self, command):
        # execute a quiet command - one that should not produce any output but prompt
        self.checkForPrompt()
        if command != '' or self.DEBUG:
            log("Executing switch command '%s'" % command)
        self.telnet.write('%s\r' % command)
        out = self.telnet.read_until('#', timeout=self.TIMEOUT)
        self.checkPrompt(out, subtract=command)
        out = self.telnet.read_eager()
        if out.strip():
            log("Remaining output read from switch console '%s'" % out)
            raise xenrt.XRTError("Unexpected output read from switch console!")
        prompt = self.checkForPrompt()
        return prompt


    def proposeLAG(self):
        # Dell has 8 LAG grops, labelled with numbers 0-23
        lags, members = self.getExistingLAGs(setChRange=True)
        availableLAGs = range(1, self.maxCh+1)
        availableLAGs = filter(lambda l: l not in lags, availableLAGs)
        if len(availableLAGs) > 0:
            return random.choice(availableLAGs)
        else:
            raise xenrt.XRTError("Unable to find a free LAG number on the switch." )
    
    def disconnect(self):
        self.telnet.close()
        
    def clearPrompt(self):
        regex = re.compile('\s*'+self.prompt+'#')
        prompt = self.command('')
        for i in range(5):
            if not regex.match(prompt):
                prompt = self.command('exit')
            else:
                break
        else:
            log("Failed to clear switch patch, reconnecting." )
            self.disconnect()
            self.connectToSwitch()
        
    def unsetLagOnPort(self, port):
        self.setLagOnPort(port, None)

    def portChannelInterfaceConfigure(self):
        # copy settings from one of the ports to the port-channel
        # also disable spanning tree to speed up bond creation/failover
        portSettings = self.commandWithResponse('show running-config interface %s%s' % (self.PORTPREFIX, self.ports[0]))
        commandList = [ s.strip() for s in portSettings if s.lstrip().startswith('switchport ') or s.lstrip().startswith('no switchport')]
        commandList.append('spanning-tree portfast')
        self.setChannelCleanUpFlag(self.lag)
        self._portChannelInterfaceConfigure(self.lag, commandList)
        
    def portChannelInterfaceClean(self, lag=None):
        # clear setting on given port-channel
        if lag is None:
            lag = self.lag
        self._portChannelInterfaceConfigure(lag, commandList=['no switchport mode'])
        self.clearChannelCleanUpFlag(lag)
        
    def _portChannelInterfaceConfigure(self, LAG, commandList):
        # execute settings for given port-channel
        self.configureMode() 
        self.command('interface port-channel %s' % LAG)
        for command in commandList:
            self.command(command)
        self.clearPrompt()    
        
    def checkPortHasNoLagSet(self, port):
        out = self.commandWithResponse("show running-config interface %s%s" % (self.PORTPREFIX, port))
        regex = re.compile('channel-group \d+')
        matched = [ l for l in out if regex.match(l) ]
        if len(matched) > 0:
            line = matched[0]
            LAG = re.match('channel-group (\d+)', line).group(1)
            raise xenrt.XRTError("Port %s is already a member of LAG %s" % (port, LAG) )
    
    def setLACP(self):
        # Check that no port has LAG/LACP already set
        for port in self.ports:
            self.checkPortHasNoLagSet(port)
        # Set LAG and enable LACP on all the ports
        proposedLAG = self.proposeLAG()
        ports = self.ports[:]
        firstPort = ports.pop(0)
        # Avoid the (unlikely) situation where two TCs try to set up the same LAG 
        # (let the other TC win, revert and re-propose LAG)
        for i in range(self.MAX_ATTEMPTS):
            log("Trying LAG number %s." % proposedLAG)
            self.setLagOnPort(firstPort, proposedLAG)
            if self.checkLagIsOnlyOnPort(proposedLAG, firstPort):
                break
            else:
                log("Reverting, LAG %s seems to be used by another port." % proposedLAG) 
                self.unsetLagOnPort(firstPort)
                proposedLAG = self.proposeLAG()
        else:
            raise xenrt.XRTError("%s attempts to set up LAC on port %s failed." % (self.MAX_ATTEMPTS, firstPort) )

        # Set up chosen LAG on the remaining ports
        self.lag = proposedLAG
        for port in ports:
            self.setLagOnPort(port, self.lag)
        
        # Set the port-channel interface
        self.portChannelInterfaceConfigure()
        self.disconnect()
        
    def unsetLACP(self):
        for port in self.ports:
            self.unsetLagOnPort(port)
        if self.lag:
            self.portChannelInterfaceClean()
        for port in self.ports:
            self.bouncePort(port)
        self.disconnect()
        if self.cleanUpFlags:
            self.cleanUpFlags._tidyUpHostDir()
        
    def setChannelCleanUpFlag(self, LAG):
        if self.cleanUpFlags:
            self.cleanUpFlags.set('LAG', LAG)
    
    def clearChannelCleanUpFlag(self, LAG):
        if self.cleanUpFlags:
            self.cleanUpFlags.clear('LAG', LAG)
        
    def setPortCleanUpFlag(self, port):
        if self.cleanUpFlags:
            self.cleanUpFlags.set('PORT', port)
    
    def clearPortCleanUpFlag(self, port):
        if self.cleanUpFlags:
            self.cleanUpFlags.clear('PORT', port)
        
    def setLagOnPort(self, port, LAG):
        
        self.configureMode() 
        self.command('interface %s%s' % (self.PORTPREFIX, port))
        if LAG:
            self.setPortCleanUpFlag(port)
            self.command('channel-group %s mode %s' % (LAG, self.LACP_STRING))
        else:
            self.command('no channel-group')
            self.clearPortCleanUpFlag(port)
        self.clearPrompt()
       
    def bouncePort(self, port):
        """Disable and enable switch port, useful for when the switch gets stuck after unsetting LACP on ports"""
        self.configureMode() 
        self.command('interface %s%s' % (self.PORTPREFIX, port))
        self.command('shutdown')
        self.command('no shutdown')
        self.clearPrompt()
   
class _DellSwitch(_CiscoStyleSwitch):
    KNOWN_WARNINGS = ['^Warning: The use of large numbers of VLANs or interfaces may cause significant delays[^.]+\.']

    def connectToSwitch(self):
        log("initialising telnet to switch (%s)" % self.ip)
        i = 0
        while True:
            i += 1
            try:
                self.telnet = Telnet(self.ip, 23, timeout=self.CONNECT_TIMEOUT)
                break
            except:
                if i >= self.CONNECT_ATTEMPTS:
                    raise
                xenrt.sleep(self.CONNECT_TIMEOUT)
        self.telnet.read_until('User:', timeout=self.TIMEOUT)
        self.telnet.write('%s\r' % self.login)
        self.telnet.read_until('Password:', timeout=self.TIMEOUT)
        self.telnet.write('%s\r' % self.password)
        out = self.telnet.read_until('>', timeout=self.TIMEOUT)
        re_prompt = re.compile('^([a-zA-Z0-9-]+)>$', re.MULTILINE)
        m_prompt = re_prompt.search(out)
        if m_prompt:
            self.prompt = m_prompt.group(1)
        else: 
            log("Unexpected output returned by the switch:\n'%s'" % out)
            raise xenrt.XRTError("Unexpected string returned by the switch")
        self.sendEnable()
        log("Successfully connected to the switch.")
        
    def getExistingLAGs(self, setChRange=False, quiet=False):
        lines = self.commandWithResponse('show interfaces port-channel')
        re_ch = re.compile("%s\d+" % self.CHANNELPREFIX)
        re_no_ch = re.compile('[^c]')
        re_wrapped = re.compile("\s+((?:%s,?\s?)+)" % self.PORTREGEX)
        # fix wrapped second column of the list
        for i in range(1,len(lines)):
            if re_no_ch.match(lines[i]) and re_ch.match(lines[i-1]):
                m = re_wrapped.match(lines[i])
                if m:
                    wrapped = m.group(1).strip()
                    s1, s2 = lines[i-1].rsplit(None, 1)
                    lines[i-1] = s1 + ", " + wrapped + s2
        lines = filter(re_ch.match,lines)
        if setChRange is True:
            # find last chX line and set maxCh to X
            self.maxCh = int(re.match("%s(\d+)" % self.CHANNELPREFIX, lines[-1]).group(1))
        re_noports = re.compile("%s\d+\s+No Configured Ports" % self.CHANNELPREFIX)
        lines = filter(lambda x: not re_noports.match(x) , lines)
        LAGs = []
        members = []
        if len(lines)>0:
            log("Existing configured channels found: \n%s" % "\n".join(lines))
            # convert \d+ into integers and return list of existing LAG numbers
            LAGs = map(lambda line : int(re.match("%s(\d+)" % self.CHANNELPREFIX, line).group(1)), lines)
            members =  [re.findall(self.PORTREGEX, line) for line in lines]
        return (LAGs, members)

    def configureMode(self):
        self.command("configure")

    def checkLagIsOnlyOnPort(self, LAG, port):
        out = self.commandWithResponse("show interfaces port-channel %s" % LAG)
        line = [l for l in out if re.match("%s%s\s+" % (self.CHANNELPREFIX, LAG), l)][0]
        m = re.findall(self.PORTREGEX, line)
        if  len(m)==1 and m[0]==port :
            return True
        else:
            return False
            
    def setLacpTimeout(self, port, value):
        # value can be either 'long' or 'fast'
        self.configureMode() 
        self.command("interface %s%s" % (self.PORTPREFIX, port))
        self.command("lacp timeout %s" % value)
        self.clearPrompt()

class DellPC8024Switch(_DellSwitch):

    CHANNELPREFIX = "ch"
    PORTREGEX = '\d+/xg\d+'
    PORTPREFIX = "ethernet "
    LACP_STRING="auto"
    def __init__(self, switchName, hostname='', ports=[]):
        self.ports = []
        for p in ports:
            (unit, port) = p
            self.ports.append("%s/xg%s" % (unit, port))
        _DellSwitch.__init__(self, switchName, hostname, ports)

    def sendEnable(self):
        self.telnet.write('enable\r')
        out = self.telnet.read_until('#', timeout=self.TIMEOUT)
        self.checkPrompt(out, pattern=None, subtract='enable')

class DellPC62xxSwitch(_DellSwitch):

    CHANNELPREFIX = "ch"
    PORTREGEX = '\d+/g\d+'
    PORTPREFIX = "ethernet "
    LACP_STRING="auto"
    def __init__(self, switchName, hostname='', ports=[]):
        self.ports = []
        for p in ports:
            (unit, port) = p
            self.ports.append("%s/g%s" % (unit, port))
        _DellSwitch.__init__(self, switchName, hostname, ports)

    def sendEnable(self):
        self.telnet.write('enable\r')
        out = self.telnet.read_until('#', timeout=self.TIMEOUT)
        self.checkPrompt(out, pattern=None, subtract='enable')

class DellM6348Switch(_DellSwitch):

    CHANNELPREFIX = "Po"
    PORTREGEX = 'Gi\d+/0/\d+'
    PORTPREFIX = ""
    LACP_STRING="auto"

    def __init__(self, switchName, hostname='', ports=[]):
        self.ports = []
        for p in ports:
            (unit, port) = p
            self.ports.append("Gi%s/0/%s" % (unit, port))
        self.enablePassword = xenrt.TEC().lookup(["NETSWITCHES", switchName, 'ENABLEPASSWORD'])
        _DellSwitch.__init__(self, switchName, hostname, ports)

    def sendEnable(self):
        self.telnet.write('enable\r')
        self.telnet.read_until('Password:', timeout=self.TIMEOUT)
        self.telnet.write('%s\r' % self.enablePassword)
        self.telnet.read_until('#', timeout=self.TIMEOUT)

class DellM6348Switchv5(DellM6348Switch):
    LACP_STRING="active"

class _CiscoIOSSwitch(_CiscoStyleSwitch):
    KNOWN_WARNINGS = [
        '^Enter configuration commands, one per line\.  End with CNTL/Z\.',
        '^Creating a port-channel interface Port-channel \d+',
        '^%Warning: portfast should only be enabled on ports connected to a single',
        '^\s*host. Connecting hubs, concentrators, switches, bridges, etc... to this',
        '^\s*interface  when portfast is enabled, can cause temporary bridging loops.',
        '^\s*Use with CAUTION',
        '^%Portfast has been configured on Port-channel\d+ but will only',
        '\s*have effect when the interface is in a non-trunking mode.'
        ]
    LACP_STRING="active"
    
    def connectToSwitch(self):
        log("initialising telnet to switch (%s)" % self.ip)
        i = 0
        while True:
            i += 1
            try:
                self.telnet = Telnet(self.ip, 23, timeout=self.CONNECT_TIMEOUT)
                break
            except:
                if i >= self.CONNECT_ATTEMPTS:
                    raise
                xenrt.sleep(self.CONNECT_TIMEOUT)
        log("Connected, sending username")
        self.telnet.read_until('Username:', timeout=self.TIMEOUT)
        self.telnet.write('%s\r' % self.login)
        log("Sending password")
        self.telnet.read_until('Password:', timeout=self.TIMEOUT)
        self.telnet.write('%s\r' % self.password)
        log("Waiting for prompt")
        out = self.telnet.read_until('#', timeout=self.TIMEOUT)
        re_prompt = re.compile('^([a-zA-Z0-9-]+)#$', re.MULTILINE)
        m_prompt = re_prompt.search(out)
        if m_prompt:
            self.prompt = m_prompt.group(1)
        else: 
            log("Unexpected output returned by the switch:\n'%s'" % out)
            raise xenrt.XRTError("Unexpected string returned by the switch")
        log("Sending enable")
        self.sendEnable()
        log("Setting terminal settings")
        self.command("terminal length 0")
        self.command("terminal width 0")
        
        log("Successfully connected to the switch.")
        
    def getExistingLAGs(self, setChRange=False, quiet=False):
        lines = self.commandWithResponse('show etherchannel summary')
        re_ch = re.compile("\d+\s+%s\d+" % self.CHANNELPREFIX)
        re_no_ch = re.compile('[^0-9]')
        re_wrapped = re.compile("\s+((?:%s,?\s?)+)" % self.PORTREGEX)
        # fix wrapped second column of the list
        for i in range(1,len(lines)):
            if re_no_ch.match(lines[i]) and re_ch.match(lines[i-1]):
                m = re_wrapped.match(lines[i])
                if m:
                    wrapped = m.group(1).strip()
                    s1, s2 = lines[i-1].rsplit(None, 1)
                    lines[i-1] = s1 + ", " + wrapped + s2
        lines = filter(re_ch.match,lines)
        lines = filter(lambda x: len(x.split()) > 3 , lines)
        LAGs = []
        members = []
        if len(lines)>0:
            log("Existing configured channels found: \n%s" % "\n".join(lines))
            # convert \d+ into integers and return list of existing LAG numbers
            LAGs = map(lambda line : int(re.search("%s(\d+)" % self.CHANNELPREFIX, line).group(1)), lines)
            members =  [re.findall(self.PORTREGEX, line) for line in lines]
        return (LAGs, members)

    def configureMode(self):
        self.command("configure terminal")

    def checkLagIsOnlyOnPort(self, LAG, port):
        out = self.commandWithResponse("show etherchannel %s summary" % LAG)
        line = [l for l in out if re.search("%s%s\(" % (self.CHANNELPREFIX, LAG), l)][0]
        m = re.findall(self.PORTREGEX, line)
        if  len(m)==1 and m[0]==port :
            return True
        else:
            return False
            
    def setLacpTimeout(self, port, value):
        raise xenrt.XRTError("LACP timeout not supported on this switch")

class CiscoC3750GSwitch(_CiscoIOSSwitch):
    CHANNELPREFIX = "Po"
    PORTREGEX = 'Gi\d+/0/\d+'
    PORTPREFIX = ""

    def __init__(self, switchName, hostname='', ports=[]):
        self.ports = []
        for p in ports:
            (unit, port) = p
            self.ports.append("Gi%s/0/%s" % (unit, port))
        self.maxCh = 48
        _CiscoIOSSwitch.__init__(self, switchName, hostname, ports)

    def sendEnable(self):
        pass

class CiscoC2960XSwitch(_CiscoIOSSwitch):
    CHANNELPREFIX = "Po"
    PORTREGEX = 'Gi\d+/0/\d+'
    PORTPREFIX = ""

    def __init__(self, switchName, hostname='', ports=[]):
        self.ports = []
        for p in ports:
            (unit, port) = p
            self.ports.append("Gi%s/0/%s" % (unit, port))
        self.maxCh = 24
        _CiscoIOSSwitch.__init__(self, switchName, hostname, ports)

    def sendEnable(self):
        pass

def switchChooser(switchName):
    switchType = xenrt.TEC().lookup(["NETSWITCHES", switchName, 'TYPE'])
    if switchType == "DellPC62xx":
        return DellPC62xxSwitch
    elif switchType == "DellM6348":
        return DellM6348Switch
    elif switchType == "DellM6348v5":
        return DellM6348Switchv5
    elif switchType == "DellPC8024":
        return DellPC8024Switch
    elif switchType == "CiscoC3750G":
        return CiscoC3750GSwitch
    elif switchType == "CiscoC2960X":
        return CiscoC2960XSwitch
    else:
        raise xenrt.XRTError("XenRT support not implemented for the switch type '%s'" 
                            % switchType )
    

def createSwitch(switchName, hostName):
    return switchChooser(switchName)(switchName, hostName)

def createSwitchForNICs(host, eths):
    """This function is not part of any automated test but is used for semi-manual tests"""
    nics = []
    netports = []
    for e in eths:
        nicIndex = host.getNICEnumerationId(e)
        nic = "NIC%s" % nicIndex 
        nics.append(nic)
        netport = None
        if nicIndex==0 : 
            netport = host.lookup("NETPORT", None)
        else:
            netport = host.lookup(["NICS", nic, "NETPORT"], None)
        print "netport is %s" % netport
        if not netport: 
            raise xenrt.XRTError("Could not find NETPORT information for host %s, %s, %s.\n" 
                    % (host.getName(), nic, e) )
        if len(netport.split("/")) != 2:
            raise xenrt.XRTError("NETPORT syntax error: %s (%s)" % (netport, host.getName()))
        netports.append(netport)

    hostname = host.getName()
        
    switches = []
    ports = []
    for netport in netports:
        ( switch, port) = netport.split("/")
        switch, unit = switch.rsplit('-', 1)
        switch = re.sub('^XenRT','', switch)
        ports.append((unit, port))
        switches.append(switch)
        
    # Check that we have only one switch
    if len(set(switches)) > 1: 
        raise xenrt.XRTError(
            "Ports %s are not within one switch stack. Switches found: %s" %
                (",".join(ports), switches) )
    
    switchName = switches[0]
    
    return switchChooser(switchName)(switchName, hostname, ports)

def createSwitchForPifs(host, bondpifs):
    # find out switch type
    
    # For each PIF, get eth/NIC number and NETPORT string

    nics = []
    netports = [] 
    
    # find interface, NIC and NETPORT string corresponding to the PIF
    # We can't rely on the device as the enumeration may change in XenServer - instead use the MAC address
    macMappings = {} # This maps a MAC address to an assumed id
    macMappings[xenrt.normaliseMAC(host.lookup("MAC_ADDRESS"))] = 0
    nicData = host.lookup("NICS")
    for n in nicData.keys():
        assumedid = int(n.replace("NIC",""))
        macMappings[xenrt.normaliseMAC(nicData[n]['MAC_ADDRESS'])] = assumedid

    for pif in bondpifs :
        mac = host.genParamGet("pif", pif, "MAC")
        i = macMappings[xenrt.normaliseMAC(mac)]
        nic = "NIC%s" % i 
        nics.append(nic)
        netport = None
        if nic == "NIC0" : 
            netport = host.lookup("NETPORT", None)
        else:
            netport = host.lookup(["NICS", nic, "NETPORT"], None)
        print "netport is %s" % netport
        if not netport: 
            raise xenrt.XRTError("Could not find NETPORT information for host %s, %s, %s.\n" 
                    % (host.getName(), nic, pif) )
        if len(netport.split("/")) != 2:
            raise xenrt.XRTError("NETPORT syntax error: %s (%s)" % (netport, host.getName()))
        netports.append(netport)

    # TODO: check that MAC addresses of PIFs match those in the config file


    hostname = host.getName()
    
    switches = []
    ports = []
    for netport in netports:
        ( switch, port) = netport.split("/")
        switch, unit = switch.rsplit('-', 1)
        ports.append((unit, port))
        switches.append(switch)
        
    # Check that we have only one switch
    if len(set(switches)) > 1: 
        raise xenrt.XRTError(
            "Ports %s are not within one switch stack. Switches found: %s" %
                (",".join(["%s/g%s" %(unit, port) for (unit, port) in ports]), switches) )
    
    switchName = switches[0]
    
    

    return switchChooser(switchName)(switchName, hostname, ports)
 
