"""Artifact TTL."""
from enum import Enum


class ArtifactTTL(Enum):
    INHERIT = 0


class ArtifactTTLChange(Enum):
    INHERITED = -1
    NOT_INHERITED = -2
