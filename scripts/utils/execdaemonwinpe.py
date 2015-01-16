import subprocess
from SimpleXMLRPCServer import SimpleXMLRPCServer
import os.path

class WinPEExec(object):
    def __init__(self):
        pass
        
    def exec_shell(self, cmd):
        return subprocess.check_output(cmd, shell=True)

    def start_shell(self, cmd):
        subprocess.Popen(cmd, shell=True)

    def write_file(self, fname, content):
        with open(fname, "w") as f:
            f.write(content)

    def read_file(self, fname):
        with open(fname) as f:
            return f.read()

    def file_exists(self, fname):
        return os.path.exists(fname)

xmlrpc = SimpleXMLRPCServer(("0.0.0.0", 8080), allow_none=True)
xmlrpc.register_introspection_functions()
xmlrpc.register_instance(WinPEExec())
xmlrpc.serve_forever()
