import os
import platform
from functools import wraps
from pathlib import Path, PurePath, PurePosixPath
from typing import Any, NewType, Union

# Path _inputs_ should generally accept any kind of path. This is named the same and
# modeled after the hint defined in the Python standard library's `typeshed`:
# https://github.com/python/typeshed/blob/0b1cd5989669544866213807afa833a88f649ee7/stdlib/_typeshed/__init__.pyi#L56-L65
StrPath = Union[str, "os.PathLike[str]"]

# An artifact-relative or run-relative path. It is always POSIX-style.
LogicalFilePathStr = NewType("LogicalFilePathStr", str)

# A native path to a file on a local filesystem.
FilePathStr = NewType("FilePathStr", str)

URIStr = NewType("URIStr", str)


class LocalPath(str):
    """A string that represents a path on the local filesystem.

    It can be used as a pathlib.Path object.
    """

    def __new__(cls, path: StrPath) -> "LocalPath":
        if hasattr(path, "__fspath__"):
            path = path.__fspath__()
        if isinstance(path, bytes):
            path = os.fsdecode(path)
        return super().__new__(cls, str(Path(path)))

    def to_path(self) -> Path:
        """Convert to a local pathlib.Path."""
        return Path(self)

    def __getattr__(self, attr: str) -> Any:
        """Act like a subclass of pathlib.Path for all methods not defined on str."""
        result = getattr(self.to_path(), attr)
        if isinstance(result, Path):
            return LocalPath(result)
        if callable(result):

            @wraps(result)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                inner_result = result(*args, **kwargs)
                if isinstance(inner_result, Path):
                    return LocalPath(inner_result)
                return inner_result

            return wrapper
        return result

    def __truediv__(self, other: StrPath) -> "LocalPath":
        """Act like a PurePosixPath for the / operator, but return a LocalPath."""
        return LocalPath(self.to_path() / other)

    def __eq__(self, other: object) -> bool:
        """Compare equal with Path objects."""
        if isinstance(other, Path):
            return self.to_path() == other
        return super().__eq__(other)

    def __ne__(self, other: object) -> bool:
        """Compare not equal with Path objects."""
        if isinstance(other, Path):
            return self.to_path() != other
        return super().__ne__(other)


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

    def __new__(cls, path: StrPath) -> "LogicalPath":
        if hasattr(path, "as_posix"):
            path = path.as_posix()
        if hasattr(path, "__fspath__"):
            path = path.__fspath__()  # Can be str or bytes.
        if isinstance(path, bytes):
            path = os.fsdecode(path)
        path = str(path)
        if platform.system() == "Windows":
            path = path.replace("\\", "/")
        path = str(PurePosixPath(path))
        return super().__new__(cls, path)

    def to_path(self) -> PurePosixPath:
        """Convert this path to a PurePosixPath."""
        return PurePosixPath(self)

    def __getattr__(self, attr: str) -> Any:
        """Act like a subclass of PurePosixPath for all methods not defined on str."""
        try:
            result = getattr(self.to_path(), attr)
        except AttributeError as e:
            raise AttributeError(f"LogicalPath has no attribute {attr!r}") from e

        if isinstance(result, PurePosixPath):
            return LogicalPath(result)

        # If the result is a callable (a method), wrap it so that it has the same
        # behavior: if the call result returns a PurePosixPath, return a LogicalPath.
        if callable(result):

            @wraps(result)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                inner_result = result(*args, **kwargs)
                if isinstance(inner_result, PurePosixPath):
                    return LogicalPath(inner_result)
                return inner_result

            return wrapper
        return result

    def __truediv__(self, other: StrPath) -> "LogicalPath":
        """Act like a PurePosixPath for the / operator, but return a LogicalPath."""
        return LogicalPath(self.to_path() / other)

    def __eq__(self, other: object) -> bool:
        """Compare equal with PurePosixPath objects."""
        if isinstance(other, PurePosixPath):
            return self.to_path() == other
        return super().__eq__(other)

    def __ne__(self, other: object) -> bool:
        """Compare not equal with PurePosixPath objects."""
        if isinstance(other, PurePosixPath):
            return self.to_path() != other
        return super().__ne__(other)

