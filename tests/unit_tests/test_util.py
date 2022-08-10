import datetime
import os
import platform
import random
import sys
import tarfile
import tempfile
import time
from unittest import mock

import matplotlib.pyplot as plt
import numpy as np
import plotly
import pytest
import requests
import tensorflow as tf
import wandb
from wandb import util

try:
    import torch
except ImportError:
    pass


###############################################################################
# Test util.json_friendly
###############################################################################


def pt_variable(nested_list, requires_grad=True):
    v = torch.autograd.Variable(torch.Tensor(nested_list))
    v.requires_grad = requires_grad
    return v


def nested_list(*shape):
    """Makes a nested list of lists with a "shape" argument like numpy,
    TensorFlow, etc.
    """
    if not shape:
        # reduce precision so we can use == for comparison regardless
        # of conversions between other libraries
        return [float(np.float16(random.random()))]
    else:
        return [nested_list(*shape[1:]) for _ in range(shape[0])]


def assert_deep_lists_equal(a, b, indices=None):
    try:
        assert a == b
    except ValueError:
        assert len(a) == len(b)

        # pytest's list diffing breaks at 4d, so we track them ourselves
        if indices is None:
            indices = []
            top = True
        else:
            top = False

        for i, (x, y) in enumerate(zip(a, b)):
            try:
                assert_deep_lists_equal(x, y, indices)
            except AssertionError:
                indices.append(i)
                raise
            finally:
                if top and indices:
                    print("Diff at index: %s" % list(reversed(indices)))


def json_friendly_test(orig_data, obj):
    data, converted = util.json_friendly(obj)
    assert_deep_lists_equal(orig_data, data)
    assert converted


@pytest.mark.parametrize(
    "array_shape",
    [
        (),  # 0d
        (1,),  # 1d 1x1
        (3,),  # 1d
        (300,),  # 1d large
        (3,) * 2,  # 2d
        (300,) * 2,  # 2d large
        (3,) * 3,  # 3d
        (1,) * 4,  # 4d
        (1,) * 8,  # 8d
        (3,) * 8,  # 8d large
    ],
)
def test_pytorch_json_nd(array_shape):
    a = nested_list(*array_shape)
    json_friendly_test(a, torch.Tensor(a))
    json_friendly_test(a, pt_variable(a))


@pytest.mark.parametrize(
    "array_shape",
    [
        (),  # 0d
        (1,),  # 1d 1x1
        (3,),  # 1d
        (300,),  # 1d large
        (3,) * 2,  # 2d
        (300,) * 2,  # 2d large
        (3,) * 3,  # 3d
        (1,) * 4,  # 4d
        (1,) * 8,  # 8d
        (3,) * 8,  # 8d large
    ],
)
def test_tensorflow_json_nd(array_shape):
    a = nested_list(*array_shape)
    json_friendly_test(a, tf.convert_to_tensor(a))
    v = tf.Variable(tf.convert_to_tensor(a))
    json_friendly_test(a, v)


@pytest.mark.skipif(
    platform.system() == "Windows", reason="test suite does not build jaxlib on windows"
)
@pytest.mark.parametrize(
    "array_shape",
    [
        (),
        (1,),
        (3,),
        (300,),
        (300,) * 2,
        (1,) * 8,
        (3,) * 8,
    ],
)
def test_jax_json(array_shape):
    from jax import numpy as jnp

    orig_data = nested_list(*array_shape)
    jax_array = jnp.asarray(orig_data)
    json_friendly_test(orig_data, jax_array)
    assert util.is_jax_tensor_typename(util.get_full_typename(jax_array))


@pytest.mark.skipif(
    platform.system() == "Windows", reason="test suite does not build jaxlib on windows"
)
def test_bfloat16_to_float():
    import jax.numpy as jnp

    array = jnp.array(1.0, dtype=jnp.bfloat16)
    # array to scalar bfloat16
    array_cast = util.json_friendly(array)
    assert array_cast[1] is True
    assert array_cast[0].__class__.__name__ == "bfloat16"
    # scalar bfloat16 to float
    array_cast = util.json_friendly(array_cast[0])
    assert array_cast[0] == 1.0
    assert array_cast[1] is True
    assert isinstance(array_cast[0], float)


###############################################################################
# Test util.make_json_if_not_number
###############################################################################


def test_make_json_if_not_number():
    assert util.make_json_if_not_number(1) == 1
    assert util.make_json_if_not_number(1.0) == 1.0
    assert util.make_json_if_not_number("1") == '"1"'
    assert util.make_json_if_not_number("1.0") == '"1.0"'
    assert util.make_json_if_not_number({"a": 1}) == '{"a": 1}'
    assert util.make_json_if_not_number({"a": 1.0}) == '{"a": 1.0}'
    assert util.make_json_if_not_number({"a": "1"}) == '{"a": "1"}'
    assert util.make_json_if_not_number({"a": "1.0"}) == '{"a": "1.0"}'


###############################################################################
# Test util.image_from_docker_args
###############################################################################


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


###############################################################################
# Test util.app_url
###############################################################################


def test_app_url():
    with mock.patch.dict("os.environ", {"WANDB_APP_URL": "https://foo.com/bar/"}):
        assert util.app_url("https://api.foo.com") == "https://foo.com/bar"
    assert util.app_url("http://api.wandb.test") == "http://app.wandb.test"
    assert util.app_url("https://api.wandb.ai") == "https://wandb.ai"
    assert util.app_url("https://api.foo/bar") == "https://app.foo/bar"
    assert util.app_url("https://wandb.foo") == "https://wandb.foo"


###############################################################################
# Test util.make_safe_for_json
###############################################################################


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


###############################################################################
# Test util.find_runner
###############################################################################


@pytest.mark.skipif(
    platform.system() == "Windows", reason="find_runner is broken on Windows"
)
def test_find_runner():
    res = util.find_runner(__file__)
    assert "python" in res[0]


###############################################################################
# Test util.parse_sweep_id
###############################################################################


def test_parse_sweep_id():
    parts = {"name": "test/test/test"}
    util.parse_sweep_id(parts)
    assert parts == {"name": "test", "entity": "test", "project": "test"}


###############################################################################
# Test util.from_human_size and util.to_human_size
###############################################################################


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


###############################################################################
# Test matplotlib utilities
###############################################################################


def matplotlib_with_image():
    """Creates a matplotlib figure with an image"""
    fig, ax = plt.subplots(3)
    ax[0].plot([1, 2, 3])
    ax[1].imshow(np.random.rand(200, 200, 3))
    ax[2].plot([1, 2, 3])
    return fig


def matplotlib_without_image():
    """Creates a matplotlib figure without an image"""
    fig, ax = plt.subplots(2)
    ax[0].plot([1, 2, 3])
    ax[1].plot([1, 2, 3])
    return fig


def test_matplotlib_contains_images():
    """Ensures that the utility function can properly detect if immages are in a
    matplotlib figure"""
    # fig true
    fig = matplotlib_with_image()
    assert util.matplotlib_contains_images(fig)
    plt.close()

    # plt true
    fig = matplotlib_with_image()
    assert util.matplotlib_contains_images(plt)
    plt.close()

    # fig false
    fig = matplotlib_without_image()
    assert not util.matplotlib_contains_images(fig)
    plt.close()

    # plt false
    fig = matplotlib_without_image()
    assert not util.matplotlib_contains_images(plt)
    plt.close()


def test_matplotlib_to_plotly():
    """Ensures that the utility function can properly transform a pyplot object to a
    plotly object (not the wandb.* versions"""
    fig = matplotlib_without_image()
    assert type(util.matplotlib_to_plotly(fig)) == plotly.graph_objs._figure.Figure
    plt.close()

    fig = matplotlib_without_image()
    assert type(util.matplotlib_to_plotly(plt)) == plotly.graph_objs._figure.Figure
    plt.close()


def test_apple_gpu_stats_binary():
    assert util.apple_gpu_stats_binary().endswith(
        os.path.join("bin", "apple_gpu_stats")
    )


def test_convert_plots():
    fig = matplotlib_without_image()
    obj = util.convert_plots(fig)
    assert obj.get("plot")
    assert obj.get("_type") == "plotly"


###############################################################################
# Test uri and path resolution utilities
###############################################################################


def test_is_uri():
    assert util.is_uri("http://foo.com")
    assert util.is_uri("https://foo.com")
    assert util.is_uri("file:///foo.com")
    assert util.is_uri("s3://foo.com")
    assert util.is_uri("gs://foo.com")
    assert util.is_uri("foo://foo.com")
    assert not util.is_uri("foo.com")
    assert not util.is_uri("foo")


@pytest.mark.skipif(
    platform.system() == "Windows", reason="fixme: make this work on windows"
)
def test_local_file_uri_to_path():
    assert util.local_file_uri_to_path("file:///foo.com") == "/foo.com"
    assert util.local_file_uri_to_path("file://foo.com") == ""
    assert util.local_file_uri_to_path("file:///foo") == "/foo"
    assert util.local_file_uri_to_path("file://foo") == ""
    assert util.local_file_uri_to_path("file:///") == "/"
    assert util.local_file_uri_to_path("file://") == ""
    assert util.get_local_path_or_none("https://foo.com") is None


@pytest.mark.skipif(
    platform.system() == "Windows", reason="fixme: make this work on windows"
)
def test_get_local_path_or_none():
    assert util.get_local_path_or_none("file:///foo.com") == "/foo.com"
    assert util.get_local_path_or_none("file://foo.com") is None
    assert util.get_local_path_or_none("file:///foo") == "/foo"
    assert util.get_local_path_or_none("file://foo") is None
    assert util.get_local_path_or_none("file:///") == "/"
    assert util.get_local_path_or_none("file://") == ""
    assert util.get_local_path_or_none("/foo.com") == "/foo.com"
    assert util.get_local_path_or_none("foo.com") == "foo.com"
    assert util.get_local_path_or_none("/foo") == "/foo"
    assert util.get_local_path_or_none("foo") == "foo"
    assert util.get_local_path_or_none("/") == "/"
    assert util.get_local_path_or_none("") == ""


def test_make_tarfile():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpfile = os.path.join(tmpdir, "foo.tar.gz")
        util.make_tarfile(
            output_filename=tmpfile,
            source_dir=tmpdir,
            archive_name="lol",
        )
        assert os.path.exists(tmpfile)
        assert tarfile.is_tarfile(tmpfile)


###############################################################################
# Test tensor type utilities
###############################################################################


def test_is_tf_tensor():
    assert util.is_tf_tensor(tf.constant(1))
    assert not util.is_tf_tensor(tf.Variable(1))
    assert not util.is_tf_tensor(1)
    assert not util.is_tf_tensor(None)


def test_is_pytorch_tensor():
    assert util.is_pytorch_tensor(torch.tensor(1))
    assert not util.is_pytorch_tensor(1)
    assert not util.is_pytorch_tensor(None)


###############################################################################
# Test launch utilities
###############################################################################


def test_launch_browser():
    with mock.patch("sys.platform", "linux"):
        with mock.patch.dict("sys.modules", {"webbrowser": mock.MagicMock()}):
            import webbrowser

            webbrowser.get().name = mock.MagicMock(return_value="lynx")
            assert not util.launch_browser()
            webbrowser.get().name = mock.MagicMock(side_effect=webbrowser.Error)
            assert not util.launch_browser()


def test_parse_tfjob_config():
    with mock.patch.dict(
        "os.environ", {"TF_CONFIG": '{"cluster": {"master": ["foo"]}}'}
    ):
        assert util.parse_tfjob_config() == {"cluster": {"master": ["foo"]}}
    with mock.patch.dict("os.environ", {"TF_CONFIG": "LOL"}):
        assert util.parse_tfjob_config() is False
    assert util.parse_tfjob_config() is False


###############################################################################
# Test retry utilities
###############################################################################


def test_no_retry_auth():
    e = mock.MagicMock(spec=requests.HTTPError)
    e.response = mock.MagicMock(spec=requests.Response)
    for status_code in (400, 409):
        e.response.status_code = status_code
        assert not util.no_retry_auth(e)
    e.response.status_code = 401
    with pytest.raises(wandb.CommError):
        util.no_retry_auth(e)
    e.response.status_code = 403
    with mock.patch("wandb.run", mock.MagicMock()):
        with pytest.raises(wandb.CommError):
            util.no_retry_auth(e)
    e.response.status_code = 404
    with pytest.raises(wandb.CommError):
        util.no_retry_auth(e)

    e.response = None
    assert util.no_retry_auth(e)
    e = ValueError("foo")
    assert util.no_retry_auth(e)


def test_check_retry_conflict():
    e = mock.MagicMock(spec=requests.HTTPError)
    e.response = mock.MagicMock(spec=requests.Response)

    e.response.status_code = 400
    assert util.check_retry_conflict(e) is None

    e.response.status_code = 500
    assert util.check_retry_conflict(e) is None

    e.response.status_code = 409
    assert util.check_retry_conflict(e) is True


def test_check_retry_conflict_or_gone():
    e = mock.MagicMock(spec=requests.HTTPError)
    e.response = mock.MagicMock(spec=requests.Response)

    e.response.status_code = 400
    assert util.check_retry_conflict_or_gone(e) is None

    e.response.status_code = 410
    assert util.check_retry_conflict_or_gone(e) is False

    e.response.status_code = 500
    assert util.check_retry_conflict_or_gone(e) is None

    e.response.status_code = 409
    assert util.check_retry_conflict_or_gone(e) is True


def test_make_check_reply_fn_timeout():
    """Verify case where secondary check returns a new timeout."""
    e = mock.MagicMock(spec=requests.HTTPError)
    e.response = mock.MagicMock(spec=requests.Response)

    check_retry_fn = util.make_check_retry_fn(
        check_fn=util.check_retry_conflict_or_gone,
        check_timedelta=datetime.timedelta(minutes=3),
        fallback_retry_fn=util.no_retry_auth,
    )

    e.response.status_code = 400
    check = check_retry_fn(e)
    assert check is False

    e.response.status_code = 410
    check = check_retry_fn(e)
    assert check is False

    e.response.status_code = 500
    check = check_retry_fn(e)
    assert check is True

    e.response.status_code = 409
    check = check_retry_fn(e)
    assert check
    assert check == datetime.timedelta(minutes=3)


def test_make_check_reply_fn_false():
    """Verify case where secondary check forces no retry."""
    e = mock.MagicMock(spec=requests.HTTPError)
    e.response = mock.MagicMock(spec=requests.Response)

    def is_special(e):
        if e.response.status_code == 500:
            return False
        return None

    check_retry_fn = util.make_check_retry_fn(
        check_fn=is_special,
        fallback_retry_fn=util.no_retry_auth,
    )

    e.response.status_code = 400
    check = check_retry_fn(e)
    assert check is False

    e.response.status_code = 500
    check = check_retry_fn(e)
    assert check is False

    e.response.status_code = 409
    check = check_retry_fn(e)
    assert check is False


def test_make_check_reply_fn_true():
    """Verify case where secondary check allows retry."""
    e = mock.MagicMock(spec=requests.HTTPError)
    e.response = mock.MagicMock(spec=requests.Response)

    def is_special(e):
        if e.response.status_code == 400:
            return True
        return None

    check_retry_fn = util.make_check_retry_fn(
        check_fn=is_special,
        fallback_retry_fn=util.no_retry_auth,
    )

    e.response.status_code = 400
    check = check_retry_fn(e)
    assert check is True

    e.response.status_code = 500
    check = check_retry_fn(e)
    assert check is True

    e.response.status_code = 409
    check = check_retry_fn(e)
    assert check is False


def test_downsample():
    with pytest.raises(wandb.UsageError):
        util.downsample([1, 2, 3], 1)
    assert util.downsample([1, 2, 3, 4], 2) == [1, 4]


def test_get_log_file_path(mock_run):
    assert util.get_log_file_path() == os.path.join("wandb", "debug-internal.log")
    run = mock_run()
    assert util.get_log_file_path() == run._settings.log_internal


def test_stopwatch_now():
    t_1 = util.stopwatch_now()
    time.sleep(0.1)
    t_2 = util.stopwatch_now()
    assert t_2 > t_1


def test_class_colors():
    assert util.class_colors(3) == [[0, 0, 0], (1.0, 0.0, 0.0), (0.0, 1.0, 1.0)]


def test_check_and_warn_old():
    assert util.check_and_warn_old(["wandb-metadata.json"])


def test_is_databricks():
    assert not util._is_databricks()
    with mock.patch.dict("sys.modules", {"dbutils": mock.MagicMock()}):
        dbutils = sys.modules["dbutils"]
        dbutils.shell = mock.MagicMock()
        dbutils.shell.sc = mock.MagicMock()
        dbutils.shell.sc.appName = "Databricks Shell"
        assert util._is_databricks()


def test_parse_entity_project_item():
    def f(*args, **kwargs):
        return util._parse_entity_project_item(*args, **kwargs)

    with pytest.raises(ValueError):
        f("boom/a/b/c")

    item, project, entity = f("myproj/mymodel:latest")
    assert item == "mymodel:latest"
    assert project == "myproj"
    assert entity == ""

    item, project, entity = f("boom")
    assert item == "boom"
    assert project == ""
    assert entity == ""


def test_resolve_aliases():
    with pytest.raises(ValueError):
        util._resolve_aliases(5)

    aliases = util._resolve_aliases(["best", "dev"])
    assert aliases == ["best", "dev", "latest"]

    aliases = util._resolve_aliases("boom")
    assert aliases == ["boom", "latest"]
