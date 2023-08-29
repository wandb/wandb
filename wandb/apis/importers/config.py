from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ImportConfig:
    """Configure an alternate entity/project at the dst server your data will end up in."""

    entity: Optional[str] = None
    project: Optional[str] = None
    debug_mode: bool = False

    @property
    def send_manager_overrides(self):
        overrides = {}
        if self.entity:
            overrides["entity"] = self.entity
        if self.project:
            overrides["project"] = self.project
        return overrides
