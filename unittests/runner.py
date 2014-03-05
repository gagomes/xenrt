import sys, os
from subprocess import call

#Fix up the pythonpath
sys.path.append(os.path.join(os.path.dirname(__file__), os.path.abspath("../exec")))

#Run the tests using nose
call(["nosetests", "-P ../exec", "-v"] )
