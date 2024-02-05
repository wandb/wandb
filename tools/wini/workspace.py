"""Information about the workspace for wini build scripts."""

import enum
import os
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
    ARM64 = enum.auto()


def target_osarch() -> (OS, Arch):
    """Returns the target platform."""
    sys = _parse_current_os()

    # cibuildwheel builds on an x86_64 Mac when targeting ARM64.
    # It sets an undocumented "PLAT" environment variable which we use
    # to detect this case (potential improvement: use a command-line argument
    # to the build system instead).
    if sys == OS.DARWIN and os.getenv("PLAT", "").endswith("arm64"):
        arch = Arch.ARM64
    else:
        arch = _parse_current_arch()

    return (sys, arch)


def target_os() -> OS:
    """Returns the target operating system."""
    (os, _) = target_osarch()
    return os


def _parse_current_os() -> OS:
    """Extracts the current operating system."""
    sys = platform.system().lower()
    if sys == "linux":
        return OS.LINUX
    elif sys == "darwin":
        return OS.DARWIN
    else:
        return OS.OTHER


def _parse_current_arch() -> Arch:
    """Extracts the current architecture."""
    machine = platform.machine().lower()
    if machine in ["x86_64", "amd64", "aarch64"]:
        return Arch.AMD64
    elif machine == "arm64":
        return Arch.ARM64
    else:
        return Arch.OTHER
