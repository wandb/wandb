import os
import platform
from functools import wraps
from pathlib import PurePath, PurePosixPath
from typing import Any, NewType, Union

# Path _inputs_ should generally accept any kind of path. This is named the same and
# modeled after the hint defined in the Python standard library's `typeshed`:
# https://github.com/python/typeshed/blob/0b1cd5989669544866213807afa833a88f649ee7/stdlib/_typeshed/__init__.pyi#L56-L65
StrPath = Union[str, "os.PathLike[str]"]

# A native path to a file on a local filesystem.
# Ideally it would be a pathlib.Path, but it's too late now.
FilePathStr = NewType("FilePathStr", str)

# A URI. Likewise, it should be a urllib.parse.ParseResult, but it's too late now.
URIStr = NewType("URIStr", str)


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
        return super().__new__(cls, path)

    def to_path(self) -> PurePosixPath:
        """Convert this path to a PurePosixPath."""
        return PurePosixPath(self)

    def __getattr__(self, attr: str) -> Any:
        """Act like a subclass of PurePosixPath for all methods not defined on str."""
        result = getattr(self.to_path(), attr)
        if isinstance(result, PurePosixPath):
            return LogicalPath(result)
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


PROHIBITED_CHARS = r'<>:"|?*'
RESERVED_NAMES = (
    ["CON", "PRN", "AUX", "NUL"]
    + ["COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9"]
    + ["LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"]
)


def sanitize_path(path: StrPath) -> PurePosixPath:
    """Convert a path to a Path that can be used as a relative path on any platform.

    This destructively modifies the path to be POSIX-style, removing anchors, converting
    "legal" backslashes to forward slashes, and removing or replacing all characters
    that might be allowed locally but are not allowed universally.
    """
    # Convert any non-pathlib object to a native PurePath.
    if not isinstance(path, PurePath) and hasattr(path, "__fspath__"):
        path = path.__fspath__()
    if isinstance(path, bytes):
        path = os.fsdecode(path)
    if isinstance(path, str):
        path = PurePath(path)

    # If absolute, make relative to the root/drive. Either way, convert to a posix str.
    path_str = path.relative_to(path.anchor).as_posix()

    # Remove unprintable characters.
    path_str = "".join(c for c in path_str if c.isprintable())

    # Replace all backslashes with forward slashes.
    path = PurePosixPath(path_str.replace("\\", "/"))

    # We do this again because the previous steps may have introduced a new root.
    path_str = path.relative_to(path.anchor).as_posix()

    # Replace characters not allowed in Windows filenames.
    path_str = "".join(c if c not in PROHIBITED_CHARS else "_" for c in path_str)

    # Strip trailing dots and spaces (another Windows requirement).
    # Also normalize by eliminating trailing slashes.
    path_str = path_str.rstrip(" ./")

    # Alter any path parts that are reserved on Windows.
    parts = list(PurePosixPath(path_str).parts)
    parts = [part if part not in RESERVED_NAMES else f"_{part}" for part in parts]
    posix_path = PurePosixPath(*parts)
    if posix_path.name.split(".")[0] in RESERVED_NAMES:
        posix_path = posix_path.with_name(f"_{posix_path.name}")

    return posix_path
