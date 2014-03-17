import os, string
from subprocess import call

# Fix up the pythonpath
path = []
if os.environ.has_key("PYTHONPATH"):
    path.append(os.environ["PYTHONPATH"])
path.append(os.path.abspath("../exec"))

os.environ["PYTHONPATH"] = string.join(path, ":")

#Run the tests using nose
call(["nosetests", "-v"] )
