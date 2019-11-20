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
import threading
from click.testing import CliRunner

from .api_mocks import *
from .utils import runner, git_repo
import wandb
from wandb import wandb_run
from wandb import env

# Tests which rely on row history in memory should set `History.keep_rows = True`
from wandb.history import History
History.keep_rows = True


def test_log(wandb_init_run):
    history_row = {'stuff': 5}
    wandb.log(history_row)
    assert len(wandb.run.history.rows) == 1
    assert set(history_row.items()) <= set(wandb.run.history.rows[0].items())


@pytest.mark.mocked_run_manager()
def test_log_step(wandb_init_run, capsys):
    history_row = {'stuff': 5}
    wandb.log(history_row, step=5)
    wandb.log()
    _, err = capsys.readouterr()
    assert "wandb: " in err
    assert len(wandb.run.history.rows) == 1
    assert wandb.run.history.rows[0]['_step'] == 5


@pytest.mark.silent()
@pytest.mark.mocked_run_manager()
def test_log_silent(wandb_init_run, capsys):
    wandb.log({"cool": 1})
    _, err = capsys.readouterr()
    assert "wandb: " not in err


def test_log_only_strings_as_keys(wandb_init_run):
    with pytest.raises(ValueError):
        wandb.log({1: 1000})
    with pytest.raises(ValueError):
        wandb.log({('tup', 'idx'): 1000})


def test_async_log(wandb_init_run):
    for i in range(100):
        wandb.log({"cool": 1000}, sync=False)
    wandb.shutdown_async_log_thread()
    wandb.log({"cool": 100}, sync=False)
    wandb.shutdown_async_log_thread()
    assert wandb.run.history.rows[-1]['cool'] == 100
    assert len(wandb.run.history.rows) == 101


def test_nice_log_error():
    with pytest.raises(ValueError):
        wandb.log({"no": "init"})


def test_nice_log_error_config():
    with pytest.raises(wandb.Error) as e:
        wandb.config.update({"foo": 1})
    assert e.value.message == "You must call wandb.init() before wandb.config.update"
    with pytest.raises(wandb.Error) as e:
        wandb.config.foo = 1
    assert e.value.message == "You must call wandb.init() before wandb.config.foo"


def test_nice_log_error_summary():
    with pytest.raises(wandb.Error) as e:
        wandb.summary["great"] = 1
    assert e.value.message == 'You must call wandb.init() before wandb.summary["great"]'
    with pytest.raises(wandb.Error) as e:
        wandb.summary.bam = 1
    assert e.value.message == 'You must call wandb.init() before wandb.summary.bam'


@pytest.mark.args(k8s=True)
def test_k8s_success(wandb_init_run):
    assert os.getenv("WANDB_DOCKER") == "test@sha256:1234"


@pytest.mark.args(k8s=False)
def test_k8s_failure(wandb_init_run):
    assert os.getenv("WANDB_DOCKER") is None


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
def test_io_error(wandb_init_run, capsys):
    out, err = capsys.readouterr()
    assert isinstance(wandb_init_run, wandb.LaunchError)


@pytest.mark.headless()
@pytest.mark.args(error="socket")
def test_io_headless(wandb_init_run, mocker):
    with pytest.raises(wandb.LaunchError) as err:
        wandb._init_headless(wandb_init_run)
    assert "wandb/debug.log" in str(err.value)


@pytest.mark.args(dir="/tmp")
def test_custom_dir(wandb_init_run):
    assert len(glob.glob("/tmp/wandb/run-*")) > 0


def test_login_key(local_netrc, capsys):
    wandb.login(key="A"* 40)
    out, err = capsys.readouterr()
    assert "wandb: WARNING If" in err
    assert wandb.api.api_key == "A" * 40


def test_login_existing_key(local_netrc):
    os.environ["WANDB_API_KEY"] = "B" * 40
    wandb.ensure_configured()
    wandb.login()
    assert wandb.api.api_key == "B" * 40


def test_login_no_key(local_netrc, mocker):
    stdin_mock = mocker.patch("wandb.util.sys.stdin.isatty")
    stdin_mock.return_value = True
    stdout_mock = mocker.patch("wandb.util.sys.stdout.isatty")
    stdout_mock.return_value = True
    inp = mocker.patch("wandb.util.six.moves.input")
    inp.return_value = "2"
    getpass = mocker.patch("wandb.util.getpass.getpass")
    getpass.return_value = "C" * 40

    wandb.ensure_configured()
    assert wandb.api.api_key == None
    wandb.login()
    assert wandb.api.api_key == "C" * 40


def test_run_context_multi_run(live_mock_server, git_repo):
    os.environ[env.BASE_URL] = "http://localhost:%i" % 8765
    os.environ["WANDB_API_KEY"] = "B" * 40
    with wandb.init() as run:
        run.log({"a": 1, "b": 2})

    with wandb.init(reinit=True) as run:
        run.log({"c": 3, "d": 4})

    assert len(glob.glob("wandb/*")) == 4


def test_login_jupyter_anonymous(mock_server, local_netrc, mocker):
    python = mocker.patch("wandb._get_python_type")
    python.return_value = "ipython"
    wandb.login(anonymous="allow")
    assert wandb.api.api_key == "ANONYMOOSE" * 4


def test_login_anonymous(mock_server, local_netrc):
    os.environ["WANDB_API_KEY"] = "B" * 40
    wandb.login(anonymous="must")
    assert wandb.api.api_key == "ANONYMOOSE" * 4


@pytest.mark.mock_socket
def test_save_policy_symlink(wandb_init_run):
    with open("test.rad", "w") as f:
        f.write("something")
    wandb.save("test.rad")
    assert wandb_init_run.socket.send.called


@pytest.mark.mock_socket
def test_save_absolute_path(wandb_init_run):
    with open("/tmp/test.txt", "w") as f:
        f.write("something")
    wandb.save("/tmp/test.txt")
    assert os.path.exists(os.path.join(wandb_init_run.dir, "test.txt"))


@pytest.mark.mock_socket
def test_save_relative_path(wandb_init_run):
    with open("/tmp/test.txt", "w") as f:
        f.write("something")
    wandb.save("/tmp/test.txt", base_path="/")
    assert os.path.exists(os.path.join(wandb_init_run.dir, "tmp/test.txt"))


@pytest.mark.mock_socket
def test_save_invalid_path(wandb_init_run):
    with open("/tmp/test.txt", "w") as f:
        f.write("something")
    with pytest.raises(ValueError):
        wandb.save("../tmp/../../*.txt", base_path="/tmp")


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
    #mock = query_upload_h5(request_mocker)
    wandb.run.socket = None
    wandb.save("test.rad")
    assert wandb_init_run._jupyter_agent.rm._user_file_policies == {
        'end': [], 'live': ['test.rad']}


def test_restore(runner, request_mocker, download_url, wandb_init_run):
    with runner.isolated_filesystem():
        download_url(request_mocker, size=10000)
        res = wandb.restore("weights.h5")
        assert os.path.getsize(res.name) == 10000


@pytest.mark.jupyter
@pytest.mark.mocked_run_manager
def test_jupyter_init(wandb_init_run):
    assert os.getenv(env.JUPYTER)
    wandb.log({"stat": 1})
    fsapi = wandb_init_run.run_manager._api._file_stream_api
    wandb_init_run._stop_jupyter_agent()
    payloads = {c[1][0]: json.loads(c[1][1])
                for c in fsapi.push.mock_calls}
    assert payloads["wandb-history.jsonl"]["stat"] == 1
    assert payloads["wandb-history.jsonl"]["_step"] == 16

    # TODO: saw some global state issues here...
    # assert "" == err


@pytest.mark.skip
@pytest.mark.jupyter
def test_jupyter_log_history(wandb_init_run, capsys):
    # This simulates what the happens in a Jupyter notebook, it's gnarly
    # because it resumes so this depends on the run_resume_status which returns
    # a run that's at step 15 so calling log will update step to 16
    wandb.log({"something": "new"})
    rm = wandb_init_run.run_manager
    fsapi = rm._api._file_stream_api
    wandb_init_run._stop_jupyter_agent()
    files = [c[1][0] for c in fsapi.push.mock_calls]
    assert sorted(files) == ['wandb-events.jsonl',
                             'wandb-history.jsonl', 'wandb-summary.json']
    # TODO: There's a race here where a thread isn't stopped
    time.sleep(1)
    wandb.log({"resumed": "log"})
    new_fsapi = wandb_init_run._jupyter_agent.rm._api.get_file_stream_api()
    wandb_init_run.run_manager.test_shutdown()
    payloads = {c[1][0]: json.loads(c[1][1])
                for c in new_fsapi.push.mock_calls}
    assert payloads["wandb-history.jsonl"]["_step"] == 16
    assert payloads["wandb-history.jsonl"]["resumed"] == "log"


@pytest.mark.args(tensorboard=True)
@pytest.mark.skipif(sys.version_info < (3, 6) or os.environ.get("NO_ML") == "true", reason="no tensorboardX in py2 or no ml tests")
def test_tensorboard(wandb_init_run):
    from tensorboardX import SummaryWriter
    writer = SummaryWriter()
    writer.add_scalar('foo', 1, 0)
    writer.close()
    print("Real run: %s", wandb.run)
    print(wandb.run.history.row)
    print(wandb.run.history.rows)
    assert wandb.run.history.row['global_step'] == 0
    assert wandb.run.history.row['foo'] == 1.0


@pytest.mark.args(id="123456")
def test_run_id(wandb_init_run):
    assert wandb.run.id == "123456"


@pytest.mark.args(name="coolio")
def test_run_name(wandb_init_run):
    assert wandb.run.name == "coolio"


@pytest.mark.unconfigured
def test_not_logged_in(wandb_init_run, capsys):
    out, err = capsys.readouterr()
    assert "No credentials found.  Run \"wandb login\" to visualize your metrics" in err
    assert "_init_headless called with cloud=False" in out


@pytest.mark.jupyter
@pytest.mark.unconfigured
def test_jupyter_manual_configure(wandb_init_run, capsys):
    out, err = capsys.readouterr()
    assert "Not authenticated" in err
    assert "Python.core.display.HTML" in out
