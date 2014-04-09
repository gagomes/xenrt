# Guest Launcher

Utility to launch guests from a given snapshot. To take a snapshot of the
virtual machine "windows" hosted on by virtualbox on your local computer
with a snapshot name of "snap":

    gl-snap virtualbox:windows/snap

To start the same snapshot - assuming relevant ports forwarded to 127.0.0.1:

    gl-start virtualbox-pfwd:127.0.0.1:windows/snap

## Installation

    python setup.py install

## Development

    python setup.py develop
    nosetests --with-coverage --cover-package=guest_launcher --cover-erase
