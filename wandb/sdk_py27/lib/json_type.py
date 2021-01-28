# Adapted from https://gist.github.com/BMDan/ede923f733dfdf5ed3f6c9634a3e281f on Jan 25, 2021

if False:  # TYPE_CHECKING
    from typing import List, Mapping, Union

    # Values for JSON that aren't nested
    _JSON_v = Union[str, int, float, bool, None]

    # If MyPy ever permits recursive definitions, just uncomment this:
    # JSON = Union[List['JSON'], Mapping[str, 'JSON'], _JSON_v]

    # Until then, here's a multi-layer way to represent any (reasonable) JSON we
    # might send or receive.  It terminates at _JSON_14, so the maximum depth of
    # the JSON is 15 dicts/lists, like: {'a': {'b': {'c': {'d': {'e': 'f'}}}}}.

    _JSON_15 = _JSON_v
    _JSON_14 = Union[_JSON_v, List[_JSON_15], Mapping[str, _JSON_15]]
    _JSON_13 = Union[_JSON_v, List[_JSON_14], Mapping[str, _JSON_14]]
    _JSON_12 = Union[_JSON_v, List[_JSON_13], Mapping[str, _JSON_13]]
    _JSON_11 = Union[_JSON_v, List[_JSON_12], Mapping[str, _JSON_12]]
    _JSON_10 = Union[_JSON_v, List[_JSON_11], Mapping[str, _JSON_11]]
    _JSON_9 = Union[_JSON_v, List[_JSON_10], Mapping[str, _JSON_10]]
    _JSON_8 = Union[_JSON_v, List[_JSON_9], Mapping[str, _JSON_9]]
    _JSON_7 = Union[_JSON_v, List[_JSON_8], Mapping[str, _JSON_8]]
    _JSON_6 = Union[_JSON_v, List[_JSON_7], Mapping[str, _JSON_7]]
    _JSON_5 = Union[_JSON_v, List[_JSON_6], Mapping[str, _JSON_6]]
    _JSON_4 = Union[_JSON_v, List[_JSON_5], Mapping[str, _JSON_5]]
    _JSON_3 = Union[_JSON_v, List[_JSON_4], Mapping[str, _JSON_4]]
    _JSON_2 = Union[_JSON_v, List[_JSON_3], Mapping[str, _JSON_3]]
    _JSON_1 = Union[_JSON_v, List[_JSON_2], Mapping[str, _JSON_2]]
    JSON = Union[_JSON_v, List[_JSON_1], Mapping[str, _JSON_1]]

    # To allow deeper nesting, you can of course expand the JSON definition above,
    # or you can keep typechecking for the first levels but skip typechecking
    # at the deepest levels by using UnsafeJSON:

    # UnsafeJSON_5 = Union[JSON_v, List[Any], Mapping[str, Any]]
    # UnsafeJSON_4 = Union[JSON_v, List[UnsafeJSON_5], Mapping[str, UnsafeJSON_5]]
    # UnsafeJSON_3 = Union[JSON_v, List[UnsafeJSON_4], Mapping[str, UnsafeJSON_4]]
    # UnsafeJSON_2 = Union[JSON_v, List[UnsafeJSON_3], Mapping[str, UnsafeJSON_3]]
    # UnsafeJSON_1 = Union[JSON_v, List[UnsafeJSON_2], Mapping[str, UnsafeJSON_2]]
    # UnsafeJSON = Union[JSON_v, List[UnsafeJSON_1], Mapping[str, UnsafeJSON_1]]

    __all__ = ["JSON"]
