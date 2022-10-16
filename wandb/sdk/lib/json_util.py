import contextlib
from collections import abc
from datetime import date, datetime
from functools import singledispatch

from .import_hooks import register_post_import_hook


@contextlib.contextmanager
def circular_reference_handler(visited: set, value: object):
    visit_id = id(value)
    if visit_id in visited:
        raise TypeError("Recursive data structures are not supported")
    visited.add(visit_id)
    yield
    if visit_id in visited:
        visited.remove(visit_id)


# # TODO: Revisit these limits
# VALUE_BYTES_LIMIT = 100000

# from sys import getsizeof

#     if getsizeof(obj) > VALUE_BYTES_LIMIT:
#         wandb.termwarn(
#             "Serializing object of type {} that is {} bytes".format(
#                 type(obj).__name__, getsizeof(obj)
#             )
#         )


@singledispatch
def json_serializable(value, **kwargs):
    # todo: figure out import order to check artifact types
    if hasattr(value, "json_encode"):
        return value.json_encode()

    # todo: do we want to support this?
    # if value.__class__.__module__ not in ("builtins", "__builtin__"):
    #     return str(value)

    raise TypeError("Unsupported type")


# @json_serializable.register(wandb.sdk.interface.artifact.Artifact)
# def _(value, **kwargs):
#     return value.json_encode()


@json_serializable.register(abc.Sequence)
@json_serializable.register(abc.Set)
def _(value, **kwargs):
    visited = kwargs.pop("visited", set())
    with circular_reference_handler(visited, value):
        obj = [json_serializable(item, visited=visited, **kwargs) for item in value]
    return obj


# @json_serializable.register(abc.Mapping)
@json_serializable.register(dict)
def _(value, **kwargs):
    visited = kwargs.pop("visited", set())
    with circular_reference_handler(visited, value):
        obj = {
            json_serializable(k, visited=visited, **kwargs): json_serializable(
                v, visited=visited, **kwargs
            )
            for k, v in value.items()
        }
    return obj


@json_serializable.register(abc.Callable)
def _(value, **kwargs):
    return (
        f"{value.__module__}.{value.__qualname__}"
        if hasattr(value, "__qualname__") and hasattr(value, "__module__")
        else str(value)
    )


@json_serializable.register(bytes)
def _(value, **kwargs):
    return value.decode("utf-8")


@json_serializable.register(datetime)
@json_serializable.register(date)
def _(value, **kwargs):
    return value.isoformat()


@json_serializable.register(int)
@json_serializable.register(float)
@json_serializable.register(type(None))
@json_serializable.register(str)
def _(value, **kwargs):
    return value


@json_serializable.register(slice)
def _(value, **kwargs):
    # todo: why not convert it to a string?
    return dict(slice_start=value.start, slice_step=value.step, slice_stop=value.stop)


def register_numpy_post_import_hook(np):
    @json_serializable.register(np.generic)
    def _(value, **kwargs):
        if value.dtype.kind == "f" or value.dtype == "bfloat16":
            # value is a numpy float with precision greater than that of native python float
            # (i.e., float96 or float128) or it is of custom type such as bfloat16.
            # in these cases, obj.item() does not return a native
            # python float (in the first case - to avoid loss of precision,
            # so we need to explicitly cast this down to a 64bit float)
            return float(value.item())
        return value.item()

    @json_serializable.register(np.ndarray)
    def _(value, **kwargs):
        # todo: why are we compressing this?
        if value.size > 32:
            compression_fn = kwargs.get("compression_fn")
            if compression_fn:
                return compression_fn(value)

        return value.tolist()


def register_tensorflow_post_import_hook(tf):
    @json_serializable.register(tf.Tensor)
    @json_serializable.register(tf.Variable)
    def _(value, **kwargs):
        try:
            obj = value.numpy()
        except AttributeError:
            try:
                obj = value.eval()
            except ValueError:
                obj = value.eval(session=tf.compat.v1.Session())
        return json_serializable(obj, **kwargs)

    @json_serializable.register(tf.RaggedTensor)
    def _(value, **kwargs):
        try:
            return value.to_list()
        except ValueError:
            raise TypeError(
                f"Unable to serialize RaggedTensor for tensorflow=={tf.__version__}"
            )

    @json_serializable.register(tf.SparseTensor)
    def _(value, **kwargs):
        obj = tf.sparse.to_dense(value)
        try:
            obj = obj.eval(session=tf.compat.v1.Session())
        except Exception:
            pass
        return json_serializable(obj, **kwargs)


def register_torch_post_import_hook(torch):
    @json_serializable.register(torch.Tensor)
    @json_serializable.register(torch.autograd.Variable)
    def _(value, **kwargs):

        obj = value.detach().cpu()
        obj = obj.numpy() if obj.size() else obj.item()
        return json_serializable(obj, **kwargs)


def register_jax_post_import_hook(jax):
    @json_serializable.register(jax.numpy.ndarray)
    def _(value, **kwargs):
        return json_serializable(jax.device_get(value), **kwargs)


register_post_import_hook(register_numpy_post_import_hook, __name__, "numpy")
register_post_import_hook(register_tensorflow_post_import_hook, __name__, "tensorflow")
register_post_import_hook(register_torch_post_import_hook, __name__, "torch")
register_post_import_hook(register_jax_post_import_hook, __name__, "jax")
