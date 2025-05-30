"""Artifact state."""

from __future__ import annotations

from enum import Enum


class ArtifactState(Enum):
    PENDING = "PENDING"
    COMMITTED = "COMMITTED"
    DELETED = "DELETED"
    GARBAGE_COLLECTED = "GARBAGE_COLLECTED"
    PENDING_DELETION = "PENDING_DELETION"
