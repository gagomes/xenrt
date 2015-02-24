from setuptools import setup

setup(name='xenrtapi',
      version='0.01',
      description="API for XenRT",
      url="http://xenrt.citrite.net",
      author="Citrix",
      author_email="svcacct_xs_xenrt@citrix.com",
      license="Apache",
      packages=['xenrtapi'],
      scripts=['scripts/xenrtnew'],
      zip_safe=True)
