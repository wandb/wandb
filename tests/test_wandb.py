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
import time
import json
from click.testing import CliRunner
from .api_mocks import *

import wandb
from wandb import wandb_run


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


def test_nice_log_error():
    with pytest.raises(ValueError):
        wandb.log({"no": "init"})


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


@pytest.mark.mock_socket
def test_save_policy_symlink(wandb_init_run):
    with open("test.rad", "w") as f:
        f.write("something")
    wandb.save("test.rad")
    assert wandb_init_run.socket.send.called


@pytest.mark.args(resume=True)
def test_auto_resume_first(wandb_init_run):
    assert json.load(open(os.path.join(wandb.wandb_dir(), wandb_run.RESUME_FNAME)))[
        "run_id"] == wandb_init_run.id
    assert not wandb_init_run.resumed


@pytest.mark.args(resume="testy")
def test_auto_resume_manual(wandb_init_run):
    assert wandb_init_run.id == "testy"


@pytest.mark.resume()
@pytest.mark.args(resume=True)
def test_auto_resume_second(wandb_init_run):
    assert wandb_init_run.id == "test"
    assert wandb_init_run.resumed
    assert wandb_init_run.step == 16


@pytest.mark.resume()
@pytest.mark.args(resume=False)
def test_auto_resume_remove(wandb_init_run):
    assert not os.path.exists(os.path.join(
        wandb.wandb_dir(), wandb_run.RESUME_FNAME))


@pytest.mark.jupyter
def test_save_policy_jupyter(wandb_init_run, query_upload_h5, request_mocker):
    with open("test.rad", "w") as f:
        f.write("something")
    mock = query_upload_h5(request_mocker)
    wandb.save("test.rad")
    # TODO: Hacky as hell
    time.sleep(1.5)
    assert mock.called


def test_restore(wandb_init_run, request_mocker, download_url, query_run_v2, query_run_files):
    query_run_v2(request_mocker)
    query_run_files(request_mocker)
    download_url(request_mocker, size=10000)
    res = wandb.restore("weights.h5")
    assert os.path.getsize(res.name) == 10000


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
