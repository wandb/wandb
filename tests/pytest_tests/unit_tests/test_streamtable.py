from unittest import mock

import pytest
import wandb


@pytest.fixture
@mock.patch("wandb.sdk.wandb_streamtable._InMemoryLazyLiteRun")
@mock.patch(
    "wandb.apis.public.Api.supports_streamtable", new_callable=mock.PropertyMock
)
def st(supports_streamtable, lite_run_class, runner):
    supports_streamtable.return_value = True
    run_instance = mock.MagicMock()
    run_instance._run_name = "streamtable"
    run_instance._project_name = "test"
    run_instance._entity_name = "test"
    lite_run_class.return_value = run_instance
    st = wandb.StreamTable("test/test/streamtable")
    return st


def test_streamtable_no_login():
    with pytest.raises(wandb.Error):
        wandb.StreamTable("test/test/streamtable")


def test_streamtable_no_entity():
    with pytest.raises(ValueError):
        wandb.StreamTable("test/streamtable")


def test_streamtable_no_project():
    with pytest.raises(ValueError):
        wandb.StreamTable("streamtable", entity_name="test")


@mock.patch(
    "wandb.apis.public.Api.supports_streamtable", new_callable=mock.PropertyMock
)
def test_streamtable_no_support(supports_streamtable, runner):
    supports_streamtable.return_value = False
    with pytest.raises(wandb.Error, match="version of wandb"):
        wandb.StreamTable("test/test/streamtable")


def test_streamtable_logging(st):
    st.log({"a": 1, "b": 2, "c": 3})
    st._lite_run.log_artifact.assert_called_once()
    st.finish()
    st._lite_run.log.assert_called_once_with(
        {"a": 1, "b": 2, "c": 3, "_client_id": st._client_id}
    )


def test_streamtable_finish(st):
    st.log({"a": 1, "b": 2, "c": 3})
    st._lite_run.log_artifact.assert_called_once()
    st.finish()
    st._lite_run.finish.assert_called_once()
    st._lite_run.log.assert_called_once_with(
        {"a": 1, "b": 2, "c": 3, "_client_id": st._client_id}
    )
