from functools import singledispatch

from .media import Media


@singledispatch
def bind_to_run(obj, *_):
    raise TypeError(f"Can't serialize {obj}")


@bind_to_run.register(dict)
def _(obj, interface, root_dir, *namespace):
    return {
        k: bind_to_run(v, interface, root_dir, k, *namespace) for k, v in obj.items()
    }


@bind_to_run.register(list)
@bind_to_run.register(tuple)
def _(obj, interface, root_dir, *namespace):
    return [bind_to_run(v, interface, root_dir, *namespace) for v in obj]


@bind_to_run.register(int)
@bind_to_run.register(float)
@bind_to_run.register(str)
@bind_to_run.register(bool)
def _(obj, *_):
    return obj


@bind_to_run.register(Media)
def _(obj, interface, root_dir, *namespace):
    obj.bind_to_run(interface, root_dir, *namespace)
    return obj.to_json()
