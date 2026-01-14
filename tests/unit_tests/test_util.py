import datetime
import enum
import os
import platform
import random
import sys
import tarfile
import tempfile
import time
from dataclasses import dataclass
from unittest import mock

import matplotlib.pyplot as plt
import numpy as np
import plotly
import pytest
import requests
import wandb
import wandb.errors as errors
from wandb import util

###############################################################################
# Test util.json_friendly
###############################################################################


def pt_variable(nested_list, requires_grad=True):
    pytest.importorskip("torch")
    import torch

    v = torch.autograd.Variable(torch.Tensor(nested_list))
    v.requires_grad = requires_grad
    return v


def nested_list(*shape):
    """Make a nested list of lists with a "shape" argument like numpy, TensorFlow, etc."""
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
                    print(f"Diff at index: {list(reversed(indices))}")


def json_friendly_test(orig_data, obj):
    data, converted = util.json_friendly(obj)
    assert_deep_lists_equal(orig_data, data)
    assert converted


def test_jsonify_enum():
    class TestEnum(enum.Enum):
        A = 1
        B = 2

    data, converted = util.json_friendly(TestEnum.A)
    assert data == "A"
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
    pytest.importorskip("torch")
    import torch

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
    pytest.importorskip("tensorflow")
    import tensorflow as tf

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
    jnp = pytest.importorskip("jax.numpy")

    orig_data = nested_list(*array_shape)
    jax_array = jnp.asarray(orig_data)
    json_friendly_test(orig_data, jax_array)
    assert util.is_jax_tensor_typename(util.get_full_typename(jax_array))


@pytest.mark.skipif(
    platform.system() == "Windows", reason="test suite does not build jaxlib on windows"
)
def test_bfloat16_to_float():
    jnp = pytest.importorskip("jax.numpy")

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
# Test util.json_friendly_val
###############################################################################


def test_dataclass():
    @dataclass
    class TestDataClass:
        test: bool

    test_dataclass = TestDataClass(True)
    converted = util.json_friendly_val({"test": test_dataclass})
    assert isinstance(converted["test"], dict)


def test_nested_dataclasses():
    @dataclass
    class TestDataClass:
        test: bool

    @dataclass
    class TestDataClassHolder:
        test_dataclass: TestDataClass

    nested_dataclass = TestDataClassHolder(TestDataClass(False))
    converted = util.json_friendly_val({"nested_dataclass": nested_dataclass})
    assert isinstance(converted["nested_dataclass"], dict)
    assert isinstance(converted["nested_dataclass"]["test_dataclass"], dict)
    assert converted["nested_dataclass"]["test_dataclass"]["test"] is False


def test_nested_dataclasses_containing_real_class():
    class TestRealClass:
        test: bool

        def __init__(self, test: bool):
            self.test = test

        def __str__(self):
            return f"TestRealClass(test={self.test})"

    @dataclass
    class TestDataClassHolder:
        test_real_class: TestRealClass

    real_class = TestRealClass(True)
    nested_dataclass = TestDataClassHolder(real_class)
    converted = util.json_friendly_val(nested_dataclass)
    assert isinstance(converted, dict)
    assert converted == {"test_real_class": "TestRealClass(test=True)"}


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
    """Create a matplotlib figure with an image."""
    fig, ax = plt.subplots(3)
    ax[0].plot([1, 2, 3])
    ax[1].imshow(np.random.rand(200, 200, 3))
    ax[2].plot([1, 2, 3])
    return fig


def matplotlib_without_image():
    """Create a matplotlib figure without an image."""
    fig, ax = plt.subplots(2)
    ax[0].plot([1, 2, 3])
    ax[1].plot([1, 2, 3])
    return fig


def test_matplotlib_contains_images():
    """Test detecting images in a matplotlib figure."""
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
    """Test transforming a pyplot object to a plotly object (not the wandb.* versions)."""
    fig = matplotlib_without_image()
    assert type(util.matplotlib_to_plotly(fig)) is plotly.graph_objs._figure.Figure
    plt.close()

    fig = matplotlib_without_image()
    assert type(util.matplotlib_to_plotly(plt)) is plotly.graph_objs._figure.Figure
    plt.close()


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
    pytest.importorskip("tensorflow")
    import tensorflow as tf

    assert util.is_tf_tensor(tf.constant(1))
    assert not util.is_tf_tensor(tf.Variable(1))
    assert not util.is_tf_tensor(1)
    assert not util.is_tf_tensor(None)


def test_is_pytorch_tensor():
    pytest.importorskip("torch")
    import torch

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
    e.response.reason = "Unauthorized"
    with pytest.raises(errors.AuthenticationError):
        util.no_retry_auth(e)
    e.response.status_code = 403
    e.response.reason = "Forbidden"
    with mock.patch("wandb.run", mock.MagicMock()):
        with pytest.raises(wandb.CommError):
            util.no_retry_auth(e)
    e.response.status_code = 404
    with pytest.raises(LookupError):
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


def test_resolve_aliases_requires_iterable():
    with pytest.raises(ValueError):
        util._resolve_aliases(5)


@pytest.mark.parametrize(
    "aliases", [["best", "dev"], "boom", None, ("latest"), ["boom", "boom"]]
)
def test_resolve_aliases(aliases):
    result = util._resolve_aliases(aliases)
    assert isinstance(result, list)
    assert "latest" in result
    assert len(set(result)) == len(result)
    if aliases and not isinstance(aliases, str):
        assert set(aliases) <= set(result)


# Compute recursive dicts for tests
d_recursive1i = {1: 2, 3: {4: 5}}
d_recursive1i["_"] = d_recursive1i
d_recursive2i = {1: 2, 3: {np.int64(44): 5}}
d_recursive2i["_"] = d_recursive2i
d_recursive2o = {1: 2, 3: {44: 5}}
d_recursive2o["_"] = d_recursive2o


@pytest.mark.parametrize(
    "dict_input, dict_output",
    [
        ({}, None),
        ({1: 2}, None),
        ({1: np.int64(3)}, None),  # dont care about values
        ({np.int64(3): 4}, {3: 4}),  # top-level
        ({1: {np.int64(3): 4}}, {1: {3: 4}}),  # nested key
        ({1: {np.int32(2): 4}}, {1: {2: 4}}),  # nested key
        (d_recursive1i, None),  # recursive, no numpy
        (d_recursive2i, d_recursive2o),  # recursive, numpy
    ],
)
def test_sanitize_numpy_keys(dict_input, dict_output):
    output, converted = util._sanitize_numpy_keys(dict_input)
    assert converted == (dict_output is not None)

    # pytest assert can't handle '==' on recursive dictionaries!
    if "_" in dict_input:
        # Check the recursive case ourselves.
        assert output["_"] is output

        output = {k: v for k, v in output.items() if k != "_"}
        dict_input = {k: v for k, v in dict_input.items() if k != "_"}
        if dict_output:
            dict_output = {k: v for k, v in dict_output.items() if k != "_"}

    assert output == (dict_output or dict_input)


def test_make_docker_image_name_safe():
    assert util.make_docker_image_name_safe("this-name-is-fine") == "this-name-is-fine"
    assert util.make_docker_image_name_safe("also__ok") == "also__ok"
    assert (
        util.make_docker_image_name_safe("github.com/MyUsername/my_repo")
        == "github.com__myusername__my_repo"
    )
    assert (
        util.make_docker_image_name_safe("./abc.123___def-456---_.")
        == "abc.123__def-456"
    )
    assert util.make_docker_image_name_safe("......") == "image"


def test_sampling_weights():
    xs = np.arange(0, 100)
    ys = np.arange(100, 200)
    sample_size = 1000
    sampled_xs, _, _ = util.sample_with_exponential_decay_weights(
        xs, ys, sample_size=sample_size
    )
    # Expect more samples from the start of the list
    assert np.mean(sampled_xs) < np.mean(xs)


def test_json_dump_uncompressed_with_numpy_datatypes():
    import io

    data = {
        "a": [
            np.int32(1),
            np.float32(2.0),
            np.int64(3),
        ]
    }
    iostr = io.StringIO()
    util.json_dump_uncompressed(data, iostr)
    assert iostr.getvalue() == '{"a": [1, 2.0, 3]}'


@pytest.mark.parametrize(
    "internet_state",
    [
        True,
        False,
    ],
)
def test_has_internet(internet_state):
    if internet_state:
        mock_create_connection = mock.MagicMock()
    else:
        mock_create_connection = mock.MagicMock(side_effect=OSError)
    with mock.patch("socket.create_connection", new=mock_create_connection):
        assert util._has_internet() is internet_state
