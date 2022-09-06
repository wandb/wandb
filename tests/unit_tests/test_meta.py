import os
import platform
import queue
import subprocess
import unittest.mock

import pytest
from wandb.sdk.interface.interface_queue import InterfaceQueue
from wandb.sdk.internal.meta import Meta
from wandb.sdk.internal.sender import SendManager


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
        return Meta(settings=settings, interface=interface)

    yield meta_helper


@pytest.fixture()
def send_manager(
    runner,
    git_repo,
    record_q,
    result_q,
    interface,
):
    def sand_manager_helper(run, meta):
        # test_settings.update(save_code=True, source=wandb.sdk.wandb_settings.Source.INIT)
        sm = SendManager(
            settings=run.settings,
            record_q=record_q,
            result_q=result_q,
            interface=interface,
        )

        meta._interface.publish_run(run)
        sm.send(record_q.get())
        return sm

    yield sand_manager_helper


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
        meta.probe()
        meta.write()
        sm.send(record_q.get())
        sm.finish()

    uploaded_files = relay.context.get_run_uploaded_files(run.id)
    assert sorted(uploaded_files) == sorted(
        [
            "wandb-metadata.json",
            "requirements.txt",
            "config.yaml",
            "conda-environment.yaml",
            "diff.patch",
        ]
    )


def test_executable_outside_cwd(meta, test_settings):
    meta = meta(test_settings(dict(program="asdf.py")))
    meta.probe()
    assert meta.data.get("codePath") is None
    assert meta.data["program"] == "asdf.py"


def test_jupyter_name(meta, test_settings, mocked_ipython):
    meta = meta(test_settings(dict(notebook_name="test_nb")))
    meta.probe()
    assert meta.data["program"] == "test_nb"


def test_jupyter_path(meta, test_settings, mocked_ipython, git_repo):
    # not actually how jupyter setup works but just to test the meta paths
    meta = meta(test_settings(dict(_jupyter_path="dummy/path")))
    meta.probe()
    assert meta.data["program"] == "dummy/path"
    assert meta.data.get("root") is not None


# TODO: test actual code saving
# fixme:
@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="backend sometimes crashes on Windows in CI",
)
def test_commmit_hash_sent_correctly(wandb_init, git_repo):
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
