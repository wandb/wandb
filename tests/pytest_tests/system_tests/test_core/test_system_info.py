import os
import platform
import queue
import subprocess
import unittest.mock

import pytest
import wandb
from wandb.sdk.interface.interface_queue import InterfaceQueue
from wandb.sdk.internal import context
from wandb.sdk.internal.sender import SendManager
from wandb.sdk.internal.system.system_info import SystemInfo


@pytest.fixture()
def record_q():
    return queue.Queue()


@pytest.fixture()
def result_q():
    return queue.Queue()


@pytest.fixture()
def interface(record_q):
    return InterfaceQueue(record_q=record_q)


@pytest.fixture()
def meta(interface):
    def meta_helper(settings):
        return SystemInfo(settings=settings, interface=interface)

    yield meta_helper


@pytest.fixture()
def send_manager(
    runner,
    git_repo,
    record_q,
    result_q,
    interface,
):
    def send_manager_helper(run, meta):
        # test_settings.update(save_code=True, source=wandb.sdk.wandb_settings.Source.INIT)
        context_keeper = context.ContextKeeper()
        sm = SendManager(
            settings=run.settings,
            record_q=record_q,
            result_q=result_q,
            interface=interface,
            context_keeper=context_keeper,
        )
        meta.backend_interface.publish_run(run)
        sm.send(record_q.get())
        return sm

    yield send_manager_helper


@pytest.mark.wandb_core_failure(feature="file_uploader")
def test_meta_probe(
    relay_server, meta, mock_run, send_manager, record_q, user, monkeypatch
):
    orig_exists = os.path.exists
    orig_call = subprocess.call
    monkeypatch.setattr(
        os.path,
        "exists",
        lambda path: True if "conda-meta" in path else orig_exists(path),
    )
    monkeypatch.setattr(
        subprocess,
        "call",
        lambda cmd, **kwargs: kwargs["stdout"].write("CONDA YAML")
        if "conda" in cmd
        else orig_call(cmd, **kwargs),
    )
    with open("README", "w") as f:
        f.write("Testing")
    with relay_server() as relay:
        run = mock_run(use_magic_mock=True, settings={"save_code": True})
        meta = meta(run.settings)
        sm = send_manager(run, meta)
        data = meta.probe()
        meta.publish(data)
        sm.send(record_q.get())
        sm.finish()

    uploaded_files = relay.context.get_run_uploaded_files(run.id)
    assert sorted(uploaded_files) == sorted(
        [
            "wandb-metadata.json",
            "config.yaml",
            "diff.patch",
            "conda-environment.yaml",
        ]
    )


def test_executable_outside_cwd(meta, test_settings):
    meta = meta(test_settings(dict(program="asdf.py")))
    data = meta.probe()
    assert data.get("codePath") is None
    assert data["program"] == "asdf.py"


@pytest.fixture
def mocked_ipython(mocker):
    mocker.patch("wandb.sdk.lib.ipython._get_python_type", lambda: "jupyter")
    mocker.patch("wandb.sdk.wandb_settings._get_python_type", lambda: "jupyter")
    html_mock = mocker.MagicMock()
    mocker.patch("wandb.sdk.lib.ipython.display_html", html_mock)
    ipython = unittest.mock.MagicMock()
    ipython.html = html_mock

    def run_cell(cell):
        print("Running cell: ", cell)
        exec(cell)

    ipython.run_cell = run_cell
    # TODO: this is really unfortunate, for reasons not clear to me, monkeypatch doesn't work
    orig_get_ipython = wandb.jupyter.get_ipython
    orig_display = wandb.jupyter.display
    wandb.jupyter.get_ipython = lambda: ipython
    wandb.jupyter.display = lambda obj: html_mock(obj._repr_html_())
    yield ipython
    wandb.jupyter.get_ipython = orig_get_ipython
    wandb.jupyter.display = orig_display


def test_jupyter_name(meta, test_settings, mocked_ipython):
    meta = meta(test_settings(dict(notebook_name="test_nb")))
    data = meta.probe()
    assert data["program"] == "test_nb"


def test_jupyter_path(meta, test_settings, mocked_ipython, git_repo):
    # not actually how jupyter setup works but just to test the meta paths
    meta = meta(test_settings(dict(_jupyter_path="dummy/path")))
    data = meta.probe()
    assert data["program"] == "dummy/path"
    assert data.get("root") is not None


# TODO: test actual code saving
# fixme:
@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="backend sometimes crashes on Windows in CI",
)
def test_commit_hash_sent_correctly(wandb_init, git_repo):
    # disable_git is False is by default
    # so run object should have git info
    run = wandb_init()
    assert run._commit is not None
    assert run._commit == git_repo.last_commit
    assert run._remote_url is None
    run.finish()


# fixme:
@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="backend sometimes crashes on Windows in CI",
)
def test_commit_hash_not_sent_when_disable(wandb_init, git_repo):
    with unittest.mock.patch.dict("os.environ", WANDB_DISABLE_GIT="true"):
        run = wandb_init()
        assert git_repo.last_commit
        assert run._commit is None
        run.finish()
