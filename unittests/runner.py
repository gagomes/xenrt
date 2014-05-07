import os
import string
from subprocess import call
from distutils import spawn

# Fix up the pythonpath
path = []
if "PYTHONPATH" in os.environ:
    path.append(os.environ["PYTHONPATH"])
path.append(os.path.abspath("../exec"))

os.environ["PYTHONPATH"] = string.join(path, ":")

noseTestPath = spawn.find_executable("nosetests")

# Run the tests using nose
res = call(["coverage", "run", noseTestPath, "-v", "--with-xunit"])
if res != 0:
    raise Exception("Unit tests failed")
