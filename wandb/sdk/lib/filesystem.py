#
import errno
import os


def _safe_makedirs(dir_name):
    try:
        os.makedirs(dir_name)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise
    if not os.path.isdir(dir_name):
        raise Exception("not dir")
    if not os.access(dir_name, os.W_OK):
        raise Exception("cant write: {}".format(dir_name))
