"""Agent tests"""
import pytest
import wandb
import os

from wandb.wandb_agent import Agent


def test_agent_basic(live_mock_server):
    sweep_ids = []
    sweep_configs = []

    def train():
        run = wandb.init()
        sweep_ids.append(run.sweep_id)
        sweep_configs.append(dict(run.config))
        run.finish()

    wandb.agent("test-sweep-id", function=train, count=1)

    assert len(sweep_ids) == len(sweep_configs) == 1
    assert sweep_ids[0] == "test-sweep-id"
    assert sweep_configs[0] == {"a": 1}


def test_agent_config_merge(live_mock_server):
    sweep_configs = []
    os.environ["WANDB_CONSOLE"] = "off"

    def train():
        run = wandb.init(config={"extra": 2})
        sweep_configs.append(dict(run.config))
        run.finish()

    wandb.agent("test-sweep-id-2", function=train, count=1)

    assert len(sweep_configs) == 1
    assert sweep_configs[0] == {"a": 1, "extra": 2}


def test_agent_config_ignore(live_mock_server):
    sweep_configs = []

    def train():
        run = wandb.init(config={"a": "ignored", "extra": 2})
        sweep_configs.append(dict(run.config))
        run.finish()

    wandb.agent("test-sweep-id-3", function=train, count=1)

    assert len(sweep_configs) == 1
    assert sweep_configs[0] == {"a": 1, "extra": 2}


def test_agent_ignore(live_mock_server):
    sweep_entities = []
    sweep_projects = []

    def train():
        run = wandb.init(entity="ign", project="ignored")
        sweep_projects.append(run.project)
        sweep_entities.append(run.entity)
        run.finish()

    wandb.agent("test-sweep-id-3", function=train, count=1)

    assert len(sweep_projects) == len(sweep_entities) == 1
    assert sweep_projects[0] == "test"
    assert sweep_entities[0] == "mock_server_entity"


def test_agent_ignore_runid(live_mock_server):
    sweep_run_ids = []

    def train():
        run = wandb.init(id="ignored")
        sweep_run_ids.append(run.id)
        run.finish()

    wandb.agent("test-sweep-id-3", function=train, count=1)

    assert len(sweep_run_ids) == 1
    assert sweep_run_ids[0] == "mocker-sweep-run-x91"


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
