import os.path, fnmatch
import xenrt

__all__= ["TarGzArchiver"]

class TarGzArchiver(object):
    
    def __extractFileNames(self, targetLocation, matcher):
        matches = []
        for root, dirnames, filenames in os.walk(targetLocation):
            for filename in fnmatch.filter(filenames, matcher):
                matches.append(os.path.join(root, filename))
        return matches
    
    def extractAndMatch(self, tarFile, targetLocation, matchingCriteria):
        """
        Extract archive to a specified location and return paths to files 
        matching the matching criteria e.g. *.gif
        
        @tarFile(string): The path and name of the tgz file to extract
        @targetLocation(string): The path to which the tgz will be extracted
        @matchingCriteria(string): Pattern in the extracted archive eg *.gif to return
        @return: list of file names matching the matching criteria
        """
        self.extractTo(tarFile, targetLocation)
        return self.__extractFileNames(targetLocation, matchingCriteria)

    def extractTo(self, tarFile, targetLocation):
        """
        Extract a tgz file to a location
        
        @tarFile(string): The path and name of the tgz file to extract
        @targetLocation(string): The path to which the tgz will be extracted
        """
        xenrt.TEC().logverbose("Extracting gzipped tar %s to %s" %(tarFile, targetLocation))
        xenrt.util.command("tar xzf %s -C %s" % (tarFile, targetLocation))
    
    def create(self, tarFile, contents):
        """
        Create a tgz file
        
        @tarFile(string): The path and name of the tgz file to create
        @contents(string): The path to add to the archive
        """
        xenrt.TEC().logverbose("Creating gzipped tar %s from %s" %(tarFile, contents))
        xenrt.util.command("tar czf %s %s" % (tarFile, contents))
