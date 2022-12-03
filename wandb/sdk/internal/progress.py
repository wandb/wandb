"""
progress.
"""

import os
import sys
from typing import IO, TYPE_CHECKING, Optional

from wandb.errors import CommError

if TYPE_CHECKING:
    if sys.version_info >= (3, 8):
        from typing import Protocol
    else:
        from typing_extensions import Protocol

    class ProgressFn(Protocol):
        def __call__(self, new_bytes: int, total_bytes: int) -> None:
            pass


class Progress:
    """A helper class for displaying progress"""

    ITER_BYTES = 1024 * 1024

    def __init__(
        self, file: IO[bytes], callback: Optional["ProgressFn"] = None
    ) -> None:
        self.file = file
        if callback is None:

            def callback_(new_bytes: int, total_bytes: int) -> None:
                pass

            callback = callback_

        self.callback: "ProgressFn" = callback
        self.bytes_read = 0
        self.len = os.fstat(file.fileno()).st_size

    def read(self, size=-1):
        """Read bytes and call the callback"""
        bites = self.file.read(size)
        self.bytes_read += len(bites)
        if not bites and self.bytes_read < self.len:
            # Files shrinking during uploads causes request timeouts. Maybe
            # we could avoid those by updating the self.len in real-time, but
            # files getting truncated while uploading seems like something
            # that shouldn't really be happening anyway.
            raise CommError(
                "File {} size shrank from {} to {} while it was being uploaded.".format(
                    self.file.name, self.len, self.bytes_read
                )
            )
        # Growing files are also likely to be bad, but our code didn't break
        # on those in the past so it's riskier to make that an error now.
        self.callback(len(bites), self.bytes_read)
        return bites

    def rewind(self) -> None:
        self.callback(-self.bytes_read, 0)
        self.bytes_read = 0
        self.file.seek(0)

    def __getattr__(self, name):
        """Fallback to the file object for attrs not defined here"""
        if hasattr(self.file, name):
            return getattr(self.file, name)
        else:
            raise AttributeError

    def __iter__(self):
        return self

    def __next__(self):
        bites = self.read(self.ITER_BYTES)
        if len(bites) == 0:
            raise StopIteration
        return bites

    def __len__(self):
        return self.len

    next = __next__
