import sys
import os
import imp

_xenrt_root = None


def get_xenrt_root():
    global _xenrt_root
    if _xenrt_root is None:
        raise Exception('xenrt not loaded')
    return _xenrt_root


def read_file(path):
    with open(path, 'rb') as fhandle:
        return fhandle.read()


def load_xenrt(xenrt_root):
    sys.path.insert(1, os.path.join(xenrt_root, 'server'))
    sys.path.append(os.path.join(xenrt_root, 'exec'))
    sys.path.append(os.path.join(xenrt_root, 'lib'))
    xenrt_in_path = os.path.join(xenrt_root, 'control', 'xenrt.in')

    xenrt_in_code = read_file(xenrt_in_path)

    xenrt_ctrl_module = imp.new_module(xenrt_in_path)
    exec(xenrt_in_code, xenrt_ctrl_module.__dict__)

    sys.modules['xenrt.ctrl'] = xenrt_ctrl_module

    import xenrt
    xenrt.ctrl = xenrt_ctrl_module
    global _xenrt_root
    _xenrt_root = xenrt_root
