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
    if obj.manager._bind_path is None:
        artifact = bind_to_artifact(obj, str(run.id), *namespace)
        run.log_artifact(artifact)

    obj.bind_to_run(run, *namespace)
    return obj.to_json()


def bind_to_artifact(obj, *namespace):
    artifact_name = "-".join(("run", *namespace))
    artifact = Artifact(artifact_name, type="run_table")

    name = ".".join([*namespace, obj.DEFAULT_FORMAT.lower()])
    add(artifact, obj, name)

    return artifact


# TODO: This is a temporary code will use `artifact.add` when all methods are implemented.
def add(artifact, obj, name):
    artifact._ensure_can_add()

    is_temp_name = name.startswith("media/tables")

    obj_id = id(obj)
    if obj_id in artifact._added_objs:
        return artifact._added_objs[obj_id].entry

    reference_path = obj.manager.artifact_path
    if reference_path is not None:
        return artifact.add_reference(reference_path, name)[0]

    entry = artifact._manifest.get_entry_by_path(name)
    if entry is not None:
        return entry

    serialized = obj.bind_to_artifact(artifact)
    if is_temp_name:
        file_path = "some/path"
        with open(file_path, "w") as f:
            json.dump(serialized, f, sort_keys=True)
    else:
        with artifact.new_file(name) as f:
            file_path = f.name
            json.dump(serialized, f, sort_keys=True)
    entry = artifact.add_file(str(file_path), name, is_tmp=is_temp_name)

    obj.manager.assign_artifact(artifact, entry.path)

    from wandb.sdk.wandb_artifacts import _AddedObj
    artifact._added_objs[obj_id] = _AddedObj(entry, obj)

    return entry
