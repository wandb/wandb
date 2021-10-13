#
# -*- coding: utf-8 -*-
"""
progress.
"""

import os

from wandb.errors import CommError


class Progress(object):
    """A helper class for displaying progress"""

    ITER_BYTES = 1024 * 1024

    def __init__(self, file, callback=None):
        self.file = file
        if callback is None:

            def callback(bites, total):
                return (bites, total)

        self.callback = callback
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

    def rewind(self):
        self.callback(0, -self.bytes_read)
        self.bytes_read = 0
        self.file.seek(0)

    def __iter__(self):
        return self

    def __next__(self):
        bites = self.read(self.ITER_BYTES)
        if len(bites) == 0:
            raise StopIteration
        return bites

    next = __next__
