import itertools
import platform
import re
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


def forward_slash_path_conversion(path):
    # For compatibility, we want to enforce output identical to `to_forward_slash_path`.
    # However, there are many paths that os.open etc. will coerce to the same path, and
    # we'd like to keep only one canonical representation (otherwise we can break things
    # by having artifact paths that have distinct keys but identical file paths).
    #
    # For completeness:
    # 1. The empty path '.' or '' is always represented as '.'.
    # 2. A directory is always represented as `.../d`, never as `.../d/` or `.../d/.`.
    # 3. Current directories are folded: `./a/././b` is `a/b`.
    # 4. Empty directories are folded: `a///b` is `a/b`.
    #    4a. Anchors are preserved: `///a` is `/a`, `//a` is `//a`. ("//" is a separate
    #        anchor from "/", but on posix systems "///" is considered "/").
    #
    # NOTE: there are still paths that collide! In particular, it's not possible in the
    # presence of symlinks to determine whether `a/../b` and `b` are the same path
    # without checking a specific filesystem, so those are still stored as separate
    # paths, but will almost certainly break something if they're used.
    #
    # There are also deeply broken paths (mostly due to cross platform issues) that we
    # aren't attempting to fix or work around and will just break in unpleasant ways.
    canonical = to_forward_slash_path(path)

    if re.match(r"//([^/]|$)", canonical):
        anchor, body = "//", canonical[2:]  # The anchor is "//".
    elif re.match(r"/+", canonical):
        anchor, body = "/", canonical.lstrip("/")  # The anchor is "/".
    else:
        anchor, body = "", canonical  # There is no anchor.

    while re.match(r"\./+", body):
        body = re.sub(r"^\./+", "", body)  # Remove leading "./".
    while re.findall(r"/+\./+", body):
        body = re.sub(r"/+\./+", "/", body)  # Replace "/./" with "/".
    while re.findall(r"/+\.?$", body):
        body = re.sub(r"/+\.?$", "", body)  # Remove trailing "/." or "/".
    while re.findall(r"//+", body):
        body = re.sub(r"//+", "/", body)  # Replace "//" with "/".

    if anchor and body == ".":
        body = ""
    canonical = anchor + body
    if not canonical:
        canonical = "."

    return canonical


@given(fspaths())
@example(b"")
@example(".")
@example("\\\\")
@example(" /")
@example("/")
@example(PureWindowsPath("C:/foo/bar.txt"))
@example(PurePosixPath("x\\a/b.bin"))
def test_path_conversion(path):
    logical_path = LogicalPath(path)
    assert isinstance(logical_path, str)
    if platform.system() == "Windows":
        assert "\\" not in logical_path

    if isinstance(path, str):
        assert logical_path == forward_slash_path_conversion(path)


def test_path_conversion_pathological():
    path_chars = "./\\x"  # One normal character and three that cause problems.

    # Exercise every path up to length 6 (all 5204 of them) consisting of path_chars.
    for i in range(1, 5):
        for seq in itertools.product(path_chars, repeat=i):
            path = "".join(seq)
            assert str(LogicalPath(path)) == forward_slash_path_conversion(path)


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
