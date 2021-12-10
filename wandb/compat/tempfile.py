"""
Partial backport of Python 3.5's tempfile module:
    TemporaryDirectory
Backport modifications are marked with marked with "XXX backport".
Taken from: https://github.com/PiDelport/backports.tempfile
"""

from tempfile import TemporaryDirectory as RealTemporaryDirectory


class TemporaryDirectory(RealTemporaryDirectory):
    def __init__(self, *args, **kwargs):
        if "missing_ok_on_cleanup" in kwargs:
            del kwargs["missing_ok_on_cleanup"]
        super().__init__(*args, **kwargs)


__all__ = ["TemporaryDirectory"]
