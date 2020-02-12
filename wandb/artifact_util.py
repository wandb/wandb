### This is a temporary file of helpful artifact methods for prototyping
# the new artifacts APIs. These will be removed before merging
# to master.

import json
import tempfile
import hashlib

import wandb
from wandb import util

def local_artifact_signature(filepaths=None, metadata=None):
    if metadata is None and filepaths is None:
        raise Exception('Need filepaths or metadata')
    md5s = []
    if filepaths is not None:
        filepaths = sorted(filepaths)
        for fp in filepaths:
            md5s.append(util.md5_file(fp))
        if metadata is not None:
            metadata['local_files'] = filepaths
    
    if metadata is not None:
        tf = tempfile.TemporaryFile()
        tf.write(json.dumps(metadata).encode('utf8'))
        md5s.append(util.md5_file(fp))
    hash_md5 = hashlib.md5()
    for md5 in md5s:
        hash_md5.update(md5.encode('utf8'))
    # Problem this generates signatures with '/' in them sometimes, which is not a
    # valid artifact alias
    return hash_md5.hexdigest()


def get_artifact_with_signature(artifact_name, signature):
    api = wandb.Api()
    internal_api = wandb.apis.InternalApi()

    entity_name = internal_api.settings('entity')
    project_name = internal_api.settings('project')
    try:
        return api.artifact_version(entity_name + '/' + project_name + '/' + artifact_name + ':' + signature)
    except wandb.CommError:
        pass
    return None


def create_signature_artifact_version(artifact_name, metadata, signature):
    api = wandb.Api()
    internal_api = wandb.apis.InternalApi()

    entity_name = internal_api.settings('entity')
    project_name = internal_api.settings('project')
    print('EP', entity_name, project_name)
    av = get_artifact_with_signature(artifact_name, signature)
    if av is not None:
        return av
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
        entity_name, project_name, None, artifact_id,
        metadata=json.dumps(metadata), aliases=[signature])
    av = api.artifact_version(entity_name + '/' + project_name + '/' + artifact_name + ':' + signature)
    return av
