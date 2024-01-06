from typing import Any
from unittest.mock import MagicMock

import pytest
import wandb
from wandb.sdk.integration_utils.auto_logging import AutologAPI, PatchAPI


class PatchAPITest(PatchAPI):
    def __init__(self, *args, **kwargs):
        self._test_api = kwargs.pop("test_api")
        super().__init__(*args, **kwargs)

    @property
    def set_api(self) -> Any:
        return self._test_api


# mock API and resolver for testing purposes
class MockAPI:
    def generate(self):
        assert self
        return {"text": "Hello World!"}

    class Chat:
        @staticmethod
        def complete():
            return {"text": "YES!"}


def mock_resolver(args, kwargs, response, start_time, time_elapsed):
    return {"generated_text": response["text"]}


@pytest.fixture
def patch_api():
    api = PatchAPITest(
        name="MockAPI",
        symbols=["generate", "Chat.complete"],
        resolver=mock_resolver,
        test_api=MockAPI(),
    )

    return api


@pytest.fixture
def mock_autolog_api(patch_api):
    autolog_api = AutologAPI(
        name="MockAPI",
        symbols=["generate", "Chat.complete"],
        resolver=mock_resolver,
    )
    autolog_api._patch_api = patch_api
    return autolog_api


# Tests for PatchAPI functionality
def test_patch_and_unpatch(patch_api):
    # Store the original generate method
    original_generate = patch_api.set_api.generate

    # Test patching
    assert patch_api.set_api.generate == original_generate
    patch_api.patch(MagicMock())
    assert patch_api.set_api.generate != original_generate

    # Test unpatching
    patch_api.unpatch()
    assert patch_api.set_api.generate == original_generate


# Test case for AutologAPI
def test_autolog_api(mock_autolog_api):
    wandb.run = MagicMock()
    # Test enabling AutologAPI
    mock_autolog_api.enable()

    # Check if AutologAPI is enabled
    assert mock_autolog_api._is_enabled

    # Test AutologAPI features
    original_generate = mock_autolog_api._patch_api.set_api.generate
    patched_result = original_generate()
    wandb.run.log.assert_called_with({"generated_text": "Hello World!"})

    # this call should not be logged
    unlogged_result = mock_autolog_api._patch_api.original_methods["generate"]()

    assert unlogged_result == patched_result
    assert unlogged_result["text"] == "Hello World!"

    # Ensure metrics are logged
    logged_text = mock_resolver([], {}, unlogged_result, 0.0, 0.0)["generated_text"]

    assert logged_text == unlogged_result["text"]
    assert logged_text == "Hello World!"

    # call the dotted method
    mock_autolog_api._patch_api.set_api.Chat.complete()

    # check that wandb.run.log was called twice and with the correct arguments
    assert wandb.run.log.call_count == 2
    wandb.run.log.assert_called_with({"generated_text": "YES!"})
