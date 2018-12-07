import argparse
import pytest
import os
import sys
import os
import textwrap
import yaml
import mock
import glob
import socket
import six
from .api_mocks import *

import wandb


def test_log(wandb_init_run):
    history_row = {'stuff': 5}
    wandb.log(history_row)
    assert len(wandb.run.history.rows) == 1
    assert set(history_row.items()) <= set(wandb.run.history.rows[0].items())


def test_log_step(wandb_init_run):
    history_row = {'stuff': 5}
    wandb.log(history_row, step=5)
    wandb.log()
    assert len(wandb.run.history.rows) == 1
    assert wandb.run.history.rows[0]['_step'] == 5


@pytest.mark.args(sagemaker=True)
def test_sagemaker(wandb_init_run):
    assert wandb.config.fuckin == "A"
    assert wandb.run.id == "sage-maker"
    assert os.getenv('WANDB_TEST_SECRET') == "TRUE"
    assert wandb.run.group == "sage"


@pytest.mark.args(tf_config={"cluster": {"master": ["trainer-4dsl7-master-0:2222"]}, "task": {"type": "master", "index": 0}, "environment": "cloud"})
def test_simple_tfjob(wandb_init_run):
    assert wandb.run.group is None
    assert wandb.run.job_type == "master"


@pytest.mark.args(tf_config={"cluster": {"master": ["trainer-sj2hp-master-0:2222"], "ps": ["trainer-sj2hp-ps-0:2222"], "worker": ["trainer-sj2hp-worker-0:2222"]}, "task": {"type": "worker", "index": 0}, "environment": "cloud"})
def test_distributed_tfjob(wandb_init_run):
    assert wandb.run.group == "trainer-sj2hp"
    assert wandb.run.job_type == "worker"


@pytest.mark.args(tf_config={"cluster": {"corrupt": ["bad"]}})
def test_corrupt_tfjob(wandb_init_run):
    assert wandb.run.group is None


@pytest.mark.args(env={"TF_CONFIG": "garbage"})
def test_bad_json_tfjob(wandb_init_run):
    assert wandb.run.group is None


@pytest.mark.args(error="io")
def test_io_error(wandb_init_run):
    assert isinstance(wandb_init_run, wandb.LaunchError)


@pytest.mark.skip("Need to figure out the headless fun")
@pytest.mark.args(error="socket")
def test_io_error(wandb_init_run):
    assert isinstance(wandb_init_run, wandb.LaunchError)


@pytest.mark.args(dir="/tmp")
def test_custom_dir(wandb_init_run):
    assert len(glob.glob("/tmp/wandb/run-*")) > 0


@pytest.mark.jupyter
def test_jupyter_init(wandb_init_run, capfd):
    assert os.getenv("WANDB_JUPYTER")
    wandb.log({"stat": 1})
    out, err = capfd.readouterr()
    assert "Resuming" in out
    # TODO: saw some global state issues here...
    # assert "" == err


@pytest.mark.skip("Can't figure out how to make the test handle input :(")
@pytest.mark.jupyter
@pytest.mark.unconfigured
@mock.patch.object(wandb.Api, 'api_key', None)
@mock.patch(
    'getpass.getpass', lambda *args: '0123456789012345678901234567890123456789\n')
@mock.patch('six.moves.input', lambda *args: 'foo/bar\n')
def test_jupyter_manual_configure(wandb_init_run, capsys):
    out, err = capsys.readouterr()
    assert "Not authenticated" in err
    assert "No W&B project configured" in err
    assert "Wrap your training" in out
