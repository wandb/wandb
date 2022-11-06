"""
This module contains the logic for serializing objects to be JSON compatible.
"""

import contextlib
import json
from collections import abc
from datetime import date, time
from functools import singledispatch
from typing import IO, Any, Callable, Generator, Optional, Sequence, Union

from wandb.sdk.interface.artifacts import Artifact

from .import_hooks import register_post_import_hook

# from wandb.sdk.data_types.base_types.media import Media


JSONTypes = Union[None, bool, int, float, str, list, dict]

# # todo: is this method useful?
# VALUE_BYTES_LIMIT = 100000
#
# import wandb
# from sys import getsizeof
#
# def serialization_size_warning(func: Callable) -> Callable:
#     def decorator(obj, *args, **kwargs):
#         size = getsizeof(obj)
#         if size > VALUE_BYTES_LIMIT:
#             obj_type = type(obj).__name__
#             wandb.termwarn(
#                 f"Serialization size is {size} bytes of object of type {obj_type}.",
#                 repeat=False,
#             )
#         return func(obj, *args, **kwargs)
#     return decorator


class Tensor:
    def __init__(self, data: Any, source: Optional[Any] = None) -> None:
        self.data = data
        if source is None:
            source = data
        cls = source.__class__
        self.source = ".".join([cls.__module__, cls.__name__])

    def compress(self, compression_fn: Callable) -> dict:
        return compression_fn(self.data, source=self.source)


@contextlib.contextmanager
def circular_reference_handler(visited: set, value: object) -> Generator:
    """Context manager to detect circular references in objects."""
    visit_id = id(value)
    if visit_id in visited:
        raise TypeError("Recursive data structures are not supported")
    visited.add(visit_id)
    yield
    if visit_id in visited:
        visited.remove(visit_id)


@singledispatch
def json_serializable(value: Any, **kwargs: Any) -> JSONTypes:
    # todo: do we want to support this?
    # if value.__class__.__module__ not in ("builtins", "__builtin__"):
    #     return str(value)
    # if callable(obj):
    #     return (
    #         f"{obj.__module__}.{obj.__qualname__}"
    #         if hasattr(obj, "__qualname__") and hasattr(obj, "__module__")
    #         else str(obj)
    #     )

    raise TypeError("Unsupported type")


@json_serializable.register(abc.Sequence)
@json_serializable.register(abc.Set)
def _(value: Union[Sequence, set], **kwargs: Any) -> list:
    visited = kwargs.pop("visited", set())
    with circular_reference_handler(visited, value):
        obj = [json_serializable(item, visited=visited, **kwargs) for item in value]
    return obj


@json_serializable.register(abc.Mapping)
def _(value: dict, **kwargs: Any) -> dict:
    visited = kwargs.pop("visited", set())
    with circular_reference_handler(visited, value):
        obj = {
            json_serializable(k, visited=visited, **kwargs): json_serializable(
                v, visited=visited, **kwargs
            )
            for k, v in value.items()
        }
    return obj


@json_serializable.register(bytes)
def _(value: bytes, **kwargs: Any) -> str:
    return value.decode("utf-8")


@json_serializable.register(time)
@json_serializable.register(date)
def _(value: Union[time, date], **kwargs: Any) -> str:
    return value.isoformat()


@json_serializable.register(int)
@json_serializable.register(float)
@json_serializable.register(type(None))
@json_serializable.register(str)
def _(value, **kwargs):  # type: ignore [no-untyped-def]
    return value


@json_serializable.register(slice)
def _(value: slice, **kwargs: Any) -> dict:
    # todo: why not convert it to a string?
    return dict(slice_start=value.start, slice_step=value.step, slice_stop=value.stop)


@json_serializable.register(Tensor)
def _(value, **kwargs: Any):
    compression_fn = kwargs.pop("compression_fn", None)
    if compression_fn:
        try:
            return value.compress(compression_fn)
        except TypeError:
            pass

    return json_serializable(value.data, **kwargs)


def register_numpy_post_import_hook(np: Any) -> None:
    @json_serializable.register(np.generic)
    def _(value, **kwargs):  # type: ignore [no-untyped-def]
        obj = value.item()
        if value.dtype.kind == "f" or value.dtype == "bfloat16":
            # value is a numpy float with precision greater than that of native python float
            # (i.e., float96 or float128) or it is of custom type such as bfloat16.
            # in these cases, obj.item() does not return a native
            # python float (in the first case - to avoid loss of precision,
            # so we need to explicitly cast this down to a 64bit float)
            return float(obj)
        return obj

    @json_serializable.register(np.ndarray)
    def _(value, **kwargs):  # type: ignore [no-untyped-def]
        # todo: why are we compressing this?
        compression_fn = kwargs.get("compression_fn", False)
        if compression_fn:
            return json_serializable(Tensor(value), **kwargs)
        # need to do this conversion (np.tolist converts bfloat16 to int for py3.6)
        obj = value.astype(float) if value.dtype == "bfloat16" else value
        return obj.tolist()


def register_tensorflow_post_import_hook(tf: Any) -> None:
    @json_serializable.register(tf.Tensor)
    @json_serializable.register(tf.Variable)
    def _(value, **kwargs):  # type: ignore [no-untyped-def]
        try:
            obj = value.numpy()
        except AttributeError:
            try:
                obj = value.eval()
            except ValueError:
                obj = value.eval(session=tf.compat.v1.Session())

        obj = Tensor(obj, source=value)
        return json_serializable(obj, **kwargs)

    # @json_serializable.register(tf.RaggedTensor)
    # def _(value, **kwargs):  # type: ignore [no-untyped-def]
    #     try:
    #         return value.to_list()
    #     except ValueError:
    #         raise TypeError(
    #             f"Unable to serialize RaggedTensor for tensorflow=={tf.__version__}"
    #         )

    # @json_serializable.register(tf.SparseTensor)
    # def _(value, **kwargs):  # type: ignore [no-untyped-def]
    #     obj = tf.sparse.to_dense(value)
    #     try:
    #         obj = obj.eval(session=tf.compat.v1.Session())
    #     except Exception:
    #         pass
    #     return json_serializable(obj, **kwargs)


def register_torch_post_import_hook(torch: Any) -> None:
    @json_serializable.register(torch.Tensor)
    @json_serializable.register(torch.autograd.Variable)
    def _(value, **kwargs):  # type: ignore [no-untyped-def]

        obj = value.detach().cpu()
        obj = obj.numpy() if obj.size() else obj.item()

        obj = Tensor(obj, source=value)
        return json_serializable(obj, **kwargs)


def register_jax_post_import_hook(jax: Any) -> None:
    @json_serializable.register(jax.numpy.ndarray)
    @json_serializable.register(jax.numpy.DeviceArray)
    def _(value, **kwargs):  # type: ignore [no-untyped-def]
        obj = jax.device_get(value)
        obj = Tensor(obj, source=value)
        return json_serializable(obj, **kwargs)


register_post_import_hook(register_numpy_post_import_hook, __name__, "numpy")
register_post_import_hook(register_tensorflow_post_import_hook, __name__, "tensorflow")
register_post_import_hook(register_torch_post_import_hook, __name__, "torch")
register_post_import_hook(register_jax_post_import_hook, __name__, "jax")


@json_serializable.register(Artifact)
def _(value, **kwargs):  # type: ignore [no-untyped-def]
    value.wait()
    return value.json_encode()


# @json_serializable.register(Media)
# def _(value, **kwargs) -> dict:  # type: ignore [no-untyped-def]
#     # todo: implement this
#     return value.to_json(**kwargs)


def json_dump_safer(
    obj: Any, fp: IO[str], compression_fn: Optional[Callable] = None, **kwargs: Any
) -> None:
    """Convert obj to json, with some extra encodable types."""
    return json.dump(
        json_serializable(obj, compression_fn=compression_fn), fp, **kwargs
    )


def json_dumps_safer(
    obj: Any, compression_fn: Optional[Callable] = None, **kwargs: Any
) -> str:
    """Convert obj to json, with some extra encodable types."""
    return json.dumps(json_serializable(obj, compression_fn=compression_fn), **kwargs)
