import subprocess
from SimpleXMLRPCServer import SimpleXMLRPCServer

class WinPEExec(object):
    def __init__(self):
        pass
        
    def exec_shell(self, cmd):
        return subprocess.check_output(cmd, shell=True)

    def start_shell(self, cmd):
        subprocess.Popen(cmd, shell=True)
        
xmlrpc = SimpleXMLRPCServer(("0.0.0.0", 8080), allow_none=True)
xmlrpc.register_introspection_functions()
xmlrpc.register_instance(WinPEExec())
xmlrpc.serve_forever()
