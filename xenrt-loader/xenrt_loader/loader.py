import sys
import os

_xenrt_root = None


def get_xenrt_root():
    global _xenrt_root
    if _xenrt_root is None:
        raise Exception('xenrt not loaded')
    return _xenrt_root


def load_xenrt(xenrt_root):
    sys.path.append(os.path.join(xenrt_root, 'exec'))
    sys.path.append(os.path.join(xenrt_root, 'lib'))
    sys.modules['xenrt.ctrl'] = object()
    global _xenrt_root
    _xenrt_root = xenrt_root
