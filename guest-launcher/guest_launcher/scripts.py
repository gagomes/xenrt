import sys
import argparse
import logging

from guest_launcher import executor
from guest_launcher import snapshot
from guest_launcher import guest_starter


def parse_args_for_snap(args):
    parser = argparse.ArgumentParser()
    parser.add_argument('guest_spec')
    return parser.parse_args(args)


def init_logging():
    logging.basicConfig(level=logging.DEBUG)


def snap():
    params = parse_args_for_snap(None)
    init_logging()
    xecutor = executor.Executor()

    snapshotter = snapshot.create_snapshotter(params.guest_spec, xecutor)

    snapshotter.snap()


def create_executor():
    return executor.Executor()


def start(args=None, stdout=None):
    init_logging()
    params = parse_args_for_snap(args)
    starter = guest_starter.create_guest_starter(
        params.guest_spec, create_executor())
    ip_address = starter.start()
    stdout = stdout or sys.stdout
    stdout.write(ip_address)
    stdout.write('\n')
