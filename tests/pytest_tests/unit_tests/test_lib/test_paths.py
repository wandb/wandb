import platform
from pathlib import PurePosixPath, PureWindowsPath

import pytest
from hypothesis import assume, example, given
from hypothesis_fspaths import fspaths
from wandb.sdk.lib.paths import LogicalPath
from wandb.util import to_forward_slash_path


@pytest.mark.parametrize(
    "target,posix,windows,_bytes",
    [
        ("foo/bar.txt", "foo/bar.txt", "foo\\bar.txt", b"foo/bar.txt"),
        ("et/tu.txt", "et//tu.txt", "et/tu.txt", b"et//tu.txt"),
        ("/ab/ra.txt", "/ab/ra.txt", "\\ab\\ra.txt", b"/ab/ra.txt"),
        ("C:/a/b.txt", "C:/a/b.txt", "C:\\a\\b.txt", b"C:/a/b.txt"),
    ],
)
def test_path_groups(target, posix, windows, _bytes):
    assert target == LogicalPath(target)
    assert target == LogicalPath(PurePosixPath(posix))
    assert target == LogicalPath(PureWindowsPath(windows))
    assert target == LogicalPath(_bytes)


@given(fspaths())
@example(b"")
@example(".")
@example("\\\\")
@example(" /")
@example("/")
@example(PureWindowsPath("C:/foo/bar.txt"))
@example(PurePosixPath("x\\a/b.bin"))
@pytest.mark.skip(reason="TODO: Hypothesis keeps finding corner cases.")
def test_path_conversion(path):
    logical_path = LogicalPath(path)
    assert isinstance(logical_path, str)
    if platform.system() == "Windows":
        assert "\\" not in logical_path

    # For compatibility, enforce output identical to `to_forward_slash_path`.
    # Three exceptions, none should affect the interpretation of the path:
    # 1. We send both `'.'` and `''` to `'.'`
    # 2. We strip trailing slashes
    # 3. We collapse multiple slashes (e.g. `'a//b'` -> `'a/b'`)
    if path and isinstance(path, str):
        canonical = to_forward_slash_path(path)
        while "//" in canonical:
            canonical = canonical.replace("//", "/")
        # We strip trailing slashes, but obviously not the root path.
        if canonical.startswith("/") and canonical.rstrip("/") == "":
            canonical = "/"
        else:
            canonical = canonical.rstrip("/")
        assert logical_path == canonical


@given(fspaths())
def test_logical_path_matches_to_posix_path(path):
    # If PurePosixPath can be constructed it should be the same as the LogicalPath.
    try:
        posix_path = PurePosixPath(path)
    except TypeError:
        assume(False)  # Tell hypothesis to skip these examples.

    assert posix_path == LogicalPath(path).to_path()
    assert str(posix_path) == LogicalPath(path)


@given(fspaths())
def test_logical_path_is_idempotent(path):
    logical_path = LogicalPath(path)
    assert logical_path == LogicalPath(logical_path)
    assert logical_path == LogicalPath(to_forward_slash_path(logical_path))
    assert logical_path == to_forward_slash_path(LogicalPath(logical_path))


@given(fspaths())
def test_logical_path_round_trip(path):
    logical_path = LogicalPath(path)
    posix_path = logical_path.to_path()
    assert isinstance(posix_path, PurePosixPath)
    assert posix_path == LogicalPath(posix_path).to_path()
    assert str(posix_path) == LogicalPath(posix_path) or not path


@given(fspaths(), fspaths())
def test_logical_path_acts_like_posix_path(path1, path2):
    path1 = LogicalPath(path1)
    assert path1.is_absolute() == PurePosixPath(path1).is_absolute()
    assert path1.parts == PurePosixPath(path1).parts
    assert not path1.is_reserved()
    if path1.is_absolute():
        assert path1.root == "/"
        assert path1.as_uri() == PurePosixPath(path1).as_uri()
        assert not path1.relative_to(path1.root).is_absolute()
    else:
        assert path1.anchor == ""

    itself = path1.joinpath("bar").parent
    assert isinstance(itself, LogicalPath)
    assert PurePosixPath(itself) == PurePosixPath(path1)

    path2 = LogicalPath(path2)
    assert path1 / path2 == path1.joinpath(path2)
    assert path1 / PurePosixPath("/foo") == LogicalPath("/foo")
