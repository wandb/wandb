"""Supported machine architectures."""

import enum
import platform
from typing import Any, Dict, List


def current() -> "Arch":
    """Returns the architecture we're running on."""
    return parse(platform.machine())


def parse(spec: str) -> "Arch":
    """Parses an architecture specifier."""
    spec = spec.lower()

    for arch in Arch:
        if spec in arch.aliases:
            return arch

    raise InvalidArchError(spec)


class Arch(enum.Enum):
    """A known machine architecture."""

    x86_64 = {"go": "amd64", "swift": "x86_64"}
    aarch64 = {"go": "arm64", "swift": "arm64"}

    def __init__(self, mappings: Dict[str, Any]):
        self.go_name: str = mappings["go"]
        """The name for this architecture used by the Go compiler."""

        self.swift_name: str = mappings["swift"]
        """The name for this architecture used by the Swift compiler."""

        self.aliases = set([self.go_name, self.swift_name, self.name])
        """Names used for the architecture."""

    @classmethod
    def options(cls) -> List[str]:
        """All known architecture strings."""
        opts: List[str] = []

        for arch in cls:
            opts.extend(arch.aliases)

        return opts


class InvalidArchError(Exception):
    """Raised when an architecture string could not be parsed."""

    def __init__(self, spec: str):
        self._spec = spec

    def __str__(self):
        options = " / ".join(["=".join(arch.aliases) for arch in Arch])
        return f"Unknown architecture: '{self._spec}'. Known: {options}"
