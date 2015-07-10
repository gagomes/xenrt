import simplejson
import xenrt

class Command(object):
    """
    A command (or commands) informtion data structure.
    """
    def __init__(self, json):
        self.command = json["command"]
        self.raiseIfError = ('raiseIfError' in json and json['raiseIfError']) or True
        self.resultSource = ('resultSource' in json and json['resultSource']) or 'RETURN_CODE'
        self.nextAction = ('nextAction' in json and json['nextAction']) or None
        self.timeout = ('timeout' in json and json['timeout']) or 60
        self.returnCode = None
        self.stdout = ''
        self.stderr = ''


class CommandsReader(object):
    """
    Reads json files and build list of Commands.

    Currently using execguest instead of an actual ssh session.
    Limited by what return information is available in this case, such as return code.
    """
    def __init__(self, jsonstr, session):
        self.current = 0
        self.session = session
        self.commands = []
        jsonobj = simplejson.loads(jsonstr)
        for cmd in jsonobj['commands']:
            self.commands.append(Command(cmd))

    def fetch(self):
        if len(self.commands) > self.current:
            return self.commands[self.current]
        return None

    def execute(self):
        cmd = self.fetch()
        result = {}
        reboot = False
        if not cmd:
            return result

        cmdtorun = cmd.command
        if cmdtorun.endswith("reboot"):
            cmdtorun = cmdtorun.replace("reboot", "").strip()
            reboot = True
        if len(cmdtorun):
            try:
                self.session.execguest(cmdtorun)
            except Exception as e:
                if cmd.raiseIfError:
                    raise e
                else:
                    xenrt.TEC().logverbose(str(e))
        # Getting assigned to defaults right now.
        result['returnCode'] = cmd.returnCode
        result['stdout'] = cmd.stdout
        result['stderr'] = cmd.stderr
        
        self.current += 1

        if reboot:
            self.session.reboot()

        return result


class Runner(object):
    """
    The command runner. This instantiates CommandsReader.
    """
    DEPTH_LIMIT = 10

    def __init__(self, json, guest, depth = 0):
        self.reader = CommandsReader(json, guest)
        self.output = ""
        self.__depth = depth
        if depth > self.DEPTH_LIMIT:
            xenrt.warning("Shell script runner is running in deeper depth than allowed. This may cause low memory issue.")

    def runStep(self):
        cmd = self.reader.fetch()
        if cmd:
            self.output = "Executing: " + str(cmd.command)
        result = self.reader.execute()
        if not len(result):
            raise xenrt.XRTError("Failed to execute command.")

        return result

    def runThrough(self):
        result = {}
        while self.reader.fetch():
            result = self.runStep()
        return result

