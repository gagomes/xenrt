from setuptools import setup


setup(
    name='guest_launcher',
    packages=['guest_launcher'],
    tests_require=['mock'],
    entry_points={
        'console_scripts': [
            'gl-snap = guest_launcher.scripts:snap',
            'gl-start = guest_launcher.scripts:start',
        ],
        'nose.plugins': [
            'guest-launcher = '
            + 'guest_launcher.nose_plugin:GuestLauncherNosePlugin'
        ],
    }
)
