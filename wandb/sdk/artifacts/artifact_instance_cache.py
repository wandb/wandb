"""Recent Artifact storage.

Artifacts are registered in the cache to ensure they won't be immediately garbage
collected and can be retrieved by their ID.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from wandb.sdk.lib.capped_dict import CappedDict

if TYPE_CHECKING:
    from wandb.sdk.artifacts.artifact import Artifact

# There is nothing special about the artifact cache, it's just a global capped dict.
artifact_instance_cache: dict[str, Artifact] = CappedDict(100)
