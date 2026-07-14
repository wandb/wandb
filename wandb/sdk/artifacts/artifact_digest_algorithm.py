"""Artifact digest algorithm."""

from __future__ import annotations

from enum import Enum


class ArtifactDigestAlgorithm(str, Enum):
    MANIFEST_MD5 = "MANIFEST_MD5"
    MANIFEST_XXH64 = "MANIFEST_XXH64"
