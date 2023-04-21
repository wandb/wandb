from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    import os

# Path _inputs_ should generally accept any kind of path. This is named the same and
# modeled after the hint defined in the Python standard library's `typeshed`:
# https://github.com/python/typeshed/blob/0b1cd5989669544866213807afa833a88f649ee7/stdlib/_typeshed/__init__.pyi#L56-L65
StrPath = Union[str, "os.PathLike[str]"]


def to_posixpath(path: StrPath) -> PurePosixPath:
    path = Path(path)
    anchor = path.anchor
    if anchor:
        return PurePosixPath("/") / path.relative_to(anchor).as_posix()
    return PurePosixPath(path.as_posix())
