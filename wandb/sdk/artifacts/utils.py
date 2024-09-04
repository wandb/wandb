REGISTRY_PREFIX = "wandb-registry-"


def is_artifact_registry_project(project: str) -> bool:
    return project.startswith(REGISTRY_PREFIX)
