class DomZeroFilesystem(object):
    def __init__(self, host):
        self.host = host

    def setContents(self, path, data):
        sftpClient = self.host.sftpClient()

        remoteFile = sftpClient.client.file(path, 'w')
        remoteFile.write(data)
        remoteFile.close()

        sftpClient.close()

    def getContents(self, path):
        sftpClient = self.host.sftpClient()

        remoteFile = sftpClient.client.file(path, 'r')
        contents = remoteFile.read()
        remoteFile.close()

        sftpClient.close()

        return contents

    def makePathExecutable(self, path):
        self.host.execdom0('chmod +x %s' % path)
