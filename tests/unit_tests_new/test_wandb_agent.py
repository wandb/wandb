"""Agent tests"""
import pytest
from wandb.wandb_agent import Agent


def test_agent_create_command_args():
    mock_command = {
        "args": {"a": {"value": True}, "b": {"value": False}, "c": {"value": 1}}
    }

    _return = Agent._create_command_args(mock_command)
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
        _ = Agent._create_command_args(mock_command_no_args)
    mock_command_missing_value = {"args": {"a": {"foo": True}}}
    with pytest.raises(ValueError):
        _ = Agent._create_command_args(mock_command_missing_value)
