import errno
import logging
import os
import platform
import re
import shutil
import threading
from os import stat
from typing import BinaryIO

logger = logging.getLogger(__name__)

WRITE_PERMISSIONS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH | stat.S_IWRITE


def _safe_makedirs(dir_name: str) -> None:
    try:
        os.makedirs(dir_name)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise
    if not os.path.isdir(dir_name):
        raise Exception("not dir")
    if not os.access(dir_name, os.W_OK):
        raise Exception(f"cant write: {dir_name}")


class WriteSerializingFile:
    """Wrapper for a file object that serializes writes."""

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
        super().__init__(f=f)
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
        super().write(b"\n".join(ret) + b"\n")

    def close(self) -> None:
        if self._buff:
            super().write(self._buff)
        super().close()


def copy_or_overwrite_changed(source_path, target_path):
    """Copy source_path to target_path, unless it already exists with the same mtime.

    We liberally add write permissions to deal with the case of multiple users needing
    to share the same cache or run directory.

    Args:
        source_path: The path to the file to copy.
        target_path: The path to copy the file to.
    Returns:
        The path to the copied file (which may be different from target_path).
    """

    if platform.system() == "Windows" and ":" in target_path:
        logger.warning(f"Replacing ':' in {target_path} with '-'")
        head, tail = os.path.splitdrive(target_path)
        target_path = head + tail.replace(":", "-")

    need_copy = (
        not os.path.isfile(target_path)
        or stat(source_path).st_mtime != stat(target_path).st_mtime
    )

    if need_copy:
        _safe_makedirs(os.path.dirname(target_path))
        try:
            # Use copy2 to preserve file metadata (including modified time).
            shutil.copy2(source_path, target_path)
        except PermissionError:
            # If the file is read-only try to make it writable. Let any exceptions after
            # this point propagate since we can't fix them.
            os.chmod(target_path, WRITE_PERMISSIONS)
            shutil.copy2(source_path, target_path)
        # Prevent future permissions issues by universal write permissions now.
        os.chmod(target_path, WRITE_PERMISSIONS)

    return target_path
