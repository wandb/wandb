from functools import singledispatch

from .media import Media
from .media_sequence import MediaSequence


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
    # item_classes = set(type(value) for value in obj)
    # if len(item_classes) == 1:
    #     item_class = item_classes.pop()
    #     if issubclass(item_class, Media):
    #         return MediaSequence(obj, item_class).bind_to_run(
    #             interface, root_dir, *namespace
    #         )
    return [bind_to_run(value, interface, root_dir, *namespace) for value in obj]


@bind_to_run.register(int)
@bind_to_run.register(float)
@bind_to_run.register(str)
@bind_to_run.register(bool)
def _(obj, *_):
    return obj


@bind_to_run.register(Media)
@bind_to_run.register(MediaSequence)
def _(obj, interface, root_dir, *namespace):
    obj.bind_to_run(interface, root_dir, *namespace)
    return obj.to_json()
