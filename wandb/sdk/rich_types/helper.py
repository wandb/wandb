from typing import Any, Sequence

# from .media_sequence import BatchableMedia
from .media import Media

# TODO: move this logic to the log function of the run
# we only care about it when we are logging


def serialize(data: dict, step: int, ignore_copy_error: bool = False) -> dict:
    serialized = {}
    for key, value in data.items():
        if isinstance(value, dict):
            serialized[key] = serialize(value, step, ignore_copy_error)
        else:
            serialized[key] = serialize_helper(value, key, str(step), ignore_copy_error)
    return serialized


def serialize_helper(
    value: Any, key: str, namespace: str, ignore_copy_error: bool
) -> Any:
    if isinstance(value, Sequence):
        if all(isinstance(v, Media) for v in value) and all(
            isinstance(v, value[0]) for v in value
        ):
            value = BatchableMedia(value)
            value.bind_to_run(value, key, namespace, ignore_copy_error)
            return value.to_json()
        else:
            return [
                serialize_helper(v, key, namespace, ignore_copy_error) for v in value
            ]

    elif isinstance(value, Media):
        value.bind_to_run(key, namespace, ignore_copy_error)
        return value.to_json(namespace=namespace)

    # TODO: handle other types

    return value
