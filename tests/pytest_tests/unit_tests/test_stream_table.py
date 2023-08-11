import json
import platform
from unittest import mock

import numpy as np
import pytest
import wandb
from wandb.sdk.wandb_lite_run import _InMemoryLazyLiteRun


@pytest.fixture
def lite_run(runner):
    run_instance = _InMemoryLazyLiteRun("test", "test", "streamtable")
    with mock.patch(
        "wandb.sdk.wandb_stream_table._InMemoryLazyLiteRun"
    ) as lite_run_class:
        run_instance.log_artifact = mock.MagicMock()
        run_instance.finish = mock.MagicMock()
        run_instance._stream = mock.MagicMock()
        run_instance._pusher = mock.MagicMock()
        run_instance._run = mock.MagicMock()
        # TODO: might need to mock supports_streamtable
        lite_run_class.return_value = run_instance
        yield run_instance


def file_stream_payload(mock):
    return json.loads(mock.mock_calls[0][1][1])


def test_streamtable_no_login():
    with pytest.raises(wandb.Error):
        wandb.StreamTable("test/test/streamtable")


@mock.patch("wandb.sdk.wandb_lite_run._p_api")
def test_streamtable_no_entity_uses_default(papi, lite_run):
    papi.default_entity = "test"
    papi.api_key = "X" * 40
    st = wandb.StreamTable("test/streamtable")
    assert st._entity_name == "test"


def test_streamtable_no_project(runner):
    with pytest.raises(ValueError):
        wandb.StreamTable("streamtable", entity_name="test")


@mock.patch(
    "wandb.sdk.wandb_stream_table._InMemoryLazyLiteRun.supports_streamtable",
    new_callable=mock.PropertyMock,
)
def test_streamtable_no_support(supports_streamtable, runner):
    supports_streamtable.return_value = False
    with pytest.raises(wandb.Error, match="version of wandb"):
        wandb.StreamTable("test/test/streamtable")


def test_streamtable_telemetry(lite_run):
    st = wandb.StreamTable("test/test/streamtable")
    assert st._lite_run._config["_wandb"]["t"] == {
        1: mock.ANY,
        3: [56],
        4: platform.python_version(),
        5: wandb.__version__,
    }


def test_streamtable_basic_logging(lite_run):
    st = wandb.StreamTable("test/test/streamtable")
    st.log({"a": 1, "b": 2, "c": 3})
    st._lite_run.log_artifact.assert_called_once()
    st.finish()
    st._lite_run.finish.assert_called_once()
    row = file_stream_payload(st._lite_run.stream.push)
    assert row == {
        "a": 1,
        "b": 2,
        "c": 3,
        "_client_id": st._client_id,
        "_timestamp": mock.ANY,
    }


def test_streamtable_basic_media_types(lite_run, capsys):
    st = wandb.StreamTable("test/test/streamtable")
    st.log({"a": 1, "b": 2, "c": 3, "image": wandb.Image(np.zeros((28, 28)))})
    st.finish()
    row = file_stream_payload(st._lite_run.stream.push)
    assert row == {
        "a": 1,
        "b": 2,
        "c": 3,
        "image": None,
        "_client_id": st._client_id,
        "_timestamp": mock.ANY,
    }
    _, err = capsys.readouterr()
    assert "WARNING ignoring unsupported type for StreamTable[image]" in err


def test_streamtable_numpy(lite_run):
    st = wandb.StreamTable("test/test/streamtable")
    st.log(
        {
            "embedding": np.zeros((128,)),
            "fp16": np.float16(1.0),
            "fp96": np.array([1.0, 2.0], dtype=np.float16),
        }
    )
    st.finish()
    row = file_stream_payload(st._lite_run.stream.push)
    assert row == {
        "embedding": [0] * 128,
        "fp16": 1.0,
        "fp96": [1.0, 2.0],
        "_client_id": st._client_id,
        "_timestamp": mock.ANY,
    }


@mock.patch("wandb.run")
def test_streamtable_with_run(run, lite_run):
    st = wandb.StreamTable("test/test/streamtable")
    run.path = "testing/other/run"
    st.log({"a": 1, "b": 2, "c": 3})
    st.finish()
    row = file_stream_payload(st._lite_run.stream.push)
    assert row == {
        "a": 1,
        "b": 2,
        "c": 3,
        "_client_id": st._client_id,
        "_run": "testing/other/run",
        "_timestamp": mock.ANY,
    }
