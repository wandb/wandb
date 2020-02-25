### Functions to fake APIs we don't yet have in the server
import json

import wandb


def get_artifact_with_digest(artifact_name, digest):
    api = wandb.Api()
    internal_api = wandb.apis.InternalApi()

    entity_name = internal_api.settings('entity')
    project_name = internal_api.settings('project')
    if entity_name is None or project_name is None:
        raise ValueError('need entity_name and project_name')
    try:
        return api.artifact_version(entity_name + '/' + project_name + '/' + artifact_name + ':' + digest, expected_digest=digest)
    except wandb.CommError:
        pass
    return None


# TODO(artifacts): APIs should refer objects or something that's better-typed than dicts
def create_artifact(artifact_name, metadata, digest):
    api = wandb.Api()
    internal_api = wandb.apis.InternalApi()

    entity_name = internal_api.settings('entity')
    project_name = internal_api.settings('project')
    if entity_name is None or project_name is None:
        raise ValueError('need entity_name and project_name')
    # av = get_artifact_with_digest(artifact_name, digest)
    # if av is not None:
    #     return av
    projects = api.projects(entity_name)
    project = None
    for p in projects:
        if p.name == project_name:
            project = p
    if project is None:
        raise Exception('no project')

    artifact_id = None
    for a in project.artifacts():
        if a.name == artifact_name:
            artifact_id = a.id

    if artifact_id is None:
        artifact_id = internal_api.create_artifact(entity_name, project_name, artifact_name)

    internal_api.create_artifact_version(
        entity_name, project_name, internal_api.current_run_id, artifact_id, digest,
        metadata=json.dumps(metadata))
    av = api.artifact_version(entity_name + '/' + project_name + '/' + artifact_name + ':' + digest)
    return av
