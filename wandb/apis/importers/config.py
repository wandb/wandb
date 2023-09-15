from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Namespace:
    """Configure an alternate entity/project at the dst server your data will end up in."""

    entity: str
    project: str

    @property
    def send_manager_overrides(self):
        overrides = {}
        if self.entity:
            overrides["entity"] = self.entity
        if self.project:
            overrides["project"] = self.project
        return overrides
