from setuptools import setup


setup(
    name='xenrt_loader',
    packages=['xenrt_loader'],
    tests_require=['mock'],
    entry_points={
        'nose.plugins': [
            'xenrt-importer = '
            + 'xenrt_loader.nose_plugin:XenRTImporterNosePlugin'
        ],
    }
)
