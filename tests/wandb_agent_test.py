"""Agent tests"""
import pytest
import wandb
import os


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

def test_agent_command_flags(live_mock_server):
    sweep_config = {
        "method": "grid",
        "parameters":{
            "foo_flag" :{
            "values": [True, False],
        },
        },
        "command_flags": ["foo_flag"],
    }
    sweep_callable = lambda: sweep_config
    sweep_id = wandb.sweep(sweep_callable, project="test", entity="test")
    wandb.agent(sweep_id, function=sweep_callable, count=1)

    # TODO: test to make sure the command being executed 
    # import multiprocessing
    # from wandb.wandb_agent import Agent
    
    # agent = Agent(
    #     wandb.InternalApi(),
    #     multiprocessing.Queue(),
    #     sweep_id
    # )
    
    # assert 'foo_flag' in agent._sweep_command_flags