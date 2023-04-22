import os
import platform
from pathlib import PurePath, PurePosixPath, PureWindowsPath

import pytest
from hypothesis import example, given, settings
from hypothesis.strategies import binary, one_of, sampled_from, text
from hypothesis_fspaths import fspaths
from wandb.sdk.lib.paths import (
    PROHIBITED_CHARS,
    RESERVED_NAMES,
    LogicalPath,
    sanitize_path,
)
from wandb.util import to_forward_slash_path


@pytest.mark.parametrize(
    "target,posix,windows,_bytes",
    [
        ("foo/bar.txt", "foo/bar.txt", "foo\\bar.txt", b"foo/bar.txt"),
        ("et/tu.txt", "et/tu.txt", "et/tu.txt", b"et\\tu.txt"),
        ("/ab/ra.txt", "/ab/ra.txt", "\\ab\\ra.txt", b"/ab/ra.txt"),
        ("C:/a/b.txt", "C:/a/b.txt", "C:\\a\\b.txt", b"C:/a/b.txt"),
    ],
)
def test_path_groups(target, posix, windows, _bytes):
    assert target == LogicalPath(target)
    assert target == LogicalPath(PurePosixPath(posix))
    assert target == LogicalPath(PureWindowsPath(windows))
    assert target == LogicalPath(_bytes) or platform.system() != "Windows"


@given(fspaths())
@example(b"")
@example(".")
@example("\\")
@example(PureWindowsPath("C:/foo/bar.txt"))
@example(PurePosixPath("x\\a/b.bin"))
def test_path_conversion(path):
    logical_path = LogicalPath(path)
    assert isinstance(logical_path, str)
    if platform.system() == "Windows":
        assert "\\" not in logical_path

    # For compatibility, enforce output identical to `to_forward_slash_path`.
    if isinstance(path, str):
        assert logical_path == to_forward_slash_path(path)


@given(fspaths())
def test_logical_path_is_idempotent(path):
    norm_path = LogicalPath(path)
    logical_path = LogicalPath(norm_path)
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


def test_sanitize_path_on_awful_input():
    path = '\r/foo\u0000/AUX/<:?"*>/\0/\n\\\tCOM5.tar.gz /'
    sanitized = sanitize_path(path)
    assert sanitized == PurePosixPath("foo/_AUX/______/_COM5.tar.gz")


@settings(max_examples=500)
@given(one_of(fspaths(), text(), binary()))
def test_sanitize_path_on_arbitrary_input(path):
    try:
        check_sanitized(sanitize_path(path))
    except UnicodeDecodeError:
        # Fuzz testing leads to some invalid UTF-8 sequences we don't try to handle.
        pass


@given(fspaths(), sampled_from(RESERVED_NAMES))
def test_sanitize_path_on_paths_with_reserved_parts(path, name):
    parts = list(PurePath(path_as_str(path)).parts)
    for i in range(len(parts)):
        cut = parts[:i] + [name] + parts[i:]
        check_sanitized(sanitize_path(PurePath(*cut)))


dangerous_chars = list(PROHIBITED_CHARS + "/\\ .")


@given(fspaths(), text(dangerous_chars))
@example(path="\x01", snippet="\\")
def test_sanitize_path_on_paths_with_dangerous_chars(path, snippet):
    path = path_as_str(path)
    bookended = snippet + path + snippet
    check_sanitized(sanitize_path(bookended))
    if len(bookended) > 1:
        m = len(bookended) // 2
        inserted = bookended[:m] + snippet + bookended[m:]
        check_sanitized(sanitize_path(inserted))


def check_sanitized(path):
    assert isinstance(path, PurePosixPath)
    assert not path.is_absolute()

    str_path = str(path)
    assert "\\" not in str_path
    assert all(c.isprintable() for c in str_path)
    assert all(c not in r'<>:"\|?*' for c in str_path)
    assert not str_path.endswith(" ")
    assert not str_path.endswith(".") or str_path == "."

    assert all(part not in RESERVED_NAMES for part in path.parts)
    assert path.stem not in RESERVED_NAMES


def path_as_str(path):
    if isinstance(path, (str, PurePath)):
        return str(path)
    if hasattr(path, "__fspath__"):
        path = path.__fspath__()
    if isinstance(path, bytes):
        try:
            return os.fsdecode(path)
        except UnicodeDecodeError:
            return repr(path)
    return str(path)
