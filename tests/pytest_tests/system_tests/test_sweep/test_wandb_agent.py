"""Agent tests."""
import os
from unittest import mock

import pytest
from wandb.sdk.launch.sweeps.utils import (
    create_sweep_command,
    create_sweep_command_args,
)
from wandb.wandb_agent import Agent


def test_agent_create_command_args():
    mock_command = {
        "args": {"a": {"value": True}, "b": {"value": False}, "c": {"value": 1}}
    }

    _return = create_sweep_command_args(mock_command)
    # test has all the required fields
    assert "args" in _return
    assert "args_no_hyphens" in _return
    assert "args_no_boolean_flags" in _return
    assert "args_json" in _return
    # test fields are correct
    assert _return["args"] == ["--a=True", "--b=False", "--c=1"]
    assert _return["args_no_hyphens"] == ["a=True", "b=False", "c=1"]
    assert _return["args_no_boolean_flags"] == ["--a", "--c=1"]
    assert _return["args_json"] == ['{"a": true, "b": false, "c": 1}']


def test_agent_create_command_args_bad_command():
    mock_command_no_args = {"foo": None}
    with pytest.raises(ValueError):
        _ = create_sweep_command_args(mock_command_no_args)
    mock_command_missing_value = {"args": {"a": {"foo": True}}}
    with pytest.raises(ValueError):
        _ = create_sweep_command_args(mock_command_missing_value)


@mock.patch.dict(
    os.environ,
    {
        "FOO_DIR": "foo_dir",
        "FOO_DIR_TWO": "foo_dir_two",
        "FOO_VAR": "foo_var",
    },
)
def test_agent_create_sweep_command():
    # Given no command, function should return default
    _command = create_sweep_command()
    assert _command == Agent.DEFAULT_SWEEP_COMMAND

    # Environment variable macros should be replaced in mock command
    _command = create_sweep_command(
        [
            "${env}",
            "${interpreter}",
            "--output_dir",
            "fake/path/${envvar:FOO_DIR}/${envvar:FOO_DIR}/${envvar:FOO_DIR_TWO}",
            "--foovar",
            "${envvar:FOO_VAR}",
        ]
    )
    assert _command == [
        "${env}",
        "${interpreter}",
        "--output_dir",
        "fake/path/foo_dir/foo_dir/foo_dir_two",
        "--foovar",
        "foo_var",
    ]
