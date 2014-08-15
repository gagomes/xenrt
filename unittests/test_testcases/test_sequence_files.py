from unittest import case
import os
from nose import tools
from xml.dom import minidom

from testing import XenRTUnitTestCase


EXCLUDED_SEQS = [
    'clearwaterminiperf.seq',
]


EXCLUDED_ID_PATTERNS = [
    '.perf.',
]


def get_xenrt_root():
    this_file = os.path.abspath(__file__)
    this_dir = os.path.dirname(this_file)

    xenrt_root = os.path.join(this_dir, '..', '..')
    return xenrt_root


def get_sequence_directory():
    return os.path.join(get_xenrt_root(), 'seqs')


def get_path_to_sequence(sequence):
    return os.path.join(get_sequence_directory(), sequence)


def get_sequence(sequence):
    with open(get_path_to_sequence(sequence), 'rb') as sequence_file:
        return sequence_file.read()


def assert_valid_module(module_segments):
    if module_segments[0] == 'testcases':
        module_segments = module_segments[1:]

    absolute_path_segments = (
        [get_xenrt_root(), 'exec', 'testcases'] + module_segments
    )

    filename = os.path.join(*absolute_path_segments) + '.py'

    if not os.path.exists(filename):
        raise AssertionError('%s does not exist' % filename)
    if not os.path.isfile(filename):
        raise AssertionError('%s is not a file' % filename)


def assert_id_valid(test_id):
    segments = test_id.split('.')

    if len(segments) < 2:
        raise AssertionError('%s does not look like a valid id' % test_id)

    module_segments = segments[:-1]

    assert_valid_module(module_segments)


def assert_sequence_file_points_to_an_existing_module(sequence):
    seq = get_sequence(sequence)
    document = minidom.parseString(seq)

    testcases = document.getElementsByTagName('testcase')

    for testcase in testcases:
        test_id = testcase.getAttribute('id')

        for id_pattern in EXCLUDED_ID_PATTERNS:
            if id_pattern in test_id:
                raise case.SkipTest(
                    'test id %s is filtered out by EXCLUDED_ID_PATTERNS' %
                    test_id)
        assert_id_valid(test_id)


def test_sequence_files():
    for fname in os.listdir(get_sequence_directory()):
        if fname in EXCLUDED_SEQS:
            raise case.SkipTest('found in EXCLUDED_SEQS')

        yield assert_sequence_file_points_to_an_existing_module, fname
