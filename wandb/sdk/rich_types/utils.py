from functools import singledispatch

from .media import Media, MediaSequence, MediaSequenceFactory


@singledispatch
def bind_to_run(obj, *_):
    raise TypeError(f"Can't serialize {obj}")


@bind_to_run.register(dict)
def _(obj, interface, root_dir, *namespace):
    return {
        key: bind_to_run(value, interface, root_dir, key, *namespace)
        for key, value in obj.items()
    }


@bind_to_run.register(list)
@bind_to_run.register(tuple)
def _(obj, interface, root_dir, *namespace):
    obj_types = set(type(value) for value in obj)
    if len(obj_types) == 1:
        obj_type = obj_types.pop()
        if issubclass(obj_type, Media):
            return bind_to_run(
                MediaSequenceFactory.create(obj),
                interface,
                root_dir,
                *namespace,
            )
    return [bind_to_run(value, interface, root_dir, *namespace) for value in obj]


@bind_to_run.register(int)
@bind_to_run.register(float)
@bind_to_run.register(str)
@bind_to_run.register(bool)
def _(obj, *_):
    return obj


@bind_to_run.register(MediaSequence)
@bind_to_run.register(Media)
def _(obj, interface, root_dir, *namespace):
    obj.bind_to_run(interface, root_dir, *namespace)
    return obj.to_json()
