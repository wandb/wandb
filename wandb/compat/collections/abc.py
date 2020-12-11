import sys

Awaitable = None
Coroutine = None
AsyncIterable = None
AsyncIterator = None
AsyncGenerator = None
Hashable = None
Iterable = None
Iterator = None
Generator = None
Reversible = None
Sized = None
Container = None
Callable = None
Collection = None
Set = None
MutableSet = None
Mapping = None
MutableMapping = None
MappingView = None
KeysView = None
ItemsView = None
ValuesView = None
Sequence = None
MutableSequence = None
ByteString = None

if sys.version_info.major == 3 and sys.version_info.minor >= 3:
    # serves as a pass through
    from collections.abs import *
    from collections.abs import __all__
else:
    import collections as __collections

    # Copied from 3.9.0
    abc_namespace = [
        "Awaitable",
        "Coroutine",
        "AsyncIterable",
        "AsyncIterator",
        "AsyncGenerator",
        "Hashable",
        "Iterable",
        "Iterator",
        "Generator",
        "Reversible",
        "Sized",
        "Container",
        "Callable",
        "Collection",
        "Set",
        "MutableSet",
        "Mapping",
        "MutableMapping",
        "MappingView",
        "KeysView",
        "ItemsView",
        "ValuesView",
        "Sequence",
        "MutableSequence",
        "ByteString",
    ]
    __all__ = []
    for abc_name in abc_namespace:
        if hasattr(__collections, abc_name):
            locals()[abc_name] = getattr(__collections, abc_name)
            __all__.append(abc_name)
