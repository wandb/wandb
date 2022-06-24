import os
import pytest
import platform
import queue
import subprocess
import wandb


from wandb.sdk.internal.meta import Meta
from wandb.sdk.internal.sender import SendManager
from wandb.sdk.interface.interface_queue import InterfaceQueue


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
def meta(test_settings, interface):
    return Meta(settings=test_settings, interface=interface)


@pytest.fixture()
def sm(
    runner,
    git_repo,
    record_q,
    result_q,
    test_settings,
    meta,
    mock_server,
    mocked_run,
    interface,
):
    test_settings.update(save_code=True, source=wandb.sdk.wandb_settings.Source.INIT)
    sm = SendManager(
        settings=test_settings,
        record_q=record_q,
        result_q=result_q,
        interface=interface,
    )
    meta._interface.publish_run(mocked_run)
    sm.send(record_q.get())
    yield sm


def test_meta_probe(mock_server, meta, sm, record_q, log_debug, monkeypatch):
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
    meta.probe()
    meta.write()
    sm.send(record_q.get())
    sm.finish()
    print(mock_server.ctx)
    assert len(mock_server.ctx["storage?file=wandb-metadata.json"]) == 1
    assert len(mock_server.ctx["storage?file=requirements.txt"]) == 1
    assert len(mock_server.ctx["storage?file=conda-environment.yaml"]) == 1
    assert len(mock_server.ctx["storage?file=diff.patch"]) == 1


def test_executable_outside_cwd(mock_server, meta):
    meta._settings.update(
        program="asdf.py", source=wandb.sdk.wandb_settings.Source.INIT
    )
    meta.probe()
    assert meta.data.get("codePath") is None
    assert meta.data["program"] == "asdf.py"


def test_jupyter_name(meta, mocked_ipython):
    meta._settings.update(
        notebook_name="test_nb", source=wandb.sdk.wandb_settings.Source.INIT
    )
    meta.probe()
    assert meta.data["program"] == "test_nb"


def test_jupyter_path(meta, mocked_ipython):
    # not actually how jupyter setup works but just to test the meta paths
    meta._settings.update(
        _jupyter_path="dummy/path", source=wandb.sdk.wandb_settings.Source.INIT
    )
    meta.probe()
    assert meta.data["program"] == "dummy/path"
    assert meta.data.get("root") is not None


# TODO: test actual code saving
# fixme:
@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="backend sometimes crashes on Windows in CI",
)
def test_commmit_hash_sent_correctly(test_settings, git_repo):
    # disable_git is False is by default
    # so run object should have git info
    run = wandb.init(settings=test_settings)
    assert run._last_commit is not None
    assert run._last_commit == git_repo.last_commit
    assert run._remote_url is None
    run.finish()


# fixme:
@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="backend sometimes crashes on Windows in CI",
)
def test_commit_hash_not_sent_when_disable(test_settings, git_repo, disable_git_save):
    run = wandb.init(settings=test_settings)
    assert git_repo.last_commit
    assert run._last_commit is None
    run.finish()
