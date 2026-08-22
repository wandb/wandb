from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SweepInfo:
    """Static facts about the sweep an optimizer searches.

    A plain value object so that optimizers do not depend on the public API
    and can be built from scheduler protocol payloads or literals in tests.

    Attributes:
        id: The sweep's short id, unique within the project.
        name: The sweep's display name.
        entity: The entity that owns the sweep.
        project: The project the sweep belongs to.
        config: The parsed sweep config. Treat it as read-only.
    """

    id: str
    name: str
    entity: str
    project: str
    config: dict[str, Any]
