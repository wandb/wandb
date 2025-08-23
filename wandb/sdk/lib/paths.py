from __future__ import annotations

import os
import platform
from functools import wraps
from pathlib import PurePath, PurePosixPath
from typing import Any, Union

from typing_extensions import TypeAlias

# Path _inputs_ should generally accept any kind of path. This is named the same and
# modeled after the hint defined in the Python standard library's `typeshed`:
# https://github.com/python/typeshed/blob/0b1cd5989669544866213807afa833a88f649ee7/stdlib/_typeshed/__init__.pyi#L56-L65
StrPath: TypeAlias = Union[str, "os.PathLike[str]"]

FilePathStr: TypeAlias = str  #: A native path to a file on a local filesystem.
URIStr: TypeAlias = str


class LogicalPath(str):
    """A string that represents a path relative to an artifact or run.

    The format of the string is always as a POSIX path, e.g. "foo/bar.txt".

    A neat trick is that you can use this class as if it were a PurePosixPath. E.g.:
    ```
    >>> path = LogicalPath("foo/bar.txt")
    >>> path.parts
    ('foo', 'bar.txt')
    >>> path.parent / "baz.txt"
    'foo/baz.txt'
    >>> type(path.relative_to("foo"))
    LogicalPath
    ```
    """

    # It should probably always be a relative path, but that would be a behavior change.
    #
    # These strings used to be the output of `to_forward_slash_path`, which only works
    # with strings and whose behavior is pretty simple:
    # ```
    # if platform.system() == "Windows":
    #     path = path.replace("\\", "/")
    # ```
    #
    # This results in some weird things, such as backslashes being allowed from
    # non-Windows platforms (which would probably break if such an artifact was used
    # from Windows) and anchors or absolute paths being allowed. E.g., the Windows path
    # "C:\foo\bar.txt" becomes "C:/foo/bar.txt", which then would mount as
    # "./artifacts/artifact_name:v0/C:/foo/bar.txt" on MacOS and as
    # "./artifacts/artifact_name-v0/C-/foo/bar.txt" on Windows.
    #
    # This implementation preserves behavior for strings but attempts to sanitize other
    # formerly unsupported inputs more aggressively. It uses the `.as_posix()` form of
    # pathlib objects rather than the `str()` form to reduce how often identical inputs
    # will result in different outputs on different platforms; however, it doesn't alter
    # absolute paths or check for prohibited characters etc.

    def __new__(cls, path: StrPath) -> LogicalPath:
        if isinstance(path, LogicalPath):
            return super().__new__(cls, path)
        if hasattr(path, "as_posix"):
            path = PurePosixPath(path.as_posix())
            return super().__new__(cls, str(path))
        if hasattr(path, "__fspath__"):
            path = path.__fspath__()  # Can be str or bytes.
        if isinstance(path, bytes):
            path = os.fsdecode(path)
        # For historical reasons we have to convert backslashes to forward slashes, but
        # only on Windows, and need to do it before any pathlib operations.
        if platform.system() == "Windows":
            path = path.replace("\\", "/")
        # This weird contortion and the one above are because in some unusual cases
        # PurePosixPath(path.as_posix()).as_posix() != path.as_posix().
        path = PurePath(path).as_posix()
        return super().__new__(cls, str(PurePosixPath(path)))

    def to_path(self) -> PurePosixPath:
        """Convert this path to a PurePosixPath."""
        return PurePosixPath(self)

    def __getattr__(self, name: str) -> Any:
        """Act like a subclass of PurePosixPath for all methods not defined on str."""
        try:
            attr = getattr(self.to_path(), name)
        except AttributeError:
            classname = type(self).__qualname__
            raise AttributeError(f"{classname!r} has no attribute {name!r}") from None

        if isinstance(attr, PurePosixPath):
            return LogicalPath(attr)

        # If the result is a callable (a method), wrap it so that it has the same
        # behavior: if the call result returns a PurePosixPath, return a LogicalPath.
        if callable(fn := attr):

            @wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                if isinstance(res := fn(*args, **kwargs), PurePosixPath):
                    return LogicalPath(res)
                return res

            return wrapper
        return attr

    def __truediv__(self, other: StrPath) -> LogicalPath:
        """Act like a PurePosixPath for the / operator, but return a LogicalPath."""
        return LogicalPath(self.to_path() / LogicalPath(other))
