from typing import TYPE_CHECKING, NewType, Union

if TYPE_CHECKING:
    import os

# Path _inputs_ should generally accept any kind of path. This is named the same and
# modeled after the hint defined in the Python standard library's `typeshed`:
# https://github.com/python/typeshed/blob/0b1cd5989669544866213807afa833a88f649ee7/stdlib/_typeshed/__init__.pyi#L56-L65
StrPath = Union[str, "os.PathLike[str]"]


# An artifact-relative or run-relative path. It is always POSIX-style.
# This *should* be a PurePosixPath, but changing now it would change the public API.
LogicalFilePathStr = NewType("LogicalFilePathStr", str)

# A native path to a file on a local filesystem.
# Ideally it would be a pathlib.Path, but it's too late now.
FilePathStr = NewType("FilePathStr", str)

# A URI. Likewise, it should be a urllib.parse.ParseResult, but it's too late now.
URIStr = NewType("URIStr", str)
