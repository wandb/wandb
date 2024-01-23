from dataclasses import dataclass


@dataclass(frozen=True)
class Namespace:
    """Configure an alternate entity/project at the dst server your data will end up in."""

    entity: str
    project: str

    @classmethod
    def from_path(cls, path):
        entity, project = path.split("/")
        return cls(entity, project)

    @property
    def path(self):
        return f"{self.entity}/{self.project}"

    @property
    def send_manager_overrides(self):
        overrides = {}
        if self.entity:
            overrides["entity"] = self.entity
        if self.project:
            overrides["project"] = self.project
        return overrides
