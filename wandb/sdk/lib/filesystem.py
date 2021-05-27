#
import errno
import os
import re
import threading


import wandb


if wandb.TYPE_CHECKING:
    from typing import BinaryIO


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


class WriteSerializingFile(object):
    """Wrapper for a file object that serializes writes.
    """

    def __init__(self, f: BinaryIO) -> None:
        self.lock = threading.Lock()
        self.f = f

    def write(self, *args, **kargs) -> None:  # type: ignore
        self.lock.acquire()
        try:
            self.f.write(*args, **kargs)
            self.f.flush()
        finally:
            self.lock.release()

    def close(self) -> None:
        self.lock.acquire()  # wait for pending writes
        try:
            self.f.close()
        finally:
            self.lock.release()


class CRDedupedFile(WriteSerializingFile):
    def __init__(self, f: BinaryIO) -> None:
        super(CRDedupedFile, self).__init__(f=f)
        self._buff = b""

    def write(self, data) -> None:  # type: ignore
        lines = re.split(b"\r\n|\n", data)
        ret = []  # type: ignore
        for line in lines:
            if line[:1] == b"\r":
                if ret:
                    ret.pop()
                elif self._buff:
                    self._buff = b""
            line = line.split(b"\r")[-1]
            if line:
                ret.append(line)
        if self._buff:
            ret.insert(0, self._buff)
        if ret:
            self._buff = ret.pop()
        super(CRDedupedFile, self).write(b"\n".join(ret) + b"\n")

    def close(self) -> None:
        if self._buff:
            super(CRDedupedFile, self).write(self._buff)
        super(CRDedupedFile, self).close()
