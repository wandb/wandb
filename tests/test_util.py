import itertools
import sys
import os
import pytest
import numpy
import platform
import random

if sys.version_info >= (3, 9):
    pytest.importorskip("tensorflow")
import tensorflow

import plotly
import matplotlib.pyplot as plt

from . import utils
from wandb import util

try:
    import torch
except ImportError:
    pass


def pt_variable(nested_list, requires_grad=True):
    v = torch.autograd.Variable(torch.Tensor(nested_list))
    v.requires_grad = requires_grad
    return v


def r():
    return random.random()


def nested_list(*shape):
    """Makes a nested list of lists with a "shape" argument like numpy,
    TensorFlow, etc.
    """
    if not shape:
        # reduce precision so we can use == for comparison regardless
        # of conversions between other libraries
        return [float(numpy.float16(random.random()))]
    else:
        return [nested_list(*shape[1:]) for _ in range(shape[0])]


def json_friendly_test(orig_data, obj):
    data, converted = util.json_friendly(obj)
    utils.assert_deep_lists_equal(orig_data, data)
    assert converted


def tensorflow_json_friendly_test(orig_data):
    json_friendly_test(orig_data, tensorflow.convert_to_tensor(orig_data))
    v = tensorflow.Variable(tensorflow.convert_to_tensor(orig_data))
    json_friendly_test(orig_data, v)


@pytest.mark.skipif(sys.version_info < (3, 5), reason="PyTorch no longer supports py2")
def test_pytorch_json_0d():
    a = nested_list()
    json_friendly_test(a, torch.Tensor(a))
    json_friendly_test(a, pt_variable(a))


@pytest.mark.skipif(sys.version_info < (3, 5), reason="PyTorch no longer supports py2")
def test_pytorch_json_1d_1x1():
    a = nested_list(1)
    json_friendly_test(a, torch.Tensor(a))
    json_friendly_test(a, pt_variable(a))


@pytest.mark.skipif(sys.version_info < (3, 5), reason="PyTorch no longer supports py2")
def test_pytorch_json_1d():
    a = nested_list(3)
    json_friendly_test(a, torch.Tensor(a))
    json_friendly_test(a, pt_variable(a))


@pytest.mark.skipif(sys.version_info < (3, 5), reason="PyTorch no longer supports py2")
def test_pytorch_json_1d_large():
    a = nested_list(300)
    json_friendly_test(a, torch.Tensor(a))
    json_friendly_test(a, pt_variable(a))


@pytest.mark.skipif(sys.version_info < (3, 5), reason="PyTorch no longer supports py2")
def test_pytorch_json_2d():
    a = nested_list(3, 3)
    json_friendly_test(a, torch.Tensor(a))
    json_friendly_test(a, pt_variable(a))


@pytest.mark.skipif(sys.version_info < (3, 5), reason="PyTorch no longer supports py2")
def test_pytorch_json_2d_large():
    a = nested_list(300, 300)
    json_friendly_test(a, torch.Tensor(a))
    json_friendly_test(a, pt_variable(a))


@pytest.mark.skipif(sys.version_info < (3, 5), reason="PyTorch no longer supports py2")
def test_pytorch_json_3d():
    a = nested_list(3, 3, 3)
    json_friendly_test(a, torch.Tensor(a))
    json_friendly_test(a, pt_variable(a))


@pytest.mark.skipif(sys.version_info < (3, 5), reason="PyTorch no longer supports py2")
def test_pytorch_json_4d():
    a = nested_list(1, 1, 1, 1)
    json_friendly_test(a, torch.Tensor(a))
    json_friendly_test(a, pt_variable(a))


@pytest.mark.skipif(sys.version_info < (3, 5), reason="PyTorch no longer supports py2")
def test_pytorch_json_nd():
    a = nested_list(1, 1, 1, 1, 1, 1, 1, 1)
    json_friendly_test(a, torch.Tensor(a))
    json_friendly_test(a, pt_variable(a))


@pytest.mark.skipif(sys.version_info < (3, 5), reason="PyTorch no longer supports py2")
def test_pytorch_json_nd_large():
    a = nested_list(3, 3, 3, 3, 3, 3, 3, 3)
    json_friendly_test(a, torch.Tensor(a))
    json_friendly_test(a, pt_variable(a))


@pytest.mark.skipif(sys.version_info < (3, 5), reason="TF has sketchy support for py2")
def test_tensorflow_json_0d():
    tensorflow_json_friendly_test(nested_list())


@pytest.mark.skipif(sys.version_info < (3, 5), reason="TF has sketchy support for py2")
def test_tensorflow_json_1d_1x1():
    tensorflow_json_friendly_test(nested_list(1))


@pytest.mark.skipif(sys.version_info < (3, 5), reason="TF has sketchy support for py2")
def test_tensorflow_json_1d():
    tensorflow_json_friendly_test(nested_list(3))


@pytest.mark.skipif(sys.version_info < (3, 5), reason="TF has sketchy support for py2")
def test_tensorflow_json_1d_large():
    tensorflow_json_friendly_test(nested_list(300))


@pytest.mark.skipif(sys.version_info < (3, 5), reason="TF has sketchy support for py2")
def test_tensorflow_json_2d():
    tensorflow_json_friendly_test(nested_list(3, 3))


@pytest.mark.skipif(sys.version_info < (3, 5), reason="TF has sketchy support for py2")
def test_tensorflow_json_2d_large():
    tensorflow_json_friendly_test(nested_list(300, 300))


@pytest.mark.skipif(sys.version_info < (3, 5), reason="TF has sketchy support for py2")
def test_tensorflow_json_nd():
    tensorflow_json_friendly_test(nested_list(1, 1, 1, 1, 1, 1, 1, 1))


@pytest.mark.skipif(sys.version_info < (3, 5), reason="TF has sketchy support for py2")
def test_tensorflow_json_nd_large():
    tensorflow_json_friendly_test(nested_list(3, 3, 3, 3, 3, 3, 3, 3))


@pytest.mark.skipif(
    platform.system() == "Windows", reason="test suite does not build jaxlib on windows"
)
@pytest.mark.parametrize(
    "array_shape", [(), (1,), (3,), (300,), (300, 300), (1,) * 8, (3,) * 8]
)
def test_jax_json(array_shape):
    from jax import numpy as jnp

    orig_data = nested_list(*array_shape)
    jax_array = jnp.asarray(orig_data)
    json_friendly_test(orig_data, jax_array)
    assert util.is_jax_tensor_typename(util.get_full_typename(jax_array))


def test_image_from_docker_args_simple():
    image = util.image_from_docker_args(
        ["run", "-v", "/foo:/bar", "-e", "NICE=foo", "-it", "wandb/deepo", "/bin/bash"]
    )
    assert image == "wandb/deepo"


def test_image_from_docker_args_simple_no_namespace():
    image = util.image_from_docker_args(["run", "-e", "NICE=foo", "nginx", "/bin/bash"])
    assert image == "nginx"


def test_image_from_docker_args_simple_no_equals():
    image = util.image_from_docker_args(
        ["run", "--runtime=runc", "ufoym/deepo:cpu-all"]
    )
    assert image == "ufoym/deepo:cpu-all"


def test_image_from_docker_args_bash_simple():
    image = util.image_from_docker_args(
        ["run", "ufoym/deepo:cpu-all", "/bin/bash", "-c", "python train.py"]
    )
    assert image == "ufoym/deepo:cpu-all"


def test_image_from_docker_args_sha():
    dsha = (
        "wandb/deepo@sha256:"
        "3ddd2547d83a056804cac6aac48d46c5394a76df76b672539c4d2476eba38177"
    )
    image = util.image_from_docker_args([dsha])
    assert image == dsha


def test_safe_for_json():
    res = util.make_safe_for_json(
        {
            "nan": float("nan"),
            "inf": float("+inf"),
            "ninf": float("-inf"),
            "str": "str",
            "seq": [float("nan"), 1],
            "map": {"foo": 1, "nan": float("nan")},
        }
    )
    assert res == {
        "inf": "Infinity",
        "map": {"foo": 1, "nan": "NaN"},
        "nan": "NaN",
        "ninf": "-Infinity",
        "seq": ["NaN", 1],
        "str": "str",
    }


@pytest.mark.skipif(
    platform.system() == "Windows", reason="find_runner is broken on Windows"
)
def test_find_runner():
    res = util.find_runner(__file__)
    assert "python" in res[0]


def test_parse_sweep_id():
    parts = {"name": "test/test/test"}
    util.parse_sweep_id(parts)
    assert parts == {"name": "test", "entity": "test", "project": "test"}


def test_from_human_size():
    assert util.from_human_size("1000B", units=util.POW_2_BYTES) == 1000
    assert util.from_human_size("976.6KiB", units=util.POW_2_BYTES) == 1000038
    assert util.from_human_size("4.8MiB", units=util.POW_2_BYTES) == 5033164

    assert util.from_human_size("1000.0B") == 1000
    assert util.from_human_size("1000KB") == 1000000
    assert util.from_human_size("5.0MB") == 5000000


def test_to_human_size():
    assert util.to_human_size(1000, units=util.POW_2_BYTES) == "1000.0B"
    assert util.to_human_size(1000000, units=util.POW_2_BYTES) == "976.6KiB"
    assert util.to_human_size(5000000, units=util.POW_2_BYTES) == "4.8MiB"

    assert util.to_human_size(1000) == "1000.0B"
    assert util.to_human_size(1000000) == "1000.0KB"
    assert util.to_human_size(5000000) == "5.0MB"


def test_matplotlib_contains_images():
    """Ensures that the utility function can properly detect if immages are in a
    matplotlib figure"""
    # fig true
    fig = utils.matplotlib_with_image()
    assert util.matplotlib_contains_images(fig)
    plt.close()

    # plt true
    fig = utils.matplotlib_with_image()
    assert util.matplotlib_contains_images(plt)
    plt.close()

    # fig false
    fig = utils.matplotlib_without_image()
    assert not util.matplotlib_contains_images(fig)
    plt.close()

    # plt false
    fig = utils.matplotlib_without_image()
    assert not util.matplotlib_contains_images(plt)
    plt.close()


def test_matplotlib_to_plotly():
    """Ensures that the utility function can properly transform a pyplot object to a
    plotly object (not the wandb.* versions"""
    fig = utils.matplotlib_without_image()
    assert type(util.matplotlib_to_plotly(fig)) == plotly.graph_objs._figure.Figure
    plt.close()

    fig = utils.matplotlib_without_image()
    assert type(util.matplotlib_to_plotly(plt)) == plotly.graph_objs._figure.Figure
    plt.close()
