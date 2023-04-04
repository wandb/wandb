import json
from functools import singledispatch

from wandb.sdk.wandb_artifacts import Artifact

from .media import Media, MediaSequence, MediaSequenceFactory
from .table import Table


@singledispatch
def bind(obj, *_):
    raise TypeError(f"Can't serialize {obj}")


@bind.register(dict)
def _(obj, run, *namespace):
    return {key: bind(value, run, key, *namespace) for key, value in obj.items()}


@bind.register(list)
@bind.register(tuple)
def _(obj, run, *namespace):
    obj_types = set(type(value) for value in obj)
    if len(obj_types) == 1:
        obj_type = obj_types.pop()
        if issubclass(obj_type, Media):
            return bind(
                MediaSequenceFactory.create(obj),
                run,
                *namespace,
            )
    return [bind(value, run, *namespace) for value in obj]


@bind.register(int)
@bind.register(float)
@bind.register(str)
@bind.register(bool)
def _(obj, *_):
    return obj


@bind.register(MediaSequence)
@bind.register(Media)
def _(obj, run, *namespace):
    obj.bind_to_run(run, *namespace)
    return obj.to_json()


@bind.register(Table)
def _(obj, run, *namespace):
    artifact = bind_to_artifact(obj, str(run.id), *namespace)
    run.log_artifact(artifact)

    obj.bind_to_run(run, *namespace)
    return obj.to_json()


def bind_to_artifact(obj, *namespace):
    artifact_name = "-".join(("run", *namespace))
    artifact = Artifact(artifact_name, type="run_table")
    artifact._ensure_can_add()

    obj_id = id(obj)
    if obj_id in artifact._added_objs:
        return

    name = ".".join([namespace[1], obj.DEFAULT_FORMAT.lower()])
    entry = artifact._manifest.get_entry_by_path(name)
    if entry is not None:
        return

    serialized = obj.bind_to_artifact(artifact)
    with artifact.new_file(name) as f:
        file_path = f.name
        json.dump(serialized, f, sort_keys=True)
    entry = artifact.add_file(str(file_path), name, is_tmp=False)
    from .media import ArtifactReference

    obj._artifact = ArtifactReference(artifact, entry.path)  # type: ignore

    return artifact
