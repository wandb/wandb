"""
Partial backport of Python 3.5's tempfile module:
    TemporaryDirectory
Backport modifications are marked with marked with "XXX backport".
Taken from: https://github.com/PiDelport/backports.tempfile
"""
from __future__ import absolute_import

import sys
import warnings as _warnings
from shutil import rmtree as _rmtree


# XXX backport:  Rather than backporting all of mkdtemp(), we just create a
# thin wrapper implementing its Python 3.5 signature.
if sys.version_info < (3, 5):
    from tempfile import mkdtemp as old_mkdtemp
    from .weakref import finalize

    def mkdtemp(suffix=None, prefix=None, dir=None):
        """
        Wrap `tempfile.mkdtemp()` to make the suffix and prefix optional.
        """
        kwargs = {
            k: v
            for (k, v) in dict(suffix=suffix, prefix=prefix, dir=dir).items()
            if v is not None
        }
        return old_mkdtemp(**kwargs)

    # XXX backport: ResourceWarning was added in Python 3.2.
    # For earlier versions, fall back to RuntimeWarning instead.
    if sys.version_info < (3, 2):
        _ResourceWarning = RuntimeWarning  # noqa: F821
    else:
        _ResourceWarning = ResourceWarning  # noqa: F821

    class TemporaryDirectory(object):
        """Create and return a temporary directory.  This has the same
        behavior as mkdtemp but can be used as a context manager.  For
        example:
            with TemporaryDirectory() as tmpdir:
                ...
        Upon exiting the context, the directory and everything contained
        in it are removed.
        """

        def __init__(
            self, suffix=None, prefix=None, dir=None, missing_ok_on_cleanup=False
        ):
            self._missing_ok_on_remove = missing_ok_on_cleanup
            self.name = mkdtemp(suffix, prefix, dir)
            self._finalizer = finalize(
                self,
                self._cleanup,
                self.name,
                warn_message="Implicitly cleaning up {!r}".format(self),
                missing_ok_on_cleanup=missing_ok_on_cleanup,
            )

        @classmethod
        def _cleanup(cls, name, warn_message, missing_ok_on_cleanup):
            try:
                _rmtree(name)
            # On windows only one process can open a file at a time
            except OSError:
                if not missing_ok_on_cleanup:
                    _warnings.warn("Couldn't remove temp directory %s" % name)
            # _warnings.warn(warn_message, _ResourceWarning)

        def __repr__(self):
            return "<{} {!r}>".format(self.__class__.__name__, self.name)

        def __enter__(self):
            return self.name

        def __exit__(self, exc, value, tb):
            self.cleanup()

        def cleanup(self):
            if self._finalizer.detach():
                try:
                    _rmtree(self.name)
                # On windows only one process can open a file at a time
                except OSError:
                    if not self._missing_ok_on_cleanup:
                        _warnings.warn("Couldn't remove temp directory %s" % self.name)


else:
    from tempfile import TemporaryDirectory as RealTemporaryDirectory

    class TemporaryDirectory(RealTemporaryDirectory):
        def __init__(self, *args, **kwargs):
            if "missing_ok_on_cleanup" in kwargs:
                del kwargs["missing_ok_on_cleanup"]
            super(TemporaryDirectory, self).__init__(*args, **kwargs)


__all__ = ["TemporaryDirectory"]
