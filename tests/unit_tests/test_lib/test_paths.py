from __future__ import annotations

import itertools
import platform
import re
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath

import pytest
from wandb.sdk.lib.paths import LogicalPath
from wandb.util import to_forward_slash_path


# Once upon a time I used hypothesis and fspaths to generate test cases. This was a good
# thing, and unearthed many many corner cases I had not accounted for. But it was a bad
# thing as well, because it found them over time, one by one, and generally on CI,
# flaking on innocent developers.
# Instead, we'll deterministically test on a large set of known difficult cases.
def pathological_path_strings(max_length=6, alphabet="./\\C:"):
    """All possible strings of up to `max_length` drawn from the given alphabet."""
    for n in range(max_length + 1):
        for seq in itertools.product(alphabet, repeat=n):
            yield "".join(seq)


def pathological_paths(max_length=6, alphabet="./\\x", include_bytes=True):
    for path_str in pathological_path_strings(max_length, alphabet):
        yield path_str
        if include_bytes:
            yield path_str.encode("ascii")
        yield Path(path_str)
        yield PurePosixPath(path_str)
        yield PureWindowsPath(path_str)


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
    #    4a. Anchors are preserved: `///a` and `/a` are `/a`.
    #    4b. `//a` is `//a`, since '//' is a separate anchor. `///+` is always `/`.
    #        4b(i). `//` is not an anchor on Windows unless it's succeeded by a
    #               directory followed by a single slash.
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
        # On Windows, this gets even weirder. The anchor is "/" instead of "//" unless
        # the first non-anchor directory marker is also doubled. We're not trying to
        # replicate this logic.
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


def test_path_conversion():
    for path in pathological_paths():
        logical_path = LogicalPath(path)
        assert isinstance(logical_path, str)
        if not isinstance(path, str):
            continue

        if logical_path.anchor:
            # Anchor handling can get REALLY WEIRD. It shouldn't ever come up in
            # practice (LogicalPaths are supposed to be relative anyway!), and trying to
            # follow the logic of how its done is way too complicated. Instead we can
            # compare paths by ignoring the anchor.
            relative = logical_path.relative_to(logical_path.anchor)
            matching = forward_slash_path_conversion(path).lstrip("/")
            assert relative == matching or matching == ""
        else:
            assert logical_path == forward_slash_path_conversion(path)

        if platform.system() == "Windows":
            assert "\\" not in logical_path


def test_logical_path_matches_to_posix_path():
    # If PurePosixPath can be constructed it should be the same as the LogicalPath.
    for path in pathological_paths(include_bytes=False):
        logical_path = LogicalPath(path)
        path_obj = path if isinstance(path, PurePath) else PurePath(path)
        posix_path = PurePosixPath(path_obj.as_posix())
        assert posix_path == logical_path.to_path()
        assert str(posix_path) == logical_path


def test_logical_path_is_idempotent():
    for path in pathological_paths():
        logical_path = LogicalPath(path)
        assert logical_path == LogicalPath(logical_path)
        if isinstance(path, str):
            assert logical_path == LogicalPath(to_forward_slash_path(path))
            assert logical_path == to_forward_slash_path(logical_path)


def test_logical_path_round_trip():
    for path in pathological_paths():
        logical_path = LogicalPath(path)
        posix_path = logical_path.to_path()
        assert isinstance(posix_path, PurePosixPath)
        assert posix_path == LogicalPath(posix_path).to_path()
        assert str(posix_path) == LogicalPath(posix_path) or not path


def test_logical_path_acts_like_posix_path():
    for path in pathological_paths(include_bytes=False):
        lp = LogicalPath(path)
        local_path = PurePath(path) if isinstance(path, str) else path
        ppp = PurePosixPath(local_path.as_posix())
        assert lp.is_absolute() == ppp.is_absolute()
        assert lp.parts == ppp.parts
        assert not lp.is_reserved()
        if lp.is_absolute():
            assert lp.root == "/" or lp.root == "//"
            assert lp.as_uri() == ppp.as_uri()
            assert not lp.relative_to(lp.root).is_absolute()
        else:
            assert lp.anchor == ""
        assert lp / PurePosixPath("/foo") == LogicalPath("/foo")

        itself = lp.joinpath("bar").parent
        assert isinstance(itself, LogicalPath)
        assert PurePosixPath(itself) == ppp


def test_logical_path_joins_like_pathlib():
    base_path_set = pathological_path_strings(max_length=3)
    for path1, path2 in itertools.product(base_path_set, repeat=2):
        lp1 = LogicalPath(path1)
        lp2 = LogicalPath(path2)
        assert lp1.joinpath(lp2) == lp1 / path2
