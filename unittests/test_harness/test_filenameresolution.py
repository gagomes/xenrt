from mock import patch, Mock, PropertyMock
import xenrt
from testing import XenRTUnitTestCase

import xenrt.filemanager

class TestFilenameResolution(XenRTUnitTestCase):

    DEFAULT_VARS = {"FORCE_HTTP_FETCH": "http://baseurl/path/",
                    "INPUTDIR": "input/dir"}

    def test_resolve_file_paths(self):
        # Each item of data is a tuple of (supplied file name, expected file name, extra variable for LOOKUP)
        data = [("http://website/path/to/file", "http://website/path/to/file", {}),
              ("/usr/groups/xen/path/to/file", "http://baseurl/path/usr/groups/xen/path/to/file", {}),
              ("/usr/groups/xen/path/to/file", "http://baseurl/path/usr/groups/xen/path/to/file", {"FORCE_HTTP_FETCH": "http://baseurl/path"}),
              ("https://website/path/to/file", "https://website/path/to/file", {}),
              ("test/test.txt", "http://baseurl/path/input/dir/test/test.txt", {}),
              ("test/test.txt", "http://baseurl/path/input/dir/test/test.txt", {"INPUTDIR": "/input/dir/"}),
              ("${VAR1}/test", "http://baseurl/path/input/dir/val/test", {"VAR1": "val"}),
              ("${VAR1}/${VAR2}/test", "http://baseurl/path/input/dir/val1/val2/test", {"VAR1": "val1", "VAR2": "val2"}),
              ("${VAR1}/test", "http://baseurl/path/val/test", {"VAR1": "/val"}),
              ("${VAR1}/test", "http://val/test", {"VAR1": "http://val"})]
        self.run_for_many(data, self.__test_resolve_filename)
    
    @patch("xenrt.TEC")
    def __test_resolve_filename(self, data, tec):
        (infn, outfn, extravars) = data
        self.extravars = extravars

        # Replace lookup with a custom function
        tec.return_value.lookup=self.__mylookup
        # Lookup INPUTDIR using mylookup
        tec.return_value.getInputDir.return_value = self.__mylookup("INPUTDIR")
        
        foundfn = xenrt.filemanager.FileNameResolver(infn).url
        print "For input \"%s\", \"%s\" expected, \"%s\" actual" % (infn, outfn, foundfn)
        assert foundfn == outfn

    def __mylookup(self, var, default=None):
        values = {}
        values.update(self.DEFAULT_VARS)
        values.update(self.extravars)
        if not values.has_key(var):
            return default
        else:
            return values[var]
