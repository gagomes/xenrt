from setuptools import setup

setup(name='xenrtapi',
      version='0.09',
      description="API for XenRT",
      url="https://xenrt.citrite.net",
      author="Citrix",
      author_email="svcacct_xs_xenrt@citrix.com",
      license="Apache",
      packages=['xenrtapi'],
      scripts=['scripts/xenrtnew', 'scripts/xenrt'],
      zip_safe=True)
