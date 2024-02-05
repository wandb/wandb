"""Information about the workspace for wini build scripts."""

import enum
import platform
import subprocess


def git_commit_sha():
    """Returns the hash of the current Git commit."""
    return subprocess.check_output(["git", "rev-parse", "HEAD"]).decode("utf-8").strip()


class OS(enum.Enum):
    """A possible operating system to build for."""

    OTHER = 0
    LINUX = enum.auto()
    DARWIN = enum.auto()


class Arch(enum.Enum):
    """A possible architecture to build for."""

    OTHER = 0
    AMD64 = enum.auto()


def osarch() -> (OS, Arch):
    """Returns the current platform."""
    sys = platform.system().lower()
    machine = platform.machine().lower()

    return (
        _parse_os(sys),
        _parse_arch(machine),
    )


def current_os() -> OS:
    """Returns the current operating system."""
    (os, _) = osarch()
    return os


def _parse_os(sys: str) -> OS:
    """Extracts the current operating system."""
    if sys == "linux":
        return OS.LINUX
    elif sys == "darwin":
        return OS.DARWIN
    else:
        return OS.OTHER


def _parse_arch(machine: str) -> Arch:
    """Extracts the current architecture."""
    if machine in ["x86_64", "amd64"]:
        return Arch.AMD64
    else:
        return
