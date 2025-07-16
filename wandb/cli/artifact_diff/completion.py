from functools import cache

from wandb import Api

# HACK: Use a global wandb.Api instance
api = Api()


@cache
def _project_names(entity: str | None = None) -> tuple[str, ...]:
    return tuple(sorted({project.name for project in api.projects()}))


@cache
def _artifact_types(project: str) -> tuple[str, ...]:
    return tuple(sorted({atype.name for atype in api.artifact_types(project)}))


@cache
def _artifact_names(project: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                artifact.name
                for type_name in _artifact_types(project)
                for artifact in api.artifact_collection(
                    type_name=type_name, project_name=project
                )
            }
        )
    )


@cache
def _matching_artifact_names(project: str, incomplete: str) -> list[str]:
    incomplete_lower = incomplete.lower()
    return [
        artifact_name
        for artifact_name in map(str.lower, _artifact_names(project))
        if artifact_name.startswith(incomplete_lower)
    ]


@cache
def _matching_project_names(incomplete: str) -> list[str]:
    incomplete_lower = incomplete.lower()
    return [
        project_name
        for project_name in map(str.lower, _project_names())
        if project_name.startswith(incomplete_lower)
    ]


def complete_artifact_path(incomplete: str):
    # Autocomplete project names
    if "/" not in incomplete:
        return _matching_project_names(incomplete)

    # We've got a project name, autocomplete artifact names
    project_name, incomplete_artifact_name = incomplete.split("/", 1)
    yield from (
        f"{project_name}/{artifact_name}"
        for artifact_name in _matching_artifact_names(
            project_name, incomplete_artifact_name
        )
    )
