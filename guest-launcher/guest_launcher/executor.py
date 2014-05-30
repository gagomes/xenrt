import subprocess
import logging


log = logging.getLogger(__name__)


class ProcessResult(object):
    def __init__(self, returncode, stdout, stderr):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def as_logstring(self):
        return (
            "returncode: {returncode}"
            " stdout: {stdout}"
            " stderr: {stderr}".format(
                returncode=self.returncode,
                stdout=self.stdout,
                stderr=self.stderr)
        )


class Executor(object):
    def run(self, args):
        log.info('Running %s', args)
        proc = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = proc.communicate()
        log.info('Return code: %s', proc.returncode)
        return ProcessResult(
            proc.returncode, out, err)


def escaped(args):
    return [arg.replace(' ', '\\ ') for arg in args]


class OverSSHExecutor(object):
    def __init__(self, decorated_executor, username, host, password):
        self.decorated_executor = decorated_executor
        self.username = username
        self.host = host
        self.password = password

    def run(self, args):
        return self.decorated_executor.run(
            [
                'sshpass',
                '-p{password}'.format(password=self.password),
                'ssh',
                '-q',
                '-o',
                'StrictHostKeyChecking=no',
                '-o',
                'UserKnownHostsFile=/dev/null',
                '{username}@{host}'.format(
                    username=self.username, host=self.host)
            ] + escaped(args)
        )
