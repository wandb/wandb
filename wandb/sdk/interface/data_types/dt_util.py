from wandb import util


def is_numpy_array_require_load(data):
    np = util.get_module("numpy", required="Operation requires numpy")
    return util.is_numpy_array(data)


def numpy_arrays_to_lists(payload):
    # Casts all numpy arrays to lists so we don't convert them to histograms, primarily for Plotly

    if isinstance(payload, dict):
        res = {}
        for key, val in six.iteritems(payload):
            res[key] = numpy_arrays_to_lists(val)
        return res
    elif isinstance(payload, collections.Sequence) and not isinstance(
        payload, six.string_types
    ):
        return [numpy_arrays_to_lists(v) for v in payload]
    elif util.is_numpy_array_require_load(payload):
        return [numpy_arrays_to_lists(v) for v in payload.tolist()]

    return payload
